"""Native email/Slack/Teams/webhook routing and maintenance, using local sinks only."""
from acceptance import ROOT,host,wait
import json,time,tempfile,subprocess,threading,socketserver,base64,urllib.request,yaml
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from datetime import datetime,timezone
received=[];mail=[]
class HTTP(BaseHTTPRequestHandler):
 def do_POST(self):
  payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));received.append((self.path,payload,time.time()));self.send_response(200);self.end_headers();self.wfile.write(b'ok')
 def log_message(self,*args):pass
class SMTP(socketserver.StreamRequestHandler):
 def handle(self):
  def answer(s):self.wfile.write((s+'\r\n').encode());self.wfile.flush()
  answer('220 local.fixture ESMTP')
  while True:
   line=self.rfile.readline()
   if not line:break
   command=line.decode().strip().upper()
   if command.startswith(('EHLO','HELO')):answer('250 local.fixture')
   elif command=='DATA':
    answer('354 End with dot');parts=[]
    while True:
     line=self.rfile.readline()
     if line in (b'.\r\n',b''):break
     parts.append(line)
    mail.append((b''.join(parts).decode(errors='replace'),time.time()));answer('250 accepted')
   elif command=='QUIT':answer('221 bye');break
   else:answer('250 ok')
http=ThreadingHTTPServer(('127.0.0.1',4197),HTTP);smtp=socketserver.ThreadingTCPServer(('127.0.0.1',4196),SMTP)
for server in (http,smtp):threading.Thread(target=server.serve_forever,daemon=True).start()
operator=(ROOT/'secrets/operator-token').read_text().strip();original=(ROOT/'config/inventory.yaml').read_bytes();compose=['docker','compose','-f',str(ROOT/'docker/compose.yaml')]
auth='Basic '+base64.b64encode(('admin:'+(ROOT/'secrets/grafana-admin').read_text().strip()).encode()).decode()
def grafana(path):
 with urllib.request.urlopen(urllib.request.Request('http://localhost:8080'+path,headers={'Authorization':auth}),timeout=10) as r:return json.load(r)
def apply(c):
 with tempfile.TemporaryDirectory() as d:
  path=Path(d)/'inventory.yaml';path.write_text(yaml.safe_dump(c));subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/monitoring.py'),'apply','--config',str(path)],check=True,capture_output=True)
 wait(lambda:host('/ready')['status']=='ok')
refs=[];report={}
try:
 c=yaml.safe_load(original);c['notifications']=[{'name':'local','type':'local'}]
 for typ in ['webhook','slack','teams']:
  ref='fixture-native-'+typ;refs.append(ROOT/'secrets'/ref);refs[-1].write_text('http://host.docker.internal:4197/'+typ);refs[-1].chmod(0o600);c['notifications'].append({'name':'fixture-'+typ,'type':typ,'secretRef':ref,'project':'commerce','severity':'critical'})
 c['notifications'].append({'name':'fixture-email','type':'email','addresses':'test@local.invalid','project':'commerce','severity':'critical'});c['smtp']={'host':'host.docker.internal:4196','fromAddress':'monitoring@local.invalid','startTLSPolicy':'NoStartTLS'}
 apply(c);start=time.time();host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
 incident=wait(lambda:next((r for r in host('/control/incidents',operator) if r['service']=='catalog-api' and not r['recovered']),None),60)
 wait(lambda:{p for p,data,t in received if t>=start}>={'/webhook','/slack','/teams'} and any(t>=start for data,t in mail),120)
 payloads={p:data for p,data,t in received if t>=start};assert payloads['/webhook']['status']=='firing';assert 'attachments' in payloads['/slack'];assert any(k in payloads['/teams'] for k in ('attachments','sections','@type')),payloads['/teams'].keys();assert 'Content-Type:' in mail[-1][0]
 report['nativeFiringPayloads']=['Grafana webhook','Slack attachment','Teams card','SMTP message'];before=len(received);before_mail=len(mail)
 host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
 wait(lambda:{p for p,data,t in received[before:]}>={'/webhook','/slack','/teams'} and len(mail)>before_mail,120);assert any(p=='/webhook' and data['status']=='resolved' for p,data,t in received[before:]);report['allFourNativeResolvedDeliveries']='PASS'
 start=time.time();end=start+180
 for s in c['services']:
  if s['service']=='catalog-api':s['maintenance']=[{'start':datetime.fromtimestamp(start,timezone.utc).isoformat(),'end':datetime.fromtimestamp(end,timezone.utc).isoformat(),'excludeFromSlo':True}]
 apply(c)
 wait(lambda:any(x['status']['state']=='active' and x['createdBy']=='portable-observability' for x in grafana('/api/alertmanager/grafana/api/v2/silences')),60)
 baseline=time.time();before_ids={r['id'] for r in host('/control/incidents',operator)};host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
 wait(lambda:next((r for r in host('/control/incidents',operator) if r['service']=='catalog-api' and r['id'] not in before_ids and not r['recovered']),None),60)
 wait(lambda:any(a.get('labels',{}).get('service')=='catalog-api' and a['status']['silencedBy'] for a in grafana('/api/alertmanager/grafana/api/v2/alerts')),60)
 time.sleep(35);assert not any(t>=baseline and p=='/webhook' and data.get('status')=='firing' and any(a['labels'].get('service')=='catalog-api' for a in data['alerts']) for p,data,t in received)
 r=next(r for r in host('/control/reliability?start='+str(start),operator) if r['service']=='catalog-api');assert r['excludedMaintenanceSeconds']>0;report['maintenanceSuppressesDeliveryPreservesIncidentAndExcludesSlo']='PASS';report['status']='PASS'
 (ROOT/'artifacts/native-notifications.json').write_text(json.dumps(report,indent=2));print('PASS native firing/resolved, multiple destinations, maintenance silence and separate incident evidence')
finally:
 host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
 (ROOT/'config/inventory.yaml').write_bytes(original);subprocess.run(compose+['restart','monitoring'],check=True,capture_output=True)
 for ref in refs:ref.unlink(missing_ok=True)
 for server in (http,smtp):server.shutdown();server.server_close()
