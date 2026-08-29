FROM nginx:stable-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
USER root
RUN apk upgrade --no-cache \
    && rm -f /etc/nginx/conf.d/default.conf
USER 101:101
