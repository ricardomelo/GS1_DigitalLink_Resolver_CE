# nginx 1.30 (stable branch; the tag follows its security releases at each build with --pull): "resolve"
# in an upstream block needs 1.27.3 or later (nginx.conf). Deliberate change to the official image (1.25.1).
FROM nginx:1.30-alpine
LABEL authors="nick"

COPY nginx.conf /etc/nginx/nginx.conf
# Who may use /api and /swaggerui (Documentation/adr/0021-data-entry-api-closed.md): the image's entrypoint runs the
# script before nginx starts, writing /etc/nginx/api-access.conf from DATA_ENTRY_API_ALLOW and
# /etc/nginx/real-ip.conf from the trusted proxies; the empty files baked in keep both closed, and the client's
# address the connection's, if it never runs.
COPY api-access.sh /docker-entrypoint.d/40-api-access.sh
RUN chmod 755 /docker-entrypoint.d/40-api-access.sh && : > /etc/nginx/api-access.conf && : > /etc/nginx/real-ip.conf
# Home page served at "/" (see nginx.conf)
COPY home /usr/share/nginx/home
RUN chmod -R a+rX /usr/share/nginx/home
