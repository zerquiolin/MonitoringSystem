"""Uptime grows, known downtime increases during failure, recovery and restart preserve history."""
from acceptance import ROOT,host,wait
import time,json,subprocess
read=(ROOT/'secrets/dashboard-read').read_text().strip();operator=(ROOT/'secrets/operator-token').read_text().strip();start=time.time()-10
wait(lambda:host('/ready')['status']=='ok',150)
wait(lambda:any(r['state']=='UP' and r['service']=='catalog-api' for r in host('/control/state',read)),60)
url='/control/reliability?service=catalog-api&start='+str(start)
before=host(url,read)[0]
time.sleep(7);after=host(url,read)[0];assert after['uptimeSeconds']>before['uptimeSeconds']
host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
try:
 wait(lambda:any(r['state']=='DOWN' and r['service']=='catalog-api' for r in host('/control/state',read)),45)
 time.sleep(7);failure=host(url,read)[0];assert failure['downtimeSeconds']>=5,failure
finally:host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
wait(lambda:any(r['state']=='UP' and r['service']=='catalog-api' for r in host('/control/state',read)),45)
wait(lambda:host(url,read)[0]['activeIncidents']==0,45);recovered=host(url,read)[0];assert recovered['mttrSeconds'] is not None
subprocess.run(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),'restart','monitoring'],check=True,capture_output=True)
wait(lambda:host('/ready')['status']=='ok',150)
restored=host(url,read)[0];assert restored['downtimeSeconds']>=recovered['downtimeSeconds']-.1
assert restored['unknownSeconds']>0
(ROOT/'artifacts/reliability.json').write_text(json.dumps({'status':'PASS','before':before,'failure':failure,'recovered':recovered,'afterRestart':restored},indent=2))
print('PASS live uptime, downtime, incident MTTR, restart persistence and unknown coverage')
