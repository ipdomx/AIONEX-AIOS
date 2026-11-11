"""FR-16D source contracts for the hardened Hunyuan3D and TripoSR images.

Source-only: no Docker, GPU, network or RunPod. The image build and Trivy/SBOM
gate run in .github/workflows/fr16d-3d-runtime-container-security.yml.
"""
from __future__ import annotations

import base64
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
HUNYUAN = ROOT / "infra/runpod/hunyuan3d"
TRIPOSR = ROOT / "infra/runpod/triposr"
DOCKERFILE = (HUNYUAN / "Dockerfile").read_text()
POLICY = (ROOT / "web-dashboard/backend/app/services/three_d_provider_policy.py").read_text()


def _guard():
    # The guard runs in the GPU images; skip only its behaviour tests where the
    # contract job has no Pillow. Source contracts below never need it.
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("aionex_input_guard", HUNYUAN / "input_guard.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _image(mode: str, size: tuple[int, int], color: object = 0):
    image_module = pytest.importorskip("PIL.Image")
    return image_module.new(mode, size, color)


def _encode(image, fmt: str = "PNG") -> str:
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode()


def test_quarantine_gate_is_not_lifted_by_this_change() -> None:
    assert "HUNYUAN_RUNTIME_SECURITY_APPROVED = False" in POLICY
    roadmap = (ROOT / "docs/project/COMPLETION-ROADMAP.md").read_text()
    for item in ("T-18", "T-19", "O-10"):
        assert f"- [ ] {item} " in roadmap


def test_image_is_rebuilt_from_pinned_public_inputs_not_the_opaque_base() -> None:
    froms = re.findall(r"(?m)^ARG CUDA_(?:DEVEL|RUNTIME)=(\S+)$", DOCKERFILE)
    assert len(froms) == 2 and all(re.fullmatch(r"pytorch/pytorch:[^@]+@sha256:[0-9a-f]{64}", ref) for ref in froms)
    assert not re.search(r"(?m)^(FROM|ARG)\s.*ipdomx/aionex-hunyuan3d", DOCKERFILE)
    assert 'test "$(git rev-parse HEAD)" = "$HUNYUAN_COMMIT"' in DOCKERFILE
    assert "ARG HUNYUAN_COMMIT=82920d643c0dc2f7bfd7255f45f62d386edfe60c" in DOCKERFILE
    assert "82920d643c0dc2f7bfd7255f45f62d386edfe60c" in POLICY
    assert "USER aionex" in DOCKERFILE
    assert "| bash" not in DOCKERFILE and "npm install -g" not in DOCKERFILE


def test_python_dependencies_are_hash_locked_and_exclude_quarantined_stacks() -> None:
    assert "--require-hashes --no-deps --no-build-isolation -r /tmp/requirements.lock" in DOCKERFILE
    lock = (HUNYUAN / "requirements.lock").read_text()
    pins = re.findall(r"(?m)^([A-Za-z0-9_.\-]+)==(\S+) \\$", lock)
    assert len(pins) > 50
    blocks = re.split(r"(?m)^(?=[A-Za-z0-9])", lock)
    assert all("--hash=sha256:" in block for block in blocks if re.match(r"[A-Za-z0-9]", block))
    names = {name.lower() for name, _ in pins}
    assert not names & {"gradio", "pytorch-lightning", "basicsr", "realesrgan", "tb-nightly", "deepspeed", "open3d", "torch", "bpy"}
    assert "--extra-index-url" not in lock + (HUNYUAN / "requirements.in").read_text()


def test_weights_are_revision_pinned_checksummed_and_converted_to_safetensors() -> None:
    lock = json.loads((HUNYUAN / "weights.lock.json").read_text())
    files = [item for source in lock["sources"] for item in source["files"]]
    assert {source["revision"] for source in lock["sources"]} >= {"0b94677654c57bb9a6b6845cd7b704ccf551d327", "611a9d42f2335e0f921f1e313ad3c1b7178d206d"}
    for item in files:
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) and int(item["size"]) > 0
        assert not item["path"].endswith(".py"), "model code must come from the reviewed source only"
        if item["path"].endswith((".ckpt", ".bin", ".pth")):
            assert item["convert"]["to"].endswith(".safetensors")
    fetch = (HUNYUAN / "fetch_weights.py").read_text()
    assert "weights_only=True" in fetch and "assert_no_pickle(root)" in fetch
    assert "COPY --from=weights --chown=root:root /models /models" in DOCKERFILE
    # Weights must be world-readable but not writable: the runtime runs as a non-root user.
    assert "chmod -R a+rX,go-w /models" in DOCKERFILE
    assert "sha256sum --check --strict --quiet MANIFEST.sha256" in DOCKERFILE


def test_runtime_patches_remove_remote_code_pickle_and_shell_paths() -> None:
    patch = (HUNYUAN / "patch_hunyuan_runtime.py").read_text()
    for token in (
        "Hunyuan paint weights must be a baked local directory",
        "use_safetensors=True, local_files_only=True",
        "diffusion_pytorch_model.safetensors",
        "safetensors.torch.load_file(unet_ckpt_path",
        "from \\.unet\\.model import HunyuanPaint",
        "external mesh simplifier is disabled",
        "trust_remote_code enabled in",
        "shell execution remains in",
        "pickle load remains in",
    ):
        assert token in patch, token
    handler = (HUNYUAN / "handler.py").read_text()
    assert 'torch.load = _forbidden("torch.load (pickle)")' in handler
    assert "snapshot_download" in handler and "hf_hub_download" in handler
    assert "use_safetensors=True" in handler
    assert "shutil.rmtree(work, ignore_errors=True)" in handler
    assert "MAX_OUTPUT_BYTES" in handler and "_check_deadline" in handler
    override = (HUNYUAN / "overrides/image_super_utils.py").read_text()
    assert "torch.load(" not in override and "safetensors.torch.load_file" in override


def test_input_guard_copies_are_identical() -> None:
    assert (HUNYUAN / "input_guard.py").read_bytes() == (TRIPOSR / "input_guard.py").read_bytes()


def test_input_guard_accepts_a_normal_image() -> None:
    guard = _guard()
    image = guard.decode_image(_encode(_image("RGB", (128, 96), "red")))
    assert image.size == (128, 96) and image.mode == "RGBA"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "input.image required"),
        ("not base64!!", "not valid base64"),
        (base64.b64encode(b"GIF89a" + b"\x00" * 40).decode(), "could not be decoded|must be PNG"),
        ("A" * (16 * 1024 * 1024 + 4), "exceeds the size limit"),
    ],
)
def test_input_guard_rejects_bad_payloads(raw: str, message: str) -> None:
    guard = _guard()
    with pytest.raises(guard.InputError, match=message):
        guard.decode_image(raw)


def test_input_guard_blocks_decompression_bombs_and_tiny_or_animated_images() -> None:
    guard = _guard()
    with pytest.raises(guard.InputError, match="dimensions"):
        guard.decode_image(_encode(_image("1", (5000, 5000))))
    with pytest.raises(guard.InputError, match="dimensions"):
        guard.decode_image(_encode(_image("RGB", (32, 32))))
    frames = [_image("RGB", (80, 80), color) for color in ("red", "blue")]
    buffer = BytesIO()
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(guard.InputError, match="single frame"):
        guard.decode_image(base64.b64encode(buffer.getvalue()).decode())


def test_scalar_options_and_unknown_fields_are_rejected() -> None:
    guard = _guard()
    with pytest.raises(guard.InputError, match="unsupported input fields: trust_remote_code"):
        guard.reject_unknown_fields({"image": "x", "trust_remote_code": True}, frozenset({"image"}))
    for bad in (True, "7", -1, 2**31):
        with pytest.raises(guard.InputError):
            guard.bounded_int({"seed": bad}, "seed", 1, 0, guard.SEED_MAX)
    assert guard.bounded_int({}, "seed", 12345, 0, guard.SEED_MAX) == 12345


def test_triposr_is_hash_locked_safetensors_and_non_root() -> None:
    dockerfile = (TRIPOSR / "Dockerfile").read_text()
    assert "--require-hashes --no-deps" in dockerfile and "--no-index -r /tmp/requirements.txt" in dockerfile
    assert "USER aionex" in dockerfile and "fetch_models.py" in dockerfile
    fetch = (TRIPOSR / "fetch_models.py").read_text()
    assert "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee" in fetch
    assert "model.safetensors" in fetch and "checkpoint.unlink()" in fetch
    handler = (TRIPOSR / "handler.py").read_text()
    assert "safetensors.torch.load_file" in handler and "install_runtime_guards()" in handler
    requirements = (TRIPOSR / "requirements.txt").read_text()
    for pin in ("rembg==2.0.87", "msgpack==1.2.3", "Brotli==1.2.1"):
        assert pin in requirements
