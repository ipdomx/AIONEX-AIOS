FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN groupadd --gid 10001 aios \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin aios

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m compileall -q /app/src \
    && chown -R 10001:10001 /app

USER 10001:10001
EXPOSE 8443

ENTRYPOINT ["python", "-m", "aios.cluster_runtime.node"]
