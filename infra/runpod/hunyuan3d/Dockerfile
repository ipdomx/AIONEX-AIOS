# AIONEX Hunyuan3D 2.1 PBR RunPod worker, FR-16D hardened rebuild.
#
# Replaces the quarantined image that was layered on an opaque, unreviewed base
# (ipdomx/aionex-hunyuan3d@sha256:e4220d58...). Everything here is rebuilt from
# pinned public inputs:
#   * base images by immutable digest (pytorch 2.10.0 / CUDA 12.8 / cuDNN 9)
#   * Hunyuan3D-2.1 source at the reviewed commit, patched by
#     patch_hunyuan_runtime.py (no Hub/code downloads, no pickle, no shells)
#   * Python packages from requirements.lock with --require-hashes --no-deps
#   * Blender and Node by exact version + published SHA-256
#   * gltf-transform/sharp from package-lock.json (npm integrity hashes)
#   * model weights from pinned revisions, SHA-256 verified, converted to
#     safetensors in a throwaway stage (fetch_weights.py)
#
# Targets:
#   runtime  code + dependencies, no weights. Built and scanned in CI.
#   release  runtime + verified safetensors weights. Built for RunPod in the
#            pre-launch window (FR16D receipt, T-11). Same package inventory.
ARG CUDA_DEVEL=pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel@sha256:b574d4ccf6d8856a5d87dcadc667aa4f95dc18d337ef3a28d02b7b01897d7081
ARG CUDA_RUNTIME=pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime@sha256:b85566342b86d13a67712e9315d40cdc2dad7f8d86df1aff3831f80835edbcca

# ---------------------------------------------------------------- source/build
FROM ${CUDA_DEVEL} AS source
ARG HUNYUAN_COMMIT=82920d643c0dc2f7bfd7255f45f62d386edfe60c
ARG TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_BREAK_SYSTEM_PACKAGES=1
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*cuda* /etc/apt/sources.list.d/*nvidia*; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates g++; \
    rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    git init -q /opt/Hunyuan3D-2.1; \
    cd /opt/Hunyuan3D-2.1; \
    git remote add origin https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git; \
    git fetch -q --depth 1 origin "$HUNYUAN_COMMIT"; \
    git checkout -q FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "$HUNYUAN_COMMIT"; \
    rm -rf .git
COPY build-requirements.lock /tmp/build-requirements.lock
COPY patch_hunyuan_runtime.py /opt/patch/patch_hunyuan_runtime.py
COPY overrides /opt/patch/overrides
RUN set -eux; \
    python -m pip install --require-hashes --no-deps -r /tmp/build-requirements.lock; \
    python /opt/patch/patch_hunyuan_runtime.py /opt/Hunyuan3D-2.1; \
    cd /opt/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer; \
    TORCH_CUDA_ARCH_LIST="$TORCH_CUDA_ARCH_LIST" python -m pip wheel --no-deps --no-build-isolation -w /opt/wheels .; \
    rm -rf build *.egg-info; \
    cd /opt/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer; \
    c++ -O3 -Wall -shared -std=c++11 -fPIC $(python -m pybind11 --includes) mesh_inpaint_processor.cpp \
      -o "mesh_inpaint_processor$(python -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"; \
    ls /opt/wheels

# ------------------------------------------------------------------ toolchains
FROM ${CUDA_RUNTIME} AS tools
ARG BLENDER_SERIES=5.2
ARG BLENDER_VERSION=5.2.3
ARG BLENDER_SHA256=78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec
ARG NODE_VERSION=v24.22.2
ARG NODE_SHA256=48cc0e21e048790e54c0cf5749c2725005313d652651c40b7a21feb9697aaf75
ENV DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*cuda* /etc/apt/sources.list.d/*nvidia*; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    curl -fsSL --retry 8 --retry-all-errors -o /tmp/blender.tar.xz \
      "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz"; \
    printf '%s  %s\n' "$BLENDER_SHA256" /tmp/blender.tar.xz | sha256sum -c -; \
    mkdir -p /opt/blender; \
    tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 --no-same-owner --no-same-permissions; \
    site="$(find /opt/blender -maxdepth 5 -type d -name site-packages -path "*/${BLENDER_SERIES}/python/*")"; \
    for pkg in pip setuptools wheel requests urllib3 certifi idna charset_normalizer; do \
      rm -rf "$site/$pkg" "$site"/${pkg}-*.dist-info "$site"/${pkg}-*.egg-info; \
    done; \
    rm -rf /tmp/blender.tar.xz /opt/blender/${BLENDER_SERIES}/python/lib/python3.*/ensurepip
RUN set -eux; \
    curl -fsSL --retry 8 --retry-all-errors -o /tmp/node.tar.xz \
      "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"; \
    printf '%s  %s\n' "$NODE_SHA256" /tmp/node.tar.xz | sha256sum -c -; \
    mkdir -p /opt/node; \
    tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 --no-same-owner; \
    rm -f /tmp/node.tar.xz
COPY gltf-tools/package.json gltf-tools/package-lock.json /opt/gltf-tools/
RUN set -eux; \
    cd /opt/gltf-tools; \
    PATH="/opt/node/bin:$PATH" npm ci --omit=dev --ignore-scripts --no-audit --no-fund; \
    rm -rf /root/.npm /opt/node/lib/node_modules/npm /opt/node/lib/node_modules/corepack \
           /opt/node/bin/npm /opt/node/bin/npx /opt/node/bin/corepack /opt/node/include /opt/node/share; \
    /opt/node/bin/node /opt/gltf-tools/node_modules/@gltf-transform/cli/bin/cli.js --version

# ---------------------------------------------------------------- dependencies
FROM ${CUDA_RUNTIME} AS deps
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_BREAK_SYSTEM_PACKAGES=1 PYTHONUNBUFFERED=1
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*cuda* /etc/apt/sources.list.d/*nvidia*; \
    apt-get update; \
    apt-get dist-upgrade -y; \
    apt-get install -y --no-install-recommends ca-certificates libgl1 libegl1 libglx0 libopengl0 libglib2.0-0 libgomp1 \
      libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 libxext6 libxcursor1 libxinerama1 libxrandr2 libwayland-client0 libdecor-0-0; \
    apt-get purge -y --auto-remove linux-libc-dev curl gnupg gnupg-l10n gnupg-utils gpg gpg-agent gpgconf gpgsm dirmngr || true; \
    rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
COPY --from=source /opt/wheels /tmp/wheels
RUN set -eux; \
    python -m pip install --require-hashes --no-deps --no-build-isolation -r /tmp/requirements.lock; \
    python -m pip install --no-deps --no-index /tmp/wheels/*.whl; \
    python -m pip uninstall -y spin; \
    python -m pip check; \
    rm -rf /tmp/wheels /tmp/requirements.lock /root/.cache

# --------------------------------------------------------------------- weights
FROM deps AS weights
COPY weights.lock.json fetch_weights.py /opt/weights/
# The converted safetensors are written 0600; the non-root runtime user must read them
# (T-18 build 2026-11-09 failed the release manifest check with "Permission denied").
RUN python /opt/weights/fetch_weights.py /opt/weights/weights.lock.json /models \
 && chmod -R a+rX,go-w /models

# --------------------------------------------------------------------- runtime
FROM deps AS runtime
COPY --from=source /opt/Hunyuan3D-2.1 /opt/Hunyuan3D-2.1
COPY --from=tools /opt/blender /opt/blender
COPY --from=tools /opt/node /opt/node
COPY --from=tools /opt/gltf-tools /opt/gltf-tools
COPY handler.py input_guard.py phase34c_blender.py /opt/
RUN set -eux; \
    test -e /opt/gltf-tools/node_modules/.bin/gltf-transform; \
    python -m pip uninstall -y uv wheel setuptools; \
    python -m pip uninstall -y pip || true; \
    rm -rf /root/.cache; \
    for tool in pip pip3 uv uvx; do rm -f "/usr/local/bin/$tool" "/usr/bin/$tool"; done; \
    groupadd --gid 10001 aionex; \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin aionex; \
    chown -R root:root /opt/Hunyuan3D-2.1 /opt/blender /opt/node /opt/gltf-tools /opt/handler.py /opt/input_guard.py /opt/phase34c_blender.py; \
    chmod -R go-w /opt/Hunyuan3D-2.1 /opt/blender /opt/node /opt/gltf-tools
# Runtime inference is offline. Model assets are baked under /models (release
# target) and the request contract exposes no repository/checkpoint selector.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    DIFFUSERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/aionex-hf \
    HOME=/tmp \
    PATH=/opt/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    AIONEX_HUNYUAN_WORKDIR=/tmp/aionex-hunyuan
USER aionex
# Build-time contracts: pinned toolchain versions, hardened imports and early
# request rejection, all without a GPU or model weights.
RUN set -eux; \
    /opt/blender/blender --factory-startup --version | head -1 | grep -Eq '^Blender 5\.2\.3( LTS)?$'; \
    /opt/gltf-tools/node_modules/.bin/gltf-transform --version; \
    cd /opt && python -I - <<'PY'
import sys, types
sys.path.insert(0, "/opt")
import handler
handler.install_runtime_guards()
handler._prepare_import_path()
assert handler.handler({"input": {}}) == {"error": "input.image required"}
assert "error" in handler.handler({"input": {"image": "x" * 64, "trust_remote_code": True}})
import torch
try:
    torch.load("/nonexistent")
except RuntimeError as exc:
    assert "disabled" in str(exc)
else:
    raise AssertionError("torch.load guard missing")
sys.modules.setdefault("bpy", types.ModuleType("bpy"))
from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline  # noqa: F401
from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline  # noqa: F401
from hunyuanpaintpbr.pipeline import HunyuanPaintPipeline  # noqa: F401
from hunyuanpaintpbr.unet.modules import UNet2p5DConditionModel  # noqa: F401
from utils.image_super_utils import imageSuperNet  # noqa: F401
import custom_rasterizer  # noqa: F401
print("Hunyuan hardened runtime contract: PASS")
PY
ENTRYPOINT ["python", "-u", "/opt/handler.py"]

# --------------------------------------------------------------------- release
FROM runtime AS release
COPY --from=weights --chown=root:root /models /models
RUN cd /models && sha256sum --check --strict --quiet MANIFEST.sha256 && echo "model manifest verified"
