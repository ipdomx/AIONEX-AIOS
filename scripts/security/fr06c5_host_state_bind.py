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
def sealed_underlay(dst):
 if not exact_mount(dst):return False
 try:opts=set(run(['findmnt','-n','-o','OPTIONS','--target',str(dst)]).split(','))
 except Exception:return False
 return 'ro' in opts
def rollback_mounts():
 for _,dst,_ in reversed(PAIRS):
  if exact_mount(dst):subprocess.run(['umount',str(dst)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def apply():
 if os.geteuid()!=0:raise B('root required')
 if active('docker.service'):raise B('Docker must be stopped before host-state bind')
 vault_ready();mounted=[]
 try:
  for src,dst,ro in PAIRS:
   if not src.exists() or src.is_symlink() or not dst.exists() or dst.is_symlink():raise B('bind source/target unsafe')
   if exact_mount(dst) and not sealed_underlay(dst):raise B('host-state target already mounted without accepted read-only seal')
   run(['mount','--bind',str(src),str(dst)]);mounted.append(dst);opts='remount,bind,nodev,nosuid,noexec'+(',ro' if ro else '') ;run(['mount','-o',opts,str(dst)])
  return status(True)
 except Exception:
  for dst in reversed(mounted):subprocess.run(['umount',str(dst)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  raise
def rollback():
 if active('docker.service'):raise B('Docker must be stopped before host-state bind rollback')
 rollback_mounts();return {'status':'legacy_host_state_underlays_exposed','validation':'FR06C5_HOST_STATE_BIND_REMOVED'}
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);q=s.add_parser('status');q.add_argument('--require-ready',action='store_true');s.add_parser('apply');s.add_parser('rollback');a=p.parse_args()
 try:o=status(a.require_ready) if a.cmd=='status' else apply() if a.cmd=='apply' else rollback();print(json.dumps(o,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':raise SystemExit(main())
