FROM python:3.12-slim-bookworm
LABEL authors="nick"

# The environment variable ensures that the python output is set straight
# to the terminal without buffering it first
ENV PYTHONUNBUFFERED 1

# Install Node for GS1 Digital Link Toolikit
RUN apt-get update && apt-get install -y curl && curl -sL https://deb.nodesource.com/setup_24.x | bash -
RUN apt-get install -y nodejs nano
ADD src/gs1-digitallink-toolkit /app/gs1-digitallink-toolkit
WORKDIR /app/gs1-digitallink-toolkit
RUN npm init es6
# The GS1 Barcode Syntax Engine at the release docker-compose.yml gives every service (deliberate change to
# the official image, which installed whatever release was newest; ADR 0003).
ARG GS1_SYNTAX_ENGINE_RELEASE
RUN test -n "$GS1_SYNTAX_ENGINE_RELEASE" || { echo "GS1_SYNTAX_ENGINE_RELEASE is not set: build with docker compose"; exit 1; } \
 && npm install --save "gs1encoder@$GS1_SYNTAX_ENGINE_RELEASE"

WORKDIR /app

# Add requirements.txt before rest of repo for caching
ADD src/requirements.txt /app/
RUN pip install --isolated --no-cache-dir --index-url https://pypi.org/simple -r requirements.txt

# Add the current directory contents into the container at /app
ADD src /app/

EXPOSE 3000

# gunicorn instead of Flask's built-in server, which is meant for development (deliberate change to the
# official image; "python -m main" still starts the built-in server for development). WEB_CONCURRENCY is
# the number of server processes (gunicorn reads it); docker-compose.yml sets it from .env. The application
# factory is loaded directly, so that main.py's own signal handlers do not replace gunicorn's.
# On "docker compose stop" the requests in hand finish within Docker's 10-second stop period
# (--graceful-timeout 8); gunicorn's control socket is not used.
ENV WEB_CONCURRENCY=2
CMD ["gunicorn", "--threads", "8", "--bind", "0.0.0.0:3000", "--graceful-timeout", "8", "--no-control-socket", "--access-logfile", "-", "__init__:create_app()"]
