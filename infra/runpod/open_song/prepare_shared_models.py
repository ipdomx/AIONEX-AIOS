"""Build-only download of ACE-Step shared VAE/text-encoder components."""
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
