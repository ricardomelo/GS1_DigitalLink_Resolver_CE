# nginx 1.30 (stable branch), by digest: its security releases arrive as a new digest proposed by Dependabot (ADR 0033); "resolve"
# in an upstream block needs 1.27.3 or later (nginx.conf). Deliberate change to the official image (1.25.1).
FROM nginx:1.30-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3
LABEL authors="nick"

COPY nginx.conf /etc/nginx/nginx.conf
# Who may use /api and /swaggerui (Documentation/adr/0021-data-entry-api-closed.md): the image's entrypoint runs the
# script before nginx starts, writing /etc/nginx/api-access.conf from DATA_ENTRY_API_ALLOW and
# /etc/nginx/real-ip.conf from the trusted proxies; the empty files baked in keep both closed, and the client's
# address the connection's, if it never runs.
COPY api-access.sh /docker-entrypoint.d/40-api-access.sh
# The request limits (Documentation/adr/0031-request-limits.md) are written by the same script: empty, none.
RUN chmod 755 /docker-entrypoint.d/40-api-access.sh && : > /etc/nginx/api-access.conf && : > /etc/nginx/real-ip.conf \
    && for f in limits-http limit-exempt limit-server limit-resolve limit-portal limit-signin; do : > /etc/nginx/$f.conf; done
# Home page served at "/" (see nginx.conf)
COPY home /usr/share/nginx/home
RUN chmod -R a+rX /usr/share/nginx/home
