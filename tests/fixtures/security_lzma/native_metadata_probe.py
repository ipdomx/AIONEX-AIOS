"""Offline, non-root copied-dpkg-metadata regression; never mutate image/host DB."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('verifier', '/review/verifier.py')
assert spec and spec.loader
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

def query(*args):
    return subprocess.check_output(['dpkg-query', *args], text=True, timeout=20)

pkg = 'liblzma5:amd64'
status = query('-s', pkg)
listing = query('-L', pkg)
manifest = query('--control-show', pkg, 'md5sums')
lib = v.LIBRARY.resolve(strict=True)
original_hash = hashlib.sha256(lib.read_bytes()).hexdigest()
native_lines = [line for line in manifest.splitlines() if Path('/' + line.split(maxsplit=1)[1]).resolve() == lib]
assert len(native_lines) == 1, native_lines
native_line = native_lines[0]
without_native = '\n'.join(line for line in manifest.splitlines() if line != native_line) + '\n'
cases = {'intact': manifest, 'empty-manifest': '', 'native-entry-missing': without_native,
         'manifest-missing': None, 'wrong-native-digest': manifest.replace(native_line[:32], '0' * 32, 1)}
rows = []
with tempfile.TemporaryDirectory(prefix='lzma-copied-dpkg-') as td:
    admin = Path(td)
    (admin / 'info').mkdir()
    (admin / 'info' / 'format').write_text('1\n')
    (admin / 'arch').write_text('amd64\n')
    (admin / 'status').write_text(status + '\n')
    (admin / 'info' / (pkg + '.list')).write_text(listing)
    control = admin / 'info' / (pkg + '.md5sums')
    os.environ['DPKG_ADMINDIR'] = str(admin)
    control.write_text(manifest)
    initial = subprocess.run(['dpkg', '--verify', 'liblzma5'], capture_output=True, text=True, timeout=20, check=False)
    assert initial.returncode == 0 and not initial.stdout.strip() and not initial.stderr.strip(), (initial.returncode, initial.stdout, initial.stderr)
    for name, content in cases.items():
        if content is None:
            control.unlink(missing_ok=True)
        else:
            control.write_text(content)
        raw = subprocess.run(['dpkg', '--verify', 'liblzma5'], capture_output=True, text=True, timeout=20, check=False)
        accepted = False
        error = None
        try:
            identity = v.package_identity()
            accepted = True
        except (RuntimeError, OSError, ValueError) as exc:
            error = str(exc)
        rows.append({'case': name, 'dpkg_returncode': raw.returncode,
                     'dpkg_stdout_empty': not raw.stdout.strip(), 'dpkg_stderr': raw.stderr.strip(),
                     'verifier_accepted': accepted, 'error': error})
    control.write_text(manifest)
    native = [v.native_case(name) for name in v.CASES]
    assert hashlib.sha256(lib.read_bytes()).hexdigest() == original_hash
    assert Path('/var/lib/dpkg/info/' + pkg + '.md5sums').read_text() == manifest
expected = sys.argv[1]
if expected == 'baseline':
    passed = all(row['verifier_accepted'] for row in rows[:4]) and not rows[4]['verifier_accepted']
else:
    assert expected == 'corrected'
    passed = bool(rows[0]['verifier_accepted']) and all(not row['verifier_accepted'] for row in rows[1:])
print(json.dumps({'expectation': expected, 'expectation_matched': passed, 'uid': os.getuid(),
                  'library_sha256': original_hash, 'cases': rows, 'native_compatibility_cases': native,
                  'image_metadata_unchanged': True, 'library_bytes_unchanged': True,
                  'host_database_accessed': False, 'full_image_security_passed': False}, indent=2))
raise SystemExit(0 if passed else 1)
