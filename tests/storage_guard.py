"""Storage admission on an isolated 16 MiB memory filesystem, never fills a disk."""
from acceptance import ROOT,wait,host
import subprocess,json,time,urllib.request,urllib.error
name='portable-storage-fixture-'+str(int(time.time()))
try:
 subprocess.run(['docker','run','-d','--name',name,'--label','portable-observability.test=true','--memory','256m','--cpus','1','--tmpfs','/fixture:rw,size=16m','-e','MONITORING_DATA=/fixture','-e','MONITORING_MIN_FREE_BYTES=33554432','-e','MONITORING_SECRETS=/run/secrets','-e','MONITORING_CONFIG=/config/inventory.yaml','-v',str(ROOT/'config')+':/config:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','--network','none','--entrypoint','uvicorn','portable-observability:local','app:app','--app-dir','/opt/monitoring/docker/control','--host','127.0.0.1','--port','8000','--no-access-log'],check=True,capture_output=True)
 def rejected():
  code="import urllib.request,urllib.error;from pathlib import Path;token=Path('/run/secrets/demo-orders').read_text().strip();req=urllib.request.Request('http://127.0.0.1:8000/api/ingest/logs',data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'});\ntry: urllib.request.urlopen(req,timeout=3)\nexcept urllib.error.HTTPError as e: print(e.code);print(e.read().decode())"
  result=subprocess.run(['docker','exec',name,'python','-c',code],capture_output=True,text=True)
  return result.returncode==0 and '503' in result.stdout and 'storage admission' in result.stdout
 wait(rejected,30)
 (ROOT/'artifacts/storage-guard.json').write_text(json.dumps({'status':'PASS','filesystem':'isolated 16 MiB tmpfs','minimumFreeBytes':33554432,'ingressRejected':503,'productionDiskFilled':False},indent=2));print('PASS low-space admission rejects new telemetry on a bounded memory fixture')
finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
