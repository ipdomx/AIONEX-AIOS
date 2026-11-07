# AIONEX headless Blender converter sidecar (roadmap 2.4, FR-16).
#
# Reproducible inputs: base image by immutable digest, Blender by exact version
# and the SHA-256 published by blender.org, verified before extraction. Runtime:
# non-root, no network (compose `network_mode: none`), read-only root, factory
# startup with add-on/script auto-execution disabled.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS fetch
ARG BLENDER_SERIES=5.2
ARG BLENDER_VERSION=5.2.3
ARG BLENDER_SHA256=78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    curl -fsSL --retry 8 --retry-all-errors --connect-timeout 20 -o /tmp/blender.tar.xz \
      "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz"; \
    printf '%s  %s\n' "$BLENDER_SHA256" /tmp/blender.tar.xz | sha256sum -c -; \
    mkdir -p /opt/blender; \
    tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 --no-same-owner --no-same-permissions; \
    rm -f /tmp/blender.tar.xz; \
    test -x /opt/blender/blender
# Blender's bundled Python ships networking/packaging modules that only serve
# online extension repositories and pip. Offline headless conversion never uses
# them; removing them shrinks the attack surface and the scanned inventory.
RUN set -eux; \
    py="$(find /opt/blender -maxdepth 3 -type d -name python -path "*/${BLENDER_SERIES}/python")"; \
    test -n "$py"; \
    site="$(find "$py/lib" -maxdepth 2 -type d -name site-packages)"; \
    for pkg in pip setuptools wheel requests urllib3 certifi idna charset_normalizer; do \
      rm -rf "$site/$pkg" "$site"/${pkg}-*.dist-info "$site"/${pkg}-*.egg-info; \
    done; \
    rm -rf "$py"/lib/python3.*/ensurepip "$py"/bin/pip*; \
    ls "$site"

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS runtime
ARG BLENDER_SERIES=5.2
ARG BLENDER_VERSION=5.2.3
# Shared libraries the official Linux build links against; GHOST runs headless
# (--background), so no display server is installed.
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get dist-upgrade -y; \
    apt-get install -y --no-install-recommends \
      python3 \
      libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 \
      libgl1 libegl1 libglx0 libopengl0 libgomp1 libxext6 libxcursor1 libxinerama1 libxrandr2 libwayland-client0 libdecor-0-0; \
    apt-get purge -y --auto-remove linux-libc-dev || true; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/*; \
    userdel --remove ubuntu 2>/dev/null || true; \
    groupadd --gid 1000 aionex; \
    useradd --uid 1000 --gid 1000 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin aionex; \
    install -d -m 0770 -o aionex -g aionex /var/lib/aionex/three-d-conversion
COPY --from=fetch /opt/blender /opt/blender
COPY three_d_convert.py converter_daemon.py /opt/aionex/
RUN set -eux; \
    chown -R root:root /opt/blender /opt/aionex; \
    chmod -R go-w /opt/blender /opt/aionex; \
    missing="$(ldd /opt/blender/blender | grep 'not found' || true)"; \
    test -z "$missing" || { echo "$missing" >&2; exit 1; }
ENV AIONEX_BLENDER_BINARY=/opt/blender/blender \
    AIONEX_BLENDER_SCRIPT=/opt/aionex/three_d_convert.py \
    AIONEX_BLENDER_SERIES=${BLENDER_SERIES} \
    AIONEX_CONVERTER_SPOOL=/var/lib/aionex/three-d-conversion \
    PYTHONDONTWRITEBYTECODE=1
USER aionex
# Build-time functional contract: the exact pinned Blender converts a generated
# cube GLB to OBJ, FBX and USDZ and renders a preview, all offline and headless.
RUN set -eux; \
    export HOME=/tmp/aionex-contract TMPDIR=/tmp/aionex-contract; \
    mkdir -p -m 0700 "$HOME"; \
    /opt/blender/blender --factory-startup --version | head -1 | grep -Eq "^Blender ${BLENDER_VERSION}( LTS)?$"; \
    /opt/blender/blender --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 \
      --python-expr "import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.mesh.primitive_cube_add(); bpy.ops.export_scene.gltf(filepath='$HOME/cube.glb', export_format='GLB')"; \
    mkdir -p "$HOME/job"; cp "$HOME/cube.glb" "$HOME/job/input.glb"; \
    printf '%s' '{"input_format":"glb","formats":["obj","fbx","usdz"],"thumbnail":true}' > "$HOME/job/request.json"; \
    python3 -I - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/opt/aionex")
import converter_daemon as daemon
daemon.THUMBNAIL_SIZE = 64
job = Path(os.environ["HOME"]) / "job"
result = daemon.process_request(job)
print(json.dumps(result))
assert result["ok"], result
for kind in ("obj", "fbx", "usdz", "thumbnail"):
    assert result["results"].get(kind, {}).get("ok"), (kind, result)
assert (job / "out" / "fbx" / "model.fbx").read_bytes().startswith(b"Kaydara FBX Binary")
assert (job / "out" / "usdz" / "model.usdz").read_bytes().startswith(b"PK\x03\x04")
assert (job / "out" / "preview.png").read_bytes().startswith(b"\x89PNG")
print("Blender converter contract: PASS")
PY
RUN rm -rf /tmp/aionex-contract
WORKDIR /var/lib/aionex/three-d-conversion
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python3", "-I", "/opt/aionex/converter_daemon.py", "--healthcheck"]
ENTRYPOINT ["python3", "-I", "/opt/aionex/converter_daemon.py"]
