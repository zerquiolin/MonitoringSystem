import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import json,time
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait,host
operator=(ROOT/'secrets/operator-token').read_text().strip()
def state(service):return next(s for s in host('/control/state',operator) if s['service']==service)
def fault(role,values):host('/',operator,'POST',{'role':role,'action':'fault','values':values},port=4199)
checks=[]
for role,service,key,reason,timeout in [('worker','billing-worker','heartbeatLoss','heartbeat_expired',50),('worker','billing-worker','stall','job_stalled',60),('scheduler','nightly-job','missSchedule','scheduled_deadline_missed',120)]:
 wait(lambda:state(service)['state']=='UP',45);fault(role,{key:True})
 try:wait(lambda:state(service)['state']=='DOWN' and state(service)['reason']==reason,timeout)
 finally:fault(role,{key:False})
 wait(lambda:state(service)['state']=='UP',45);checks.append({'fault':key,'reason':reason,'recovery':'UP'});print('PASS '+key+' and confirmed recovery',flush=True)
(ROOT/'artifacts/workers.json').write_text(json.dumps({'status':'PASS','checks':checks},indent=2))
