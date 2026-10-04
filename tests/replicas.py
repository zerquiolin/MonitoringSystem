import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import json,time
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait,host,prom
operator=(ROOT/'secrets/operator-token').read_text().strip()
wait(lambda:len(prom('app_http_requests_total{service="orders-api",route="/orders/:id"}'))>=2)
wait(lambda:any(s['service']=='orders-api' and s['healthyInstances']==2 for s in host('/control/state',operator)))
host('/',operator,'POST',{'role':'orders2','action':'stop'},port=4199)
try:
 wait(lambda:any(s['service']=='orders-api' and s['state']=='DEGRADED' and s['healthyInstances']==1 for s in host('/control/state',operator)),40)
finally:host('/',operator,'POST',{'role':'orders2','action':'restart'},port=4199)
wait(lambda:any(s['service']=='orders-api' and s['state']=='UP' and s['healthyInstances']==2 for s in host('/control/state',operator)),40)
q='histogram_quantile(0.95,sum by(le)(rate(app_http_request_duration_seconds_bucket{service="orders-api"}[2m])))';assert prom(q)
(ROOT/'artifacts/replicas.json').write_text(json.dumps({'status':'PASS','assertions':['two independent instance counters stored','compatible summed histogram query returns data','one stopped replica produces DEGRADED with quorum preserved','second replica recovery returns UP']},indent=2));print('Partial replica failure, quorum, recovery, and aggregate histogram assertions passed')
