"""Installation boundary regressions: no host writes or privileged execution.

The I/O fixture models installation; these separate tests exercise the actual
production boundary, including its invocation before any command or receipt IO.
"""
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts.security import fr06_execution_enrollment as m


@pytest.mark.parametrize("uid", [1, 1000, 65534])
def test_real_entry_rejects_nonroot_before_any_command_or_receipt(uid, monkeypatch):
    from scripts.security import fr06_source_operator as operator
    def forbidden(*args, **kwargs):
        raise AssertionError("permission denial must precede I/O")
    monkeypatch.setattr(m, "os", SimpleNamespace(geteuid=lambda: uid))
    monkeypatch.setattr(operator, "command", forbidden)
    monkeypatch.setattr(m, "read_bounded", forbidden)
    with pytest.raises(m.EnrollmentBlocked, match="fixed installed root required"):
        m.verify_installed_routes(source_root=m.ROOT, guard_root=m.GUARD, enrollment={})


@pytest.mark.parametrize("wrong", ["source", "guard", "both"])
def test_root_does_not_authorize_alternative_installation_paths(wrong, monkeypatch):
    monkeypatch.setattr(m, "os", SimpleNamespace(geteuid=lambda: 0))
    source=m.ROOT if wrong == "guard" else Path("/not-installed/source")
    guard=m.GUARD if wrong == "source" else Path("/not-installed/guard")
    with pytest.raises(m.EnrollmentBlocked, match="fixed installed root required"):
        m._require_installed_context(source, guard)


def test_real_entry_rejects_uninstalled_module_even_with_root_identity(monkeypatch):
    from scripts.security import fr06_source_operator as operator
    def forbidden(*args, **kwargs):
        raise AssertionError("installation denial must precede I/O")
    monkeypatch.setattr(m, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(m, "__file__", "/not-installed/fr06_execution_enrollment.py")
    monkeypatch.setattr(operator, "command", forbidden)
    monkeypatch.setattr(m, "read_bounded", forbidden)
    with pytest.raises(m.EnrollmentBlocked, match="uninstalled enrollment verifier"):
        m.verify_installed_routes(source_root=m.ROOT, guard_root=m.GUARD, enrollment={})


def test_exact_synthetic_installed_context_alone_returns_no_authority(monkeypatch):
    monkeypatch.setattr(m, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(m, "__file__", str(m.ROOT/"scripts/security/fr06_execution_enrollment.py"))
    assert m._require_installed_context(m.ROOT, m.GUARD) is None
