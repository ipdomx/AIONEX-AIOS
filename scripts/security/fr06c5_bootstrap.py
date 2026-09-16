#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,secrets,shutil,stat,subprocess
from pathlib import Path
ROOT=Path('/opt/AIOS');LEGACY_KEY=Path('/root/.config/aionex/aionex-tunnel-runtime.key');LEGACY_UP=Path('/root/.config/aionex/trendbost-mcp-upstream.url');BOOT=Path('/root/.config/aionex-bootstrap');KEY=BOOT/'control-plane.key';UP=BOOT/'trendbost-mcp-upstream.url';STATE=Path('/var/lib/aionex/fr06c5-bootstrap');WRAPPERS=('aionex-phase22c-2-tunnel','aionex-phase22c-tunnel','trendbost-mcp-bridge-tunnel');CONFIGS=(Path('/root/.config/tunnel-client/aionex-phase22c-2.yaml'),Path('/root/.config/tunnel-client/aionex-phase22c.yaml'),Path('/root/.config/tunnel-client/trendbost-mcp-bridge.yaml'))
class B(RuntimeError):pass
def run(a):
 r=subprocess.run(a,capture_output=True,text=True,check=False,timeout=60)
 if r.returncode:raise B(f'{a[0]} failed')
 return r.stdout.strip()
def gitgate(sha):
 heads=run(['git','-C',str(ROOT),'rev-parse','HEAD','origin/main']).splitlines()
 if heads!=[sha,sha] or run(['git','-C',str(ROOT),'status','--porcelain=v1']):raise B('production source is not clean exact accepted main')
def sha(p):
 h=hashlib.sha256();fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  with os.fdopen(fd,'rb',closefd=False) as f:
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 finally:os.close(fd)
 return h.hexdigest()
def private(p,label,maxb=1024*1024):
 s=os.lstat(p)
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or s.st_gid!=0 or stat.S_IMODE(s.st_mode)&0o077 or not 1<=s.st_size<=maxb:raise B(f'{label} unsafe')
def source_exec(p,label):
 s=os.lstat(p)
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or s.st_gid!=0 or stat.S_IMODE(s.st_mode)!=0o755:raise B(f'{label} source unsafe')
def atomic_bytes(dst,data,mode):
 dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=dst.parent/(dst.name+'.aionex-new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,mode)
 try:os.write(fd,data);os.fsync(fd)
 finally:os.close(fd)
 os.chmod(tmp,mode);os.chown(tmp,0,0);os.replace(tmp,dst)
def atomic_copy(src,dst,mode):atomic_bytes(dst,src.read_bytes(),mode)
def inspect():
 private(LEGACY_KEY,'legacy control-plane key',65536);private(LEGACY_UP,'legacy shared bridge upstream',65536)
 for p in CONFIGS:
  private(p,'tunnel config',1024*1024);text=p.read_text(errors='strict')
  if 'CONTROL_PLANE_API_KEY' not in text:raise B('tunnel config does not reference shared environment key')
  if LEGACY_KEY.read_text().strip() and LEGACY_KEY.read_text().strip() in text:raise B('raw control-plane key embedded in tunnel config')
 return {'status':'bootstrap_preflight_ready','legacy_key_sha256':sha(LEGACY_KEY),'legacy_upstream_sha256':sha(LEGACY_UP),'tunnel_config_count':3,'production_changed':False}
def apply(confirm,merge_sha):
 if os.geteuid()!=0 or confirm!='INSTALL_FR06C5_MINIMAL_BOOTSTRAP':raise B('root/exact confirmation required')
 gitgate(merge_sha);pre=inspect();BOOT.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BOOT,0o700);os.chown(BOOT,0,0)
 atomic_copy(LEGACY_KEY,KEY,0o600);atomic_copy(LEGACY_UP,UP,0o600)
 if sha(KEY)!=pre['legacy_key_sha256'] or sha(UP)!=pre['legacy_upstream_sha256']:raise B('bootstrap copy mismatch')
 installed={}
 for name in WRAPPERS:
  src=ROOT/'deploy/bin'/name;source_exec(src,f'{name}');dst=Path('/usr/local/sbin')/name;atomic_copy(src,dst,0o755);installed[name]=sha(dst)
 if (BOOT/'aionex_aios_deploy').exists() or (BOOT/'aionex_cpanel_ai_vip_e_net_ed25519').exists():raise B('deployment key entered bootstrap')
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700);receipt={'schema_version':1,'subpart':'FR-06C5C1','status':'minimal_management_bootstrap_installed','merge_sha':merge_sha,'control_plane_key_sha256':sha(KEY),'shared_bridge_upstream_sha256':sha(UP),'wrapper_sha256':installed,'tunnel_services_restarted':False,'deployment_private_keys_in_bootstrap':False,'host_state_vault_required_for_tunnel_start':False}
 p=STATE/'bootstrap-receipt.json';p.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');os.chmod(p,0o600);return receipt
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);s.add_parser('inspect');a=s.add_parser('apply');a.add_argument('--confirmation',required=True);a.add_argument('--merge-sha',required=True);x=p.parse_args()
 try:r=inspect() if x.cmd=='inspect' else apply(x.confirmation,x.merge_sha);print(json.dumps(r,sort_keys=True));return 0
 except B as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':raise SystemExit(main())
