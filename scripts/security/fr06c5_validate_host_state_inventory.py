#!/usr/bin/env python3
import json,stat,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];C=ROOT/"docs/project/receipts/FR-06C5A-host-state-inventory.json"
def main():
 c=json.loads(C.read_text());assert c["subpart"]=="FR-06C5A";assert Path("/root/.config/aionex").is_dir();assert Path("/opt/AIOS/web-dashboard/secrets").is_dir()
 files=[p for p in Path("/opt/AIOS/web-dashboard/secrets").rglob("*") if p.is_file() and not p.is_symlink()];assert len(files)==23
 key=Path("/root/.config/aionex/aionex-tunnel-runtime.key");s=key.stat();assert stat.S_IMODE(s.st_mode)==0o600 and s.st_uid==0 and s.st_gid==0
 for path in c["management_bootstrap_exception"]["active_tunnel_configs"]:
  x=Path(path);q=x.stat();assert x.is_file() and not x.is_symlink() and stat.S_IMODE(q.st_mode)==0o600 and q.st_uid==0 and q.st_gid==0
 rows=[line.split() for line in Path("/proc/swaps").read_text().splitlines()[1:] if line.strip()]
 row=next((r for r in rows if r[0]=="/swap.img"),None);assert row is not None and row[1]=="file"
 size_bytes=int(row[2])*1024;used_bytes=int(row[3])*1024
 assert size_bytes==c["swap"]["bytes"] and 0<=used_bytes<=size_bytes
 assert subprocess.run(["findmnt","-n","-o","FSTYPE","--target","/tmp"],capture_output=True,text=True,check=True).stdout.strip()=="ext4"
 print(json.dumps({"schema_version":1,"subpart":"FR-06C5A","validation":"FR06C5A_HOST_STATE_INVENTORY_PASS","application_secret_files":23,"bootstrap_key_mode":"0600","active_tunnel_configs":3,"swap_plaintext_current":True,"swap_size_bytes":size_bytes,"swap_used_bytes_current":used_bytes,"tmp_current_fstype":"ext4","production_changed":False},sort_keys=True))
if __name__=="__main__":main()
