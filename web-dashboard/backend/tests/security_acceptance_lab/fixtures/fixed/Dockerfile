FROM python:3.11.15-slim-bookworm
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --chown=appuser:appuser . /app
USER appuser
CMD ["python", "app.py"]
