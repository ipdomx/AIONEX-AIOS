"""Build-only download of exact public ACE-Step model revisions."""
from huggingface_hub import snapshot_download

ACE_STEP_MAIN_MODEL_REVISION = "19671f406d603126926c1b7e2adc169acbcade22"

snapshot_download(
    repo_id="ACE-Step/Ace-Step1.5",
    revision=ACE_STEP_MAIN_MODEL_REVISION,
    local_dir="/app/checkpoints",
    allow_patterns=[
        "vae/*",
        "Qwen3-Embedding-0.6B/*",
    ],
)
snapshot_download(
    repo_id="ACE-Step/acestep-v15-base",
    revision="e432212fec32b8965a14ffa57ae653438d6abd14",
    local_dir="/app/checkpoints/acestep-v15-base",
)
snapshot_download(
    repo_id="ACE-Step/acestep-5Hz-lm-4B",
    revision="0a3ec94b557aea7d508da38b31cfe7341f6ff737",
    local_dir="/app/checkpoints/acestep-5Hz-lm-4B",
)
