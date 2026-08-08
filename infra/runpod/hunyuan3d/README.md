# AIONEX Hunyuan3D RunPod Serverless runtime

Known-good image digest:
`sha256:e4220d58bbef3fc6ba06cb28f02bda35fcb9a0bd2232de77ab0cdd7f52180cc3`

Required RunPod template settings:
- Container image: the pinned image/digest built from this directory.
- Container disk: 100 GB.
- Container start command / Docker command override: empty.
- Docker entrypoint override: empty.
- `RUNPOD_INIT_TIMEOUT=1800`.
- Serverless endpoint: min workers 0, max workers 1, GPU count 1, bounded execution timeout.

Do not commit API keys, model caches, generated GLBs, runtime logs, or cloned Hunyuan source trees here.

Phase 33 live acceptance produced a valid GLB (`glTF` magic) of 13,147,684 bytes before the test endpoint was deleted to prevent idle spend.
