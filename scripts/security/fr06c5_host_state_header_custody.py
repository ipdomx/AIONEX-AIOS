#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,re,stat,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
INPUT=Path('/run/aionex-fr06c5-host-state-header/host-state-vault.header');DEFAULT=Path('/run/operator-secrets/r2-backup-source.env');ALLOWED={'R2_BACKUP_ENDPOINT','R2_BACKUP_BUCKET','R2_BACKUP_ACCESS_KEY_ID','R2_BACKUP_SECRET_ACCESS_KEY'};GEN=re.compile(r'^[0-9a-f]{32}$');PREFIX=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,180}$');CHUNK=1024*1024
class E(RuntimeError):pass
def private(p,label,maxb):
 s=os.lstat(p)
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.geteuid() or s.st_mode&0o077 or not 1<=s.st_size<=maxb:raise E(f'{label} unsafe')
def creds(p):
 private(p,'credentials',65536);d={}
 for raw in p.read_text().splitlines():
  line=raw.strip()
  if not line or line.startswith('#'):continue
  k,sep,v=line.partition('=')
  if not sep or k not in ALLOWED or k in d or not v:raise E('credential fields invalid')
  d[k]=v
 if set(d)!=ALLOWED:raise E('credentials incomplete')
 u=urlparse(d['R2_BACKUP_ENDPOINT'])
 if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.r2.cloudflarestorage.com') or u.path not in ('','/'):raise E('R2 endpoint invalid')
 return d
def fhash(p):
 h=hashlib.sha256();n=0
 with p.open('rb') as f:
  magic=f.read(6)
  if magic!=b'LUKS\xba\xbe':raise E('header magic invalid')
  h.update(magic);n=6
  for b in iter(lambda:f.read(CHUNK),b''):h.update(b);n+=len(b)
 return h.hexdigest(),n
def main():
 a=argparse.ArgumentParser();a.add_argument('--generation',required=True);a.add_argument('--prefix',default='aionex-production');a.add_argument('--credentials',type=Path,default=DEFAULT);x=a.parse_args()
 try:
  if not GEN.fullmatch(x.generation):raise E('generation invalid')
  prefix=x.prefix.strip('/')
  if not PREFIX.fullmatch(prefix) or '..' in prefix.split('/'):raise E('prefix invalid')
  p=INPUT.resolve(strict=True);private(p,'host-state header',32*1024*1024);sha,size=fhash(p);c=creds(x.credentials.resolve());import boto3;from botocore.config import Config
  client=boto3.client('s3',endpoint_url=c['R2_BACKUP_ENDPOINT'],aws_access_key_id=c['R2_BACKUP_ACCESS_KEY_ID'],aws_secret_access_key=c['R2_BACKUP_SECRET_ACCESS_KEY'],region_name='auto',config=Config(signature_version='s3v4',retries={'max_attempts':4,'mode':'standard'},connect_timeout=10,read_timeout=120));bucket=c['R2_BACKUP_BUCKET'];key=f"{prefix}/fr06c5/luks2-headers/{x.generation}/host-state-vault.header";client.head_bucket(Bucket=bucket)
  try:client.head_object(Bucket=bucket,Key=key);raise E('header object already exists')
  except E:raise
  except Exception as exc:
   code=str((getattr(exc,'response',{}).get('Error') or {}).get('Code','')) if isinstance(getattr(exc,'response',{}),dict) else ''
   if code not in {'404','NoSuchKey','NotFound'}:raise E('cannot establish new object') from exc
  meta={'sha256':sha,'aionex-subpart':'fr-06c5c1','vault-role':'host-state-vault'}
  with p.open('rb') as f:client.put_object(Bucket=bucket,Key=key,Body=f,ContentLength=size,ContentType='application/octet-stream',Metadata=meta,IfNoneMatch='*')
  head=client.head_object(Bucket=bucket,Key=key);remote={str(k).lower():str(v) for k,v in (head.get('Metadata') or {}).items()}
  if int(head.get('ContentLength',-1))!=size or any(remote.get(k)!=v for k,v in meta.items()):raise E('metadata readback failed')
  body=client.get_object(Bucket=bucket,Key=key)['Body'];h=hashlib.sha256();n=0
  try:
   for b in iter(lambda:body.read(CHUNK),b''):h.update(b);n+=len(b)
  finally:body.close()
  if n!=size or h.hexdigest()!=sha:raise E('full readback failed')
  print(json.dumps({'schema_version':1,'subpart':'FR-06C5C1','status':'off_host_host_state_header_verified','generation':x.generation,'reference':f'r2://{bucket}/{key}','sha256':sha,'size_bytes':size,'full_readback_verified':True,'recovery_key_stored_in_r2':False},sort_keys=True));return 0
 except E as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':sys.exit(main())
