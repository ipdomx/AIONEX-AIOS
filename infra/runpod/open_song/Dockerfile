# Phase 36G Stage 8 — isolated ACE-Step full-song + Demucs four-stem handler.
# A small source-only target validates Docker parsing without pulling GPU layers.
FROM python:3.11-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3 AS source-contract
WORKDIR /source
COPY contract.py handler.py prepare_models.py verify_runtime.py /source/
RUN python -m compileall -q /source

# The runtime image is pinned to the audited linux/amd64 manifest, not a tag.
FROM ghcr.io/ace-step/ace-step-1.5@sha256:c289cb5c0cbc60d428baa9283a49966d2fe54ecf2028fa254f99f164f3953159 AS runtime

USER root

ARG ACE_STEP_SOURCE_COMMIT=dce621408bee8c31b4fcf4811682eb9359e1bc94
ARG ACE_STEP_MODEL_REVISION=e432212fec32b8965a14ffa57ae653438d6abd14
ARG ACE_STEP_LM_REVISION=0a3ec94b557aea7d508da38b31cfe7341f6ff737
ARG DEMUCS_SOURCE_COMMIT=ef66d254cd6d558e207eeff2c4b8d053db2e77dd
ARG DEMUCS_CHECKPOINT_URL=https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th
ARG DEMUCS_CHECKPOINT_SHA256=8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4

LABEL org.opencontainers.image.title="AIONEX Open Song Handler" \
      org.opencontainers.image.description="Governed ACE-Step song generation and Demucs four-stem separation" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/ipdomx/AIONEX-AIOS" \
      ai.aionex.ace-step.source-commit="${ACE_STEP_SOURCE_COMMIT}" \
      ai.aionex.ace-step.model-revision="${ACE_STEP_MODEL_REVISION}" \
      ai.aionex.ace-step.language-model-revision="${ACE_STEP_LM_REVISION}" \
      ai.aionex.demucs.source-commit="${DEMUCS_SOURCE_COMMIT}" \
      ai.aionex.demucs.checkpoint-sha256="${DEMUCS_CHECKPOINT_SHA256}"

COPY requirements.txt /tmp/aionex-open-song-requirements.txt
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl ffmpeg libsndfile1; \
    rm -rf /var/lib/apt/lists/*; \
    uv pip install --python /app/.venv/bin/python --no-cache \
      -r /tmp/aionex-open-song-requirements.txt; \
    rm -f /tmp/aionex-open-song-requirements.txt

# Bake exact model revisions. Runtime is offline and cannot silently refresh.
COPY prepare_models.py /tmp/aionex-prepare-open-song-models.py
RUN set -eux; \
    /app/.venv/bin/python /tmp/aionex-prepare-open-song-models.py; \
    cp -f /app/acestep/models/base/*.py /app/checkpoints/acestep-v15-base/; \
    test -d /app/checkpoints/acestep-v15-base; \
    test -d /app/checkpoints/acestep-5Hz-lm-4B; \
    rm -f /tmp/aionex-prepare-open-song-models.py

RUN set -eux; \
    install -d -m 0755 /opt/aionex-demucs-models /opt/aionex-open-song; \
    curl -fsSLo /opt/aionex-demucs-models/955717e8-8726e21a.th \
      "${DEMUCS_CHECKPOINT_URL}"; \
    printf '%s  %s\n' "${DEMUCS_CHECKPOINT_SHA256}" \
      /opt/aionex-demucs-models/955717e8-8726e21a.th | sha256sum -c -; \
    test "$(stat -c %s /opt/aionex-demucs-models/955717e8-8726e21a.th)" = "84141911"

# Remove build-only packages and patch runtime dependencies before the final image.
# ACE-Step 1.5 keeps transformers<4.58 and gradio==6.2.0; exploitability of
# their remaining scanner findings is captured by the package-scoped OpenVEX.
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y --only-upgrade \
      libssl3 openssl \
      gnupg2 gnupg gnupg-l10n gnupg-utils \
      gpg gpg-agent gpg-wks-client gpg-wks-server gpgconf gpgsm gpgv dirmngr; \
    apt-get purge -y \
      build-essential g++ g++-11 \
      libc6-dev libexpat1-dev libpython3.11-dev libssl-dev \
      libstdc++-11-dev linux-libc-dev python3.11-dev; \
    /usr/bin/uv pip install --python /app/.venv/bin/python --no-cache \
      diffusers==0.38.0 \
      orjson==3.11.6 \
      pillow==12.3.0 \
      python-multipart==0.0.30 \
      starlette==1.3.1; \
    /usr/bin/uv pip uninstall --python /app/.venv/bin/python \
      setuptools wheel jaraco.context; \
    rm -f /usr/bin/uv /usr/bin/uvx; \
    rm -rf /var/lib/apt/lists/* /root/.cache /tmp/*; \
    ! dpkg-query -W linux-libc-dev >/dev/null 2>&1; \
    ! dpkg-query -W python3.11-dev >/dev/null 2>&1; \
    ! command -v uv; \
    ! command -v uvx

COPY contract.py handler.py verify_runtime.py /opt/aionex-open-song/

ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONPATH=/opt/aionex-open-song:/app \
    ACESTEP_PROJECT_ROOT=/app \
    ACESTEP_CHECKPOINTS_DIR=/app/checkpoints \
    ACESTEP_CONFIG_PATH=acestep-v15-base \
    ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-4B \
    ACESTEP_LLM_BACKEND=pt \
    ACESTEP_TMPDIR=/tmp/aionex-open-song/acestep-tmp \
    TRITON_CACHE_DIR=/tmp/aionex-open-song/triton \
    TORCHINDUCTOR_CACHE_DIR=/tmp/aionex-open-song/torchinductor \
    XDG_CACHE_HOME=/tmp/aionex-open-song/xdg-cache \
    HF_HOME=/tmp/aionex-open-song/hf-cache \
    MPLCONFIGDIR=/tmp/aionex-open-song/matplotlib \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    TMPDIR=/tmp/aionex-open-song \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN set -eux; \
    /app/.venv/bin/python -m compileall -q /opt/aionex-open-song; \
    /app/.venv/bin/python /opt/aionex-open-song/verify_runtime.py; \
    rm -f /opt/aionex-open-song/verify_runtime.py; \
    groupadd --system aionex-song; \
    useradd --system --gid aionex-song --create-home \
      --home-dir /home/aionex-song --shell /usr/sbin/nologin aionex-song; \
    chown -R root:root /opt/aionex-open-song /opt/aionex-demucs-models /app/checkpoints; \
    chmod -R go-w /opt/aionex-open-song /opt/aionex-demucs-models /app/checkpoints; \
    install -d -m 0755 -o root -g root /app/.cache; \
    install -d -m 0700 -o aionex-song -g aionex-song /app/.cache/acestep; \
    install -d -m 0700 -o aionex-song -g aionex-song \
      /tmp/aionex-open-song \
      /tmp/aionex-open-song/acestep-tmp \
      /tmp/aionex-open-song/triton \
      /tmp/aionex-open-song/torchinductor \
      /tmp/aionex-open-song/xdg-cache \
      /tmp/aionex-open-song/hf-cache \
      /tmp/aionex-open-song/matplotlib; \
    test "$(stat -c '%U:%G:%a' /app/.cache/acestep)" = "aionex-song:aionex-song:700"; \
    test "$(stat -c '%U:%G:%a' /tmp/aionex-open-song)" = "aionex-song:aionex-song:700"; \
    test "$(stat -c '%U:%G' /app/checkpoints)" = "root:root"

WORKDIR /opt/aionex-open-song
USER aionex-song:aionex-song
ENTRYPOINT ["/app/.venv/bin/python", "/opt/aionex-open-song/handler.py"]
