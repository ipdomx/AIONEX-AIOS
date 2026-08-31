# Phase 34C full textured/PBR worker. Base contains Hunyuan3D 2.1 shape+paint weights.
FROM ipdomx/aionex-hunyuan3d@sha256:e4220d58bbef3fc6ba06cb28f02bda35fcb9a0bd2232de77ab0cdd7f52180cc3

USER root

# Install only the inference/post-processing runtime we need, then update the
# inherited Ubuntu userspace before removing server, compiler and development
# baggage that is not part of the RunPod serverless execution path.
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y --no-install-recommends blender python3-numpy curl ca-certificates; \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; \
    apt-get install -y --no-install-recommends nodejs; \
    npm install -g @gltf-transform/cli@4.4.2; \
    cd /usr/lib/node_modules/@gltf-transform/cli; \
    npm install --omit=dev --no-audit --no-fund --save-exact sharp@0.35.4; \
    apt-get update; \
    apt-get dist-upgrade -y; \
    apt-get purge -y --auto-remove \
      linux-libc-dev \
      python3.11-dev libpython3.11-dev \
      openssh-server openssh-sftp-server \
      nginx nginx-core nginx-common \
      packagekit gir1.2-packagekitglib-1.0 libpackagekit-glib2-18 \
      git git-man gnupg2; \
    apt-get purge -y \
      python3.11 python3.11-minimal python3.11-venv \
      libpython3.11-stdlib libpython3.11-minimal || true; \
    rm -rf \
      /usr/local/lib/python3.11 \
      /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx \
      /var/lib/apt/lists/* /root/.npm /root/.cache; \
    find /usr/local/bin -maxdepth 1 -type f -exec sh -c \
      'head -1 "$1" 2>/dev/null | grep -qE "python3\\.11|/usr/local/bin/python" && rm -f "$1" || true' _ '{}' ';'; \
    node --version; \
    gltf-transform --version; \
    test ! -e /usr/sbin/sshd; \
    test ! -e /usr/sbin/nginx; \
    test ! -e /usr/bin/npm; \
    test ! -e /usr/bin/python3.11

# Security-updated, inference-compatible Python runtime.  Gradio is not served
# by this image; RunPod's serverless SDK is the only network runtime.  Keep
# Transformers on the 4.x line required by the baked Hunyuan stack; model paths
# are fixed to image-local assets by handler.py and never accepted from users.
RUN set -eux; \
    /opt/hunyuan-venv/bin/pip install --no-cache-dir --upgrade \
      "setuptools==80.10.2" \
      "msgpack==1.2.1" \
      "ninja==1.13.0" \
      "pillow==12.3.0" \
      "cryptography==50.0.0" \
      "diffusers==0.38.0" \
      "protobuf==5.29.6" \
      "transformers==4.48.0" \
      "runpod==1.12.0" \
      "fastapi==0.141.1" \
      "starlette==1.6.0" \
      "tb-nightly==2.21.0a20251023"; \
    /opt/hunyuan-venv/bin/pip uninstall -y gradio gradio-client || true; \
    /opt/hunyuan-venv/bin/pip check; \
    rm -rf /root/.cache

RUN /opt/hunyuan-venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('facebook/dinov2-giant', revision='611a9d42f2335e0f921f1e313ad3c1b7178d206d', local_dir='/models/dinov2-giant')"
COPY patch_hunyuan_runtime.py /opt/patch_hunyuan_runtime.py
RUN /opt/hunyuan-venv/bin/python /opt/patch_hunyuan_runtime.py \
 && grep -q 'os.path.isdir(config.multiview_pretrained_path)' /opt/Hunyuan3D-2.1/hy3dpaint/utils/multiview_utils.py \
 && grep -q '/models/dinov2-giant' /opt/Hunyuan3D-2.1/hy3dpaint/textureGenPipeline.py
COPY handler.py /opt/handler.py
COPY phase34c_blender.py /opt/phase34c_blender.py

# Runtime inference is deliberately offline. All model assets are baked under
# /models during the image build; the request contract exposes no repository or
# checkpoint selector. This also prevents future accidental Hub lookups.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1

# Build-time contract: exact hardened runtime remains importable and the handler
# rejects an empty job before model initialization/provider work.
RUN set -eux; \
    /opt/hunyuan-venv/bin/python - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("aionex_hunyuan_handler", "/opt/handler.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.handler)
assert module.handler({"input": {}}) == {"error": "input.image required"}
print("Hunyuan handler contract: PASS")
PY

ENTRYPOINT ["/opt/hunyuan-venv/bin/python","-u","/opt/handler.py"]
