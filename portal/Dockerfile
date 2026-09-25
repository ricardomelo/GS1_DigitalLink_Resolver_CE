FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gs1.py label.py users.py create_user.py ./
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
