import time
import logging
from typing import Any

from flask_restx import Api
from flask import Flask, request, url_for
from flask import Blueprint
from flask_cors import CORS
import os
from dotenv import load_dotenv
from data_entry_namespace import data_entry_namespace
from mongo_db_init import mongo, init_mongo
import example_secrets
import service_db

logger = logging.getLogger(__name__)

# The Swagger UI of flask-restx writes its start-up script and style in the page, with the address of the description
# in it, so they are allowed inline; it loads and calls nothing outside this origin (ADR 0038, as the web server's)
SWAGGER_POLICY = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                  "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                  "frame-ancestors 'none'")
OTHER_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True, static_folder='public')
    CORS(app)  # enable CORS

    # the example token and the example password of the service's own MongoDB user (ADR 0030) refused outside
    # development, the root password warned about (ADR 0021)
    example_secrets.refuse(['SESSION_TOKEN', 'DATA_ENTRY_DB_PASSWORD'])
    example_secrets.warn(['MONGO_URI'], logger)

    mongo_url = service_db.uri('DATA_ENTRY', logger)
    # Log the host only — do not log credentials
    logger.info("Connecting to MongoDB at %s", service_db.host_of(mongo_url))
    app.config["MONGO_URI"] = mongo_url
    app.config["MONGO_DBNAME"] = "resolver_ce"

    # initialise the MongoDB connection
    init_mongo(app)
    logger.info("MongoDB connection initialised")


    with app.app_context():
        # setting up a blueprint for your API routes
        api_blueprint = Blueprint('api', __name__, url_prefix='/api')

        # setting up restx API and binding it with blueprint
        api = Api(api_blueprint,
                  version='1.0',
                  title='GS1 Resolver Community Edition API',
                  description='This data entry API enables editing of links made available by Resolver',
                  doc='/docs',  # This enables Swagger UI at /api/docs
                  prefix='')


        # adding namespace (which contains routes) to api
        api.add_namespace(data_entry_namespace)

        # registering api blueprint to app
        app.register_blueprint(api_blueprint)

    @app.after_request
    def browser_rules(response):
        """The browser's rules (Documentation/adr/0038-browser-hardening.md, finding F-021): the Swagger UI of the
        library runs its own inline start-up script and calls this origin only; every other answer may load nothing.
        Nothing frames either, and no type is guessed."""
        response.headers.setdefault('Content-Security-Policy',
                                    SWAGGER_POLICY if request.endpoint == 'api.doc' else OTHER_POLICY)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        return response

    return app
