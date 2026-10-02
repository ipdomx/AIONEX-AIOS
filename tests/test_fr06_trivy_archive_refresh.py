"""No host/archive effects: build-lock boundary tests only."""
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'web-dashboard/backend/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('trivy_archive_contract', SCRIPTS/'build_trivy.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)

@pytest.fixture
def locked(tmp_path):
    dst=tmp_path/'lock';shutil.copytree(ROOT/'web-dashboard/backend/security-build/trivy',dst)
    return dst

def rehash(dst):
    p=dst/'lock.json';d=json.loads(p.read_text())
    d['files']['go.mod']=hashlib.sha256((dst/'go.mod').read_bytes()).hexdigest()
    p.write_text(json.dumps(d))

def test_patched_archive_lock_matches_real_resolved_graph(locked):
    assert m.read_lock(locked)['local_version']=='0.74.0+aios.1'
    assert 'github.com/moby/go-archive v0.3.0 // indirect' in (locked/'go.mod').read_text()
    assert 'github.com/moby/go-archive v0.3.0 h1:nos4BtzzUIqB406BgQnWGMI4qib9BZ8XUHU+ucv/n1c=' in (locked/'go.sum').read_text()

@pytest.mark.parametrize('version',['v0.2.1','v0.2.2','v0.3.0-unreviewed','v99.0.0'])
def test_rehashed_unreviewed_archive_still_refused(locked,version):
    p=locked/'go.mod';p.write_text(p.read_text().replace('github.com/moby/go-archive v0.3.0','github.com/moby/go-archive '+version));rehash(locked)
    with pytest.raises(ValueError,match='Reviewed go-archive'):m.read_lock(locked)

@pytest.mark.parametrize('directive',[
    'replace github.com/moby/go-archive => github.com/moby/go-archive v0.2.1',
    'replace (\n github.com/moby/go-archive => ./unreviewed\n)',
])
def test_rehashed_replacement_does_not_masquerade_as_fixed(locked,directive):
    p=locked/'go.mod';p.write_text(p.read_text()+'\n'+directive+'\n');rehash(locked)
    with pytest.raises(ValueError,match='Reviewed go-archive'):m.read_lock(locked)

@pytest.mark.parametrize('mutation',['missing','duplicate','comment_only'])
def test_missing_or_ambiguous_floor_rejected(locked,mutation):
    p=locked/'go.mod';text=p.read_text();line='\tgithub.com/moby/go-archive v0.3.0 // indirect'
    replacement='' if mutation=='missing' else line+'\n'+line if mutation=='duplicate' else '// '+line
    p.write_text(text.replace(line,replacement));rehash(locked)
    with pytest.raises(ValueError,match='Reviewed go-archive'):m.read_lock(locked)

def test_linked_runtime_module_floor_and_binary_pin_remain_present(locked):
    value=m.read_lock(locked)
    assert value['modules']['google.golang.org/grpc']=='v1.83.2'
    assert value['expected_binary_sha256']=='82e0a73a831efc894c1df0de6893eb653145570d2b186f395338628ba380345e'
