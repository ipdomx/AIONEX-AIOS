from pathlib import Path

multiview = Path('/opt/Hunyuan3D-2.1/hy3dpaint/utils/multiview_utils.py')
text = multiview.read_text()
old = '''        model_path = huggingface_hub.snapshot_download(\n            repo_id=config.multiview_pretrained_path,\n            allow_patterns=["hunyuan3d-paintpbr-v2-1/*"],\n        )\n'''
new = '''        if os.path.isdir(config.multiview_pretrained_path):\n            model_path = config.multiview_pretrained_path\n        else:\n            model_path = huggingface_hub.snapshot_download(\n                repo_id=config.multiview_pretrained_path,\n                allow_patterns=["hunyuan3d-paintpbr-v2-1/*"],\n            )\n'''
if old not in text and new not in text:
    raise SystemExit('multiview patch target missing')
if old in text:
    multiview.write_text(text.replace(old, new))

texture = Path('/opt/Hunyuan3D-2.1/hy3dpaint/textureGenPipeline.py')
text = texture.read_text()
text = text.replace('self.dino_ckpt_path = "facebook/dinov2-giant"', 'self.dino_ckpt_path = "/models/dinov2-giant"')
texture.write_text(text)

unet = Path('/opt/Hunyuan3D-2.1/hy3dpaint/hunyuanpaintpbr/unet/model.py')
text = unet.read_text()
text = text.replace('Dino_v2("facebook/dinov2-giant")', 'Dino_v2("/models/dinov2-giant")')
unet.write_text(text)
