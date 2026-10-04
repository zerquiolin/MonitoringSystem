"""Exercise AMD64 runtime under Docker Desktop emulation; no native AMD64 claim."""
import os,sys,json,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait,host
compose=['docker','compose','-f',str(ROOT/'docker/compose.yaml')];name='portable-amd64-test-'+str(int(time.time()));volume=name+'-data';subprocess.run(compose+['stop'],check=True)
try:
 subprocess.run(['docker','run','-d','--platform','linux/amd64','--name',name,'--label','portable-observability.test=true','--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:18081:8080','-v',str(ROOT/'config')+':/config:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','-v',volume+':/data','portable-observability:amd64'],check=True)
 wait(lambda:host('/ready',port=18081).get('status')=='ok',180)
 output=subprocess.check_output(['docker','exec',name,'supervisorctl','-c','/run/monitoring/supervisord.conf','status'],text=True);assert output.count('RUNNING')==9,output
 report={'status':'PASS','imageArchitecture':'amd64','execution':'Docker Desktop emulation on Apple Silicon','assertions':['all 9 supervised processes running','actual backend configurations accepted','gateway and evaluator readiness']};(ROOT/'artifacts/platform-amd64.json').write_text(json.dumps(report,indent=2));print('AMD64 emulated runtime readiness passed')
finally:
 subprocess.run(['docker','stop','--timeout','75',name],check=False);subprocess.run(['docker','rm',name],check=False);subprocess.run(compose+['start'],check=False)
