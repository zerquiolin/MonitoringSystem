from acceptance import ROOT,prom,wait
import time,json,subprocess,tempfile
from pathlib import Path
fixture=r'''
import time,json,urllib.request
from pathlib import Path
resource={'attributes':[{'key':k,'value':{'stringValue':v}} for k,v in {'project':'commerce','service':'orders-api','environment':'demo','instance':'orders-api-2'}.items()]}
token=Path('/token').read_text().strip();start=int(time.time()*1e9)-1000000000;previous=start
for n in range(3):
 now=int(time.time()*1e9);point={'attributes':[{'key':'kind','value':{'stringValue':'delta-v2'}}],'asInt':str(n+1),'startTimeUnixNano':str(previous),'timeUnixNano':str(now)}
 histogram={'attributes':[{'key':'kind','value':{'stringValue':'delta-v2'}}],'startTimeUnixNano':str(previous),'timeUnixNano':str(now),'count':'1','sum':.2,'explicitBounds':[.1,.5,1.0],'bucketCounts':['0','1','0','0']}
 payload={'resourceMetrics':[{'resource':resource,'scopeMetrics':[{'scope':{'name':'pipeline-fixture'},'metrics':[{'name':'app_business_delta_total','sum':{'aggregationTemporality':1,'isMonotonic':True,'dataPoints':[point]}},{'name':'app_business_delta_duration_seconds','histogram':{'aggregationTemporality':1,'dataPoints':[histogram]}}]}]}]}
 req=urllib.request.Request('http://host.docker.internal:8080/v1/metrics',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},data=json.dumps(payload).encode())
 with urllib.request.urlopen(req,timeout=10) as r:assert r.status==200
 previous=now;time.sleep(2)
'''
with tempfile.TemporaryDirectory() as d:
 path=Path(d)/'fixture.py';path.write_text(fixture)
 subprocess.run(['docker','run','--rm','--entrypoint','python','--add-host','host.docker.internal:host-gateway','-v',str(path)+':/fixture.py:ro','-v',str(ROOT/'secrets/demo-orders')+':/token:ro','portable-observability:local','/fixture.py'],check=True,capture_output=True)
 counter=wait(lambda:next((v for v in prom('app_business_delta_total{service="orders-api",instance="orders-api-2",kind="delta-v2"}') if float(v['value'][1])==6),None));counter=[counter]
 assert float(counter[0]['value'][1])==6,counter
 buckets=wait(lambda:next((v for v in prom('app_business_delta_duration_seconds_bucket{le="0.5",kind="delta-v2"}') if float(v['value'][1])==3),None));buckets=[buckets]
 assert float(buckets[0]['value'][1])==3,buckets
 count=prom('app_business_delta_duration_seconds_count{kind="delta-v2"}');assert float(count[0]['value'][1])==3,count
 (ROOT/'artifacts/metric-pipeline.json').write_text(json.dumps({'status':'PASS','deltaSumConvertedToCumulative':6,'deltaHistogramCount':3,'deltaHistogramBucket':3,'outboundOnlyApplication':'container publishes no ports and has no listening application server'},indent=2));print('PASS real outbound push, delta conversion and histogram buckets')
