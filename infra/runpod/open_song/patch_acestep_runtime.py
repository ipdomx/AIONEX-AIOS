"""Build-only narrow patch for ACE-Step selected-model offline initialization.

ACE-Step 1.5's generic precheck requires every component from the default main
model bundle, including Turbo DiT and the 1.7B LM, even when a caller selects a
separately downloaded Base DiT and 4B LM. The actual loader only needs the
selected DiT plus the official VAE and Qwen text encoder. AIONEX bakes those
exact components and disables runtime downloads, so this patch narrows the
precheck to the components that the selected runtime actually loads.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

TARGET = Path("/app/acestep/core/generation/handler/init_service_downloads.py")
EXPECTED_UPSTREAM_SHA256 = (
    "02a95f2293dc0cd82ff5046816503668f8339157ba0b18715e061f3142999f8f"
)

source = TARGET.read_text(encoding="utf-8")
observed = hashlib.sha256(source.encode("utf-8")).hexdigest()
if observed != EXPECTED_UPSTREAM_SHA256:
    raise SystemExit(
        f"unexpected ACE-Step init_service_downloads.py sha256: {observed}"
    )

source = source.replace("    check_main_model_exists,\n", "")
source = source.replace("    ensure_main_model,\n", "")
old = """        if not check_main_model_exists(checkpoint_path):
            logger.info("[initialize_service] Main model not found, starting auto-download...")
            success, msg = ensure_main_model(checkpoint_path, prefer_source=prefer_source)
            if not success:
                return f"ERROR: Failed to download main model: {msg}", False
            logger.info(f"[initialize_service] {msg}")
"""
new = """        # AIONEX selects a separately pinned DiT + LM and runs offline. The
        # loader below still requires the official VAE and Qwen text encoder
        # from the main bundle, but it does not use the default Turbo DiT or
        # 1.7B LM. Fail closed on the actually required shared components
        # instead of triggering a runtime download of unused defaults.
        if not check_model_exists("Qwen3-Embedding-0.6B", checkpoint_path):
            return "ERROR: Required Qwen3 text encoder is unavailable", False
        if not check_vae_exists(DEFAULT_VAE_VARIANT, checkpoint_path):
            return "ERROR: Required official VAE is unavailable", False
"""
if old not in source:
    raise SystemExit("expected ACE-Step main-model precheck block not found")
source = source.replace(old, new, 1)
TARGET.write_text(source, encoding="utf-8")
print("patched_sha256=" + hashlib.sha256(source.encode("utf-8")).hexdigest())
