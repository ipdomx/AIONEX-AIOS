"""Offline security-tool smoke test; run only in a disposable scanner image.

No targets outside fresh synthetic files are scanned. No credentials, service
startup or production database is used. A successful result is functional
acceptance only, NOT a substitute for a full image vulnerability gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run(args: list[str], *, allowed: tuple[int, ...] = (0,), env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=90, check=False, env=env)
    if result.returncode not in allowed:
        raise RuntimeError(f"Offline check failed: {args[0]} ({result.returncode}): {result.stderr[-1500:]}")
    return result.stdout


def environment(executable: str) -> dict[str, Any]:
    # Use the target environment's metadata, not the host test runner's packages.
    code = '''import importlib.metadata as md,json,re
from packaging.requirements import Requirement
from packaging.version import Version
packages={}
for d in md.distributions():
 name=re.sub(r'[-_.]+','-',d.metadata['Name']).lower()
 assert name not in packages, name
 packages[name]=d
errors=[]
for name,d in packages.items():
 for raw in d.requires or []:
  req=Requirement(raw)
  if req.marker is not None and not req.marker.evaluate({'extra':''}):continue
  key=re.sub(r'[-_.]+','-',req.name).lower()
  if key not in packages or Version(packages[key].version) not in req.specifier:
   errors.append(name+': '+raw)
assert not errors, errors
print(json.dumps({'versions':{n:d.version for n,d in packages.items()},'checked_distributions':len(packages),'dependency_errors':errors}))'''
    return json.loads(run([executable, "-c", code]))


def main() -> None:
    app = environment("/opt/venv/bin/python")
    tool = environment("/opt/semgrep/bin/python")
    assert app["versions"]["pyjwt"] == tool["versions"]["pyjwt"] == "2.15.0"
    assert "semgrep" not in app["versions"] and "mcp" not in app["versions"]
    assert app["versions"]["opentelemetry-api"] == "1.44.0"
    assert tool["versions"]["semgrep"] == "1.178.0+aios.2"
    assert tool["versions"]["mcp"] == "1.29.0"
    assert tool["versions"]["opentelemetry-api"] == "1.37.0"
    assert "pip" not in tool["versions"]
    pip_check = run(["/opt/venv/bin/python", "-m", "pip", "check"])
    assert "No broken requirements" in pip_check
    roots = [Path("/usr/local/share/aionex/semgrep-compat-provenance.json"),
             Path("/usr/local/share/aionex/scanner-python/semgrep-compat-provenance.json")]
    proof = json.loads(next(p for p in roots if p.is_file()).read_text())
    site = Path("/opt/semgrep/lib/python3.11/site-packages")
    for name, expected in proof["payload_files_unchanged"].items():
        relative = name.removeprefix("semgrep-1.178.0.data/purelib/")
        assert hashlib.sha256((site / relative).read_bytes()).hexdigest() == expected, name
    assert proof["upstream_sha256"] == "b7c4a4ba5cad1a6b0e76f7143c164b3f2853b9d0f902f2db2f64006257c941f2"
    assert proof["only_metadata_changed"] and not proof["dependency_checks_disabled"]
    system = Path("/usr/local/lib/python3.11/site-packages")
    assert not any(system.glob("pip*")) and not any(system.glob("setuptools*"))
    assert not (system / "pkg_resources").exists()
    from app.services.security_tools import _normalize_source_findings

    env = {**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0", "SEMGREP_SEND_METRICS": "off"}
    with tempfile.TemporaryDirectory(prefix="aios-security-offline-") as folder:
        root = Path(folder)
        (root / "bad.py").write_text("def inspect_text(text):\n    return eval(text)\n")
        (root / "good.py").write_text("def inspect_text(text):\n    return str(text)\n")
        semgrep = json.loads(run([
            "/opt/semgrep/bin/semgrep", "scan", "--config", "/app/security-rules/semgrep/aionex.yml",
            "--json", "--quiet", "--metrics=off", "--disable-version-check", "--no-git-ignore", str(root),
        ], env=env))
        findings = semgrep.get("results", [])
        assert findings and any("dynamic-eval" in f["check_id"] for f in findings)
        assert all(f["path"].endswith("bad.py") for f in findings) and not semgrep.get("errors")
        normalized_semgrep = _normalize_source_findings("semgrep", semgrep, "")
        assert normalized_semgrep and all(x["state"] == "observed" for x in normalized_semgrep)
        bandit = json.loads(run(["/opt/venv/bin/bandit", "-r", str(root), "-f", "json", "-q"], allowed=(1,)))
        assert any(f["test_id"] == "B307" for f in bandit["results"])
        assert not bandit.get("errors")
        normalized_bandit = _normalize_source_findings("bandit", bandit, "")
        assert normalized_bandit and all(x["state"] == "observed" for x in normalized_bandit)
        assert all(f["filename"].endswith("bad.py") for f in bandit["results"])
    schema = '''import json,schemathesis
s=schemathesis.openapi.from_dict({'openapi':'3.0.3','info':{'title':'offline','version':'1'},'paths':{'/alive':{'get':{'responses':{'200':{'description':'ok'}}}}}})
operation=s['/alive']['GET']
assert operation.method.upper()=='GET'
print(json.dumps({'schema_loaded':True,'method':operation.method,'network_used':False}))'''
    schema_result = json.loads(run(["/opt/venv/bin/python", "-c", schema]))
    audit_version = run(["/opt/venv/bin/pip-audit", "--version"]).strip()
    assert "2.10.1" in audit_version
    security = '''import asyncio,json
from starlette.requests import Request
from mcp.server.transport_security import TransportSecurityMiddleware,TransportSecuritySettings
async def main():
 settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=['localhost:8989'],allowed_origins=['http://localhost:8989'])
 middleware=TransportSecurityMiddleware(settings)
 results=[]
 for host,origin,wanted in [('localhost:8989','http://localhost:8989',None),('untrusted.invalid','http://localhost:8989',421),('localhost:8989','http://untrusted.invalid',403)]:
  scope={'type':'http','method':'GET','path':'/','scheme':'http','query_string':b'','headers':[(b'host',host.encode()),(b'origin',origin.encode())]}
  result=await middleware.validate_request(Request(scope))
  status=result.status_code if result is not None else None
  assert status==wanted,(status,wanted)
  results.append(status)
 print(json.dumps({'explicitly_enabled_host_origin_checks':results,'network_used':False,'server_started':False}))
asyncio.run(main())'''
    transport = json.loads(run(["/opt/semgrep/bin/python", "-c", security]))
    print(json.dumps({
        "status": "PASS", "application_environment": app, "semgrep_environment": tool,
        "pip_check": "PASS", "upstream_payload_files_matched": len(proof["payload_files_unchanged"]),
        "semgrep_detected_bad_not_good": True, "bandit_detected_bad_not_good": True,
        "application_finding_normalizers_verified": True,
        "schemathesis": schema_result, "pip_audit": audit_version, "mcp_transport": transport,
        "full_image_security_gate_passed": False, "production_changed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
