"""Native, fixed-path initial-install caller; no approval or enrollment issuer.

An independently provisioned owner public key and signed, short-lived permit
are mandatory. They are NOT generated, installed or accepted by this module.
The signed control/history evidence is an external review decision, not proof
manufactured from PID absence or a boolean supplied by this process. Signature
validation does not establish the truth of a review; its independent issuance
and real three-role fencing remain operational prerequisites.

The default CLI action only checks. The explicit install action calls the
existing journaled file publisher after every native check, under the SAME
preexisting coordinator lock, and leaves enrollment/activation unauthorized.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.security import fr06_executor_preparation as prep
from scripts.security import fr06_executor_installation as installer
from scripts.security.fr06_execution_guard import Binding
from scripts.security.fr06_source_operator import required_checks

ROOT = Path('/opt/AIOS')
TRUST = Path('/etc/aionex/fr06-initial-install')
AUTHORITY = Path('/var/lib/aionex/fr06-initial-install-authority')
STORE = Path('/var/lib/aionex/fr06-inert-packages')
JOURNALS = Path('/var/lib/aionex/fr06-installation-journals')
GUARD = Path('/var/lib/aionex/fr06-executor')
LAUNCH = Path('/usr/local/libexec/aionex/fr06')
REPOSITORY = 'ipdomx/AIONEX-AIOS'
TASK = '6abd4c859254819191f562715e18c916'
WATCHDOG = '6abe498cd0ec8191962f9a6d3e4d3bcc'
SCHEMA = 'aionex.fr06-initial-install-permit.v1'
ROLES = {'scheduled': TASK, 'watchdog': WATCHDOG, 'interactive': TASK}
MAX_WINDOW = 900
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C',
       'OPENSSL_CONF': '/dev/null'}


class AdmissionBlocked(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise AdmissionBlocked(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fields(value, expected):
    need(type(value) is dict and set(value) == set(expected), 'unexpected evidence fields')


def identity(value):
    fields(value, {'device', 'inode'})
    need(type(value['device']) is int and value['device'] >= 0
         and type(value['inode']) is int and value['inode'] > 0, 'invalid coordinator identity')


def uid(value):
    try:
        need(isinstance(value, str) and str(UUID(value)) == value, 'canonical UUID required')
    except (ValueError, TypeError, AttributeError) as exc:
        raise AdmissionBlocked('canonical UUID required') from exc


def moment(value):
    try:
        need(isinstance(value, str), 'UTC timestamp required')
        result = datetime.fromisoformat(value)
        need(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, 'UTC timestamp required')
        return result
    except (ValueError, AttributeError) as exc:
        raise AdmissionBlocked('UTC timestamp required') from exc


def parse(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 65536, 'evidence size invalid')
    try:
        return prep.decode(raw)
    except (ValueError, prep.PreparationBlocked) as exc:
        raise AdmissionBlocked('evidence JSON is not canonical') from exc


@contextmanager
def sealed(raw):
    fd = os.memfd_create('fr06-public-verification-input', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        left = memoryview(raw)
        while left:
            n = os.write(fd, left); need(n > 0, 'public input copy stalled'); left = left[n:]
        os.lseek(fd, 0, os.SEEK_SET)
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        need(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & seals == seals, 'verification input is not sealed')
        yield fd
    finally:
        os.close(fd)


def verify_signature(public_pem, message, signature):
    """Verify only Ed25519 with sealed descriptors; no private key or disk copy."""
    need(type(public_pem) is bytes and len(public_pem) <= 1024
         and type(message) is bytes and 0 < len(message) <= 65536
         and type(signature) is bytes and len(signature) == 64, 'signature input invalid')
    try:
        lines = public_pem.strip().splitlines()
        need(len(lines) >= 3 and lines[0] == b'-----BEGIN PUBLIC KEY-----'
             and lines[-1] == b'-----END PUBLIC KEY-----', 'public key format invalid')
        der = base64.b64decode(b''.join(lines[1:-1]), validate=True)
        need(len(der) == 44 and der[:12] == bytes.fromhex('302a300506032b6570032100'),
             'only independently trusted Ed25519 keys accepted')
    except (ValueError, TypeError) as exc:
        raise AdmissionBlocked('public key format invalid') from exc
    with ExitStack() as stack:
        key, data, sig = [stack.enter_context(sealed(x)) for x in (public_pem, message, signature)]
        result = subprocess.run(['/usr/bin/openssl', 'pkeyutl', '-verify', '-pubin',
             '-inkey', f'/proc/self/fd/{key}', '-rawin', '-in', f'/proc/self/fd/{data}',
             '-sigfile', f'/proc/self/fd/{sig}'], pass_fds=(key, data, sig), env=ENV,
             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
             timeout=10, check=False)
        need(result.returncode == 0, 'independent permit signature rejected')


def verify_permit(raw, signature, public_pem, control_raw, history_raw, *, now, authorization_id):
    # Signature and fixed scope precede any remote or maintenance access.
    verify_signature(public_pem, raw, signature)
    permit = parse(raw)
    fields(permit, {'schema', 'authorization_id', 'task_id', 'repository', 'action', 'binding',
        'source_pr', 'reviewed_head', 'preparation_id', 'issued_at', 'expires_at',
        'coordinator_identity', 'journal_anchor', 'control_sha256', 'history_sha256'})
    uid(authorization_id); uid(permit['authorization_id']); uid(permit['preparation_id'])
    need(permit['authorization_id'] == authorization_id and permit['schema'] == SCHEMA
         and permit['task_id'] == TASK and permit['repository'] == REPOSITORY
         and permit['action'] == 'initial_install_unenrolled', 'permit scope differs')
    fields(permit['binding'], Binding.__dataclass_fields__)
    binding = Binding(**permit['binding']); binding.validate()
    need(type(permit['source_pr']) is int and permit['source_pr'] > 0
         and isinstance(permit['reviewed_head'], str)
         and re.fullmatch('[0-9a-f]{40}', permit['reviewed_head']), 'protected source reference invalid')
    need(isinstance(now, datetime) and now.tzinfo is not None
         and now.utcoffset().total_seconds() == 0, 'live UTC time required')
    start, end = moment(permit['issued_at']), moment(permit['expires_at'])
    need(start <= now < end and 0 < (end-start).total_seconds() <= MAX_WINDOW, 'permit stale or future-dated')
    identity(permit['coordinator_identity'])
    fields(permit['journal_anchor'], {'byte_count', 'sha256'})
    anchor = permit['journal_anchor']
    need(type(anchor['byte_count']) is int and 0 < anchor['byte_count'] <= 16*1024*1024
         and isinstance(anchor['sha256'], str) and re.fullmatch('[a-f0-9]{64}', anchor['sha256']),
         'exact historical journal anchor required')
    need(sha(control_raw) == permit['control_sha256'] and sha(history_raw) == permit['history_sha256'],
         'signed external evidence changed')
    control, history = parse(control_raw), parse(history_raw)
    fields(control, {'schema', 'authorization_id', 'binding', 'coordinator_identity', 'roles', 'evidence_reference'})
    need(control['schema'] == 'aionex.fr06-independent-install-control.v1'
         and control['authorization_id'] == authorization_id and control['binding'] == permit['binding']
         and control['coordinator_identity'] == permit['coordinator_identity'], 'external control epoch differs')
    fields(control['roles'], ROLES)
    for role, task in ROLES.items():
        value = control['roles'][role]
        fields(value, {'task_id', 'disposition', 'evidence_sha256'})
        need(value['task_id'] == task and value['disposition'] == 'fenced_for_this_installation'
             and isinstance(value['evidence_sha256'], str)
             and re.fullmatch('[0-9a-f]{64}', value['evidence_sha256']), 'role fencing not independently accepted')
    fields(history, {'schema', 'authorization_id', 'journal_anchor', 'disposition',
                     'unresolved_runs', 'evidence_reference'})
    need(history['schema'] == 'aionex.fr06-independent-history-review.v1'
         and history['authorization_id'] == authorization_id and history['journal_anchor'] == anchor
         and history['disposition'] == 'effects_reconciled' and history['unresolved_runs'] == [],
         'historical effects remain uncertain')
    for item in (control, history):
        need(isinstance(item['evidence_reference'], str)
             and re.fullmatch('[0-9a-f]{64}', item['evidence_reference']), 'external review evidence reference required')
    # These are signed independent review attestations; no historical terminal
    # is created and the enrollment verifier's separate checks remain mandatory.
    return permit


def read_fixed(directory, name, *, mode=0o400, maximum=65536):
    need(name not in ('', '.', '..') and '/' not in name, 'fixed evidence leaf required')
    with prep._root(directory, private=True) as parent:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                 and stat.S_IMODE(before.st_mode) == mode and before.st_nlink == 1
                 and 0 < before.st_size <= maximum, 'unsafe external evidence file')
            value = bytearray()
            while len(value) <= before.st_size:
                chunk = os.read(fd, min(65536, before.st_size + 1 - len(value)))
                if not chunk: break
                value.extend(chunk)
            need(len(value) == before.st_size and prep._same(before, os.fstat(fd))
                 and prep._same(before, os.stat(name, dir_fd=parent, follow_symlinks=False)),
                 'external evidence changed while reading')
            return bytes(value)
        finally:
            os.close(fd)


class NativeSession:
    """Fixed native reads; injectable test ports are not exposed through the CLI."""
    def __init__(self, authorization_id):
        uid(authorization_id)
        self.authorization_id = authorization_id
        self.directory = AUTHORITY / authorization_id
        self.lock_fd = None
        self.original = None

    def require_installed(self):
        need(os.geteuid() == 0 and Path(__file__).resolve() == ROOT/'scripts/security/fr06_executor_native_install.py',
             'native caller must be installed from accepted source')

    @contextmanager
    def hold(self):
        self.require_installed()
        # No trust key, permit, directory or coordinator lock is ever created.
        with prep._root(self.directory, private=True) as parent:
            fd = os.open('coordinator.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                value = os.fstat(fd)
                need(stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid() and value.st_nlink == 1
                     and value.st_size == 0 and stat.S_IMODE(value.st_mode) == 0o600, 'unsafe independent coordinator lock')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock_fd = fd
                yield self
            finally:
                self.lock_fd = None
                os.close(fd)

    def files(self):
        return (read_fixed(TRUST, 'owner-ed25519.pub'),
                read_fixed(self.directory, 'permit.json'), read_fixed(self.directory, 'permit.sig'),
                read_fixed(self.directory, 'control-evidence.json'), read_fixed(self.directory, 'history-evidence.json'))

    def supporting_evidence(self, control_raw, history_raw):
        control, history = parse(control_raw), parse(history_raw)
        digests = {control['evidence_reference'], history['evidence_reference'],
                   *[value['evidence_sha256'] for value in control['roles'].values()]}
        result = {}
        for digest in sorted(digests):
            need(isinstance(digest, str) and re.fullmatch('[a-f0-9]{64}', digest),
                 'unsafe supporting evidence reference')
            raw = read_fixed(self.directory/'evidence', digest+'.json')
            need(sha(raw) == digest, 'referenced independent evidence missing or changed')
            parse(raw)  # bounded canonical sanitized object; paths never come from its fields
            result[digest] = raw
        return result

    def coordinator(self):
        need(self.lock_fd is not None, 'independent coordinator must remain held')
        current = os.fstat(self.lock_fd)
        with prep._root(self.directory, private=True) as parent:
            named = os.stat('coordinator.lock', dir_fd=parent, follow_symlinks=False)
        need(prep._same(current, named) and current.st_uid == os.geteuid() and current.st_nlink == 1
             and current.st_size == 0 and stat.S_IMODE(current.st_mode) == 0o600,
             'independent coordinator changed')
        # Detect loss of lock by a true competing child, not PID absence.
        probe = subprocess.run(['/usr/bin/python3', '-I', '-c',
            'import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR|os.O_NOFOLLOW);\n'
            'try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
            'except BlockingIOError: sys.exit(73)\n'
            'else: sys.exit(74)', str(self.directory/'coordinator.lock')], env=ENV,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        need(probe.returncode == 73, 'independent coordinator contention not observed')
        with prep._root(self.directory, private=True) as parent:
            named_after = os.stat('coordinator.lock', dir_fd=parent, follow_symlinks=False)
        need(prep._same(current, os.fstat(self.lock_fd)) and prep._same(current, named_after),
             'coordinator changed during contention probe')
        return {'device': current.st_dev, 'inode': current.st_ino}

    def source(self, permit):
        from scripts.security.fr06_source_operator import NativePort
        port = NativePort()
        local, main, clean = port.local()
        need(local == main == permit['binding']['source_commit'] and clean, 'installed source is not exact clean main')
        for rel in ['scripts/security/fr06_executor_native_install.py',
                    'scripts/security/fr06_executor_installation.py', 'scripts/security/fr06_executor_preparation.py',
                    'scripts/security/fr06_source_operator.py', 'scripts/security/fr06_execution_guard.py',
                    'scripts/security/fr06_execution_enrollment.py']:
            metadata = (ROOT/rel).lstat()
            need(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o022,
                 'unsafe installed admission source')
            need(port.git('hash-object', '--', rel) == port.git('rev-parse', local+':'+rel), 'admission source differs from Git')
        remote = port.api('repos/'+REPOSITORY+'/branches/main')
        pr = port.api('repos/'+REPOSITORY+'/pulls/'+str(permit['source_pr']))
        need(remote.get('commit', {}).get('sha') == local and pr.get('merged') is True
             and pr.get('base', {}).get('ref') == 'main' and pr.get('head', {}).get('sha') == permit['reviewed_head']
             and pr.get('merge_commit_sha') == local, 'exact protected main merge not observed')
        rules = port.api('repos/'+REPOSITORY+'/rules/branches/main')
        checks = port.api('repos/'+REPOSITORY+'/commits/'+local+'/check-runs?filter=latest&per_page=100')
        required_checks(rules, checks, local)

    def journal(self):
        from scripts.security.fr06_execution_enrollment import read_bounded, MAX_EVENTS
        return read_bounded(ROOT/'docs/project/runtime', 'events.jsonl', mode=0o644, maximum=MAX_EVENTS)

    def live_binding(self, permit):
        from scripts.security.fr06c5d11_graceful_stop_operator import _authority
        b = Binding(**permit['binding'])
        need(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == b.boot_id, 'boot identity changed')
        _authority(b.operation_id, b.generation)  # fixed explicit DB projection; never full Docker inspection
        return b

    def authorize(self):
        self.require_installed()
        need(self.lock_fd is not None, 'independent coordinator not held')
        inputs = self.files(); key, raw, sig, control, history = inputs
        need(self.original is None or inputs == self.original, 'independent authorization was replaced')
        permit = verify_permit(raw, sig, key, control, history, now=datetime.now(timezone.utc),
                               authorization_id=self.authorization_id)
        supporting = self.supporting_evidence(control, history)
        need(self.coordinator() == permit['coordinator_identity'], 'permit names a different coordinator')
        self.source(permit)
        journal = self.journal(); anchor = permit['journal_anchor']
        need(len(journal) == anchor['byte_count'] and sha(journal) == anchor['sha256'],
             'history changed after independent review')
        binding = self.live_binding(permit)
        need(asdict(binding) == permit['binding'], 'current installation binding changed')
        self.source(permit)
        need(self.journal() == journal, 'history changed during native checks')
        need(self.files() == inputs and self.coordinator() == permit['coordinator_identity']
             and self.supporting_evidence(control, history) == supporting,
             'authorization changed during native checks')
        # Remote/DB checks take time: validity must still hold at RETURN.
        verify_permit(raw, sig, key, control, history, now=datetime.now(timezone.utc),
                      authorization_id=self.authorization_id)
        self.original, self.permit = inputs, permit
        return binding


def run(action, authorization_id):
    need(action in {'check', 'install'}, 'unsupported native action')
    session = NativeSession(authorization_id)
    with session.hold():
        binding = session.authorize()
        if action == 'check':
            return {'status': 'initial_install_checks_passed', 'files_installed': False,
                    'enrolled': False, 'production_activation_authorized': False}
        permit = session.permit
        result = installer.install_unenrolled(source_root=ROOT, source_commit=binding.source_commit,
            store=STORE, preparation_id=permit['preparation_id'], journal=JOURNALS/authorization_id,
            operation_id=authorization_id, guard_root=GUARD, launch_root=LAUNCH,
            binding=binding, authorize=session.authorize)
        session.authorize()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'install'], nargs='?', default='check')
    parser.add_argument('--authorization-id', required=True)
    args = parser.parse_args()
    try:
        result = run(args.action, args.authorization_id)
    except Exception:
        print(json.dumps({'status': 'admission_blocked_or_effect_uncertain', 'automatic_retry': False,
                          'enrolled': False, 'production_activation_authorized': False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
