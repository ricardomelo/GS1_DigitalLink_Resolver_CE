# GS1 Barcode Syntax Engine (native library, Python binding, syntax dictionary), built in a separate
# stage so the compiler does not end up in the portal image. It validates GS1 Digital Link data
# attributes (syntax.py), at the release docker-compose.yml gives every service (ADR 0003).
FROM python:3.12-slim-bookworm AS syntax-engine
ARG GS1_SYNTAX_ENGINE_RELEASE
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates make gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
COPY tools/build-syntax-engine.sh /tmp/
RUN bash /tmp/build-syntax-engine.sh /opt/gs1-syntax-engine "$GS1_SYNTAX_ENGINE_RELEASE"

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GS1_SYNTAX_ENGINE_DIR=/opt/gs1-syntax-engine
WORKDIR /app
COPY --from=syntax-engine /opt/gs1-syntax-engine /opt/gs1-syntax-engine

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module and data file at the top of portal/ (gs1_dictionary.json holds the GS1 rules, ADR 0003). A list
# of names once left a new module out of the image: the development test test_deploy.py starts the portal from
# the files these lines copy.
COPY *.py *.json ./
COPY assets ./assets
COPY static ./static

RUN useradd --system --uid 10001 portal \
 && mkdir -p /app/config && chown portal /app/config && chmod 700 /app/config
# /app/config is a named volume: secret.key when PORTAL_SECRET_KEY is not set, and the users.json,
# records-meta.json and journal.jsonl of earlier versions, renamed *.migrated once moved into the
# database. Docker initialises a new volume from this
# directory, so it starts out owned by the portal user and needs no chown on the host.
VOLUME /app/config
USER portal

EXPOSE 8000
# The portal-worker service runs the same image with "python worker.py" (docker-compose.yml).
# WEB_CONCURRENCY is the number of gunicorn processes; docker-compose.yml sets it from .env. Since the
# portal keeps its state in MongoDB (ADR 0001), any number of processes and replicas share it.
# Requests in hand finish within Docker's 10-second stop period; gunicorn's control socket is not used.
ENV WEB_CONCURRENCY=2
CMD ["gunicorn", "--threads", "8", "--bind", "0.0.0.0:8000", "--graceful-timeout", "8", "--no-control-socket", "--access-logfile", "-", "app:app"]
