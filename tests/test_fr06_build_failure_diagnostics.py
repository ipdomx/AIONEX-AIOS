"""Offline real-process tests for bounded, non-disclosing build diagnostics."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web-dashboard/backend/scripts/build_gitleaks.py"
spec = importlib.util.spec_from_file_location("build_failure_diagnostics", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PREFIX = "AIONEX_BUILD_FAILURE "


def invoke(tmp_path: Path, code: str, *, name: str = "download.log", timeout: float = 5) -> None:
    m.run([sys.executable, "-c", code], tmp_path, {"LANG": "C.UTF-8"}, tmp_path / name, timeout=timeout)


def diagnostic(capsys: pytest.CaptureFixture[str]) -> dict:
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count(PREFIX) == 1
    assert captured.err.startswith(PREFIX)
    return json.loads(captured.err.removeprefix(PREFIX))


def test_failed_download_exposes_safe_category_without_losing_failure(tmp_path, capsys):
    with pytest.raises(RuntimeError, match="Pinned build step failed"):
        invoke(tmp_path, "import sys; print('proxy: 503 Service Unavailable', file=sys.stderr); sys.exit(7)")
    result = diagnostic(capsys)
    assert result["event"] == "pinned_build_step_failure"
    assert result["return_code"] == 7
    assert result["error_categories"] == ["http_5xx"]
    assert result["timed_out"] is False
    assert "503 Service Unavailable" in (tmp_path / "download.log").read_text()


@pytest.mark.parametrize("message,category", [
    ("checksum mismatch", "checksum_mismatch"),
    ("SECURITY ERROR: sums do not match", "checksum_mismatch"),
    ("429 Too Many Requests", "http_429"),
    ("500 Internal Server Error", "http_5xx"),
    ("502 Bad Gateway", "http_5xx"),
    ("503 Service Unavailable", "http_5xx"),
    ("504 Gateway Timeout", "http_5xx"),
    ("403 Forbidden", "http_403"),
    ("404 Not Found", "http_404"),
    ("i/o timeout", "network_timeout"),
    ("TLS handshake timeout", "network_timeout"),
    ("no such host", "dns_failure"),
    ("connection reset by peer", "connection_reset"),
    ("x509: certificate signed by unknown authority", "tls_certificate"),
    ("no space left on device", "disk_full"),
    ("permission denied", "permission_denied"),
    ("unknown revision v0.0.0", "module_revision_missing"),
    ("unrecognized upstream response", "unclassified"),
])
def test_categories_are_fixed_labels_not_raw_output(tmp_path, capsys, message, category):
    with pytest.raises(RuntimeError):
        invoke(tmp_path, f"import sys; print({message!r}); sys.exit(1)")
    result = diagnostic(capsys)
    assert result["error_categories"] == [category]
    assert message not in json.dumps(result)


def test_success_preserves_log_without_emitting_failure(tmp_path, capsys):
    invoke(tmp_path, "print('ok')")
    assert capsys.readouterr() == ("", "")
    assert (tmp_path / "download.log").read_text() == "ok\n"


def test_unknown_failure_never_emits_credentials_urls_or_terminal_controls(tmp_path, capsys):
    secret = "SYNTHETIC-DO-NOT-EXPOSE-credential"
    payload = "https://user:" + secret + "@example.invalid/private?q=" + secret + "\x1b[31m\x00\u202e"
    with pytest.raises(RuntimeError):
        invoke(tmp_path, f"import sys; print({payload!r}); sys.exit(1)")
    result = diagnostic(capsys)
    encoded = json.dumps(result)
    assert secret not in encoded and "example.invalid" not in encoded
    assert "user:" not in encoded and "\\u001b" not in encoded
    assert result["error_categories"] == ["unclassified"]
    assert secret in (tmp_path / "download.log").read_text()


def test_timeout_still_raises_original_timeout_and_emits_summary(tmp_path, capsys):
    with pytest.raises(subprocess.TimeoutExpired):
        invoke(tmp_path, "import time; print('waiting', flush=True); time.sleep(10)", timeout=0.15)
    result = diagnostic(capsys)
    assert result["timed_out"] is True
    assert result["return_code"] is None


def test_failure_reads_only_bounded_tail(tmp_path, capsys):
    with pytest.raises(RuntimeError):
        invoke(tmp_path, "import sys; sys.stdout.write('x'*200000+'\\nno space left on device\\n'); sys.exit(1)")
    result = diagnostic(capsys)
    assert result["log_bytes"] > 200000
    assert result["bytes_examined"] == 65536
    assert result["tail_only"] is True
    assert result["error_categories"] == ["disk_full"]
    assert len(result["tail_sha256"]) == 64


def test_binary_log_is_retained_and_diagnostic_remains_json(tmp_path, capsys):
    with pytest.raises(RuntimeError):
        invoke(tmp_path, "import os; os.write(1,b'\\xff\\xfe checksum mismatch'); raise SystemExit(1)")
    result = diagnostic(capsys)
    assert result["error_categories"] == ["checksum_mismatch"]
    assert (tmp_path / "download.log").read_bytes().startswith(b"\xff\xfe")


def test_existing_log_cannot_be_overwritten_or_command_started(tmp_path, capsys):
    (tmp_path / "download.log").write_text("preserve")
    with pytest.raises(FileExistsError):
        invoke(tmp_path, "from pathlib import Path; Path('unexpected').touch()")
    assert not (tmp_path / "unexpected").exists()
    assert (tmp_path / "download.log").read_text() == "preserve"
    assert capsys.readouterr() == ("", "")


def test_replaced_log_path_does_not_redirect_diagnostic_read(tmp_path, capsys):
    replacement = tmp_path / "other-private-file"
    replacement.write_text("checksum mismatch SYNTHETIC_PRIVATE_CONTENT")
    code = ("import os; from pathlib import Path; "
            "Path('download.log').rename('original.log'); "
            "Path('download.log').symlink_to('other-private-file'); "
            "os.write(1,b'503 Service Unavailable'); raise SystemExit(1)")
    with pytest.raises(RuntimeError):
        invoke(tmp_path, code)
    result = diagnostic(capsys)
    assert result["error_categories"] == ["http_5xx"]
    assert replacement.read_text() == "checksum mismatch SYNTHETIC_PRIVATE_CONTENT"


def test_diagnostic_never_includes_log_path_or_command(tmp_path, capsys):
    with pytest.raises(RuntimeError):
        invoke(tmp_path, "raise SystemExit(1)", name="synthetic-sensitive-name.log")
    result = diagnostic(capsys)
    text = json.dumps(result)
    assert str(tmp_path) not in text
    assert "synthetic-sensitive-name" not in text
    assert "raise SystemExit" not in text


def test_report_does_not_retry_or_turn_failure_into_success(tmp_path, capsys):
    code = ("from pathlib import Path; p=Path('invocations'); "
            "p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
            "print('503 Service Unavailable'); raise SystemExit(1)")
    with pytest.raises(RuntimeError):
        invoke(tmp_path, code)
    diagnostic(capsys)
    assert (tmp_path / "invocations").read_text() == "x"


def test_checksum_failure_is_reported_even_with_transport_marker(tmp_path, capsys):
    with pytest.raises(RuntimeError):
        invoke(tmp_path, "print('503 Service Unavailable; checksum mismatch'); raise SystemExit(1)")
    result = diagnostic(capsys)
    assert result["error_categories"] == ["checksum_mismatch", "http_5xx"]
