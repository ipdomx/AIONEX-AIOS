# Known-good Phase 33 runtime layer with model weights baked in.
# Pin by digest to prevent tag drift.
FROM ipdomx/aionex-hunyuan3d@sha256:e4220d58bbef3fc6ba06cb28f02bda35fcb9a0bd2232de77ab0cdd7f52180cc3
COPY handler.py /opt/handler_lazy.py
ENTRYPOINT ["/opt/hunyuan-venv/bin/python","-u","/opt/handler_lazy.py"]
