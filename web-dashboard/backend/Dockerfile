# AIONEX AIOS — Backend Dockerfile

# Both production Compose stacks run PostgreSQL 16. Pin the Debian suite and
# install the matching client from PostgreSQL's signed official PGDG repository.
FROM python:3.11-slim-bookworm AS base

WORKDIR /app

# Install build/runtime dependencies and PostgreSQL client 16. The downloaded
# repository key is authenticated by its full fingerprint before it is trusted,
# and apt is restricted to that key through a repository-scoped signed-by rule.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg; \
    curl -fsSL \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /tmp/postgresql-pgdg.asc; \
    gpg --batch --show-keys --with-colons /tmp/postgresql-pgdg.asc \
        | grep -qx 'fpr:::::::::B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8:'; \
    gpg --batch --yes --dearmor \
        --output /usr/share/keyrings/postgresql-pgdg.gpg \
        /tmp/postgresql-pgdg.asc; \
    echo 'deb [signed-by=/usr/share/keyrings/postgresql-pgdg.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' \
        > /etc/apt/sources.list.d/postgresql-pgdg.list; \
    rm -f /tmp/postgresql-pgdg.asc; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        postgresql-client-16; \
    apt-get purge -y --auto-remove gnupg; \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user and the protected, persistent backup mount point.
RUN useradd -m -u 1000 aionex \
    && install -d -m 0700 -o aionex -g aionex /var/lib/aionex/backups \
    && chown -R aionex:aionex /app
USER aionex

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/ready || exit 1

# Apply non-destructive schema migrations before serving authenticated routes.
# Alembic resolves the same Settings.DATABASE_URL used by the application and
# serializes concurrent PostgreSQL migrations with an advisory transaction lock.
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && exec python main.py"]
