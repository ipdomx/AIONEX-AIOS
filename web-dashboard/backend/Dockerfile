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

# Phase 36D — dedicated FFmpeg 9 media worker.
# Release tarballs are downloaded only from ffmpeg.org and are verified with the
# official FFmpeg release signing key before compilation.
FROM python:3.11-alpine3.23@sha256:f73754c398b259dfbbe482361dca8b464dea57da74efe5214966ca2ee767ee12 AS ffmpeg-builder
ARG FFMPEG_VERSION=9.0
ARG FFMPEG_SHA256=7f607a00dd0d28a729d5a4811205812eef01cf6ef6155025febb6f36a9062d52
ARG FFMPEG_SIGNING_FINGERPRINT=FCF986EA15E6E293A5644F10B4322F04D67658D8
RUN set -eux; \
    apk add --no-cache build-base curl gnupg xz nasm pkgconf x264-dev opus-dev svt-av1-dev zlib-dev libva-dev libvpl-dev; \
    mkdir -p /build/ffmpeg /opt/ffmpeg; \
    cd /build/ffmpeg; \
    curl -fsSLo ffmpeg.tar.xz "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    curl -fsSLo ffmpeg.tar.xz.asc "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz.asc"; \
    curl -fsSLo ffmpeg-devel.asc "https://ffmpeg.org/ffmpeg-devel.asc"; \
    printf '%s  %s\n' "$FFMPEG_SHA256" ffmpeg.tar.xz | sha256sum -c -; \
    GNUPGHOME=/tmp/ffmpeg-gnupg; export GNUPGHOME; \
    mkdir -m 0700 "$GNUPGHOME"; \
    gpg --batch --import ffmpeg-devel.asc; \
    fingerprint="$(gpg --batch --with-colons --fingerprint | awk -F: '$1 == "fpr" {print $10; exit}')"; \
    test "$fingerprint" = "$FFMPEG_SIGNING_FINGERPRINT"; \
    gpg --batch --verify ffmpeg.tar.xz.asc ffmpeg.tar.xz; \
    tar -xJf ffmpeg.tar.xz --strip-components=1; \
    ./configure \
      --prefix=/opt/ffmpeg \
      --disable-debug \
      --disable-doc \
      --disable-ffplay \
      --enable-gpl \
      --enable-libx264 \
      --enable-libopus \
      --enable-libsvtav1 \
      --enable-vaapi \
      --enable-libvpl; \
    make -j"$(getconf _NPROCESSORS_ONLN)"; \
    make install; \
    /opt/ffmpeg/bin/ffmpeg -version | head -1; \
    /opt/ffmpeg/bin/ffprobe -version | head -1; \
    /opt/ffmpeg/bin/ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264; \
    /opt/ffmpeg/bin/ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libsvtav1; \
    /opt/ffmpeg/bin/ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_vaapi; \
    /opt/ffmpeg/bin/ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_qsv

FROM runtime AS media-worker
USER root
RUN set -eux; \
    apk add --no-cache x264-libs opus libSvtAv1Enc zlib libva libvpl libdrm; \
    install -d -m 0700 -o aionex -g aionex /var/lib/aionex/media-assets /tmp/aionex-media-render
COPY --from=ffmpeg-builder /opt/ffmpeg /opt/ffmpeg
ENV MEDIA_FFMPEG_BINARY=/opt/ffmpeg/bin/ffmpeg \
    MEDIA_FFPROBE_BINARY=/opt/ffmpeg/bin/ffprobe \
    MEDIA_FFMPEG_TARGET_VERSION=9.0
RUN /opt/ffmpeg/bin/ffmpeg -version | grep -q '^ffmpeg version 9\.0' \
    && /opt/ffmpeg/bin/ffprobe -version | grep -q '^ffprobe version 9\.0'

# Dedicated project-worker target. It is the only production image that carries
# Node/npm and a local Chromium/ChromeDriver pair for real 3D build + browser QA.
FROM builder AS project-worker-builder
COPY requirements-project-worker.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements-project-worker.txt \
    && /opt/venv/bin/pip check

FROM runtime AS project-worker
USER root
RUN set -eux; \
    apk add --no-cache nodejs npm chromium chromium-chromedriver ttf-freefont xvfb mesa-gl mesa-egl; \
    install -d -m 0700 -o aionex -g aionex /var/lib/aionex/project-npm-cache
COPY --from=project-worker-builder /opt/venv /opt/venv
RUN rm -rf /opt/venv/lib/python3.11/site-packages/pip* \
           /opt/venv/lib/python3.11/site-packages/setuptools* \
           /opt/venv/lib/python3.11/site-packages/wheel* \
    && rm -f /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.11
ENV PROJECT_EXECUTION_NPM_CACHE=/var/lib/aionex/project-npm-cache \
    CHROME_BIN=/usr/bin/chromium-browser
