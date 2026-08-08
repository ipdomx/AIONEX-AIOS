from __future__ import annotations
import base64
from io import BytesIO
import logging
from pathlib import Path
import sys
import uuid
import runpod
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('aionex-hunyuan3d-worker')

ROOT = Path('/opt/Hunyuan3D-2.1')
MODEL_ROOT = Path('/models/Hunyuan3D-2.1')
SAVE = Path('/workspace/gradio_cache')
SAVE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'hy3dshape'))

_PIPE = None

def get_pipe():
    global _PIPE
    if _PIPE is None:
        log.info('loading Hunyuan3D pipeline from %s', MODEL_ROOT)
        from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline
        _PIPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            str(MODEL_ROOT), subfolder='hunyuan3d-dit-v2-1'
        )
        log.info('Hunyuan3D pipeline loaded')
    return _PIPE

def handler(job: dict) -> dict:
    try:
        payload = job.get('input') or {}
        raw = payload.get('image') if isinstance(payload, dict) else None
        if not raw:
            return {'error': 'input.image required'}
        image = Image.open(BytesIO(base64.b64decode(raw))).convert('RGBA')
        mesh = get_pipe()(image=image)[0]
        path = SAVE / f'{uuid.uuid4()}_shape.glb'
        mesh.export(path)
        body = path.read_bytes()
        log.info('generated GLB %s bytes=%s', path.name, len(body))
        return {
            'filename': path.name,
            'content_type': 'model/gltf-binary',
            'size_bytes': len(body),
            'content_base64': base64.b64encode(body).decode('ascii'),
        }
    except Exception as exc:
        log.exception('handler failed')
        return {'error': f'{type(exc).__name__}: {exc}'}

if __name__ == '__main__':
    log.info('starting RunPod serverless handler')
    runpod.serverless.start({'handler': handler})
