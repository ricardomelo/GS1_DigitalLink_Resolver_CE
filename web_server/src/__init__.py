from flask_restx import Api
from flask import Flask, Response
from flask import Blueprint
from flask_cors import CORS
import logging
import os
from typing import Any
import domains
import forwarding
import gs1_syntax
import landing
import request_log
import web_pages
from web_namespace import web_namespace
from mongo_db_init import mongo, init_mongo

logger = logging.getLogger(__name__)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True, static_folder='public')

    # turn off requiring different routes if the URL ends with a '/'.
    # This will affect all routes, ensuring that any request URL with a trailing slash is matched to its non-slash counterpart.
    app.url_map.strict_slashes = False

    # Enable CORS (cross-site scripting allowed)
    CORS(app)

    # the GS1 Barcode Syntax Engine loaded before the first request (its absence is logged now, not at a scan)
    gs1_syntax.available()

    server_description = f"The web server is running at https://{os.getenv('FQDN', 'set-domain-name-in-env-variable-FQDN.com')}"
    logger.info(server_description)

    mongo_url = os.getenv('MONGO_URI')
    if not mongo_url:
        raise RuntimeError("MONGO_URI environment variable is not set")
    # Log the host only — do not log credentials
    mongo_host = mongo_url.split('@')[-1] if '@' in mongo_url else mongo_url
    logger.info("Connecting to MongoDB at %s", mongo_host)
    app.config["MONGO_URI"] = mongo_url
    app.config["MONGO_DBNAME"] = "resolver_ce"

    # initialise the MongoDB connection
    init_mongo(app)
    logger.info("MongoDB connection initialised")

    with app.app_context():
        # setting up a blueprint for your API routes
        # If this server is going to run standalone and not by proxied the NGINX proxy server in this project,
        # then you can change your url_prefix to '/', otherwise your GS1 Digital Link URLs would have to be prefixed
        # with '/api' which is not the standard way to use GS1 Digital Link URLs. The reason for '/api' is for use
        # with the NGINX proxy server in this project with this setting:
        #   location / {
        #                  proxy_pass http://web-service:4000/api/; <-- this is the /api prefix in use
        #                  proxy_buffer_size 16k;
        #                  proxy_buffers 4 16k;
        #                  proxy_busy_buffers_size 16k;
        #              }
        api_blueprint = Blueprint('api', __name__, url_prefix='/api')

        # setting up restx API and binding it with blueprint
        api = Api(api_blueprint, version='1.0', title='GS1 Resolver Community Edition API', description='')

        api.doc(
            description=f"{server_description}.\n\n"

        )

        # adding namespace (which contains routes) to api
        api.add_namespace(web_namespace)

        # registering api blueprint to app
        app.register_blueprint(api_blueprint)

    # The log of resolver requests (ADR 0006): the routes note what they resolved, these hooks time the request and
    # queue its event; a background thread writes it to resolver_log.requests. A test may set its own collection. How
    # long events are kept is read from the portal's database (section 8 of the ADR).
    if request_log.WRITER.collection is None:
        request_log.WRITER.collection = lambda: mongo.cx[request_log.DB_NAME][request_log.COLLECTION]
    if request_log.RETENTION.database is None:
        request_log.RETENTION.database = lambda: mongo.cx[domains.portal_db_name()]
    app.before_request(request_log.start)
    app.after_request(request_log.record)

    # The organisations' own domains (Documentation/adr/0009-tenant-domains.md): read from the portal's database with
    # the same connection; the middleware removes a domain's path stem before the routes see the path.
    if domains.MAP.database is None:
        domains.MAP.database = lambda: mongo.cx[domains.portal_db_name()]
    app.wsgi_app = domains.Middleware(app.wsgi_app)
    # The brands of the item's page (Documentation/adr/0011-item-page.md), from the same database
    if landing.BRANDS.database is None:
        landing.BRANDS.database = lambda: mongo.cx[domains.portal_db_name()]
    # Forwarding by prefix and the resolver of last resort (Documentation/adr/0018-forwarding.md), from the same database
    if forwarding.FORWARDING.database is None:
        forwarding.FORWARDING.database = lambda: mongo.cx[domains.portal_db_name()]
    # The installation's appearance (Documentation/adr/0019-appearance.md): title, logo and colours of its pages
    if web_pages.APPEARANCE.database is None:
        web_pages.APPEARANCE.database = lambda: mongo.cx[domains.portal_db_name()]

    @app.after_request
    def add_headers(response: Response) -> Response:
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Expose-Headers'] = 'Link, Location'
        return response

    return app
