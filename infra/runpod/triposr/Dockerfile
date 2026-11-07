FROM pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime@sha256:b85566342b86d13a67712e9315d40cdc2dad7f8d86df1aff3831f80835edbcca
# FR-16D hardening applied to the TripoSR fallback: hash-locked dependencies,
# checksum-verified model assets converted to safetensors (no pickle at
# runtime), offline runtime, non-root user, bounded request validation.
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_BREAK_SYSTEM_PACKAGES=1 PYTHONUNBUFFERED=1 \
    PYOPENGL_PLATFORM=egl MGL_BACKEND=egl U2NET_HOME=/models/rembg
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*cuda* /etc/apt/sources.list.d/*nvidia*; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y; \
    apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 libegl1; \
    apt-get purge -y --auto-remove linux-libc-dev curl gnupg gnupg-l10n gnupg-utils gpg gpg-agent gpgconf gpgsm dirmngr || true; \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
COPY requirements.lock /tmp/requirements.lock
# Every wheel/sdist is verified against requirements.lock; the second, offline
# install proves that the Dependabot-managed requirements.txt pins are exactly
# what the lock installed.
RUN python -m pip install --no-cache-dir --require-hashes --no-deps --no-build-isolation -r /tmp/requirements.lock \
 && python -m pip install --no-cache-dir --no-index -r /tmp/requirements.txt \
 && python -m pip uninstall -y spin \
 && python -m pip check \
 && python -c "from transformers.models.vit.modeling_vit import ViTModel; assert ViTModel is not None"
# Model assets: pinned revisions, SHA-256 verified (fetch_models.py), TripoSR
# checkpoint converted to safetensors; dino config at /models/dino-vitb16.
# Replaces the unverified huggingface_hub snapshot_download used before FR-16D.
ARG TRIPOSR_MODEL_REVISION=5b521936b01fbe1890f6f9baed0254ab6351c04a
ARG DINO_REVISION=f205d5d8e640a89a2b8ef0369670dfc37cc07fc2
COPY fetch_models.py /tmp/fetch_models.py
RUN python /tmp/fetch_models.py /models "$TRIPOSR_MODEL_REVISION" "$DINO_REVISION" && rm -f /tmp/fetch_models.py
COPY vendor/tsr /opt/triposr/tsr
COPY vendor/LICENSE /opt/triposr/LICENSE
COPY vendor/UPSTREAM_COMMIT /opt/triposr/UPSTREAM_COMMIT
COPY handler.py input_guard.py /opt/triposr/
RUN python -m pip uninstall -y uv wheel setuptools \
 && (python -m pip uninstall -y pip || true) \
 && rm -rf /root/.cache /tmp/requirements.txt /tmp/requirements.lock \
 && for tool in pip pip3 uv uvx; do rm -f "/usr/local/bin/$tool" "/usr/bin/$tool"; done \
 && groupadd --gid 10001 aionex \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin aionex \
 && chown -R root:root /opt/triposr /models && chmod -R go-w /opt/triposr /models
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/aionex-hf HOME=/tmp PYTHONDONTWRITEBYTECODE=1 AIONEX_TRIPOSR_WORKDIR=/tmp/aionex-triposr
USER aionex
WORKDIR /opt/triposr
RUN python -I -c "import sys; sys.path.insert(0, '/opt/triposr'); import handler; handler.install_runtime_guards(); assert handler.handler({'input': {}}) == {'error': 'input.image required'}; assert 'error' in handler.handler({'input': {'image': 'eA==', 'model': 'x'}}); print('TripoSR hardened runtime contract: PASS')"
ENTRYPOINT ["python","-u","/opt/triposr/handler.py"]
