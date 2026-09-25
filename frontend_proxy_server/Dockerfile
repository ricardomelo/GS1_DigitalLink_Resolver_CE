FROM nginx:1.25.1-alpine
LABEL authors="nick"

COPY nginx.conf /etc/nginx/nginx.conf
# Home page served at "/" (see nginx.conf)
COPY home /usr/share/nginx/home
RUN chmod -R a+rX /usr/share/nginx/home
