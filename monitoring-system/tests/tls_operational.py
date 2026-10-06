"""Operational HTTPS + authenticated custom-CA JSON probe + expired/revoked scoped credentials."""
import os,sys,tempfile,subprocess,json,time,ssl,urllib.request,urllib.error,threading,secrets,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import yaml
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait
compose=['docker','compose','-f',str(ROOT/'docker/compose.yaml')];name='portable-operational-fixture-'+str(int(time.time()));volume=name+'-data';report={}
with tempfile.TemporaryDirectory(prefix='monitoring-tls-') as temp:
 d=Path(temp);private=d/'secrets';shutil.copytree(ROOT/'secrets',private);configuration=d/'config';configuration.mkdir();auth=secrets.token_urlsafe(32)
 subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(private/'fixture-key'),'-out',str(private/'fixture-cert'),'-days','2','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,DNS:host.docker.internal,IP:127.0.0.1'],check=True,capture_output=True)
 (private/'fixture-auth').write_text('Bearer '+auth)
 for p in private.iterdir():p.chmod(0o600)
 c=yaml.safe_load((ROOT/'config/inventory.yaml').read_text());c.update(profile='operational',publicUrl='https://localhost:18443',tls={'certificateRef':'fixture-cert','keyRef':'fixture-key'})
 s=c['services'][0];c['services']=[s];s['instances']=[{'id':'orders-api-1','healthUrl':'https://host.docker.internal:4198/health','readyUrl':'https://host.docker.internal:4198/ready','observationType':'instance-endpoint'}];s['dependencies']=[]
 s['checks'].update(caRef='fixture-cert',headerSecretRefs={'Authorization':'fixture-auth'},bodyAssertion={'mode':'json-field','field':'status','equals':'ok'});c['projects'][0]['criticalServices']=['orders-api']
 (configuration/'inventory.yaml').write_text(yaml.safe_dump(c))
 from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   success=self.headers.get('Authorization')=='Bearer '+auth;self.send_response(200 if success else 401);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"status":"ok"}' if success else b'{"status":"unauthorized"}')
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('0.0.0.0',4198),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(private/'fixture-cert',private/'fixture-key');server.socket=ctx.wrap_socket(server.socket,server_side=True);threading.Thread(target=server.serve_forever,daemon=True).start()
 trust=ssl.create_default_context(cafile=str(private/'fixture-cert'));operator=(private/'operator-token').read_text().strip();read=(private/'dashboard-read').read_text().strip();ingest=(private/s['metrics']['tokenRef']).read_text().strip()
 def call(path,token=None,payload=None):
  headers={'Content-Type':'application/json'}
  if token:headers['Authorization']='Bearer '+token
  req=urllib.request.Request('https://localhost:18443'+path,headers=headers,data=json.dumps(payload).encode() if payload is not None else None)
  with urllib.request.urlopen(req,context=trust,timeout=10) as r:return json.load(r)
 subprocess.run(compose+['stop'],check=True,capture_output=True)
 try:
  subprocess.run(['docker','run','-d','--name',name,'--label','portable-observability.test=true','--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:18443:8443','-v',str(configuration)+':/config:ro','-v',str(private)+':/run/secrets:ro','-v',volume+':/data','portable-observability:local'],check=True,capture_output=True)
  wait(lambda:call('/ready')['status']=='ok',150);wait(lambda:call('/control/state',read)[0]['state']=='UP',60)
  report['httpsGatewayAndAuthenticatedCustomCaJsonProbe']='PASS'
  try:urllib.request.urlopen('https://localhost:18443/ready',timeout=3);raise AssertionError('Untrusted certificate accepted')
  except urllib.error.URLError:report['untrustedCertificateRejected']='PASS'
  log={'resource':{'project':s['project'],'service':s['service'],'environment':s['environment'],'instance':'orders-api-1'},'events':[{'eventId':'expiry-fixture-'+str(time.time()),'timestamp':int(time.time()*1000),'severity':'info','message':'credential fixture','attributes':{}}]}
  call('/api/ingest/logs',ingest,log)
  call('/control/tokens/revoke',operator,{'sha256':hashlib.sha256(ingest.encode()).hexdigest()})
  try:call('/api/ingest/logs',ingest,log);raise AssertionError('Revoked token accepted')
  except urllib.error.HTTPError as e:assert e.code==403
  report['durableImmediateRevocation']='PASS'
  token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
  code='import json,time;from pathlib import Path;Path('+repr('/run/monitoring/secrets/'+s['metrics']['tokenRef'])+').write_text(json.dumps({"tokens":[{"sha256":'+repr(digest)+',"expiresAt":time.time()+3}]}))'
  subprocess.run(['docker','exec',name,'python','-c',code],check=True,capture_output=True)
  call('/api/ingest/logs',token,{**log,'events':[{**log['events'][0],'eventId':'valid-expiry-fixture'}]});time.sleep(4)
  try:call('/api/ingest/logs',token,log);raise AssertionError('Expired token accepted')
  except urllib.error.HTTPError as e:assert e.code==403
  report['automaticExpiry']='PASS'
  for path,payload in [('/control/tokens/revoke',{'sha256':digest}),('/control/incidents/missing/acknowledge',{})]:
   try:call(path,read,payload);raise AssertionError('Read role write allowed')
   except urllib.error.HTTPError as e:assert e.code==403
  report['readRoleCannotWrite']='PASS';(ROOT/'artifacts/operational-tls.json').write_text(json.dumps(report,indent=2));print('PASS operational HTTPS, custom-CA authenticated probes, expiry/revocation and read-role boundaries')
 except Exception:
  try:print('Fixture status: '+json.dumps(call('/control/state',read)),flush=True)
  except Exception:pass
  print(subprocess.run(['docker','exec',name,'tail','-20','/run/monitoring/control.log'],capture_output=True,text=True).stdout,flush=True)
  raise
 finally:
  subprocess.run(['docker','stop','--timeout','75',name],check=False,capture_output=True);subprocess.run(['docker','rm',name],check=False,capture_output=True);subprocess.run(compose+['start'],check=True,capture_output=True);server.shutdown()
