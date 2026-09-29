# GS1 Barcode Syntax Engine (native library, Python binding, syntax dictionary), built in a separate
# stage so the compiler does not end up in the portal image. It validates GS1 Digital Link data
# attributes (syntax.py); the release is pinned in tools/build-syntax-engine.sh.
FROM python:3.12-slim-bookworm AS syntax-engine
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates make gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
COPY tools/build-syntax-engine.sh /tmp/
RUN bash /tmp/build-syntax-engine.sh /opt/gs1-syntax-engine

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GS1_SYNTAX_ENGINE_DIR=/opt/gs1-syntax-engine
WORKDIR /app
COPY --from=syntax-engine /opt/gs1-syntax-engine /opt/gs1-syntax-engine

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gs1.py journal.py label.py linkcheck.py users.py meta.py sheet.py syntax.py create_user.py ./
COPY assets ./assets
COPY static ./static

RUN useradd --system --uid 10001 portal \
 && mkdir -p /app/config && chown portal /app/config && chmod 700 /app/config
# /app/config (users.json, secret.key) is a named volume; Docker initialises a new volume from this
# directory, so it starts out owned by the portal user and needs no chown on the host.
VOLUME /app/config
USER portal

EXPOSE 8000
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "app:app"]
