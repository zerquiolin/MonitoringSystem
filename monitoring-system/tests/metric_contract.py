"""Actual Prometheus pull compatibility, cumulative resets and histogram rejection."""
from acceptance import ROOT,wait,prom,host
import subprocess,tempfile,json,time,urllib.request,secrets
from pathlib import Path
from security import send
name='portable-pull-fixture-'+str(int(time.time()));node=subprocess.Popen(['node',str(ROOT/'tests/pull-fixture.mjs')],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 wait(lambda:urllib.request.urlopen('http://127.0.0.1:4202/metrics',timeout=2).status==200,20)
 for _ in range(3):urllib.request.urlopen('http://127.0.0.1:4202/pull/a',timeout=2).read()
 text=urllib.request.urlopen('http://127.0.0.1:4202/metrics',timeout=2).read().decode();assert 'app_http_requests_total' in text and 'app_http_request_duration_seconds_bucket' in text and 'le="0.5"' in text;assert 'app_http_requests_total_total' not in text
 with tempfile.TemporaryDirectory() as d:
  path=Path(d)/'prometheus.yaml';path.write_text('global:\n  scrape_interval: 2s\nscrape_configs:\n- job_name: pull-fixture\n  honor_labels: true\n  static_configs:\n  - targets: [host.docker.internal:4202]\n')
  subprocess.run(['docker','run','-d','--name',name,'--label','portable-observability.test=true','--memory','256m','--cpus','1','--add-host','host.docker.internal:host-gateway','--entrypoint','prometheus','-v',str(path)+':/fixture.yaml:ro','portable-observability:local','--config.file=/fixture.yaml','--storage.tsdb.path=/tmp/pull-tsdb','--web.listen-address=127.0.0.1:9090'],check=True,capture_output=True)
  def pulled():
   code="import urllib.request,json;print(urllib.request.urlopen('http://127.0.0.1:9090/api/v1/query?query=app_http_requests_total',timeout=3).read().decode())";r=subprocess.run(['docker','exec',name,'python','-c',code],capture_output=True,text=True)
   if r.returncode:return False
   results=json.loads(r.stdout)['data']['result'];return next((v for v in results if v['metric'].get('route')=='/pull/:id' and float(v['value'][1])==3),None)
  series=wait(pulled,30);assert series['metric']['instance']=='orders-api-2';assert series['metric']['project']=='commerce'
 kind='reset-'+secrets.token_hex(4);start=int(time.time()*1e9)-1000000000;observed=[]
 resource={'attributes':[{'key':k,'value':{'stringValue':v}} for k,v in {'project':'commerce','service':'orders-api','environment':'demo','instance':'orders-api-2'}.items()]}
 for value in [2,5,1]:
  now=int(time.time()*1e9)
  if value==1:start=now-1000000
  payload={'resourceMetrics':[{'resource':resource,'scopeMetrics':[{'scope':{'name':'reset-fixture'},'metrics':[{'name':'app_business_reset_total','sum':{'aggregationTemporality':2,'isMonotonic':True,'dataPoints':[{'attributes':[{'key':'kind','value':{'stringValue':kind}}],'asInt':str(value),'startTimeUnixNano':str(start),'timeUnixNano':str(now)}]}}]}]}]}
  assert send('/v1/metrics',json.dumps(payload).encode())==200
  row=wait(lambda:next((v for v in prom('app_business_reset_total{kind="'+kind+'"}') if float(v['value'][1])==value),None),45);observed.append(float(row['value'][1]));time.sleep(2)
 payload['resourceMetrics'][0]['scopeMetrics'][0]['metrics']=[{'name':'app_business_invalid_histogram','histogram':{'aggregationTemporality':2,'dataPoints':[{'explicitBounds':[.5,.1],'bucketCounts':['0','1','0'],'count':'1','timeUnixNano':str(now),'startTimeUnixNano':str(start)}]}}];assert send('/v1/metrics',json.dumps(payload).encode())==400
 (ROOT/'artifacts/metric-contract.json').write_text(json.dumps({'status':'PASS','realPullStoredCount':3,'pushPullCanonicalNamesAndBuckets':'PASS','cumulativeResetValues':observed,'invalidHistogramRejected':400},indent=2));print('PASS real pull identity/names/buckets, cumulative counter reset and histogram rejection')
finally:
 node.terminate();node.wait(timeout=10);subprocess.run(['docker','rm','-f',name],capture_output=True)
