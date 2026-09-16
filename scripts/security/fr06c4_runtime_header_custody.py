#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,re,stat,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
INPUT_ROOT=Path('/run/aionex-fr06c4-runtime-header'); HEADER='container-runtime-vault.header'; DEFAULT_CREDENTIALS=Path('/run/operator-secrets/r2-backup-source.env'); ALLOWED={'R2_BACKUP_ENDPOINT','R2_BACKUP_BUCKET','R2_BACKUP_ACCESS_KEY_ID','R2_BACKUP_SECRET_ACCESS_KEY'}; GEN=re.compile(r'^[0-9a-f]{32}$'); PREFIX=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,180}$'); CHUNK=1024*1024
class E(RuntimeError):pass
def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def private(p,label,maxsize):
 s=os.lstat(p)
 if stat.S_ISLNK(s.st_mode) or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.geteuid() or s.st_mode&0o077 or not 1<=s.st_size<=maxsize:raise E(f'{label} unsafe')
def credentials(p):
 private(p,'credentials',65536);d={}
 for raw in p.read_text().splitlines():
  line=raw.strip()
  if not line or line.startswith('#'):continue
  k,sep,v=line.partition('=')
  if not sep or k not in ALLOWED or k in d or not v:raise E('credential fields invalid')
  d[k]=v
 if set(d)!=ALLOWED:raise E('credentials incomplete')
 u=urlparse(d['R2_BACKUP_ENDPOINT'])
 if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.r2.cloudflarestorage.com') or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:raise E('R2 endpoint invalid')
 return d
def hashfile(p):
 h=hashlib.sha256();n=0;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  with os.fdopen(fd,'rb',closefd=False) as f:
   magic=f.read(6)
   if magic!=b'LUKS\xba\xbe':raise E('header magic invalid')
   h.update(magic);n+=6
   for b in iter(lambda:f.read(CHUNK),b''):h.update(b);n+=len(b)
 finally:os.close(fd)
 return h.hexdigest(),n
def main():
 a=argparse.ArgumentParser();a.add_argument('--generation',required=True);a.add_argument('--prefix',default='aionex-production');a.add_argument('--credentials',type=Path,default=DEFAULT_CREDENTIALS);x=a.parse_args()
 try:
  if not GEN.fullmatch(x.generation):raise E('generation invalid')
  prefix=x.prefix.strip('/')
  if not PREFIX.fullmatch(prefix) or '..' in prefix.split('/'):raise E('prefix invalid')
  p=(INPUT_ROOT/HEADER).resolve(strict=True)
  if p.parent!=INPUT_ROOT:raise E('header escaped fixed input root')
  private(p,'runtime header',32*1024*1024);sha,size=hashfile(p);c=credentials(x.credentials.resolve())
  import boto3
  from botocore.config import Config
  client=boto3.client('s3',endpoint_url=c['R2_BACKUP_ENDPOINT'],aws_access_key_id=c['R2_BACKUP_ACCESS_KEY_ID'],aws_secret_access_key=c['R2_BACKUP_SECRET_ACCESS_KEY'],region_name='auto',config=Config(signature_version='s3v4',retries={'max_attempts':4,'mode':'standard'},connect_timeout=10,read_timeout=120));bucket=c['R2_BACKUP_BUCKET'];client.head_bucket(Bucket=bucket);key=f'{prefix}/fr06c4/luks2-headers/{x.generation}/{HEADER}'
  try:client.head_object(Bucket=bucket,Key=key);raise E('header object already exists')
  except E:raise
  except Exception as exc:
   code=str((getattr(exc,'response',{}).get('Error') or {}).get('Code','')) if isinstance(getattr(exc,'response',{}),dict) else ''
   if code not in {'404','NoSuchKey','NotFound'}:raise E('cannot establish new object') from exc
  meta={'sha256':sha,'aionex-subpart':'fr-06c4c1','vault-role':'container-runtime-vault'}
  with p.open('rb') as f:client.put_object(Bucket=bucket,Key=key,Body=f,ContentLength=size,ContentType='application/octet-stream',Metadata=meta,IfNoneMatch='*')
  head=client.head_object(Bucket=bucket,Key=key);remote={str(k).lower():str(v) for k,v in (head.get('Metadata') or {}).items()}
  if int(head.get('ContentLength',-1))!=size or any(remote.get(k)!=v for k,v in meta.items()):raise E('metadata readback failed')
  body=client.get_object(Bucket=bucket,Key=key)['Body'];h=hashlib.sha256();n=0
  try:
   for b in iter(lambda:body.read(CHUNK),b''):h.update(b);n+=len(b)
  finally:body.close()
  if n!=size or h.hexdigest()!=sha:raise E('full readback failed')
  print(json.dumps({'schema_version':1,'subpart':'FR-06C4C1','status':'off_host_runtime_header_verified','generation':x.generation,'observed_at':utc(),'object_count':1,'reference':f'r2://{bucket}/{key}','sha256':sha,'size_bytes':size,'full_readback_verified':True,'recovery_key_stored_in_r2':False},sort_keys=True));return 0
 except E as e:print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True));return 2
if __name__=='__main__':sys.exit(main())
