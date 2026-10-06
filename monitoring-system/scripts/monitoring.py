#!/usr/bin/env python3
"""Run from any directory. Secrets never appear in console output."""
import sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'.venv/bin/python').exists() and sys.prefix!=str(ROOT/'.venv'):
 os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__,*sys.argv[1:]])
sys.path.insert(0,str(ROOT/'docker/control'))
import argparse,json,secrets,hashlib,shutil,subprocess,tempfile,difflib,tarfile,time,urllib.request
import yaml
from configuration import load,render

def compose(*args):return subprocess.run(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),*args],check=True)
def api(path,method='GET',payload=None):
 t=(ROOT/'secrets/operator-token').read_text().strip();req=urllib.request.Request('http://localhost:8080/control/'+path,headers={'Authorization':'Bearer '+t,'Content-Type':'application/json'},method=method,data=json.dumps(payload).encode() if payload is not None else None)
 with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
def preflight(config):
 subprocess.run(['docker','run','--rm','--entrypoint','python','--add-host','host.docker.internal:host-gateway','-v',str(Path(config).resolve())+':/config/inventory.yaml:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','portable-observability:local','/opt/monitoring/docker/runtime/validate.py'],check=True)
def ready_deadline():
 deadline=time.monotonic()+180
 while time.monotonic()<deadline:
  try:
   with urllib.request.urlopen('http://localhost:8080/ready',timeout=5) as r:
    if r.status==200:return
  except Exception:pass
  time.sleep(2)
 raise RuntimeError('Candidate did not become ready within deadline')
def init(args):
 config=ROOT/'config/inventory.yaml';private=ROOT/'secrets';private.mkdir(exist_ok=True);private.chmod(0o700)
 for ref in ['grafana-admin','grafana-key','dashboard-read','operator-token','demo-orders','demo-catalog','demo-worker','demo-scheduler']:
  f=private/ref
  if not f.exists():f.write_text(secrets.token_urlsafe(32));f.chmod(0o600)
 if not config.exists():
  services=[]
  for name,kind,port,ref in [('orders-api','http',4101,'demo-orders'),('catalog-api','http',4102,'demo-catalog'),('billing-worker','worker',None,'demo-worker'),('nightly-job','scheduled-job',None,'demo-scheduler')]:
   instance={'id':name+'-1'}
   if port:instance.update(healthUrl=f'http://host.docker.internal:{port}/health',readyUrl=f'http://host.docker.internal:{port}/ready',observationType='instance-endpoint')
   s={'project':'commerce','service':name,'environment':'demo','kind':kind,'owner':'demo-team','criticality':'critical','instances':[instance],'quorum':1,'metrics':{'mode':'push','tokenRef':ref},'checks':{'intervalSeconds':5,'timeoutSeconds':2},'heartbeat':{'intervalSeconds':3,'graceSeconds':12,'startupGraceSeconds':20},'objectives':{'probeAvailability':{'target':.99,'windowDays':30},'requestSuccess':{'target':.995,'minimumRequests':100},'requestLatency':{'target':.99,'thresholdSeconds':.5}}}
   if kind=='http':s['checks']['bodyAssertion']={'mode':'json-field','field':'status','equals':'ok'}
   if name=='orders-api':
    s['dependencies']=['catalog-api'];s['instances'].append({'id':'orders-api-2','healthUrl':'http://host.docker.internal:4103/health','readyUrl':'http://host.docker.internal:4103/ready','observationType':'instance-endpoint','required':False})
   if kind=='worker':s['jobs']={'maximumRunningSeconds':15}
   if kind=='scheduled-job':s['jobs']={'schedule':'* * * * *','timezone':'America/Bogota','completionDeadlineSeconds':30,'allowedOverlap':1}
   services.append(s)
  value={'profile':args.profile,'publicUrl':'http://localhost:8080','projects':[{'id':'commerce','criticalServices':['orders-api','billing-worker']}],'services':services,'network':{'allowedHosts':['host.docker.internal'],'allowedCidrs':['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']},'retention':{'metricsDays':7,'metricsSize':'1GB','logsDays':7,'tracesHours':48,'controlDays':90},'policies':{'failureCount':2,'recoveryCount':2,'startupGraceSeconds':20,'freshnessSeconds':30,'alertPendingSeconds':10},'notifications':[{'name':'local','type':'local'}]}
  if args.profile=='operational':value.update(publicUrl='https://monitoring.example.com',tls={'certificateRef':'tls-cert','keyRef':'tls-key'})
  config.write_text(yaml.safe_dump(value,sort_keys=False))
 print('Initialized operator config and private credentials without overwriting existing files.')
def backup(path):
 if Path(path).exists():raise ValueError('Backup destination exists')
 cid=subprocess.check_output(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),'ps','-q','monitoring'],text=True).strip()
 if not cid:raise ValueError('Start the monitoring container before backup')
 metadata=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0];volume=next(x['Name'] for x in metadata['Mounts'] if x['Destination']=='/data')
 compose('stop')
 try:
  with tempfile.TemporaryDirectory() as temp:
   # Same assembled image, ephemeral offline backup utility; never a second running central backend.
   subprocess.run(['docker','run','--rm','--entrypoint','tar','-v',volume+':/data:ro','-v',temp+':/backup','portable-observability:local','-czf','/backup/data.tar.gz','-C','/data','.'],check=True)
   with tarfile.open(path,'w:gz') as tar:tar.add(temp+'/data.tar.gz',arcname='data.tar.gz');tar.add(ROOT/'config/inventory.yaml',arcname='inventory.yaml');tar.add(ROOT/'secrets',arcname='secrets')
   Path(path).chmod(0o600)
 finally:compose('start')
 print('Stopped-stack backup saved; monitoring was unavailable during the copy.')
def main():
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 p=sub.add_parser('init');p.add_argument('--profile',choices=['local','operational'],default='local')
 for cmd in ['validate','render','diff','apply']:
  p=sub.add_parser(cmd);p.add_argument('--config',default=str(ROOT/'config/inventory.yaml'));p.add_argument('--output',default=str(ROOT/'config/generated'))
 p=sub.add_parser('token-rotate');p.add_argument('--ref',required=True);p.add_argument('--output',required=True);p.add_argument('--ttl-seconds',type=int,default=2592000);p.add_argument('--overlap-seconds',type=int,default=300)
 p=sub.add_parser('token-revoke');p.add_argument('--token-file',required=True)
 sub.add_parser('rollback');sub.add_parser('diagnose');p=sub.add_parser('notification-test');p.add_argument('--destination',default='local')
 p=sub.add_parser('backup');p.add_argument('--output',required=True)
 p=sub.add_parser('restore');p.add_argument('--archive',required=True);p.add_argument('--volume',required=True);p.add_argument('--confirm-empty-volume',action='store_true',required=True)
 args=parser.parse_args()
 if args.command=='init':init(args)
 elif args.command in ('validate','render','diff','apply'):
  c=load(args.config,ROOT/'secrets')
  if args.command=='apply':preflight(args.config)
  if args.command=='validate':print('Inventory and all secret references are valid.');return
  with tempfile.TemporaryDirectory() as temp:
   render(c,temp,ROOT/'secrets')
   if args.command=='diff':
    for f in sorted(Path(temp).rglob('*')):
     if f.is_file():
      old=Path(args.output)/f.relative_to(temp)
      # Diff secret-bearing generated files by hash only.
      if not old.exists() or old.read_bytes()!=f.read_bytes():print('changed:',f.relative_to(temp))
   else:
    out=Path(args.output);staging=out.with_name(out.name+'.staging');previous=out.with_name(out.name+'.previous')
    if staging.exists():shutil.rmtree(staging)
    shutil.copytree(temp,staging)
    if previous.exists():shutil.rmtree(previous)
    if out.exists():out.rename(previous)
    staging.rename(out);print('Validated configuration rendered atomically.')
    if args.command=='apply':
     target=ROOT/'config/inventory.yaml';prior=ROOT/'config/inventory.previous.yaml'
     if target.exists():shutil.copy2(target,prior)
     tmp=target.with_suffix('.staging');tmp.write_text(yaml.safe_dump(c,sort_keys=False));tmp.replace(target)
     try:compose('restart','monitoring');ready_deadline()
     except Exception:
      if prior.exists():shutil.copy2(prior,target);compose('restart','monitoring');ready_deadline()
      raise RuntimeError('Apply failed; previous inventory restored and checked')
 elif args.command=='rollback':
  previous=ROOT/'config/inventory.previous.yaml'
  c=load(previous,ROOT/'secrets');preflight(previous);(ROOT/'config/inventory.yaml').write_text(yaml.safe_dump(c,sort_keys=False));compose('restart','monitoring')
 elif args.command=='diagnose':print(json.dumps(api('diagnostics'),indent=2));compose('ps')
 elif args.command=='notification-test':
  # Grafana's actual native contact test endpoint, not merely writing a receiver event.
  import base64
  password=(ROOT/'secrets/grafana-admin').read_text().strip();operator=(ROOT/'secrets/operator-token').read_text().strip()
  authorization='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
  base='http://localhost:8080/apis/notifications.alerting.grafana.app/v1beta1/namespaces/default/receivers'
  with urllib.request.urlopen(urllib.request.Request(base,headers={'Authorization':authorization}),timeout=10) as r:receivers=json.load(r)['items']
  receiver=next((r for r in receivers if r['spec']['title']==args.destination),None)
  if not receiver:raise ValueError('Configured destination not found')
  for integration in receiver['spec']['integrations']:
   req=urllib.request.Request(base+'/'+receiver['metadata']['name']+'/test',method='POST',headers={'Authorization':authorization,'Content-Type':'application/json'},data=json.dumps({'integration':integration}).encode())
   with urllib.request.urlopen(req,timeout=15) as r:result=json.load(r)
   if result.get('status')!='success':raise ValueError('Grafana contact test failed: '+str(result.get('error','unknown')))
  print('Grafana native notification test delivered successfully: '+args.destination)
 elif args.command=='token-rotate':
  c=load(ROOT/'config/inventory.yaml',ROOT/'secrets')
  if args.ref not in {s['metrics']['tokenRef'] for s in c['services']}:raise ValueError('Only configured ingestion credentials may be rotated')
  if not 60<=args.ttl_seconds<=366*86400 or not 0<=args.overlap_seconds<=3600:raise ValueError('Invalid token lifetime or overlap')
  destination=Path(args.output)
  if destination.exists():raise ValueError('Token output already exists')
  ref=ROOT/'secrets'/args.ref;prior=ref.read_text().strip();now=time.time()
  records=json.loads(prior)['tokens'] if prior.startswith('{') else [{'sha256':hashlib.sha256(t.encode()).hexdigest(),'expiresAt':now+args.overlap_seconds} for t in prior.splitlines()]
  records=[{**r,'expiresAt':min(r['expiresAt'],now+args.overlap_seconds)} for r in records if r['expiresAt']>now and not r.get('revoked')]
  token=secrets.token_urlsafe(32);records.append({'sha256':hashlib.sha256(token.encode()).hexdigest(),'notBefore':now,'expiresAt':now+args.ttl_seconds})
  destination.write_text(token);destination.chmod(0o600);temporary=ref.with_suffix('.next');temporary.write_text(json.dumps({'tokens':records}));temporary.chmod(0o600);temporary.replace(ref)
  compose('restart','monitoring');print('Rotated scoped ingestion token. Private application token saved to the specified file; overlap expires automatically.')
 elif args.command=='token-revoke':
  token=Path(args.token_file).read_text().strip();api('tokens/revoke','POST',{'sha256':hashlib.sha256(token.encode()).hexdigest()});print('Token revoked immediately and durably.')
 elif args.command=='backup':backup(args.output)
 elif args.command=='restore':
  names=subprocess.check_output(['docker','volume','ls','-q'],text=True).splitlines()
  if args.volume in names:raise ValueError('Restore requires a new isolated volume name')
  subprocess.run(['docker','volume','create',args.volume],check=True)
  with tempfile.TemporaryDirectory() as temp:
   with tarfile.open(args.archive) as archive:
    member=archive.getmember('data.tar.gz')
    with archive.extractfile(member) as src,open(temp+'/data.tar.gz','wb') as dst:shutil.copyfileobj(src,dst)
   subprocess.run(['docker','run','--rm','--entrypoint','tar','-v',args.volume+':/data','-v',temp+':/backup:ro','portable-observability:local','-xzf','/backup/data.tar.gz','-C','/data'],check=True)
  print('Restored isolated volume. Use archive inventory/secrets and verify signals before any operational replacement.')
if __name__=='__main__':
 try:main()
 except Exception as e:print('Command failed: '+type(e).__name__+' '+str(e)[:300],file=sys.stderr);sys.exit(1)
