"""Real wheel integrity/rewriting and pure installer-command contract tests."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


m = module("build_pip_vendor_wheel")
a = module("security_pip_audit")


def make_wheel(path, payload, dist, *, bad_hash=False, extra_record=False, symlink=False, duplicate=False):
    rows = [(n, m.record_hash(v), str(len(v))) for n, v in payload.items()]
    if bad_hash:
        rows[0] = (rows[0][0], "sha256=" + "0" * 43, rows[0][2])
    if extra_record:
        rows.append(("absent.py", m.record_hash(b""), "0"))
    record = dist + "/RECORD"
    rows.append((record, "", ""))
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    data = {**payload, record: buf.getvalue().encode()}
    with zipfile.ZipFile(path, "x") as z:
        for i, (name, content) in enumerate(data.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 29, 0, 0, 0))
            info.external_attr = ((stat.S_IFLNK if symlink and i == 0 else stat.S_IFREG) | 0o644) << 16
            z.writestr(info, content)
        if duplicate:
            with pytest.warns(UserWarning):
                z.writestr(next(iter(payload)), b"duplicate")
    return m.sha(path.read_bytes())


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    directory = tmp_path / "inputs"
    directory.mkdir()
    resources = b"""import sys,os
sys.path.extend(((vendor_path := os.path.join(os.path.dirname(os.path.dirname(__file__)), 'setuptools', '_vendor')) not in sys.path) * [vendor_path])  # fmt: skip
# workaround for #4476
sys.modules.pop('backports', None)
import packaging.markers
import packaging.requirements
import packaging.specifiers
import packaging.utils
import packaging.version
from jaraco.text import drop_comment, join_continuation, yield_lines
from platformdirs import user_cache_dir as _user_cache_dir
def example():
    return packaging.version.Version('1.0')
"""
    bom = {"components": [{"name": n, "version": v, "bom-ref": f"pkg:pypi/{n}@{v}", "purl": f"pkg:pypi/{n}@{v}", "type": "library"} for n, v in [("msgpack", "1.1.2"), ("setuptools", "70.3.0")]], "dependencies": [{"ref": "bom-ref:pip", "dependsOn": ["pkg:pypi/msgpack@1.1.2", "pkg:pypi/setuptools@70.3.0"]}, {"ref": "pkg:pypi/msgpack@1.1.2"}, {"ref": "pkg:pypi/setuptools@70.3.0"}], "metadata": {"component": {"name": "pip"}}}
    pipsrc = {m.OLD_DIST + "METADATA": b"Name: pip\nVersion: 26.2.1\n", "pip/__init__.py": b'__version__ = "26.2.1"\n', "pip/_internal/resolution.py": b"# Original resolver stays byte-identical.\n", "pip/_vendor/README.rst": b"Original policy\n", "pip/_vendor/vendor.txt": b"msgpack==1.1.2\nsetuptools==70.3.0\n", "pip/_vendor/bom.cdx.json": json.dumps(bom).encode(), "pip/_vendor/pkg_resources/__init__.py": b"old resource source\n", "pip/_vendor/requests/sessions.py": b"verify = True\n"}
    msgsrc = {"msgpack/" + n: ("# Actual refreshed " + n + "\n").encode() for n in ("__init__.py", "exceptions.py", "ext.py", "fallback.py")}
    msgsrc["msgpack-1.2.3.dist-info/licenses/COPYING"] = b"MessagePack test license\n"
    sources = {"pip": (pipsrc, "pip-26.2.1.dist-info"), "setuptools": ({"pkg_resources/__init__.py": resources, "setuptools-80.9.0.dist-info/licenses/LICENSE": b"Setuptools test license\n"}, "setuptools-80.9.0.dist-info"), "msgpack": (msgsrc, "msgpack-1.2.3.dist-info")}
    specifications = {}
    for name, (payload, dist) in sources.items():
        filename = m.INPUTS[name][0]
        digest = make_wheel(directory / filename, payload, dist)
        specifications[name] = (filename, digest, "https://example.invalid/fixture")
    monkeypatch.setattr(m, "INPUTS", specifications)
    return directory, sources


def test_real_vendor_bytes_update_with_truthful_bom_record_and_local_identity(inputs, tmp_path):
    directory, original = inputs
    result = m.build(directory, tmp_path / "out")
    path = tmp_path / "out" / result["wheel"]
    payload = m.verified_wheel(path, result["sha256"])
    assert result["local_version"] == "26.2.1+aios.1" and result["scan_suppressions"] == []
    assert payload["pip/_internal/resolution.py"] == original["pip"][0]["pip/_internal/resolution.py"]
    assert payload["pip/_vendor/requests/sessions.py"] == original["pip"][0]["pip/_vendor/requests/sessions.py"]
    for name in ("__init__.py", "exceptions.py", "ext.py", "fallback.py"):
        assert payload["pip/_vendor/msgpack/" + name] == original["msgpack"][0]["msgpack/" + name]
    assert payload["pip/_vendor/pkg_resources/__init__.py"] != original["pip"][0]["pip/_vendor/pkg_resources/__init__.py"]
    assert b"from pip._vendor.packaging import version" in payload["pip/_vendor/pkg_resources/__init__.py"]
    assert b"sys.path.extend" not in payload["pip/_vendor/pkg_resources/__init__.py"]
    assert b"Version: 26.2.1+aios.1\n" in payload[m.NEW_DIST + "METADATA"]
    assert not any(x.startswith(m.OLD_DIST) for x in payload)
    assert payload["pip/_vendor/msgpack/COPYING"] == original["msgpack"][0]["msgpack-1.2.3.dist-info/licenses/COPYING"]
    bom = json.loads(payload["pip/_vendor/bom.cdx.json"])
    assert {x["name"]: x["version"] for x in bom["components"]} == {"msgpack": "1.2.3", "setuptools": "80.9.0"}
    assert bom["dependencies"][0]["dependsOn"] == ["pkg:pypi/msgpack@1.2.3", "pkg:pypi/setuptools@80.9.0"]
    assert not result["msgpack_compiled_extension_included"]


def test_deterministic_output_and_existing_directory_not_overwritten(inputs, tmp_path):
    directory, _ = inputs
    first = m.build(directory, tmp_path / "one")
    second = m.build(directory, tmp_path / "two")
    assert first == second
    with pytest.raises(FileExistsError):
        m.build(directory, tmp_path / "one")


@pytest.mark.parametrize("digest", ["0" * 64, "bad", "F" * 64])
def test_bad_input_digest_rejected(tmp_path, digest):
    p = tmp_path / "a.whl"
    make_wheel(p, {"a.py": b"x=1"}, "a-1.dist-info")
    with pytest.raises(ValueError):
        m.verified_wheel(p, digest)


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "a//b", "a/./b", "a\\b", "a-1.dist-info/RECORD.jws"])
def test_unsafe_archive_members_rejected(tmp_path, bad):
    p = tmp_path / "a.whl"
    digest = make_wheel(p, {bad: b"not executed"}, "a-1.dist-info")
    with pytest.raises(ValueError):
        m.verified_wheel(p, digest)


@pytest.mark.parametrize("fault", ["bad_hash", "extra_record", "symlink", "duplicate"])
def test_integrity_or_member_identity_fault_rejected(tmp_path, fault):
    p = tmp_path / "a.whl"
    digest = make_wheel(p, {"a.py": b"x=1"}, "a-1.dist-info", **{fault: True})
    with pytest.raises(ValueError):
        m.verified_wheel(p, digest)


@pytest.mark.parametrize("bound", ["MAX_INPUT", "MAX_EXPANDED"])
def test_size_limits_enforced(tmp_path, monkeypatch, bound):
    p = tmp_path / "a.whl"
    digest = make_wheel(p, {"a.py": b"x=1"}, "a-1.dist-info")
    monkeypatch.setattr(m, bound, 1)
    with pytest.raises(ValueError):
        m.verified_wheel(p, digest)


def test_symlink_input_rejected(inputs, tmp_path):
    directory, _ = inputs
    filename, digest, _ = m.INPUTS["pip"]
    p = tmp_path / "alias"
    p.symlink_to(directory / filename)
    with pytest.raises(ValueError):
        m.verified_wheel(p, digest)


def test_pinned_resource_import_drift_rejected():
    with pytest.raises(ValueError, match="drifted"):
        m.adapt_resources(b"# Unexpected upstream code")


@pytest.mark.parametrize("indexes", [[], ["--index-url", "https://example.invalid/simple"], ["--extra-index-url", "https://other.invalid/simple"]])
def test_pinned_pip_command_preserves_inputs_and_no_unchecked_upgrades(indexes):
    args = ["--require-hashes", "-r", "/synthetic/requirements.txt"]
    before = list(args), list(indexes)
    command = a.pip_command("/synthetic/venv/bin/python", "/synthetic/report.json", indexes, args)
    assert command[:7] == [a.sys.executable, "-m", "pip", "--python", "/synthetic/venv/bin/python", "install", "--no-input"]
    assert "--dry-run" in command and "--report" in command and "--keyring-provider=subprocess" in command
    assert command[-len(args):] == args and (args, indexes) == before
    assert "--no-deps" not in command and "--upgrade" not in command


def test_image_build_installs_local_pip_and_keeps_full_scanner_capabilities():
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    assert "python build_pip_vendor_wheel.py --download" in dockerfile
    assert "pip-26.2.1+aios.1-py3-none-any.whl" in dockerfile
    assert "ln -sf /app/scripts/security_pip_audit.py /opt/venv/bin/pip-audit" in dockerfile
    assert "/usr/local/sbin/install-security-tools.sh" in dockerfile
    assert "COPY --from=semgrep-builder /opt/semgrep /opt/semgrep" in dockerfile
    assert "--ignore-unfixed" not in dockerfile and "--ignore-vuln" not in dockerfile


@pytest.fixture
def adapter(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    calls = []
    state = SimpleNamespace(update_state=lambda value: None)
    class VirtualEnvError(Exception):
        pass
    class CalledProcessError(Exception):
        pass
    class Original:
        def __init__(self, arguments, **kwargs):
            self.with_pip = True
            self._install_args = list(arguments)
            self._index_url_args = ["--index-url", "https://synthetic.invalid/simple"]
            self._state = state
            self._packages = None
    virtual = ModuleType("pip_audit._virtual_env")
    virtual.VirtualEnv = Original
    virtual.VirtualEnvError = VirtualEnvError
    package = ModuleType("pip_audit")
    package.__path__ = []
    package._virtual_env = virtual
    source = ModuleType("pip_audit._dependency_source")
    source.requirement = SimpleNamespace(VirtualEnv=Original)
    source.pyproject = SimpleNamespace(VirtualEnv=Original)
    process = ModuleType("pip_audit._subprocess")
    process.CalledProcessError = CalledProcessError
    outcome = {"payload": {"version": "1", "install": [{"metadata": {"name": "fixture", "version": "1.0"}}]}, "failed": False}
    def run(command, **kwargs):
        calls.append(list(command))
        if outcome["failed"]:
            raise CalledProcessError("synthetic resolver failure")
        report = Path(command[command.index("--report") + 1])
        report.write_text(json.dumps(outcome["payload"]))
    process.run = run
    for name, value in {"pip": SimpleNamespace(__version__="26.2.1+aios.1"), "pip_audit": package, "pip_audit._virtual_env": virtual, "pip_audit._dependency_source": source, "pip_audit._subprocess": process}.items():
        monkeypatch.setitem(sys.modules, name, value)
    monkeypatch.setattr(a.importlib.metadata, "version", lambda name: "2.10.1")
    return SimpleNamespace(source=source, virtual=virtual, original=Original, calls=calls, outcome=outcome)


def test_adapter_configures_both_sources_and_is_idempotent(adapter):
    cls = a.configure()
    assert cls is a.configure() is adapter.virtual.VirtualEnv
    assert cls is adapter.source.requirement.VirtualEnv is adapter.source.pyproject.VirtualEnv
    assert cls(["-r", "/synthetic/req"]).with_pip is False
    assert adapter.calls == []


@pytest.mark.parametrize("drift", ["pip", "pip-audit"])
def test_dependency_version_drift_rejected_before_adapter_activation(adapter, monkeypatch, drift):
    if drift == "pip":
        monkeypatch.setattr(a.sys.modules["pip"], "__version__", "26.2.1")
    else:
        monkeypatch.setattr(a.importlib.metadata, "version", lambda name: "99.0")
    with pytest.raises(RuntimeError, match="Unreviewed"):
        a.configure()
    assert adapter.virtual.VirtualEnv is adapter.original and adapter.calls == []


def test_adapter_collects_exact_real_pip_report_without_installing_another_pip(adapter):
    from types import SimpleNamespace
    obj = a.configure()(["--require-hashes", "-r", "/synthetic/req"])
    obj.post_setup(SimpleNamespace(env_exe="/synthetic/venv/bin/python"))
    assert [(n, str(v)) for n, v in obj._packages] == [("fixture", "1.0")]
    assert len(adapter.calls) == 1 and "--upgrade" not in adapter.calls[0]
    assert adapter.calls[0][-3:] == ["--require-hashes", "-r", "/synthetic/req"]


@pytest.mark.parametrize("payload", [{}, {"version": "2", "install": []}, {"version": "1", "install": {}}, {"version": "1", "install": None}])
def test_invalid_installer_report_is_not_successful_empty_audit(adapter, payload):
    from types import SimpleNamespace
    adapter.outcome["payload"] = payload
    obj = a.configure()([])
    with pytest.raises(adapter.virtual.VirtualEnvError):
        obj.post_setup(SimpleNamespace(env_exe="/synthetic/python"))
    assert obj._packages is None


def test_installer_failure_does_not_become_empty_success(adapter):
    from types import SimpleNamespace
    adapter.outcome["failed"] = True
    obj = a.configure()([])
    with pytest.raises(adapter.virtual.VirtualEnvError, match="resolution failed"):
        obj.post_setup(SimpleNamespace(env_exe="/synthetic/python"))
    assert obj._packages is None and len(adapter.calls) == 1
