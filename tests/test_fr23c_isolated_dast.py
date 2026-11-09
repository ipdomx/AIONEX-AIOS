"""FR-23C isolated DAST harness: production-safety guards and dry-run behaviour."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fr23c", ROOT / "scripts/security/fr23c_isolated_dast.py")
dast = importlib.util.module_from_spec(spec)
sys.modules["fr23c"] = dast
spec.loader.exec_module(dast)

PROJECT = "aionex-fr23c-dast-20261109t120000z"


def clean_config() -> dict:
    net = {"dast_isolated": {"name": f"{PROJECT}_dast_isolated", "internal": True}}
    vols = {key: {"name": f"{PROJECT}_{key}"} for key in dast.ALLOWED_VOLUMES}
    services = {
        "backend": {"networks": {"dast_isolated": {}}, "volumes": [{"type": "volume", "source": "dast_data"}]},
        "probe": {"networks": {"dast_isolated": {}},
                  "volumes": [{"type": "bind", "source": "/x/probe.py", "read_only": True}]},
    }
    return {"name": PROJECT, "networks": net, "volumes": vols, "services": services}


def test_clean_config_passes():
    assert dast.validate_compose_config(clean_config(), PROJECT, {"probe": {"/x/probe.py"}}) == []


def test_guards_refuse_production_reach():
    config = clean_config()
    config["networks"]["dast_isolated"]["internal"] = False
    config["services"]["backend"]["ports"] = ["8000:8000"]
    config["services"]["backend"]["volumes"].append({"type": "volume", "source": "postgres_data"})
    config["services"]["probe"]["volumes"].append({"type": "bind", "source": "/var/run/docker.sock"})
    config["services"]["zap"] = {"network_mode": "host"}
    problems = " | ".join(dast.validate_compose_config(config, PROJECT, {"probe": {"/x/probe.py"}}))
    for expected in ("must be internal", "publishes ports", "foreign volume postgres_data", "Docker socket",
                     "network_mode host"):
        assert expected in problems


def test_project_name_is_guarded():
    for bad in ("web-dashboard", "aionex-fr23c-dast-web-dashboard", "aionex-fr23c-dast-2026"):
        assert dast.validate_compose_config(clean_config(), bad, {})


def test_real_compose_file_is_internal_only():
    text = (ROOT / "deploy/fr23c-dast/docker-compose.fr23c-dast.yml").read_text()
    assert "internal: true" in text and "ports:" not in text and "docker.sock" not in text
    assert "web-dashboard" not in text


def test_plan_runs_nothing(capsys):
    assert dast.main(["plan", "--project", PROJECT]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "DRY_RUN" and out["docker_commands_run"] == 0


def test_run_requires_confirmation(capsys):
    assert dast.main(["run", "--execute", "--project", PROJECT, "--confirm-project", "other"]) == 2
