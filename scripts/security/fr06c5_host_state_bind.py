#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,subprocess
from pathlib import Path
ROOT=Path('/opt/AIOS');MOUNT=Path('/mnt/aionex/fr06-host-state-vault');PAIRS=((MOUNT/'operator-state',Path('/root/.config/aionex'),False),(MOUNT/'app-secrets',Path('/opt/AIOS/web-dashboard/secrets'),False),(MOUNT/'ssh/aionex_aios_deploy',Path('/root/.ssh/aionex_aios_deploy'),True),(MOUNT/'ssh/aionex_cpanel_ai_vip_e_net_ed25519',Path('/root/.ssh/aionex_cpanel_ai_vip_e_net_ed25519'),True))
class B(RuntimeError):pass
def run(a,t=60):
 r=subprocess.run(a,capture_output=True,text=True,timeout=t,check=False)
 if r.returncode:raise B(f'{a[0]} failed')
 return r.stdout.strip()
def active(u):return subprocess.run(['systemctl','is-active','--quiet',u]).returncode==0
def vault_ready():
 d=json.loads(run(['python3',str(ROOT/'scripts/security/fr06c5_host_state_vault.py'),'status','--require-host-ready']))
 if d.get('validation')!='FR06C5_HOST_STATE_VAULT_READY':raise B('host-state vault not ready')
def exact_mount(dst):
 r=subprocess.run(['findmnt','-n','-o','TARGET','--target',str(dst)],capture_output=True,text=True,check=False)
 return r.returncode==0 and r.stdout.strip()==str(dst)
def same(src,dst):
 if not exact_mount(dst):return False
 a=os.stat(src);b=os.stat(dst);return (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino)
def status(require=False):
 try:
  vault_ready();rows=[]
  for src,dst,ro in PAIRS:
   if not src.exists() or src.is_symlink():raise B('candidate host-state source missing/unsafe')
   if not dst.exists() or dst.is_symlink():raise B('host-state target missing/unsafe')
   if not same(src,dst):raise B('host-state bind target not active')
   opts=set(run(['findmnt','-n','-o','OPTIONS','--target',str(dst)]).split(','))
   if not {'nodev','nosuid','noexec'}.issubset(opts):raise B('host-state bind options drifted')
   if ro and 'ro' not in opts:raise B('private-key bind is not read-only')
   rows.append({'source':str(src),'target':str(dst),'read_only':ro})
  return {'status':'ready','validation':'FR06C5_HOST_STATE_BIND_READY','binds':rows}
 except Exception as e:
  if require:raise
  return {'status':'not-ready','validation':'FR06C5_HOST_STATE_BIND_NOT_READY','reason':str(e)}
def mount_record(dst):
 rows=json.loads(run(['findmnt','--json','--output','TARGET,FSROOT,MAJ:MIN,OPTIONS','--target',str(dst)])).get('filesystems',[])
 if len(rows)!=1 or any(not isinstance(rows[0].get(k),str) or not rows[0][k] for k in ('target','fsroot','maj:min','options')):raise B('host-state mount identity unavailable')
 return rows[0]
def sealed_underlay(dst):
 if not exact_mount(dst):return False
 try:
  current=mount_record(dst);parent=mount_record(dst.parent);opts=set(current['options'].split(','))
  # A seal must bind the legacy path on its parent filesystem, not an arbitrary ro source.
  expected_root=Path(parent['fsroot'])/dst.relative_to(Path(parent['target']))
  return 'ro' in opts and current['target']==str(dst) and parent['target']!=str(dst) and current['maj:min']==parent['maj:min'] and Path(current['fsroot'])==expected_root
 except Exception:return False
def rollback_mounts(pairs=None):
 pairs=PAIRS if pairs is None else pairs;removed=[];seals=[]
 # Refuse visible foreign mounts before changing any of the requested targets.
 for src,dst,_ in pairs:
  if exact_mount(dst) and not same(src,dst) and not sealed_underlay(dst):raise B('unexpected host-state mount preserved; rollback blocked')
 for src,dst,_ in reversed(pairs):
  if same(src,dst):
   run(['umount',str(dst)])
   if same(src,dst):raise B('owned host-state bind remained after umount')
   removed.append(str(dst))
  if exact_mount(dst):
   if not sealed_underlay(dst):raise B('unexpected host-state mount preserved after unbind')
   seals.append(str(dst))
 return {'removed_bind_targets':removed,'preserved_legacy_seals':seals}
def apply():
 if os.geteuid()!=0:raise B('root required')
 if active('docker.service'):raise B('Docker must be stopped before host-state bind')
 vault_ready();attempted=[]
 try:
  for src,dst,ro in PAIRS:
   if not src.exists() or src.is_symlink() or not dst.exists() or dst.is_symlink():raise B('bind source/target unsafe')
   if exact_mount(dst) and not sealed_underlay(dst):raise B('host-state target already mounted without accepted read-only seal')
   attempted.append((src,dst,ro));run(['mount','--bind',str(src),str(dst)]);opts='remount,bind,nodev,nosuid,noexec'+(',ro' if ro else '') ;run(['mount','-o',opts,str(dst)])
  return status(True)
 except Exception:
  try:rollback_mounts(attempted)
  except Exception as cleanup:raise B('host-state bind failed and owned-bind cleanup incomplete') from cleanup
  raise
def rollback():
 if active('docker.service'):raise B('Docker must be stopped before host-state bind rollback')
 result=rollback_mounts();return {'status':'owned_host_state_binds_removed','validation':'FR06C5_HOST_STATE_BIND_REMOVED','restoration_complete':False,**result}
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);q=s.add_parser('status');q.add_argument('--require-ready',action='store_true');s.add_parser('apply');s.add_parser('rollback');a=p.parse_args()
 try:o=status(a.require_ready) if a.cmd=='status' else apply() if a.cmd=='apply' else rollback();print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':raise SystemExit(main())
