import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import json,time,subprocess
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait,host
compose=['docker','compose','-f',str(ROOT/'docker/compose.yaml')];wait(lambda:host('/ready')['status']=='ok')
cid=subprocess.check_output(compose+['ps','-q','monitoring'],text=True).strip()
def inspect():return json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
before=inspect()['RestartCount'];start=time.monotonic()
subprocess.run(compose+['exec','-T','monitoring','supervisorctl','-c','/run/monitoring/supervisord.conf','stop','blackbox'],check=True)
wait(lambda:inspect()['RestartCount']>before,120);wait(lambda:host('/ready')['status']=='ok',180)
report={'status':'PASS','fault':'critical Blackbox process stopped','restartCountIncrement':inspect()['RestartCount']-before,'recoverySeconds':time.monotonic()-start,'assertions':['intentional failed container exit','Docker policy recovery','all-backend readiness recovered']};(ROOT/'artifacts/watchdog.json').write_text(json.dumps(report,indent=2));print('Critical child exit causes failed container restart and healthy recovery')
