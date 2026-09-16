#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,subprocess
from pathlib import Path
ROOT=Path('/opt/AIOS'); VAULT_MOUNT=Path('/mnt/aionex/fr06-container-runtime-vault'); PAIRS=((VAULT_MOUNT/'containerd',Path('/var/lib/containerd')),(VAULT_MOUNT/'docker',Path('/var/lib/docker')))
class E(RuntimeError):pass
def run(a):
 r=subprocess.run(a,capture_output=True,text=True,check=False,timeout=60)
 if r.returncode:raise E(f'{a[0]} failed')
 return r.stdout.strip()
def active(unit):return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0
def source_for(target):
 r=subprocess.run(['findmnt','-n','-o','SOURCE','--target',str(target)],capture_output=True,text=True,check=False)
 return r.stdout.strip() if r.returncode==0 else ''
def ready():
 # The vault verifier must pass before any bind can be created. This avoids
 # binding a fallback directory from the unencrypted root after boot.
 raw=run(['python3',str(ROOT/'scripts/security/fr06c4_runtime_vault.py'),'status','--require-host-ready']);d=json.loads(raw)
 if d.get('validation')!='FR06C4_RUNTIME_VAULT_HOST_READY':raise E('runtime vault not host-ready')
 rows=[]
 for src,dst in PAIRS:
  if not src.is_dir() or src.is_symlink():raise E('runtime source subpath unsafe')
  rows.append({'source':str(src),'target':str(dst),'mounted_source':source_for(dst)})
 return rows
def status(require=False):
 try:
  rows=ready()
  for row in rows:
   # findmnt may display the underlying mapper with [/subpath]; target identity
   # is additionally proven by mountpoint plus inode/device equality.
   src=Path(row['source']);dst=Path(row['target'])
   if not os.path.ismount(dst):raise E('runtime target is not a mountpoint')
   ss=os.stat(src);ds=os.stat(dst)
   if (ss.st_dev,ss.st_ino)!=(ds.st_dev,ds.st_ino):raise E('runtime bind target does not reference encrypted subpath')
  return {'status':'ready','validation':'FR06C4_RUNTIME_BIND_READY','binds':rows}
 except Exception as x:
  if require:raise
  return {'status':'not-ready','validation':'FR06C4_RUNTIME_BIND_NOT_READY','reason':str(x)}
def rollback_mounts():
 for _,dst in reversed(PAIRS):
  if os.path.ismount(dst):subprocess.run(['umount',str(dst)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
def apply():
 if os.geteuid()!=0:raise E('root required')
 if active('docker.service') or active('containerd.service'):raise E('Docker and containerd must be stopped before runtime bind')
 ready()
 for _,dst in PAIRS:
  if os.path.ismount(dst):raise E('runtime target already mounted')
  if not dst.is_dir() or dst.is_symlink():raise E('runtime target unsafe')
 mounted=[]
 try:
  for src,dst in PAIRS:
   run(['mount','--bind',str(src),str(dst)]);mounted.append(dst);run(['mount','-o','remount,bind,nodev,nosuid',str(dst)])
  return status(True)
 except Exception:
  for dst in reversed(mounted):subprocess.run(['umount',str(dst)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
  raise
def rollback():
 if active('docker.service') or active('containerd.service'):raise E('Docker and containerd must be stopped before runtime bind rollback')
 rollback_mounts();return {'status':'legacy_runtime_underlays_exposed','validation':'FR06C4_RUNTIME_BIND_REMOVED'}
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);q=s.add_parser('status');q.add_argument('--require-ready',action='store_true');s.add_parser('apply');s.add_parser('rollback');a=p.parse_args()
 try:
  o=status(a.require_ready) if a.cmd=='status' else apply() if a.cmd=='apply' else rollback();print(json.dumps(o,sort_keys=True));return 0
 except Exception as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':raise SystemExit(main())
