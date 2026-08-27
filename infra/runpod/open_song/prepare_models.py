"""Build-only download of exact public ACE-Step model revisions."""
from huggingface_hub import snapshot_download

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
