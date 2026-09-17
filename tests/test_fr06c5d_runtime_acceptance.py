"""Exercise real C5D policy and acceptance helpers with a stateful Docker fake."""
import copy
import json
from pathlib import Path
import subprocess
from types import ModuleType, SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c5_host_state_cutover.py"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 5
        self.sleeps.append(seconds)
        self.now += seconds


class DockerFake:
    def __init__(self, module, clock):
        self.m = module
        self.clock = clock
        self.docs = {}
        choices = [("no", 0), ("always", 0), ("unless-stopped", 0),
                   ("on-failure", 3), ("on-failure", 0), ("on-failure", 7)]
        for index in range(36):
            cid = f"{index + 1:064x}"
            service = "project-worker" if index < 4 else f"service-{index % 8}"
            name, retries = choices[index % len(choices)]
            config = {"Labels": {"com.docker.compose.project": "web-dashboard",
                                 "com.docker.compose.service": service}}
            state = {"Running": True, "Status": "running", "Paused": False,
                     "Restarting": False}
            if index % 5:
                config["Healthcheck"] = {"Test": ["CMD", "healthcheck"]}
                state["Health"] = {"Status": "healthy"}
            self.docs[cid] = {"Id": cid, "Name": f"/{service}-{index}",
                              "Config": config, "State": state,
                              "HostConfig": {"RestartPolicy": {
                                  "Name": name, "MaximumRetryCount": retries}}}
        self.running_ids = list(self.docs)
        self.events = []
        self.calls = []
        self.fail_updates = {}
        self.silent_updates = set()
        self.ps_count = 0
        self.on_ps = None
        self.on_curl = None
        self.inspect_transform = None
        self.query_seconds = 0
        self.codes = {}
        self.inactive = set()
        self.validations = {
            "fr06c5_host_state_bind.py": "FR06C5_HOST_STATE_BIND_READY",
            "fr06c4_runtime_bind.py": "FR06C4_RUNTIME_BIND_READY",
        }

    def policies(self):
        return {cid: copy.deepcopy(doc["HostConfig"]["RestartPolicy"])
                for cid, doc in self.docs.items()}

    def updates(self):
        return [event for event in self.events if event[:2] == ("docker", "update")]

    def run(self, args, t=180, cwd=None, check=True):
        args = list(args)
        self.events.append(tuple(args))
        self.calls.append((tuple(args), t, self.clock.now))
        if (args[:2] in (["docker", "ps"], ["docker", "inspect"],
                         ["systemctl", "is-active"]) or args[0] == "curl"):
            assert t > 0
            self.clock.now += min(self.query_seconds, t)
            if self.query_seconds > t:
                raise subprocess.TimeoutExpired(args, t)
        if args[:2] == ["docker", "ps"]:
            assert "--no-trunc" in args
            self.ps_count += 1
            if self.on_ps:
                self.on_ps(self.ps_count)
            return "\n".join(self.running_ids)
        if args[:2] == ["docker", "inspect"]:
            payload = [copy.deepcopy(self.docs[cid]) for cid in args[2:]]
            if self.inspect_transform:
                payload = self.inspect_transform(payload)
            return json.dumps(payload)
        if args[:2] == ["docker", "update"]:
            assert len(args) == 4 and args[2].startswith("--restart=")
            specification = args[2].split("=", 1)[1]
            cid = args[3]
            key = (cid, specification)
            if self.fail_updates.get(key, 0):
                self.fail_updates[key] -= 1
                raise self.m.E("synthetic docker update failure")
            if key not in self.silent_updates:
                name, _, count = specification.partition(":")
                self.docs[cid]["HostConfig"]["RestartPolicy"] = {
                    "Name": name, "MaximumRetryCount": int(count or 0)}
            return cid
        if args[0] == "python3":
            filename = Path(args[1]).name
            assert filename in self.validations and "--require-ready" in args
            return json.dumps({"validation": self.validations[filename]})
        if args[0] == "curl":
            assert "--user-agent" in args
            assert args[args.index("--user-agent") + 1] == BROWSER_UA
            assert "-k" not in args and "-ksS" not in args
            assert "--connect-timeout" in args and "--max-time" in args
            if self.on_curl:
                self.on_curl(args[-1])
            result = self.codes.get(args[-1], "200")
            if isinstance(result, list):
                return result.pop(0) if len(result) > 1 else result[0]
            return result
        if args[:2] == ["systemctl", "is-active"]:
            assert args[2] in self.m.TUNNELS
            return "inactive" if args[2] in self.inactive else "active"
        raise AssertionError(f"unexpected command: {args}")


@pytest.fixture
def runtime():
    module = ModuleType("c5d_runtime_under_test")
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), module.__dict__)
    clock = Clock()
    fake = DockerFake(module, clock)
    module.run = fake.run
    module.time = SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    def forbidden(*args, **kwargs):
        raise AssertionError("real subprocess is forbidden in helper tests")
    module.subprocess = SimpleNamespace(run=forbidden,
                                       TimeoutExpired=subprocess.TimeoutExpired)
    plan = module.topology()
    fake.events.clear()
    fake.calls.clear()
    fake.ps_count = 0
    return SimpleNamespace(m=module, f=fake, t=plan, clock=clock)


def test_topology_captures_all_full_ids_service_memberships_and_retry_counts(runtime):
    s = runtime
    snapshot = s.m.topology()
    assert snapshot["container_count"] == 36
    assert snapshot["project_worker_scale"] == 4
    assert {row["id"] for row in snapshot["containers"]} == set(s.f.docs)
    assert all(len(row["id"]) == 64 for row in snapshot["containers"])
    assert {row["restart"] for row in snapshot["containers"]} >= {
        "on-failure:3", "on-failure:7", "on-failure", "unless-stopped"}
    assert len([event for event in s.f.events if event[:2] == ("docker", "inspect")]) == 1


@pytest.mark.parametrize("name,count,expected", [
    ("on-failure", 0, "on-failure"), ("on-failure", 9, "on-failure:9"),
    ("always", 0, "always"), ("no", 0, "no"), ("unless-stopped", 0, "unless-stopped"),
])
def test_current_restart_preserves_policy_and_retry_count(runtime, name, count, expected):
    s = runtime
    cid = s.f.running_ids[0]
    s.f.docs[cid]["HostConfig"]["RestartPolicy"] = {
        "Name": name, "MaximumRetryCount": count}
    assert s.m.current_restart(cid) == expected


def test_current_restart_rejects_inspection_of_a_different_container(runtime):
    s = runtime
    s.f.inspect_transform = lambda rows: [dict(rows[0], Id="f" * 64)]
    with pytest.raises(s.m.B, match="identity mismatch"):
        s.m.current_restart(s.f.running_ids[0])


@pytest.mark.parametrize("name,count", [("on-failure", -1), ("on-failure", True),
                                        ("always", 4), ("unknown", 0)])
def test_invalid_restart_policy_is_not_silently_normalized(runtime, name, count):
    s = runtime
    cid = s.f.running_ids[0]
    s.f.docs[cid]["HostConfig"]["RestartPolicy"] = {
        "Name": name, "MaximumRetryCount": count}
    with pytest.raises(s.m.B, match="invalid"):
        s.m.current_restart(cid)


def test_quiesce_and_restore_preserve_every_original_policy(runtime):
    s = runtime
    original = s.f.policies()
    s.m.quiesce_restart_policies(s.t)
    assert all(value == {"Name": "no", "MaximumRetryCount": 0}
               for value in s.f.policies().values())
    s.m.restore_restart_policies(s.t)
    assert s.f.policies() == original


@pytest.mark.parametrize("silent", [False, True])
def test_partial_quiesce_failure_restores_all_36_original_policies(runtime, silent):
    s = runtime
    original = s.f.policies()
    target = s.t["containers"][7]["id"]
    if original[target]["Name"] == "no":
        target = next(row["id"] for row in s.t["containers"][7:]
                      if row["restart"] != "no")
    if silent:
        s.f.silent_updates.add((target, "no"))
    else:
        s.f.fail_updates[(target, "no")] = 1
    with pytest.raises(s.m.E, match="all original policies restored"):
        s.m.quiesce_restart_policies(s.t)
    assert s.f.policies() == original
    assert {event[3] for event in s.f.updates()[-36:]} == set(original)
    assert any(event[2] == "--restart=on-failure:7"
               for event in s.f.updates()[-36:])


def test_quiesce_compensation_failure_never_claims_originals_restored(runtime):
    s = runtime
    target = next(row for row in s.t["containers"] if row["restart"] == "on-failure:7")
    last = s.t["containers"][-1]
    s.f.fail_updates[(last["id"], "no")] = 1
    s.f.fail_updates[(target["id"], target["restart"])] = 1
    with pytest.raises(s.m.E, match="original policy restoration failed"):
        s.m.quiesce_restart_policies(s.t)
    assert {event[3] for event in s.f.updates()[-36:]} == set(s.f.docs)
    assert s.f.docs[target["id"]]["HostConfig"]["RestartPolicy"] != {
        "Name": "on-failure", "MaximumRetryCount": 7}


def test_policy_drift_before_quiesce_causes_no_updates(runtime):
    s = runtime
    cid = s.t["containers"][-1]["id"]
    s.f.docs[cid]["HostConfig"]["RestartPolicy"] = {
        "Name": "on-failure", "MaximumRetryCount": 99}
    with pytest.raises(s.m.B, match="changed after planning"):
        s.m.quiesce_restart_policies(s.t)
    assert s.f.updates() == []


@pytest.mark.parametrize("silent", [False, True])
def test_restore_attempts_and_verifies_all_containers_despite_one_failure(runtime, silent):
    s = runtime
    original = s.f.policies()
    s.m.quiesce_restart_policies(s.t)
    s.f.events.clear()
    target = next(row["id"] for row in s.t["containers"] if row["restart"] == "on-failure:7")
    if silent:
        s.f.silent_updates.add((target, "on-failure:7"))
    else:
        s.f.fail_updates[(target, "on-failure:7")] = 1
    with pytest.raises(s.m.B, match="restoration failed"):
        s.m.restore_restart_policies(s.t)
    assert {event[3] for event in s.f.updates()} == set(original)
    assert len([event for event in s.f.events if event[:2] == ("docker", "inspect")]) == 36
    assert all(s.f.policies()[cid] == value for cid, value in original.items() if cid != target)
    assert s.f.policies()[target] != original[target]


def test_restore_command_failure_is_reported_even_when_policy_was_already_correct(runtime):
    s = runtime
    target = s.t["containers"][0]
    s.f.fail_updates[(target["id"], target["restart"])] = 1
    with pytest.raises(s.m.B, match="restoration failed"):
        s.m.restore_restart_policies(s.t)
    assert len(s.f.updates()) == 36


@pytest.mark.parametrize("field,value", [("Running", False), ("Paused", True),
                                         ("Restarting", True), ("Status", "exited")])
def test_topology_rejects_nonrunning_paused_or_restarting_containers(runtime, field, value):
    s = runtime
    s.f.docs[s.f.running_ids[5]]["State"][field] = value
    with pytest.raises(s.m.B, match="stably running"):
        s.m.topology(require_healthy=False)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unexpected-inspection"])
def test_topology_rejects_missing_duplicate_or_unexpected_ids(runtime, kind):
    s = runtime
    if kind == "missing":
        s.f.running_ids.pop()
    elif kind == "duplicate":
        s.f.running_ids[-1] = s.f.running_ids[0]
    else:
        s.f.inspect_transform = lambda rows: rows[:-1] + [dict(rows[-1], Id="f" * 64)]
    with pytest.raises(s.m.B):
        s.m.wait_for_topology(s.t)
    assert s.clock.sleeps == []


@pytest.mark.parametrize("accept", ["acceptance", "legacy_acceptance"])
def test_acceptance_waits_for_starting_then_preserves_exact_topology(runtime, accept):
    s = runtime
    target = s.f.running_ids[6]
    def progress(poll):
        s.f.docs[target]["State"]["Health"]["Status"] = "starting" if poll == 1 else "healthy"
    s.f.on_ps = progress
    result = getattr(s.m, accept)(s.t)
    assert result["services"] == s.t["services"]
    assert {row["id"] for row in result["containers"]} == set(s.f.docs)
    assert s.clock.sleeps == [5]
    curls = [event for event in s.f.events if event[0] == "curl"]
    assert {event[-1] for event in curls} == set(s.m.HTTP_ACCEPTANCE_URLS)
    assert len(curls) == 5
    tunnels = [event[2] for event in s.f.events if event[:2] == ("systemctl", "is-active")]
    assert tunnels == list(s.m.TUNNELS)


@pytest.mark.parametrize("accept", ["acceptance", "legacy_acceptance"])
@pytest.mark.parametrize("drift", ["id", "service", "name", "retry-count"])
def test_acceptance_rejects_planned_identity_or_policy_drift(runtime, accept, drift):
    s = runtime
    cid = s.f.running_ids[8]
    if drift == "id":
        replacement = "f" * 64
        s.f.docs[replacement] = s.f.docs.pop(cid)
        s.f.docs[replacement]["Id"] = replacement
        s.f.running_ids[8] = replacement
    elif drift == "service":
        other = s.f.running_ids[9]
        labels = s.f.docs[cid]["Config"]["Labels"]
        other_labels = s.f.docs[other]["Config"]["Labels"]
        labels["com.docker.compose.service"], other_labels["com.docker.compose.service"] = (
            other_labels["com.docker.compose.service"], labels["com.docker.compose.service"])
    elif drift == "name":
        s.f.docs[cid]["Name"] = "/unexpected-replacement-name"
    else:
        s.f.docs[cid]["HostConfig"]["RestartPolicy"] = {
            "Name": "on-failure", "MaximumRetryCount": 19}
    with pytest.raises(s.m.B, match="drifted"):
        getattr(s.m, accept)(s.t)
    assert s.clock.sleeps == []
    assert not any(event[0] == "curl" for event in s.f.events)


def test_healthcheck_without_health_state_is_not_treated_as_no_healthcheck(runtime):
    s = runtime
    target = s.f.running_ids[6]
    s.f.docs[target]["State"].pop("Health")
    with pytest.raises(s.m.B, match="health timeout"):
        s.m.wait_for_topology(s.t, timeout_seconds=10)
    assert s.clock.now == 10


def test_unhealthy_timeout_includes_docker_query_time_and_never_exceeds_deadline(runtime):
    s = runtime
    s.f.docs[s.f.running_ids[6]]["State"]["Health"]["Status"] = "unhealthy"
    s.f.query_seconds = 1
    with pytest.raises(s.m.B, match="health timeout"):
        s.m.wait_for_topology(s.t, timeout_seconds=11)
    assert s.clock.now == 11
    assert all(timeout <= min(30, 11 - when) for args, timeout, when in s.f.calls)


@pytest.mark.parametrize("kind", ["project", "worker-scale"])
def test_topology_rejects_project_or_worker_scale_drift(runtime, kind):
    s = runtime
    labels = s.f.docs[s.f.running_ids[8]]["Config"]["Labels"]
    labels["com.docker.compose.project" if kind == "project"
           else "com.docker.compose.service"] = "other-project" if kind == "project" else "project-worker"
    with pytest.raises(s.m.B):
        s.m.wait_for_topology(s.t)
    assert not s.clock.sleeps


@pytest.mark.parametrize("filename", ["fr06c5_host_state_bind.py", "fr06c4_runtime_bind.py"])
def test_candidate_acceptance_requires_both_encrypted_binds(runtime, filename):
    s = runtime
    s.f.validations[filename] = "NOT_READY"
    with pytest.raises(s.m.B, match="bind"):
        s.m.acceptance(s.t)
    assert not any(event[0] == "curl" for event in s.f.events)


def test_legacy_acceptance_keeps_encrypted_runtime_requirement(runtime):
    s = runtime
    s.f.validations["fr06c4_runtime_bind.py"] = "NOT_READY"
    with pytest.raises(s.m.B, match="encrypted container runtime"):
        s.m.legacy_acceptance(s.t)


def test_http_acceptance_uses_proven_browser_ua_and_retries_transient_ready(runtime):
    s = runtime
    s.f.codes["https://api.vip-e.net/ready"] = ["503", "200"]
    s.m.http_and_tunnel_acceptance(timeout_seconds=20)
    assert s.clock.sleeps == [5]
    assert {event[-1] for event in s.f.events if event[0] == "curl"} == set(s.m.HTTP_ACCEPTANCE_URLS)


@pytest.mark.parametrize("code", ["403", "406", "404", "302"])
def test_nontransient_http_failure_cannot_pass_acceptance(runtime, code):
    s = runtime
    s.f.codes["https://ai.vip-e.net/"] = code
    with pytest.raises(s.m.B, match="acceptance failed"):
        s.m.http_and_tunnel_acceptance(timeout_seconds=10)
    assert not s.clock.sleeps


def test_persistent_http_failure_is_bounded(runtime):
    s = runtime
    s.f.codes["https://api.vip-e.net/ready"] = "503"
    with pytest.raises(s.m.B, match="timeout"):
        s.m.http_and_tunnel_acceptance(timeout_seconds=10)
    assert s.clock.now == 10


@pytest.mark.parametrize("unit_index", [0, 1, 2])
def test_each_control_tunnel_is_required_and_timeout_is_bounded(runtime, unit_index):
    s = runtime
    s.f.inactive.add(s.m.TUNNELS[unit_index])
    with pytest.raises(s.m.B, match="timeout"):
        s.m.http_and_tunnel_acceptance(timeout_seconds=10)
    assert s.clock.now == 10


@pytest.mark.parametrize("accept", ["acceptance", "legacy_acceptance"])
@pytest.mark.parametrize("drift", ["id", "retry-count"])
def test_acceptance_rechecks_identity_and_policies_after_http_wait(runtime, accept, drift):
    s = runtime
    cid = s.f.running_ids[8]
    changed = []
    s.f.codes["https://api.vip-e.net/ready"] = ["503", "200"]
    def during_probe(url):
        if changed:
            return
        changed.append(True)
        if drift == "id":
            replacement = "e" * 64
            s.f.docs[replacement] = s.f.docs.pop(cid)
            s.f.docs[replacement]["Id"] = replacement
            s.f.running_ids[8] = replacement
        else:
            s.f.docs[cid]["HostConfig"]["RestartPolicy"] = {
                "Name": "on-failure", "MaximumRetryCount": 23}
    s.f.on_curl = during_probe
    with pytest.raises(s.m.B, match="drifted"):
        getattr(s.m, accept)(s.t)
    assert s.clock.sleeps == [5]


@pytest.mark.parametrize("accept,filename", [
    ("acceptance", "fr06c5_host_state_bind.py"),
    ("acceptance", "fr06c4_runtime_bind.py"),
    ("legacy_acceptance", "fr06c4_runtime_bind.py"),
])
def test_acceptance_rechecks_encrypted_binds_after_http(runtime, accept, filename):
    s = runtime
    s.f.on_curl = lambda url: s.f.validations.update({filename: "NOT_READY"})
    with pytest.raises(s.m.B):
        getattr(s.m, accept)(s.t)


def test_http_timeout_accounts_for_request_time(runtime):
    s = runtime
    s.f.query_seconds = 1
    s.f.codes["https://api.vip-e.net/ready"] = "503"
    with pytest.raises(s.m.B, match="timeout"):
        s.m.http_and_tunnel_acceptance(timeout_seconds=11)
    assert s.clock.now == 11
    assert all(timeout <= 11 - when for args, timeout, when in s.f.calls)
