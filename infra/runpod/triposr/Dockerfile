FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime@sha256:7b324d212a4450795b49edba9949b7cdc72429148a64e974334bfe5774d51385
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYOPENGL_PLATFORM=egl MGL_BACKEND=egl U2NET_HOME=/models/rembg
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y; \
    apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 libegl1; \
    apt-get purge -y --auto-remove linux-libc-dev curl gnupg gnupg-l10n gnupg-utils gpg gpg-agent gpgconf gpgsm dirmngr || true; \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 setuptools==80.9.0 wheel==0.46.3 \
 && python -m pip install --no-cache-dir -r /tmp/requirements.txt
RUN mkdir -p /models/TripoSR /models/dino-vitb16 /models/rembg \
 && python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='stabilityai/TripoSR', revision='5b521936b01fbe1890f6f9baed0254ab6351c04a', local_dir='/models/TripoSR')" \
 && cp -L /models/TripoSR/model.ckpt /models/TripoSR/model.ckpt.bin \
 && rm /models/TripoSR/model.ckpt \
 && mv /models/TripoSR/model.ckpt.bin /models/TripoSR/model.ckpt \
 && python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='facebook/dino-vitb16', revision='f205d5d8e640a89a2b8ef0369670dfc37cc07fc2', filename='config.json', local_dir='/models/dino-vitb16')" \
 && sed -i 's#facebook/dino-vitb16#/models/dino-vitb16#' /models/TripoSR/config.yaml \
 && U2NET_HOME=/models/rembg python -c "import rembg; rembg.new_session('u2net')"
COPY vendor/tsr /opt/triposr/tsr
COPY vendor/LICENSE /opt/triposr/LICENSE
COPY vendor/UPSTREAM_COMMIT /opt/triposr/UPSTREAM_COMMIT
COPY handler.py /opt/triposr/handler.py
RUN rm -rf /opt/conda/lib/python3.11/site-packages/pip* \
           /opt/conda/lib/python3.11/site-packages/setuptools* \
           /opt/conda/lib/python3.11/site-packages/wheel* \
           /root/.cache /tmp/requirements.txt \
 && rm -f /opt/conda/bin/pip /opt/conda/bin/pip3 /opt/conda/bin/pip3.11
WORKDIR /opt/triposr
ENTRYPOINT ["python","-u","/opt/triposr/handler.py"]
