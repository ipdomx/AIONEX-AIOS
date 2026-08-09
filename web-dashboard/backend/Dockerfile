# AIONEX AIOS — hardened backend image.
# Alpine is pinned by immutable digest; build tooling never reaches runtime.
FROM python:3.11-alpine3.23@sha256:f73754c398b259dfbbe482361dca8b464dea57da74efe5214966ca2ee767ee12 AS builder

WORKDIR /build
RUN set -eux; \
    apk add --no-cache --virtual .build-deps gcc musl-dev postgresql16-dev; \
    python -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip==26.2.1 setuptools==80.9.0 wheel==0.46.3
COPY requirements-runtime.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements-runtime.txt

# CI-only test target. It is never the final/default production stage.
FROM builder AS test
RUN apk add --no-cache bash postgresql16-client libpq
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
WORKDIR /app
COPY . .
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

FROM python:3.11-alpine3.23@sha256:f73754c398b259dfbbe482361dca8b464dea57da74efe5214966ca2ee767ee12 AS runtime

WORKDIR /app
RUN set -eux; \
    apk add --no-cache ca-certificates curl bash su-exec postgresql16-client libpq libgcc libstdc++; \
    rm -rf /usr/local/lib/python3.11/ensurepip \
           /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/lib/python3.11/site-packages/wheel* \
           /usr/local/bin/pip*

COPY --from=builder /opt/venv /opt/venv
RUN rm -rf /opt/venv/lib/python3.11/site-packages/pip* \
           /opt/venv/lib/python3.11/site-packages/setuptools* \
           /opt/venv/lib/python3.11/site-packages/wheel* \
    && rm -f /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.11
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY . .
RUN rm -rf /app/tests

RUN addgroup -g 1000 aionex \
    && adduser -D -u 1000 -G aionex aionex \
    && install -d -m 0700 -o aionex -g aionex /var/lib/aionex/backups \
    && chown -R aionex:aionex /app \
    && chmod 0755 /app/scripts/docker-entrypoint.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD su-exec aionex curl -fsS http://localhost:8000/ready || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && exec python main.py"]
