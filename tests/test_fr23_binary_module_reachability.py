from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/final_audit_reachability.py"
POLICY = ROOT / "tests/fixtures/fr23_binary_module_policy.json"


def load_target():
    spec = importlib.util.spec_from_file_location("fr23_reachability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TARGET = load_target()


def evidence(
    *deps: tuple[str, str],
    extra_count: int = 12,
    main_package: str = "example.invalid/tool",
) -> str:
    rows = [
        "/tmp/tool: go1.26.8",
        f"\tpath\t{main_package}",
    ]
    for index in range(extra_count):
        rows.append(f"\tdep\texample.invalid/dummy{index}\tv1.0.{index}")
    for module, version in deps:
        rows.append(f"\tdep\t{module}\t{version}")
    rows.append("\tbuild\t-buildmode=exe")
    rows.append("\tbuild\tGOOS=linux")
    return "\n".join(rows) + "\n"


def write_evidence(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / f"{name}.txt"
    path.write_text(text)
    return path


def all_good_evidence(tmp_path: Path) -> dict[str, Path]:
    return {
        "trivy": write_evidence(
            tmp_path,
            "trivy",
            evidence(
                ("github.com/containerd/containerd/v2", "v2.3.6"),
                ("go.opentelemetry.io/otel", "v1.45.0"),
                ("go.opentelemetry.io/otel/sdk", "v1.46.0"),
                main_package="github.com/aquasecurity/trivy/cmd/trivy",
            ),
        ),
        "grype": write_evidence(
            tmp_path,
            "grype",
            evidence(
                ("github.com/containerd/containerd/v2", "v2.3.7"),
                ("go.opentelemetry.io/otel", "v1.45.1"),
                main_package="github.com/anchore/grype/cmd/grype",
            ),
        ),
        "syft": write_evidence(
            tmp_path,
            "syft",
            evidence(
                ("github.com/containerd/containerd/v2", "v2.4.1"),
                ("go.opentelemetry.io/otel/trace", "v1.46.0"),
                main_package="github.com/anchore/syft/cmd/syft",
            ),
        ),
        "gitleaks": write_evidence(
            tmp_path,
            "gitleaks",
            evidence(
                ("github.com/nwaples/rardecode/v2", "v2.2.0"),
                ("github.com/ulikunitz/xz", "v0.5.16"),
                main_package="github.com/zricethezav/gitleaks/v8",
            ),
        ),
    }


def test_policy_preserves_high_alerts_and_forbids_reachability_closure():
    policy = TARGET.load_policy(POLICY)
    assert policy["semantics"]["dependabot_closure"] is False
    assert {48, 50} <= set(policy["semantics"]["preserved_open_alerts"])
    assert policy["semantics"]["final_live_closure_gated_by"] == ["FR-06", "FR-21"]
    assert all(
        rule["closure_effect"] == "none"
        for tool in policy["tools"].values()
        for rule in tool["rules"]
    )


def test_patched_or_unlinked_modules_pass_without_claiming_alert_closure(tmp_path: Path):
    policy = TARGET.load_policy(POLICY)
    code, report = TARGET.evaluate(policy, all_good_evidence(tmp_path))
    assert code == 0
    assert report["status"] == "PASS"
    assert report["semantics"]["dependabot_closure"] is False
    assert report["semantics"]["preserved_open_alerts"] == [48, 50]


def test_legacy_docker_linked_in_trivy_fails(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    # Real go version -m emits dep records before build metadata.
    original = paths["trivy"].read_text()
    build_anchor = "\tbuild\t-buildmode=exe\n"
    assert build_anchor in original
    paths["trivy"].write_text(
        original.replace(
            build_anchor,
            "\tdep\tgithub.com/docker/docker\tv28.5.2+incompatible\n"
            + build_anchor,
            1,
        )
    )
    policy = TARGET.load_policy(POLICY)
    code, report = TARGET.evaluate(policy, paths)
    assert code == 1
    trivy = next(item for item in report["tools"] if item["tool"] == "trivy")
    rule = next(item for item in trivy["rules"] if item["id"] == "trivy-legacy-docker-not-linked")
    assert rule["status"] == "FAIL"
    assert rule["observed"] == "v28.5.2+incompatible"
    assert rule["closure_effect"] == "none"


@pytest.mark.parametrize(
    ("tool", "module", "version", "rule_id"),
    [
        ("trivy", "github.com/containerd/containerd/v2", "v2.3.3", "trivy-containerd-floor-or-absent"),
        ("grype", "github.com/containerd/containerd/v2", "v2.3.5", "grype-containerd-floor-or-absent"),
        ("syft", "go.opentelemetry.io/otel/trace", "v1.44.0", "syft-otel-family-floor-or-absent"),
        ("gitleaks", "github.com/nwaples/rardecode/v2", "v2.1.0", "gitleaks-rardecode-floor-or-absent"),
        ("gitleaks", "github.com/ulikunitz/xz", "v0.5.12", "gitleaks-xz-floor-or-absent"),
    ],
)
def test_known_vulnerable_linked_floors_fail(
    tmp_path: Path,
    tool: str,
    module: str,
    version: str,
    rule_id: str,
):
    paths = all_good_evidence(tmp_path)
    rows = []
    replaced = False
    for line in paths[tool].read_text().splitlines():
        fields = line.strip().split()
        if len(fields) >= 3 and fields[0] == "dep" and fields[1] == module:
            rows.append(f"\tdep\t{module}\t{version}")
            replaced = True
        else:
            rows.append(line)
    if not replaced:
        rows.insert(-2, f"\tdep\t{module}\t{version}")
    paths[tool].write_text("\n".join(rows) + "\n")

    policy = TARGET.load_policy(POLICY)
    code, report = TARGET.evaluate(policy, paths)
    assert code == 1
    result = next(item for item in report["tools"] if item["tool"] == tool)
    rule = next(item for item in result["rules"] if item["id"] == rule_id)
    assert rule["status"] == "FAIL"
    assert rule["closure_effect"] == "none"


def test_target_module_can_be_removed_entirely(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    lines = [
        line
        for line in paths["trivy"].read_text().splitlines()
        if "github.com/containerd/containerd/v2" not in line
        and "go.opentelemetry.io/otel" not in line
    ]
    paths["trivy"].write_text("\n".join(lines) + "\n")
    policy = TARGET.load_policy(POLICY)
    code, report = TARGET.evaluate(policy, paths)
    assert code == 0
    trivy = next(item for item in report["tools"] if item["tool"] == "trivy")
    assert {rule["reason"] for rule in trivy["rules"]} >= {
        "module_not_linked",
        "module_family_not_linked",
    }


def test_truncated_evidence_fails_closed(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    paths["trivy"].write_text(
        "/tmp/trivy: go1.26.8\n"
        "\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n"
        "\tdep\texample.invalid/only\tv1.0.0\n"
        "\tbuild\t-buildmode=exe\n"
    )
    policy = TARGET.load_policy(POLICY)
    with pytest.raises(TARGET.EvidenceError, match="too small"):
        TARGET.evaluate(policy, paths)


def test_targeted_replacement_is_ambiguous_and_fails_closed(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    text = paths["trivy"].read_text()
    text = text.replace(
        "\tdep\tgithub.com/containerd/containerd/v2\tv2.3.6\n",
        "\tdep\tgithub.com/containerd/containerd/v2\tv2.3.6\n"
        "\t=>\texample.invalid/containerd-fork\tv2.3.6\n",
    )
    paths["trivy"].write_text(text)
    policy = TARGET.load_policy(POLICY)
    with pytest.raises(TARGET.EvidenceError, match="replaced by"):
        TARGET.evaluate(policy, paths)


def test_policy_cannot_silently_enable_dependabot_closure(tmp_path: Path):
    policy = json.loads(POLICY.read_text())
    policy["semantics"]["dependabot_closure"] = True
    path = tmp_path / "unsafe-policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(TARGET.PolicyError, match="dependabot_closure"):
        TARGET.load_policy(path)


def test_missing_tool_evidence_fails_closed(tmp_path: Path):
    policy = TARGET.load_policy(POLICY)
    paths = all_good_evidence(tmp_path)
    del paths["gitleaks"]
    with pytest.raises(TARGET.EvidenceError, match="evidence set mismatch"):
        TARGET.evaluate(policy, paths)


@pytest.mark.parametrize(
    ("observed", "minimum", "expected"),
    [
        ("v1.2.3-rc.2", "v1.2.3-rc.10", False),
        ("v1.2.3-rc.10", "v1.2.3-rc.2", True),
        ("v1.2.3-2", "v1.2.3-alpha", False),
        ("v1.2.3-rc", "v1.2.3-rc.1", False),
        ("v1.2.3", "v1.2.3-rc.100", True),
    ],
)
def test_prerelease_version_order_matches_semver(
    observed: str, minimum: str, expected: bool
):
    assert TARGET.version_at_least(observed, minimum) is expected


@pytest.mark.parametrize("invalid", ["v1.2.3-rc.01", "v1.2.3-rc..2"])
def test_invalid_prerelease_fails_closed(invalid: str):
    with pytest.raises(TARGET.EvidenceError, match="unsupported semantic version"):
        TARGET.version_at_least(invalid, "v1.2.3")


@pytest.mark.parametrize("replacement_line", ["", "\t=>\texample.invalid/fork\tv2.3.6\n"])
def test_duplicate_linked_module_cannot_erase_replacement(
    tmp_path: Path, replacement_line: str
):
    paths = all_good_evidence(tmp_path)
    module_line = "\tdep\tgithub.com/containerd/containerd/v2\tv2.3.6\n"
    original = paths["trivy"].read_text()
    assert module_line in original
    paths["trivy"].write_text(
        original.replace(
            module_line, module_line + replacement_line + module_line, 1
        )
    )
    policy = TARGET.load_policy(POLICY)
    with pytest.raises(TARGET.EvidenceError, match="duplicate linked module"):
        TARGET.evaluate(policy, paths)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_header", "missing go version -m binary header"),
        ("missing_path", "module metadata appears before binary path"),
        ("duplicate_path", "multiple path sections"),
        ("second_binary", "multiple binary headers"),
        ("module_after_build", "module metadata after binary build section"),
        ("unknown_record", "unrecognized go version -m metadata"),
    ],
)
def test_partial_or_mixed_binaries_fail_closed(
    tmp_path: Path, mutation: str, expected_error: str
):
    paths = all_good_evidence(tmp_path)
    valid = paths["trivy"].read_text()
    if mutation == "missing_header":
        invalid = valid.split("\n", 1)[1]
    elif mutation == "missing_path":
        invalid = valid.replace("\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n", "", 1)
    elif mutation == "duplicate_path":
        invalid = valid.replace(
            "\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n",
            "\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n\tpath\texample.invalid/other\n",
            1,
        )
    elif mutation == "second_binary":
        invalid = (
            valid + "/tmp/another: go1.26.8\n"
            "\tpath\texample.invalid/another\n"
            "\tdep\texample.invalid/extra\tv1.0.0\n"
            "\tbuild\t-buildmode=exe\n"
        )
    elif mutation == "module_after_build":
        invalid = valid + "\tdep\texample.invalid/late\tv1.0.0\n"
    else:
        invalid = valid.replace(
            "\tbuild\t-buildmode=exe\n",
            "\tunknown\tnot-go-metadata\n\tbuild\t-buildmode=exe\n",
            1,
        )
    assert invalid != valid
    paths["trivy"].write_text(invalid)
    policy = TARGET.load_policy(POLICY)
    with pytest.raises(TARGET.EvidenceError, match=expected_error):
        TARGET.evaluate(policy, paths)


def test_normal_main_module_metadata_is_accepted(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    original = paths["trivy"].read_text()
    paths["trivy"].write_text(
        original.replace(
            "\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n",
            "\tpath\tgithub.com/aquasecurity/trivy/cmd/trivy\n"
            "\tmod\texample.invalid/tool\t(devel)\n",
            1,
        )
    )
    code, report = TARGET.evaluate(TARGET.load_policy(POLICY), paths)
    assert code == 0
    assert report["status"] == "PASS"


@pytest.mark.parametrize(
    ("tool", "incorrect_package"),
    [
        ("trivy", "github.com/anchore/grype/cmd/grype"),
        ("grype", "github.com/aquasecurity/trivy/cmd/trivy"),
        ("syft", "github.com/zricethezav/gitleaks/v8"),
        ("gitleaks", "github.com/anchore/syft/cmd/syft"),
    ],
)
def test_mislabeled_binary_evidence_fails_closed(
    tmp_path: Path, tool: str, incorrect_package: str
):
    paths = all_good_evidence(tmp_path)
    actual_package = TARGET.EXPECTED_MAIN_PACKAGES[tool]
    assert actual_package != incorrect_package
    original = paths[tool].read_text()
    original_line = f"\tpath\t{actual_package}\n"
    assert original_line in original
    paths[tool].write_text(
        original.replace(
            original_line, f"\tpath\t{incorrect_package}\n", 1
        )
    )
    policy = TARGET.load_policy(POLICY)
    with pytest.raises(TARGET.EvidenceError, match="binary main package mismatch"):
        TARGET.evaluate(policy, paths)


@pytest.mark.parametrize("attack", ["wrong_main_package", "missing_tool", "extra_tool"])
def test_tool_identity_policy_cannot_be_relaxed(tmp_path: Path, attack: str):
    policy = json.loads(POLICY.read_text())
    if attack == "wrong_main_package":
        policy["tools"]["trivy"]["expected_main_package"] = "example.invalid/renamed"
    elif attack == "missing_tool":
        del policy["tools"]["trivy"]
    else:
        policy["tools"]["renamed"] = policy["tools"]["trivy"]
    path = tmp_path / "unsafe-identity-policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(TARGET.PolicyError, match="main package identity|pinned security-tool set"):
        TARGET.load_policy(path)


def test_cli_enforces_binary_identity_end_to_end(tmp_path: Path):
    paths = all_good_evidence(tmp_path)
    args = [sys.executable, str(SCRIPT), "--policy", str(POLICY)]
    for tool in sorted(paths):
        args.extend(["--evidence", f"{tool}={paths[tool]}"])

    accepted = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=20
    )
    assert accepted.returncode == 0
    assert json.loads(accepted.stdout)["status"] == "PASS"

    trivy_path = paths["trivy"]
    original = trivy_path.read_text()
    trivy_main = TARGET.EXPECTED_MAIN_PACKAGES["trivy"]
    grype_main = TARGET.EXPECTED_MAIN_PACKAGES["grype"]
    assert trivy_main != grype_main
    assert f"\tpath\t{trivy_main}\n" in original
    trivy_path.write_text(
        original.replace(f"\tpath\t{trivy_main}\n", f"\tpath\t{grype_main}\n", 1)
    )
    rejected = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=20
    )
    assert rejected.returncode == 2
    report = json.loads(rejected.stdout)
    assert report["status"] == "ERROR"
    assert "binary main package mismatch" in report["error"]
