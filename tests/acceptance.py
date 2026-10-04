"""Real local-stack checks. Run after Compose and npm run demo; never mocks backends."""
import sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__' and (ROOT/'.venv/bin/python').exists() and sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__,*sys.argv[1:]])
import json,subprocess,time,urllib.request,urllib.parse,urllib.error,base64
results=[]
def wait(fn,timeout=150):
 deadline=time.monotonic()+timeout;last=None
 while time.monotonic()<deadline:
  try:
   value=fn()
   if value:return value
  except Exception as e:last=e
  time.sleep(2)
 raise AssertionError('Observation deadline exceeded: '+str(last))
def host(path,token=None,method='GET',payload=None,port=8080):
 headers={}
 if token:headers['Authorization']='Bearer '+token
 if payload is not None:headers['Content-Type']='application/json'
 req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers=headers,method=method,data=json.dumps(payload).encode() if payload is not None else None)
 with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
def internal(path):
 code='import urllib.request;print(urllib.request.urlopen(urllib.request.Request('+repr(path)+',headers={"Accept":"application/json"}),timeout=10).read().decode())'
 out=subprocess.check_output(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),'exec','-T','monitoring','python','-c',code],text=True);return json.loads(out)
def prom(q):return internal('http://127.0.0.1:9090/api/v1/query?'+urllib.parse.urlencode({'query':q}))['data']['result']
def check(name,fn):
 try:detail=fn();results.append({'check':name,'status':'PASS','detail':detail});print('PASS '+name,flush=True)
 except Exception as e:results.append({'check':name,'status':'FAIL','detail':str(e)[:1000]});print('FAIL '+name+': '+str(e)[:300],flush=True)
def main():
 operator=(ROOT/'secrets/operator-token').read_text().strip();read=(ROOT/'secrets/dashboard-read').read_text().strip();orders=(ROOT/'secrets/demo-orders').read_text().strip()
 check('DEP-01/04 all required components ready',lambda:wait(lambda:host('/ready').get('status')=='ok'))
 def processes():
  text=subprocess.check_output(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),'exec','-T','monitoring','supervisorctl','-c','/run/monitoring/supervisord.conf','status'],text=True);assert text.count('RUNNING')==9,text;return '9 supervised processes inside one central container'
 check('DEP-01 process topology',processes)
 check('MET-01 real pushed request counts',lambda:wait(lambda:prom('app_http_requests_total{service="orders-api"}') and prom('app_http_request_duration_seconds_bucket{service="orders-api",le="0.5"}')) and 'Prometheus counters and explicit histogram buckets stored')
 check('HLT-01 external probes',lambda:wait(lambda:len(prom('probe_success == 1'))>=4) and 'All four external HTTP health/readiness checks successful')
 check('STA-01 expected inventory visible',lambda:len(host('/control/state',read))==4 or (_ for _ in ()).throw(AssertionError('Expected four services')))
 def security():
  resource={'project':'commerce','service':'catalog-api','environment':'demo','instance':'catalog-api-1'}
  batch={'resource':resource,'events':[{'eventId':'unauthorized','timestamp':int(time.time()*1000),'severity':'info','message':'spoof','attributes':{}}]}
  for credential,expected in [(None,401),(orders,403),(read,403)]:
   try:host('/api/ingest/logs',credential,'POST',batch);raise AssertionError('Unauthorized ingestion accepted')
   except urllib.error.HTTPError as e:assert e.code==expected,(e.code,expected)
  return 'Missing credential, cross-service spoof, and read-role write rejected'
 check('SEC-02 resource and role authorization',security)
 def logtrace():
  logs=wait(lambda:internal('http://127.0.0.1:3100/loki/api/v1/query_range?'+urllib.parse.urlencode({'query':'{service="orders-api"}','limit':100}))['data']['result'])
  events=[json.loads(v[1]) for s in logs for v in s['values']]
  assert not any('SENSITIVE_FIXTURE' in json.dumps(e) for e in events),'Sensitive value found in stored Loki events'
  traced=[e for e in events if e.get('traceId')];assert traced,'No correlated log'
  trace=wait(lambda:internal('http://127.0.0.1:3200/api/traces/'+traced[-1]['traceId']))
  encoded=json.dumps(trace);assert 'catalog-api' in encoded and 'orders-api' in encoded,'Missing cross-service trace'
  return 'Real Loki log redacted and correlated with a stored cross-service Tempo trace'
 check('LOG-01/TRC-01 stored correlated signals',logtrace)
 def grafana():
  password=(ROOT/'secrets/grafana-admin').read_text().strip();authorization='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
  def get(path):
   req=urllib.request.Request('http://localhost:8080'+path,headers={'Authorization':authorization})
   with urllib.request.urlopen(req) as r:return json.load(r)
  assert len(get('/api/search?type=dash-db'))>=8
  assert {x['uid'] for x in get('/api/datasources')} >= {'prometheus','loki','tempo','control'}
  assert len(get('/api/v1/provisioning/alert-rules'))>=8
  query={'refId':'A','datasource':{'uid':'control','type':'yesoreyeram-infinity-datasource'},'type':'json','source':'url','url':'http://127.0.0.1:8000/api/state','url_options':{'method':'GET','headers':[],'params':[],'data':''},'parser':'backend','format':'table','root_selector':'','columns':[]}
  req=urllib.request.Request('http://localhost:8080/api/ds/query',method='POST',headers={'Authorization':authorization,'Content-Type':'application/json'},data=json.dumps({'queries':[query],'from':str(int((time.time()-300)*1000)),'to':str(int(time.time()*1000))}).encode())
  with urllib.request.urlopen(req) as r:response=json.load(r)
  result=response['results']['A'];assert not result.get('error'),result.get('error');assert any(f.get('data',{}).get('values') for f in result.get('frames',[])),'Infinity returned empty inventory table'
  return '8 dashboards, 4 data sources, and Grafana alert rules provisioned'
 check('UI-01 provisioned Grafana resources',grafana)
 def incidents():
  before={i['id'] for i in host('/control/incidents',operator)}
  host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
  try:
   opened=wait(lambda:next((i for i in host('/control/incidents',operator) if i['service']=='catalog-api' and i['recovered'] is None and i['id'] not in before),None),60)
   assert (host('/health',port=4102))['status']=='ok'
  finally:host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
  wait(lambda:any(i['id']==opened['id'] and i['recovered'] for i in host('/control/incidents',operator)),60)
  return 'Dependency failure preserves liveness, opens one incident, and confirms recovery'
 check('HLT-02/INC-01 fault and recovery',incidents)
 def notification():
  subprocess.run([sys.executable,str(ROOT/'scripts/monitoring.py'),'notification-test'],check=True,capture_output=True)
  wait(lambda:host('/control/notifications',operator));return 'Grafana native webhook delivered to local audit receiver; external destinations unverified'
 check('ALT-01 local Grafana notification delivery',notification)
 path=ROOT/'artifacts/acceptance.json';path.write_text(json.dumps({'executedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'platform':subprocess.check_output(['docker','image','inspect','portable-observability:local','--format','{{.Architecture}}'],text=True).strip(),'checks':results},indent=2))
 if any(x['status']=='FAIL' for x in results):sys.exit(1)
if __name__=='__main__':main()
