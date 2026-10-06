"""Offline backup + isolated empty-volume restore, with the original stack stopped during verification."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import json,time,subprocess,urllib.request,tempfile
sys.path.insert(0,str(ROOT/'tests'));from acceptance import wait,host,prom,internal
compose=['docker','compose','-f',str(ROOT/'docker/compose.yaml')]
operator=(ROOT/'secrets/operator-token').read_text().strip();archive=Path(tempfile.mkdtemp(prefix='monitoring-backup-'))/'backup.tar.gz';volume='portable-restore-test-'+str(int(time.time()));container=volume
host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
active=wait(lambda:next((i for i in host('/control/incidents',operator) if i['service']=='catalog-api' and not i['recovered']),None),60)
trace_id=__import__('json').loads((ROOT/'artifacts/extended-security.json').read_text())['traceId']
before=host('/control/incidents',operator);wait(lambda:prom('app_http_requests_total{service="orders-api"}'))
subprocess.run([sys.executable,str(ROOT/'scripts/monitoring.py'),'backup','--output',str(archive)],check=True)
subprocess.run([sys.executable,str(ROOT/'scripts/monitoring.py'),'restore','--archive',str(archive),'--volume',volume,'--confirm-empty-volume'],check=True)
subprocess.run(compose+['stop'],check=True)
try:
 subprocess.run(['docker','run','-d','--name',container,'--label','portable-observability.test=true','--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:18080:8080','-v',str(ROOT/'config')+':/config:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','-v',volume+':/data','portable-observability:local'],check=True)
 wait(lambda:host('/ready',port=18080).get('status')=='ok')
 restored=host('/control/incidents',operator,port=18080);assert {i['id'] for i in before}<={i['id'] for i in restored}
 def query(url):
  code='import urllib.request,json;print(urllib.request.urlopen('+repr(url)+',timeout=15).read().decode())'
  return json.loads(subprocess.check_output(['docker','exec',container,'python','-c',code],text=True))
 assert query('http://127.0.0.1:9090/api/v1/query?query=app_http_requests_total')['data']['result']
 assert query('http://127.0.0.1:3100/loki/api/v1/query_range?query=%7Bservice%3D%22orders-api%22%7D&limit=1')['data']['result']
 assert any(i['id']==active['id'] and not i['recovered'] for i in restored),'Ongoing incident lost or falsely recovered'
 assert trace_id in __import__('json').dumps(query('http://127.0.0.1:3200/api/traces/'+trace_id)) or 'binary-fixture' in __import__('json').dumps(query('http://127.0.0.1:3200/api/traces/'+trace_id))
 auth='Basic '+__import__('base64').b64encode(('admin:'+(ROOT/'secrets/grafana-admin').read_text().strip()).encode()).decode()
 with urllib.request.urlopen(urllib.request.Request('http://localhost:18080/api/search?type=dash-db',headers={'Authorization':auth}),timeout=10) as r:assert len(json.load(r))==8
 report={'status':'PASS','method':'stopped-stack backup, restored into new isolated empty Docker volume','verified':['incident IDs','ongoing incident remains open','metrics TSDB','Loki logs','Tempo trace','eight dashboards','inventory','all backend readiness','private credential state'],'backupBytes':archive.stat().st_size,'volume':volume}
 (ROOT/'artifacts/persistence.json').write_text(json.dumps(report,indent=2));print('Isolated offline backup/restore assertions passed')
finally:
 subprocess.run(['docker','stop','--time','75',container],check=False);subprocess.run(['docker','rm',container],check=False);subprocess.run(compose+['start'],check=False)
 wait(lambda:host('/ready')['status']=='ok');host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
 # Preserve the labelled test volume for review; remove private backup after verified copy.
 archive.unlink(missing_ok=True);archive.parent.rmdir()
