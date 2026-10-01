#!/usr/bin/env python3
"""Fixed, fail-closed source merge/sync dispatcher; NOT installed by this module.

All three reviewed launchers select only the invocation label and use one fixed
root/guard. No shell snippets, arbitrary repositories, bypass flags, credential
reads, production lifecycle or installer are exposed. Deployment requires an
independently authorized, source-reviewed enrollment. Local tests and a root
manifest alone are NOT evidence that active automation ingress is enrolled.

No call in this module resolves an earlier platform refusal or uncertain effect.
A missing or mismatched enrollment refuses before creating the execution journal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
from scripts.security.fr06_execution_guard import (
    Binding, SyncBinding, ExecutionGuard, GuardBlocked, ObservedResult,
    TASK_ID, INVOCATIONS, _open_directory, _file_metadata, _unique_pairs,
)

ROOT = Path('/opt/AIOS')
REPOSITORY = 'ipdomx/AIONEX-AIOS'
API = 'repos/' + REPOSITORY
GUARD_ROOT = Path('/var/lib/aionex/fr06-executor')
LAUNCH_ROOT = Path('/usr/local/libexec/aionex/fr06')
LAUNCHERS = {'scheduled': 'aionex-fr06-primary', 'watchdog': 'aionex-fr06-watchdog',
             'interactive': 'aionex-fr06-interactive'}
CODE = ('scripts/security/fr06_source_operator.py', 'scripts/security/fr06_execution_guard.py',
        'scripts/security/fr06_execution_enrollment.py')
MINIMUM_CHECKS = frozenset({
    'Owner and VIP browser boundaries', 'CodeQL Analysis (python)',
    'Phase 36 Reporting Invariant', 'Backend SBOM and vulnerability gate',
    'Repository secret and hygiene audit', 'CodeQL Analysis (javascript-typescript)',
    'Core Owner / Release / Web Contracts', 'Backend Tests', 'Frontend Build',
    'Production Docker Build', 'Dependency Security',
})
MAX_OUTPUT = 1024 * 1024


class SourceBlocked(GuardBlocked):
    """No further effect is authorized; diagnostics never contain command output."""


def need(ok: bool, why: str) -> None:
    if not ok:
        raise SourceBlocked(why)


def hex40(x: object) -> bool:
    return isinstance(x, str) and re.fullmatch('[0-9a-f]{40}', x) is not None


def canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    except (ValueError, TypeError):
        raise SourceBlocked('noncanonical source evidence') from None


def decode(raw: str | bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError):
        raise SourceBlocked('invalid bounded JSON response') from None


def command(args: list[str], *, timeout: int = 30, stdin: str | None = None) -> str:
    """Bounded fixed-command child; join its owned process group on timeout.

    A timeout is still an UNKNOWN effect. Never turn it into observed_no_effect.
    stdout/stderr remain internal and are never printed in exception messages.
    """
    try:
        proc = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        try:
            out, err = proc.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                raise SourceBlocked('owned child group did not settle; outcome unknown; no replay') from None
            raise SourceBlocked('fixed command timed out; outcome unknown; do not replay') from None
    except OSError:
        raise SourceBlocked('fixed command unavailable; outcome not accepted') from None
    need(proc.returncode == 0, 'fixed command failed or was refused; do not replay')
    need(len(out.encode()) <= MAX_OUTPUT and len(err.encode()) <= MAX_OUTPUT, 'command output exceeded bound')
    return out.strip()


@dataclass(frozen=True)
class Request:
    action: str
    pr: int
    head: str
    source: str
    target: str
    boot_id: str
    operation_id: str
    generation: int

    def validate(self) -> None:
        need(isinstance(self.action, str) and self.action in {'source_merge', 'source_sync'}, 'unsupported source action')
        need(type(self.pr) is int and self.pr > 0, 'positive PR identity required')
        need(all(hex40(x) for x in (self.head, self.source, self.target)), 'exact commit identities required')
        Binding(self.source, self.source, self.boot_id, self.operation_id, self.generation, True, 'closed').validate()
        if self.action == 'source_merge':
            need(self.target == self.head, 'merge target must be exact PR head')


def required_checks(rules: Any, checks: Any, sha: str) -> list[str]:
    need(isinstance(rules, list) and all(isinstance(x, dict) for x in rules), 'active rules unavailable')
    relevant = [x for x in rules if x.get('type') == 'required_status_checks']
    pr_rules = [x for x in rules if x.get('type') == 'pull_request']
    need(relevant and pr_rules, 'protected PR and checks rules required')
    pairs: set[tuple[str, int]] = set()
    for rule in relevant:
        p = rule.get('parameters')
        need(isinstance(p, dict) and p.get('strict_required_status_checks_policy') is True, 'strict up-to-date rule required')
        items = p.get('required_status_checks')
        need(isinstance(items, list) and bool(items), 'required contexts missing')
        for item in items:
            need(isinstance(item, dict) and isinstance(item.get('context'), str)
                 and type(item.get('integration_id')) is int and item['integration_id'] > 0, 'check app identity missing')
            pairs.add((item['context'], item['integration_id']))
    need(MINIMUM_CHECKS <= {p[0] for p in pairs}, 'required security checks weakened')
    for rule in pr_rules:
        p = rule.get('parameters')
        need(isinstance(p, dict) and p.get('required_review_thread_resolution') is True
             and isinstance(p.get('allowed_merge_methods'), list) and 'merge' in p['allowed_merge_methods'],
             'normal protected merge and review resolution required')
    need(isinstance(checks, dict) and type(checks.get('total_count')) is int
         and isinstance(checks.get('check_runs'), list)
         and checks['total_count'] == len(checks['check_runs']) <= 100, 'check inventory incomplete')
    for name, app in pairs:
        matches = [c for c in checks['check_runs'] if isinstance(c, dict) and c.get('name') == name
                   and isinstance(c.get('app'), dict) and c['app'].get('id') == app]
        need(len(matches) == 1, 'required check missing or ambiguous')
        c = matches[0]
        need(c.get('head_sha') == sha and c.get('status') == 'completed' and c.get('conclusion') == 'success',
             'required current-head check is not successful')
    return sorted(name for name, _ in pairs)


def private_json(directory: Path, name: str) -> dict:
    fd = _open_directory(directory)
    try:
        f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            info = _file_metadata(f)
            need(0 < info.st_size <= 65536, 'enrollment record size invalid')
            raw = os.read(f, info.st_size + 1)
            need(len(raw) == info.st_size and raw.endswith(b'\n'), 'enrollment record incomplete')
            result = decode(raw)
            need(isinstance(result, dict), 'enrollment object required')
            return result
        finally:
            os.close(f)
    finally:
        os.close(fd)


class NativePort:
    """Only fixed repository/source operations; no arbitrary effect callback from CLI."""
    guard_root = GUARD_ROOT

    def git(self, *args: str, timeout: int = 30) -> str:
        return command(['git', '-C', str(ROOT), *args], timeout=timeout)

    def api(self, endpoint: str) -> Any:
        need(endpoint.startswith(API+'/'), 'foreign repository endpoint forbidden')
        return decode(command(['gh', 'api', '--hostname', 'github.com', '--method', 'GET', endpoint]))

    def local(self) -> tuple[str, str, bool]:
        need(self.git('rev-parse', '--show-toplevel') == str(ROOT), 'wrong source root')
        need(self.git('symbolic-ref', '--short', 'HEAD') == 'main', 'server must be on main')
        url = self.git('remote', 'get-url', 'origin')
        need(url in {'git@github.com:ipdomx/AIONEX-AIOS.git', 'https://github.com/ipdomx/AIONEX-AIOS.git',
                     'https://github.com/ipdomx/AIONEX-AIOS'}, 'origin identity differs')
        return self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'refs/heads/main'), not bool(self.git('status', '--porcelain=v1'))

    def enrollment(self, req: Request) -> None:
        """Validate external installation bytes, never issue a bootstrap receipt.

        The external, independently authorized bootstrap MUST first enforce all
        active ingress routing, reconcile earlier effects, and retain evidence.
        This check cannot establish that social/automation adoption by itself.
        No enrollment file, launcher, ACL or directory is installed here.
        """
        need(os.geteuid() == 0, 'root-owned installed route required')
        need(Path(__file__).resolve() == ROOT/'scripts/security/fr06_source_operator.py', 'uninstalled operator cannot execute')
        local, main, clean = self.local()
        need(local == main == req.source and clean, 'exact clean installed source required')
        data = private_json(GUARD_ROOT, 'enrollment.json')
        need(set(data) == {'schema', 'task_id', 'source_commit', 'boot_id', 'operation_id', 'generation',
                           'guard_directory', 'launchers', 'bootstrap_evidence_sha256'}, 'exact enrollment fields required')
        need(data['schema'] == 'aionex.fr06-fixed-source-enrollment.v1' and data['task_id'] == TASK_ID
             and data['source_commit'] == req.source and data['boot_id'] == req.boot_id
             and data['operation_id'] == req.operation_id and type(data['generation']) is int
             and data['generation'] == req.generation and data['guard_directory'] == str(GUARD_ROOT),
             'external enrollment binding differs')
        need(isinstance(data['bootstrap_evidence_sha256'], str)
             and re.fullmatch('[0-9a-f]{64}', data['bootstrap_evidence_sha256']) is not None,
             'bootstrap evidence identity missing')
        # The bootstrap attestation digest is a reference, not approval derived
        # from true flags. Code/image/routing acceptance must already be external.
        need(isinstance(data['launchers'], dict) and set(data['launchers']) == set(LAUNCHERS), 'all three enrolled routes required')
        for rel in CODE:
            actual = ROOT/rel
            st = actual.lstat()
            need(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not (st.st_mode & 0o022), 'unsafe source metadata')
            need(self.git('hash-object', '--', rel) == self.git('rev-parse', req.source+':'+rel),
                 'installed code differs byte-for-byte from tracked source')
        for kind, name in LAUNCHERS.items():
            expected = (ROOT/'deploy/bin'/name).read_bytes()
            p = LAUNCH_ROOT/name
            fd = os.open(p, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
            try:
                st = os.fstat(fd)
                need(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1
                     and stat.S_IMODE(st.st_mode) == 0o755 and st.st_size == len(expected), 'unsafe installed launcher')
                actual = os.read(fd, st.st_size+1)
                need(actual == expected and data['launchers'][kind] == hashlib.sha256(actual).hexdigest(),
                     'enrolled launcher bytes differ')
            finally:
                os.close(fd)
        d = _open_directory(GUARD_ROOT/'receipts'); os.close(d)
        verifier_rel = 'scripts/security/fr06_execution_enrollment.py'
        verifier = ROOT/verifier_rel
        need(verifier.is_file() and not verifier.is_symlink(), 'accepted ingress bootstrap verifier unavailable')
        need(self.git('hash-object', '--', verifier_rel) == self.git('rev-parse', req.source+':'+verifier_rel),
             'ingress enrollment verifier is not tracked exact source')
        # This independent verifier is intentionally not supplied or installed by
        # this source operator. It must attest actual primary/watchdog/interactive
        # ingress routing and reconciliation of pre-guard effects, not true flags.
        from scripts.security.fr06_execution_enrollment import verify_installed_routes
        verify_installed_routes(source_root=ROOT, guard_root=GUARD_ROOT, enrollment=data,
                                active_guard=getattr(self, '_enrollment_guard', None))


    def authority(self, req: Request) -> tuple[str, dict]:
        # This helper returns only its explicit five-field authority projection.
        # Never call _inspect or serialize Docker inspection/Config.Env here.
        from scripts.security.fr06c5d11_graceful_stop_operator import _authority
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip(), _authority(req.operation_id, req.generation)

    def remote(self, req: Request) -> dict:
        main = self.api(API+'/branches/main')['commit']['sha']
        pr = decode(command(['gh', 'pr', 'view', str(req.pr), '--repo', 'github.com/'+REPOSITORY, '--json',
            'number,state,isDraft,headRefOid,baseRefName,baseRefOid,mergeStateStatus,mergeable,mergeCommit,reviewDecision']))
        sha = req.head if req.action == 'source_merge' else req.target
        rules = self.api(API+'/rules/branches/main')
        checks = self.api(API+'/commits/'+sha+'/check-runs?filter=latest&per_page=100')
        return {'main': main, 'pr': pr, 'rules': rules, 'checks': checks}

    def checkout_preflight(self) -> None:
        # Do not disable existing hooks: they may be security controls. Reject
        # their presence instead of hiding extra effects in a source-only sync.
        need(not self.git('config', '--default', '', '--get', 'core.hooksPath'),
             'configured Git hooks require independent source-sync review')
        root = Path(self.git('rev-parse', '--show-toplevel'))
        hooks = Path(self.git('rev-parse', '--git-path', 'hooks'))
        if not hooks.is_absolute():
            hooks = root/hooks
        if hooks.exists():
            st = hooks.lstat()
            need(stat.S_ISDIR(st.st_mode) and not hooks.is_symlink(), 'unsafe Git hook directory')
            need(all(p.name.endswith('.sample') for p in hooks.iterdir()),
                 'existing Git hooks require independent source-sync review')
        need(self.git('config', '--default', 'false', '--type=bool', '--get', 'submodule.recurse') == 'false',
             'implicit submodule effects forbidden')

    def fetch_target(self, req: Request) -> None:
        NativePort.checkout_preflight(self)
        self.git('fetch', '--no-tags', '--no-auto-maintenance', 'origin', 'refs/heads/main:refs/remotes/origin/main', timeout=60)
        need(self.git('rev-parse', 'refs/remotes/origin/main') == req.target, 'fetched main changed; no fast-forward')
        self.git('merge-base', '--is-ancestor', req.source, req.target)
        # Forbid changed executable operator bytes during the live process.
        # Installing a changed dispatcher requires a separate accepted bootstrap.
        changed = self.git('diff', '--name-only', req.source, req.target, '--', *CODE,
                           *['deploy/bin/'+n for n in LAUNCHERS.values()])
        need(not changed, 'self-update requires independent reviewed enrollment')

    def merge(self, req: Request) -> None:
        response = decode(command(['gh', 'api', '--hostname', 'github.com', '--method', 'PUT', API+'/pulls/'+str(req.pr)+'/merge',
            '-f', 'sha='+req.head, '-f', 'merge_method=merge']))
        need(isinstance(response, dict) and response.get('merged') is True and hex40(response.get('sha')),
             'merge was refused or unproven; retain intent')

    def fast_forward(self, req: Request) -> None:
        NativePort.checkout_preflight(self)
        self.git('-c', 'gc.auto=0', '-c', 'maintenance.auto=false', 'merge', '--ff-only', '--no-edit', req.target, timeout=60)

    def merge_observation(self, req: Request) -> dict:
        p = self.api(API+'/pulls/'+str(req.pr))
        main = self.api(API+'/branches/main')['commit']['sha']
        need(p.get('number') == req.pr and p.get('merged') is True and p.get('base',{}).get('ref') == 'main'
             and p.get('head',{}).get('sha') == req.head and hex40(p.get('merge_commit_sha'))
             and main == p['merge_commit_sha'], 'exact merge not observed')
        return {'pr': req.pr, 'head': req.head, 'merge_commit': p['merge_commit_sha'], 'remote_main': main,
                'source_synced': False, 'deployment_accepted': False}

    def save(self, payload: dict) -> str:
        data = canonical(payload); name = 'source-'+uuid4().hex+'.json'
        d = _open_directory(GUARD_ROOT/'receipts')
        try:
            f = os.open(name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600, dir_fd=d)
            try:
                remaining = memoryview(data)
                while remaining:
                    n = os.write(f, remaining); need(n > 0, 'receipt write stalled'); remaining = remaining[n:]
                os.fsync(f)
            finally:
                os.close(f)
            os.fsync(d)
            f = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=d)
            try:
                st = _file_metadata(f); actual = os.read(f, st.st_size+1)
                need(actual == data, 'source receipt readback differs')
            finally:
                os.close(f)
        finally:
            os.close(d)
        return hashlib.sha256(data).hexdigest()


def validate_remote(req: Request, snapshot: Any) -> list[str]:
    need(isinstance(snapshot, dict), 'remote evidence object required')
    p = snapshot.get('pr')
    need(isinstance(p, dict) and p.get('number') == req.pr and p.get('baseRefName') == 'main'
         and p.get('headRefOid') == req.head and p.get('isDraft') is False, 'PR identity differs')
    if req.action == 'source_merge':
        need(snapshot.get('main') == req.source == p.get('baseRefOid') and p.get('state') == 'OPEN'
             and p.get('mergeStateStatus') == 'CLEAN' and p.get('mergeable') == 'MERGEABLE',
             'PR not clean current-base merge candidate')
        need(p.get('reviewDecision') in ('', None, 'APPROVED'), 'review not accepted')
        for rule in snapshot.get('rules', []):
            if isinstance(rule, dict) and rule.get('type') == 'pull_request':
                params = rule.get('parameters')
                need(isinstance(params, dict), 'review rule malformed')
                count = params.get('required_approving_review_count', 0)
                need(type(count) is int and count >= 0, 'review count invalid')
                if count or params.get('require_code_owner_review') or params.get('require_last_push_approval'):
                    need(p.get('reviewDecision') == 'APPROVED', 'required approval not observed')
    else:
        need(snapshot.get('main') == req.target and p.get('state') == 'MERGED'
             and isinstance(p.get('mergeCommit'), dict) and p['mergeCommit'].get('oid') == req.target,
             'sync target is not observed PR merge on main')
    return required_checks(snapshot.get('rules'), snapshot.get('checks'),
                           req.head if req.action == 'source_merge' else req.target)


def require_same_authority(port: NativePort, req: Request) -> None:
    boot, auth = port.authority(req)
    need(isinstance(auth, dict) and boot == req.boot_id and auth.get('operation_id') == req.operation_id
         and type(auth.get('generation')) is int and auth['generation'] == req.generation
         and auth.get('status') == 'closed' and auth.get('enabled') is False
         and auth.get('full_host_closure') is False, 'post-effect authority changed')


def binding_from(port: NativePort, req: Request) -> Binding | SyncBinding:
    local, local_main, clean = port.local()
    boot, auth = port.authority(req)
    need(isinstance(auth, dict) and auth.get('operation_id') == req.operation_id
         and type(auth.get('generation')) is int and auth['generation'] == req.generation
         and auth.get('status') == 'closed' and auth.get('enabled') is False
         and auth.get('full_host_closure') is False and boot == req.boot_id, 'closed authority or boot changed')
    remote = port.remote(req)
    validate_remote(req, remote)
    need(local == local_main == req.source and clean is True, 'source is not expected clean main')
    if req.action == 'source_sync':
        return SyncBinding(local, local_main, remote['main'], boot, req.operation_id, req.generation, clean, 'closed')
    return Binding(local, remote['main'], boot, req.operation_id, req.generation, clean, 'closed')


def execute(req: Request, *, run_id: str, invocation_type: str, port: NativePort | None = None) -> dict:
    req.validate()
    need(isinstance(invocation_type, str) and invocation_type in INVOCATIONS, 'invalid invocation')
    port = NativePort() if port is None else port  # Tests only; not exposed by CLI.
    port.enrollment(req)
    with ExecutionGuard(port.guard_root, run_id=run_id, invocation_type=invocation_type) as guard:
        port._enrollment_guard = guard
        try:
            # Re-read installed routing while ownership is held; no stale pre-lock grant.
            port.enrollment(req)
            expected = binding_from(port, req)
            def observe():
                port.enrollment(req)
                return binding_from(port, req)
            def invoke():
                # Check all mutable acceptance immediately before any remote/local effect.
                port.enrollment(req)
                need(binding_from(port, req) == expected, 'pre-effect context changed')
                if req.action == 'source_merge':
                    port.merge(req)
                    result = port.merge_observation(req)
                    local, main, clean = port.local()
                    need(local == main == req.source and clean is True, 'local source changed during merge')
                    require_same_authority(port, req)
                else:
                    port.fetch_target(req)
                    need(binding_from(port, req) == expected, 'post-fetch context changed')
                    port.fast_forward(req)
                    local, main, clean = port.local()
                    need(local == main == req.target and clean is True, 'fast-forward not observed clean')
                    require_same_authority(port, req)
                    validate_remote(req, port.remote(req))
                    result = {'pr': req.pr, 'head': req.head, 'source_commit': local, 'remote_main': req.target,
                              'source_synced': True, 'deployment_accepted': False}
                evidence = {'schema': 'aionex.fr06-source-result.v1', 'task_id': TASK_ID, 'run_id': run_id,
                            'invocation_type': invocation_type, 'at': datetime.now(timezone.utc).isoformat(),
                            'request': asdict(req), 'observations': result, 'production_deployed': False}
                return ObservedResult('observed_complete', port.save(evidence))
            return guard.perform(action=req.action, target_commit=req.target, expected=expected,
                                 observe=observe, invoke=invoke)
        finally:
            port._enrollment_guard = None



def main() -> int:
    # A fixed no-effect challenge for independent installation verification.
    # It does not create a lock/journal, accept source or issue enrollment.
    if len(sys.argv) > 1 and sys.argv[1] == 'enrollment_probe':
        p = argparse.ArgumentParser(description='Read-only kernel route challenge')
        p.add_argument('action', choices=('enrollment_probe',))
        p.add_argument('--challenge', required=True)
        p.add_argument('--invocation-type', required=True, choices=sorted(INVOCATIONS))
        a = p.parse_args()
        try:
            from scripts.security.fr06_execution_enrollment import probe_existing_lock
            need(os.geteuid() == 0, 'root-owned installed probe required')
            need(Path(__file__).resolve() == ROOT/'scripts/security/fr06_source_operator.py', 'uninstalled probe')
            result = probe_existing_lock(GUARD_ROOT, a.invocation_type, a.challenge)
        except Exception:
            print(json.dumps({'status': 'probe_blocked', 'production_accepted': False}))
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('source_merge', 'source_sync'))
    p.add_argument('--invocation-type', required=True, choices=sorted(INVOCATIONS))
    p.add_argument('--run-id', required=True)
    p.add_argument('--pr', type=int, required=True)
    p.add_argument('--head', required=True); p.add_argument('--source', required=True); p.add_argument('--target', required=True)
    p.add_argument('--boot-id', required=True); p.add_argument('--operation-id', required=True); p.add_argument('--generation', type=int, required=True)
    args = vars(p.parse_args()); run = args.pop('run_id'); kind = args.pop('invocation_type')
    try:
        result = execute(Request(**args), run_id=run, invocation_type=kind)
    except Exception:
        # No raw data, exception repr, environment or stderr is emitted.
        print(json.dumps({'status': 'blocked_or_uncertain', 'automatic_retry': False, 'production_accepted': False}))
        return 2
    print(json.dumps({'status': 'source_observed', 'evidence_sha256': result['payload']['evidence_sha256'],
                      'production_accepted': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
