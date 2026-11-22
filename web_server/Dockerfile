# The GS1 Barcode Syntax Engine's native library and Python binding (deliberate change to the official image): every
# resolution checks the GS1 Digital Link with it in-process (src/gs1_syntax.py) instead of starting Node.js. Built in a
# separate stage with the portal's script (the build context "engine-tools" of docker-compose.yml) at the release
# docker-compose.yml gives every service (ADR 0003), so that the compiler does not end up in the image.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS syntax-engine
ARG GS1_SYNTAX_ENGINE_RELEASE
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates make gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
COPY --from=engine-tools build-syntax-engine.sh /tmp/
RUN bash /tmp/build-syntax-engine.sh /opt/gs1-syntax-engine "$GS1_SYNTAX_ENGINE_RELEASE"

# Node.js and the service's npm package, the GS1 Barcode Syntax Engine (gs1encoder), from the official Node.js image
# by digest, installed from package-lock.json with its integrity hash (deliberate change to the official image, which
# piped NodeSource's setup script into bash and ran "npm init es6", fetching and running the newest create-es6;
# Documentation/adr/0033-supply-chain.md). npm stays in this stage; the final image receives node and the package.
FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS node
WORKDIR /toolkit
COPY src/gs1-digitallink-toolkit/package.json src/gs1-digitallink-toolkit/package-lock.json ./
# The release docker-compose.yml gives every service (ADR 0003) must be the one package-lock.json holds.
ARG GS1_SYNTAX_ENGINE_RELEASE
RUN test -n "$GS1_SYNTAX_ENGINE_RELEASE" || { echo "GS1_SYNTAX_ENGINE_RELEASE is not set: build with docker compose"; exit 1; }
RUN locked=$(node -p 'require("./package-lock.json").packages["node_modules/gs1encoder"].version') \
 && if [ "$locked" != "$GS1_SYNTAX_ENGINE_RELEASE" ]; then \
      echo "package-lock.json holds gs1encoder $locked, docker-compose.yml names $GS1_SYNTAX_ENGINE_RELEASE: see ADR 0033"; exit 1; fi
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
LABEL authors="nick"

# The environment variable ensures that the python output is set straight
# to the terminal without buffering it first
ENV PYTHONUNBUFFERED 1

 # This Environment variable is used to set the fully qualified domain name (FQDN) of the host machine which will be
 # Used when outputing linkset information
 ENV FQDN='id.mydomainname_currently_set_in_dockerfile.com'

# Node.js for the GS1 Digital Link Toolkit and the GS1 Barcode Syntax Engine (the stage "node" above), at the path
# the service starts it from; nano as in the official image, from Debian's signed repository.
RUN apt-get update && apt-get install -y --no-install-recommends nano && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/bin/node
RUN node --version
ADD src/gs1-digitallink-toolkit /app/gs1-digitallink-toolkit
COPY --from=node /toolkit/node_modules /app/gs1-digitallink-toolkit/node_modules

WORKDIR /app
COPY --from=syntax-engine /opt/gs1-syntax-engine /opt/gs1-syntax-engine
ENV GS1_SYNTAX_ENGINE_DIR=/opt/gs1-syntax-engine

# Add requirements.txt before rest of repo for caching
ADD src/requirements.txt /app/
# Every package at the version and with the file hashes of the lock file (ADR 0033): pip refuses any other file.
RUN pip install --isolated --no-cache-dir --index-url https://pypi.org/simple --require-hashes --no-deps -r requirements.txt

# Add the current directory contents into the container at /app
ADD src /app/

# The service runs as a user of its own, not as root (deliberate change to the official image;
# Documentation/adr/0030-least-privilege-services.md): nothing in /app is written at run time.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin resolver
USER resolver

EXPOSE 4000

# gunicorn instead of Flask's built-in server, which is meant for development (deliberate change to the
# official image; "python -m main" still starts the built-in server for development). WEB_CONCURRENCY is
# the number of server processes (gunicorn reads it); docker-compose.yml sets it from .env. The application
# factory is loaded directly, so that main.py's own signal handlers do not replace gunicorn's.
# On "docker compose stop" the requests in hand finish within Docker's 10-second stop period
# (--graceful-timeout 8); gunicorn's control socket is not used.
ENV WEB_CONCURRENCY=2
# No access log (Documentation/adr/0043-access-logs.md): the proxy writes one line per request, without the
# client's address or the query string; gunicorn's would hold the whole request line, the User-Agent and the referrer.
CMD ["gunicorn", "--threads", "8", "--bind", "0.0.0.0:4000", "--graceful-timeout", "8", "--no-control-socket", "__init__:create_app()"]
