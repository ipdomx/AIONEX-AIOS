FROM postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685
USER root
RUN apk upgrade --no-cache \
    && rm -f /usr/local/bin/gosu
USER 70:70
