"""Read/verify-only fixed-route enrollment; never provision or issue authority.

An independently reviewed bootstrap must supply the bounded, canonical, sanitized
role-run evidence. A digest, prompt edit or scheduler time is not enrollment.
The historical journal prefix must have no unfinished observed runs. Every check
also challenges all installed launcher routes against the SAME live kernel lock.
This is a cooperative-executor protocol, not isolation from malicious root or a
cryptographic claim about who typed a role label. It does not resolve refusals,
rotate credentials, install files, execute source changes or accept production.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from scripts.security.fr06_execution_guard import GuardBlocked, ConcurrentOwner, ExecutionGuard, _open_directory, _file_metadata

ROOT = Path('/opt/AIOS')
GUARD = Path('/var/lib/aionex/fr06-executor')
LAUNCH = Path('/usr/local/libexec/aionex/fr06')
RUNTIME = Path('docs/project/runtime/fr06-recurring-task-health')
TASK = '6abd4c859254819191f562715e18c916'
WATCHDOG = '6abe498cd0ec8191962f9a6d3e4d3bcc'
ROUTES = {'scheduled': 'aionex-fr06-primary', 'watchdog': 'aionex-fr06-watchdog', 'interactive': 'aionex-fr06-interactive'}
BOUND = ('source_commit', 'boot_id', 'operation_id', 'generation')
MAX_BYTES = 65536
MAX_EVENTS = 16 * 1024 * 1024
# Aggregation window for two hourly role acknowledgements, NOT drain or
# activation freshness. Runtime kernel probes still use a new challenge now.
MAX_AGE = 2 * 3600


class EnrollmentBlocked(GuardBlocked):
    pass


def need(ok: bool, why: str) -> None:
    if not ok:
        raise EnrollmentBlocked(why)


def hexdigest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ishex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{%d}' % length, value) is not None


def runid(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value) is not None


def uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def canon(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    except (ValueError, TypeError):
        raise EnrollmentBlocked('noncanonical enrollment data') from None


def _pairs(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        need(key not in out, 'duplicate enrollment key')
        out[key] = value
    return out


def decode(raw: bytes, *, maximum: int = MAX_BYTES) -> dict:
    need(type(raw) is bytes and 0 < len(raw) <= maximum and raw.endswith(b'\n'), 'invalid evidence byte bounds')
    try:
        obj = json.loads(raw, object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, TypeError):
        raise EnrollmentBlocked('malformed enrollment JSON') from None
    need(isinstance(obj, dict), 'evidence object required')
    return obj


def fields(obj: Any, keys: set[str]) -> None:
    need(isinstance(obj, dict) and set(obj) == keys, 'evidence fields differ')


def timestamp(value: Any) -> datetime:
    try:
        t = datetime.fromisoformat(value)
        need(t.utcoffset() is not None and t.utcoffset().total_seconds() == 0, 'UTC evidence required')
        return t
    except (ValueError, TypeError):
        raise EnrollmentBlocked('invalid evidence timestamp') from None


def _identity(obj: Any) -> None:
    fields(obj, {'device', 'inode', 'lock_device', 'lock_inode'})
    need(all(type(x) is int and x >= 0 for x in obj.values())
         and obj['inode'] > 0 and obj['lock_inode'] > 0, 'invalid lock identity')


def _journal(raw: bytes) -> list[dict]:
    need(type(raw) is bytes and len(raw) <= MAX_EVENTS and (not raw or raw.endswith(b'\n')), 'journal prefix incomplete')
    result, ids = [], set()
    for line in raw.splitlines():
        x = decode(line + b'\n', maximum=MAX_EVENTS)
        key = x.get('event_id')
        need(isinstance(key, str) and key and key not in ids, 'journal event identity ambiguous')
        ids.add(key); result.append(x)
    return result


def _event_run(event: dict) -> tuple[str | None, str | None]:
    refs = event.get('evidence', [])
    need(isinstance(refs, list) and all(isinstance(p, str) for p in refs), 'journal evidence list malformed')
    phase = event.get('run_phase')
    selected: set[tuple[str, str]] = set()
    # Older reports copied previous evidence. Only their newest own start/end is
    # relevant; the event id has to bind to that run rather than a copied receipt.
    for ref in refs:
        p = Path(ref)
        if p.parent.parent.as_posix() != RUNTIME.as_posix() or p.name not in {'started.json', 'terminal.json'}:
            continue
        name = p.parent.name
        if runid(name) and name in event['event_id']:
            selected.add((name, 'started' if p.name == 'started.json' else 'terminal'))
    if phase in {'started', 'terminal'}:
        selected = {x for x in selected if x[1] == phase}
    elif event['event_id'].endswith(('-terminal', '-end')):
        selected = {x for x in selected if x[1] == 'terminal'}
    elif event['event_id'].endswith(('-started', '-start')):
        selected = {x for x in selected if x[1] == 'started'}
    need(len(selected) <= 1, 'ambiguous run phase in journal')
    return next(iter(selected)) if selected else (None, None)


def verify_bundle(*, enrollment: dict, bootstrap_raw: bytes, journal_raw: bytes,
                  role_bytes: dict[str, dict[str, bytes]], live_binding: dict,
                  guard_identity: dict, now: datetime, historical_runs: dict | None = None) -> dict:
    """Pure validation of retained source/route records against live observations.

    No issuer is provided. Synthetic fixture role records are not live task
    records. Live bootstrap may proceed only via the separately authorized path.
    """
    fields(live_binding, set(BOUND))
    need(ishex(live_binding['source_commit'], 40) and uuid(live_binding['boot_id'])
         and uuid(live_binding['operation_id']) and type(live_binding['generation']) is int
         and live_binding['generation'] >= 8, 'invalid live binding')
    need(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset().total_seconds() == 0, 'live UTC clock required')
    _identity(guard_identity)
    fields(enrollment, {'schema', 'task_id', *BOUND, 'guard_directory', 'launchers', 'bootstrap_evidence_sha256'})
    need(enrollment['schema'] == 'aionex.fr06-fixed-source-enrollment.v1' and enrollment['task_id'] == TASK
         and enrollment['guard_directory'] == str(GUARD)
         and type(enrollment['generation']) is int and {k: enrollment[k] for k in BOUND} == live_binding, 'enrollment live binding differs')
    fields(enrollment['launchers'], set(ROUTES))
    need(all(ishex(v, 64) for v in enrollment['launchers'].values()), 'launcher digest invalid')
    need(ishex(enrollment['bootstrap_evidence_sha256'], 64)
         and hexdigest(bootstrap_raw) == enrollment['bootstrap_evidence_sha256'], 'bootstrap bytes do not match reference')
    b = decode(bootstrap_raw)
    fields(b, {'schema', 'task_id', *BOUND, 'guard_identity', 'journal_anchor', 'routes'})
    need(b['schema'] == 'aionex.fr06-executor-bootstrap.v1' and b['task_id'] == TASK
         and type(b['generation']) is int and {k: b[k] for k in BOUND} == live_binding, 'bootstrap binding differs')
    need(b['guard_identity'] == guard_identity, 'bootstrap kernel resource identity differs')
    _identity(b['guard_identity'])
    fields(b['journal_anchor'], {'byte_count', 'sha256'})
    length = b['journal_anchor']['byte_count']
    need(type(length) is int and 0 < length <= MAX_EVENTS and length <= len(journal_raw)
         and hexdigest(journal_raw[:length]) == b['journal_anchor']['sha256'], 'canonical journal prefix differs')
    events = _journal(journal_raw[:length]); by_id = {e['event_id']: e for e in events}
    quarantined: set[str] = set()
    for correction in events:
        if correction.get('event_type') != 'fr06_receipt_metadata_quarantine':
            continue
        target_id = correction.get('target_event_id')
        need(isinstance(target_id, str) and target_id not in quarantined, 'duplicate or invalid metadata correction')
        target = by_id.get(target_id)
        need(isinstance(target, dict) and '$' in target['event_id']
             and isinstance(target.get('source_commit'), str) and target['source_commit'].startswith('$'),
             'metadata quarantine cannot resolve a valid run or effect')
        need(correction.get('target_event_canonical_sha256') == hexdigest(canon(target))
             and correction.get('scope') == 'invalid_metadata_only_not_effect_reconciliation'
             and ishex(correction.get('source_commit'), 40), 'metadata correction identity or scope differs')
        quarantined.add(target_id)
    pending: set[str] = set()
    run_events: dict[str, dict] = {}
    for event in events:
        if event['event_id'] in quarantined:
            continue  # Invalid metadata only; no run terminal or effect result is synthesized.
        if event.get('invocation_type') not in ('scheduled', 'watchdog', 'interactive'):
            continue
        name, phase = _event_run(event)
        # Unresolved placeholder records are never enrollment evidence.
        need('$' not in event['event_id'] and not str(event.get('source_commit', '')).startswith('$'),
             'historical malformed run requires explicit authorized reconciliation')
        if event.get('run_phase') in ('started', 'terminal') or event['event_id'].endswith(('-started', '-start', '-terminal')):
            need(name is not None and phase is not None, 'unbound historical run requires reconciliation')
        if phase:
            run_events.setdefault(name, {})[phase] = event
        if phase == 'started': pending.add(name)
        elif phase == 'terminal': pending.discard(name)
    need(not pending, 'pre-bootstrap run outcomes remain uncertain')
    fields(b['routes'], set(ROUTES)); fields(role_bytes, set(ROUTES))
    seen_runs: set[str] = set()
    challenges: set[str] = set()
    for role in ROUTES:
        route = b['routes'][role]
        fields(route, {'run_id', 'started_event_id', 'terminal_event_id', 'started_sha256', 'terminal_sha256', 'probe_sha256'})
        rid = route['run_id']
        need(runid(rid) and rid not in seen_runs, 'distinct role run identity required'); seen_runs.add(rid)
        fields(role_bytes[role], {'started', 'terminal', 'probe'})
        values = {}
        for kind in ('started', 'terminal', 'probe'):
            raw = role_bytes[role][kind]
            need(ishex(route[kind + '_sha256'], 64) and hexdigest(raw) == route[kind + '_sha256'], 'role receipt bytes differ')
            values[kind] = decode(raw)
        common = {'schema', 'run_id', 'task_id', 'invocation_type', 'phase', 'at', *BOUND}
        for phase in ('started', 'terminal'):
            v = values[phase]
            fields(v, common | ({'probe_sha256'} if phase == 'terminal' else set()))
            need(v['schema'] == 'aionex.fr06-route-enrollment-run.v1' and v['run_id'] == rid
                 and v['task_id'] == (WATCHDOG if role == 'watchdog' else TASK)
                 and v['invocation_type'] == role and v['phase'] == phase
                 and type(v['generation']) is int and {k: v[k] for k in BOUND} == live_binding, 'role run binding differs')
            ev = by_id.get(route[phase + '_event_id'])
            ref = (RUNTIME / rid / (phase + '.json')).as_posix()
            need(isinstance(ev, dict) and ev.get('run_id') == rid and ev.get('invocation_type') == role
                 and ev.get('run_phase') == phase and ev.get('event_type') == 'fr06_route_enrollment'
                 and ev.get('automation_task_id') == v['task_id'] and ev.get('source_commit') == live_binding['source_commit']
                 and ref in ev.get('evidence', []) and ev.get('at') == v['at'], 'role receipt not bound in canonical journal')
        proof = values['probe']
        fields(proof, {'schema', 'challenge', 'invocation_type', 'guard_identity', 'pid', 'at', 'result'})
        need(proof['schema'] == 'aionex.fr06-route-probe.v1' and uuid(proof['challenge'])
             and proof['invocation_type'] == role and proof['guard_identity'] == guard_identity
             and type(proof['pid']) is int and proof['pid'] > 0
             and proof['result'] == 'kernel_contention_observed', 'invalid retained kernel proof')
        need(proof['challenge'] not in challenges, 'route challenge was reused')
        challenges.add(proof['challenge'])
        need(values['terminal']['probe_sha256'] == route['probe_sha256'], 'terminal proof reference differs')
        start, end, observed = timestamp(values['started']['at']), timestamp(values['terminal']['at']), timestamp(proof['at'])
        need(start <= observed <= end <= now and (now-start).total_seconds() <= MAX_AGE, 'enrollment proof stale or chronology invalid')
    # A canonical terminal event alone cannot prove a run finished. Preserve and
    # verify its actual sanitized file pair; unsupported legacy formats halt for
    # independent review. This checks run accounting, not provider/host effects.
    historical_runs = {} if historical_runs is None else historical_runs
    need(isinstance(historical_runs, dict), 'historical receipt map malformed')
    historical = set(run_events) - seen_runs
    need(set(historical_runs) == historical, 'historical run file coverage incomplete')
    for rid in historical:
        pair = historical_runs[rid]
        fields(pair, {'started', 'terminal'})
        need(set(run_events[rid]) == {'started', 'terminal'}, 'historical run chronology incomplete')
        observations = {}
        for phase in ('started', 'terminal'):
            x = decode(pair[phase]); ev = run_events[rid][phase]
            need(x.get('run_id') == rid and x.get('invocation_type') == ev.get('invocation_type')
                 and (x.get('phase') or x.get('run_phase')) == phase, 'historical run file identity differs')
            source = x.get('observed_source_commit') or x.get('source_commit')
            need(ishex(source, 40) and source == ev.get('source_commit'), 'historical run source not bound')
            value = (x.get('started_at') or x.get('started_at_utc')) if phase == 'started' else (x.get('finished_at') or x.get('finished_at_utc'))
            observations[phase] = timestamp(value)
        need(observations['started'] <= observations['terminal'] <= now, 'historical run times differ')
        t = decode(pair['terminal'])
        # No supplied flag can reconcile an uncertain shared effect here. Only
        # already-paired run accounting is accepted; actual action reconciliation
        # remains a mandatory responsibility of independent bootstrap admission.
        need(t.get('outcome') in ('progress', 'waiting_ci', 'waiting_real_time', 'concurrent_owner', 'tool_blocked', 'failed'),
             'historical outcome unknown')
    return {'schema': 'aionex.fr06-enrollment-verification.v1', **live_binding,
            'guard_identity': guard_identity, 'bootstrap_sha256': hexdigest(bootstrap_raw),
            'roles': sorted(ROUTES), 'quarantined_metadata_events': sorted(quarantined),
            'activation_authority_issued': False}


def _root(path: Path) -> int:
    need(path.is_absolute() and '..' not in path.parts, 'unsafe evidence root')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = nxt
        st = os.fstat(fd)
        need(st.st_uid == os.geteuid() and not st.st_mode & 0o022, 'untrusted evidence root')
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0: os.close(fd)


def read_bounded(root: Path, relative: str, *, mode: int = 0o600, maximum: int = MAX_BYTES) -> bytes:
    """No-follow relative fixed evidence read; never accept arbitrary raw filenames."""
    rel = Path(relative)
    need(not rel.is_absolute() and rel.parts and all(x not in ('.', '..') for x in rel.parts), 'unsafe evidence relative path')
    directory = _root(root)
    fd = -1
    try:
        for part in rel.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory); directory = child
            st = os.fstat(directory)
            need(st.st_uid == os.geteuid() and not st.st_mode & 0o022, 'unsafe evidence ancestor')
        fd = os.open(rel.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        st = os.fstat(fd)
        need(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and st.st_nlink == 1
             and stat.S_IMODE(st.st_mode) == mode and 0 < st.st_size <= maximum, 'unsafe evidence metadata')
        data = b''
        while len(data) < st.st_size:
            chunk = os.read(fd, min(65536, st.st_size-len(data)))
            need(bool(chunk), 'incomplete evidence read'); data += chunk
        final = os.fstat(fd); named = os.stat(rel.name, dir_fd=directory, follow_symlinks=False)
        need((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) ==
             (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns)
             and (named.st_dev, named.st_ino) == (st.st_dev, st.st_ino), 'evidence changed while read')
        return data
    finally:
        if fd >= 0: os.close(fd)
        os.close(directory)


def resource_identity(directory: Path) -> dict:
    root = _open_directory(directory)
    lock = -1
    try:
        lock = os.open('execution.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
        st, ls = os.fstat(root), _file_metadata(lock)
        return {'device': st.st_dev, 'inode': st.st_ino, 'lock_device': ls.st_dev, 'lock_inode': ls.st_ino}
    finally:
        if lock >= 0: os.close(lock)
        os.close(root)


@contextmanager
def held_probe_lock(directory: Path, active_guard=None):
    """No creation; reuse ONLY an actually held same-process verified guard."""
    if active_guard is not None:
        need(type(active_guard) is ExecutionGuard, 'typed live guard required')
        need(active_guard.directory == directory, 'foreign active guard')
        active_guard._assert_held()
        yield resource_identity(directory)
        active_guard._assert_held()
        return
    root = _open_directory(directory)
    fd = -1
    acquired = False
    try:
        fd = os.open('execution.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
        _file_metadata(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); acquired = True
        except BlockingIOError:
            raise ConcurrentOwner('another executor owns enrollment probe lock') from None
        ident = resource_identity(directory)
        need((ident['device'], ident['inode']) == (os.fstat(root).st_dev, os.fstat(root).st_ino)
             and (ident['lock_device'], ident['lock_inode']) == (os.fstat(fd).st_dev, os.fstat(fd).st_ino), 'probe lock replaced')
        yield ident
        need(resource_identity(directory) == ident, 'probe resources changed')
    finally:
        if acquired: fcntl.flock(fd, fcntl.LOCK_UN)
        if fd >= 0: os.close(fd)
        os.close(root)


def probe_existing_lock(directory: Path, role: str, challenge: str) -> dict:
    """No effect probe. CLI pins directory; parameter exists only for isolated tests."""
    need(isinstance(role, str) and role in ROUTES and uuid(challenge), 'invalid enrollment probe request')
    root = _open_directory(directory)
    fd = -1
    try:
        fd = os.open('execution.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
        _file_metadata(fd)
        ident = resource_identity(directory)
        need((os.fstat(root).st_dev, os.fstat(root).st_ino) == (ident['device'], ident['inode'])
             and (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (ident['lock_device'], ident['lock_inode']), 'probe inode differs')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'schema': 'aionex.fr06-route-probe.v1', 'invocation_type': role, 'challenge': challenge,
                    'guard_identity': ident, 'pid': os.getpid(), 'at': datetime.now(timezone.utc).isoformat(),
                    'result': 'kernel_contention_observed'}
        fcntl.flock(fd, fcntl.LOCK_UN)
        raise EnrollmentBlocked('no shared lock contention observed')
    finally:
        if fd >= 0: os.close(fd)
        os.close(root)


def challenge_routes(directory: Path, invoke: Callable[[str, str], dict], *, active_guard=None) -> list[dict]:
    proofs = []
    with held_probe_lock(directory, active_guard) as ident:
        for role in ROUTES:
            challenge = str(uuid4()); start = datetime.now(timezone.utc)
            proof = invoke(role, challenge)
            fields(proof, {'schema', 'invocation_type', 'challenge', 'guard_identity', 'pid', 'at', 'result'})
            need(proof['schema'] == 'aionex.fr06-route-probe.v1' and proof['invocation_type'] == role
                 and proof['challenge'] == challenge and proof['guard_identity'] == ident
                 and type(proof['pid']) is int and proof['pid'] > 0 and proof['pid'] != os.getpid()
                 and proof['result'] == 'kernel_contention_observed', 'fresh route challenge differs')
            need(start <= timestamp(proof['at']) <= datetime.now(timezone.utc), 'fresh route probe chronology differs')
            need(resource_identity(directory) == ident, 'probe identity changed')
            proofs.append(proof)
    return proofs


def _require_installed_context(source_root: Path, guard_root: Path) -> None:
    """Production privilege and installation checks; never a configurable bypass.

    Kept separate so nonprivileged tests can model installation explicitly while
    exercising real file ownership and kernel locks as their actual Unix user.
    """
    need(source_root == ROOT and guard_root == GUARD and os.geteuid() == 0, 'fixed installed root required')
    need(Path(__file__).resolve() == ROOT/'scripts/security/fr06_execution_enrollment.py', 'uninstalled enrollment verifier')


def verify_installed_routes(*, source_root: Path, guard_root: Path, enrollment: dict, active_guard=None) -> dict:
    """Native verifier. Reads only explicit allowlisted files, never incident data."""
    _require_installed_context(source_root, guard_root)
    from scripts.security.fr06_source_operator import command
    head = command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])
    need(ishex(head, 40) and head == enrollment.get('source_commit'), 'current enrollment source differs')
    need(not command(['git', '-C', str(ROOT), 'status', '--porcelain=v1']), 'dirty enrollment source')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    live = {k: enrollment[k] for k in BOUND}; live['source_commit'] = head; live['boot_id'] = boot
    stored = decode(read_bounded(GUARD, 'enrollment.json'))
    need(stored == enrollment, 'enrollment changed after outer validation')
    raw = read_bounded(GUARD, 'bootstrap-evidence.json')
    b = decode(raw)
    # Paths are derived only after validation; no arbitrary filenames from JSON.
    fields(b.get('routes'), set(ROUTES))
    role_bytes = {}
    for role, route in b['routes'].items():
        rid = route.get('run_id') if isinstance(route, dict) else None
        need(runid(rid), 'unsafe enrolled run identity')
        role_bytes[role] = {k: read_bounded(ROOT/RUNTIME, rid+'/'+filename)
                            for k, filename in [('started', 'started.json'), ('terminal', 'terminal.json'), ('probe', 'route-probe.json')]}
    journal = read_bounded(ROOT/'docs/project/runtime', 'events.jsonl', mode=0o644, maximum=MAX_EVENTS)
    anchor = b.get('journal_anchor', {})
    length = anchor.get('byte_count') if isinstance(anchor, dict) else None
    need(type(length) is int and 0 < length <= min(MAX_EVENTS, len(journal)), 'invalid journal anchor')
    enrolled = {x['run_id'] for x in b['routes'].values()}
    prior = set()
    for event in _journal(journal[:length]):
        if event.get('invocation_type') in ('scheduled', 'watchdog', 'interactive'):
            rid, phase = _event_run(event)
            if rid is not None and rid not in enrolled: prior.add(rid)
    need(len(prior) <= 256, 'historical run inventory exceeds bound')
    historical = {rid: {phase: read_bounded(ROOT/RUNTIME, rid+'/'+phase+'.json', mode=0o644)
                        for phase in ('started', 'terminal')} for rid in sorted(prior)}
    result = verify_bundle(enrollment=enrollment, bootstrap_raw=raw, journal_raw=journal, role_bytes=role_bytes,
                           live_binding=live, guard_identity=resource_identity(GUARD), now=datetime.now(timezone.utc), historical_runs=historical)
    def invoke(role, challenge):
        response = command([str(LAUNCH/ROUTES[role]), 'enrollment_probe', '--challenge', challenge], timeout=10)
        return decode((response+'\n').encode())
    result['fresh_route_probes'] = challenge_routes(GUARD, invoke, active_guard=active_guard)
    # Re-read immutable enrollment bytes after subprocess probes; unknown changes
    # are not smoothed over by a previously successful digest.
    need(read_bounded(GUARD, 'bootstrap-evidence.json') == raw
         and decode(read_bounded(GUARD, 'enrollment.json')) == stored, 'bootstrap changed during verification')
    return result
