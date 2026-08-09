# Phase 34C full textured/PBR worker. Base contains Hunyuan3D 2.1 shape+paint weights.
FROM ipdomx/aionex-hunyuan3d@sha256:e4220d58bbef3fc6ba06cb28f02bda35fcb9a0bd2232de77ab0cdd7f52180cc3

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends blender python3-numpy curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @gltf-transform/cli@4.4.2 \
 && rm -rf /var/lib/apt/lists/* /root/.npm
RUN /opt/hunyuan-venv/bin/pip install --no-cache-dir "setuptools<81"
RUN /opt/hunyuan-venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('facebook/dinov2-giant', local_dir='/models/dinov2-giant')"
COPY patch_hunyuan_runtime.py /opt/patch_hunyuan_runtime.py
RUN /opt/hunyuan-venv/bin/python /opt/patch_hunyuan_runtime.py \
 && grep -q 'os.path.isdir(config.multiview_pretrained_path)' /opt/Hunyuan3D-2.1/hy3dpaint/utils/multiview_utils.py \
 && grep -q '/models/dinov2-giant' /opt/Hunyuan3D-2.1/hy3dpaint/textureGenPipeline.py
COPY handler.py /opt/handler.py
COPY phase34c_blender.py /opt/phase34c_blender.py
ENTRYPOINT ["/opt/hunyuan-venv/bin/python","-u","/opt/handler.py"]
