"""CVE-2026-104851: keep the shipped TripoSR image off vulnerable fsspec."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIPOSR = ROOT / "infra/runpod/triposr"
FIXED = (2026, 6, 0)


def test_triposr_pins_single_patched_fsspec_direct_dependency():
    requirements = (TRIPOSR / "requirements.txt").read_text().splitlines()
    entries = [line.strip().lower() for line in requirements
               if line.strip() and not line.lstrip().startswith("#")]
    fsspec = [line for line in entries if line.split("==", 1)[0] == "fsspec"]
    assert len(fsspec) == 1, "CVE-2026-104851 must be explicitly fixed in the image build"
    assert fsspec[0].count("==") == 1
    version = fsspec[0].split("==", 1)[1]
    assert len(version.split(".")) == 3 and all(part.isdigit() for part in version.split("."))
    assert tuple(int(part) for part in version.split(".")) >= FIXED


def test_triposr_pinned_dependency_is_actually_installed_into_scanned_image():
    dockerfile = (TRIPOSR / "Dockerfile").read_text()
    workflow = (ROOT / ".github/workflows/phase34f-triposr-container-security.yml").read_text()
    assert "COPY requirements.txt /tmp/requirements.txt" in dockerfile
    assert "pip install --no-cache-dir -r /tmp/requirements.txt" in dockerfile
    assert "python -m pip check" in dockerfile
    assert "docker build --pull -t aionex-aios-triposr:phase34fg infra/runpod/triposr" in workflow
    assert "Fail on high or critical image vulnerabilities" in workflow
    assert "ignore-unfixed: false" in workflow
    assert 'severity: CRITICAL,HIGH' in workflow
    assert 'exit-code: "1"' in workflow
