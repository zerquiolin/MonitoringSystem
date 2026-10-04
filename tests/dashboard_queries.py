"""Query every shipped Grafana panel through its real provisioned data source."""
from acceptance import ROOT,wait,host
import json,time,urllib.request,base64
from pathlib import Path
auth='Basic '+base64.b64encode(('admin:'+(ROOT/'secrets/grafana-admin').read_text().strip()).encode()).decode()
def request(path,payload=None):
 req=urllib.request.Request('http://localhost:8080'+path,headers={'Authorization':auth,'Content-Type':'application/json'},data=json.dumps(payload).encode() if payload is not None else None)
 try:
  with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
 except __import__('urllib.error',fromlist=['HTTPError']).HTTPError as e:raise AssertionError(e.read().decode())
wait(lambda:host('/ready')['status']=='ok');now=int(time.time()*1000);results=[]
for uid in ['overview','project','service','infrastructure','logs','traces','incidents','monitoring']:
 dashboard=request('/api/dashboards/uid/'+uid)['dashboard']
 for panel in dashboard['panels']:
  targets=panel.get('targets',[])
  if not targets:continue
  query=json.loads(json.dumps(targets[0]));query['intervalMs']=15000;query['maxDataPoints']=1000
  for field in ['expr','url','query']:
   if field not in query:continue
   value=query[field]
   for old,new in [('${__from}',str(now-1800000)),('${__to}',str(now)),('$__rate_interval','1m'),('$__range','30m')]:value=value.replace(old,new)
   for var in ['project','service','environment','instance','host','severity']:value=value.replace('${'+var+':regex}','.*').replace('$'+var,'.*')
   query[field]=value
  print(uid+': '+panel['title'],flush=True)
  data=request('/api/ds/query',{'from':str(now-1800000),'to':str(now),'queries':[query]})['results']['A'];assert not data.get('error'),(uid,panel['title'],data)
  results.append({'dashboard':uid,'panel':panel['title'],'status':'PASS','frames':len(data.get('frames',[]))})
(ROOT/'artifacts/dashboard-queries.json').write_text(json.dumps({'status':'PASS','panels':results},indent=2));print('PASS all '+str(len(results))+' dashboard panels queried through Grafana data sources')
