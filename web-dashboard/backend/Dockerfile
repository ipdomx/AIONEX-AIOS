# AIONEX AIOS — Backend Dockerfile

# Debian trixie ships PostgreSQL client 17, which can dump the PostgreSQL 16
# server used by both production Compose stacks.  Pin the suite so a base-image
# alias cannot silently regress to the incompatible client 15 from bookworm.
FROM python:3.11-slim-trixie AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    postgresql-client-17 \
    curl \
    && rm -rf /var/lib/apt/lists/*

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
