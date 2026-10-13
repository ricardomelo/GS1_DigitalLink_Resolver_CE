# nginx 1.30 (stable branch; the tag follows its security releases at each build with --pull): "resolve"
# in an upstream block needs 1.27.3 or later (nginx.conf). Deliberate change to the official image (1.25.1).
FROM nginx:1.30-alpine
LABEL authors="nick"

COPY nginx.conf /etc/nginx/nginx.conf
# Home page served at "/" (see nginx.conf)
COPY home /usr/share/nginx/home
RUN chmod -R a+rX /usr/share/nginx/home
