"""Fresh-volume, disconnected startup and recoverable hang/kill faults."""
from acceptance import ROOT,wait
import subprocess,tempfile,json,time,yaml
from pathlib import Path
report={'status':'PASS'};name='portable-offline-fixture-'+str(int(time.time()));volume=name+'-data'
with tempfile.TemporaryDirectory() as d:
 c=yaml.safe_load((ROOT/'config/inventory.yaml').read_text());c['services']=[];c['projects']=[{'id':'offline','criticalServices':[]}];c['notifications']=[{'name':'local','type':'local'}];c['watchdog']={'startupGraceSeconds':60,'failureCount':2,'intervalSeconds':2,'shutdownBudgetSeconds':20}
 path=Path(d);(path/'inventory.yaml').write_text(yaml.safe_dump(c))
 def run(args):return subprocess.check_output(['docker',*args],text=True)
 def inspect():return json.loads(run(['inspect',name]))[0]
 def healthy():
  return inspect()['State']['Health']['Status']=='healthy'
 try:
  run(['run','-d','--name',name,'--label','portable-observability.test=true','--network','none','--memory','3g','--cpus','2','--restart','unless-stopped','-v',str(path)+':/config:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','-v',volume+':/data','portable-observability:local'])
  wait(healthy,150);assert 'none' in inspect()['NetworkSettings']['Networks'];report['freshVolumeNoNetworkStartup']='PASS';assert run(['exec',name,'supervisorctl','-c','/run/monitoring/supervisord.conf','status']).count('RUNNING')==9
  for signal in ['STOP','KILL']:
   before=inspect()['RestartCount'];pid=run(['exec',name,'supervisorctl','-c','/run/monitoring/supervisord.conf','pid','blackbox']).strip();start=time.monotonic();run(['exec',name,'kill','-'+signal,pid]);wait(lambda:inspect()['RestartCount']>before,120);wait(healthy,150);report['blackbox'+signal+'RecoverySeconds']=round(time.monotonic()-start,2)
  started=time.monotonic();run(['stop','--timeout','75',name]);assert not inspect()['State']['Running'];report['gracefulStopSeconds']=round(time.monotonic()-started,2);run(['start',name]);wait(healthy,150)
  run(['kill','--signal','KILL',name]);run(['start',name]);wait(healthy,150);report['forcedContainerStopAndRecovery']='PASS'
  (ROOT/'artifacts/offline-lifecycle.json').write_text(json.dumps(report,indent=2));print('PASS disconnected fresh startup, bounded hang/kill recovery, graceful and forced stop')
 finally:
  if report.get('freshVolumeNoNetworkStartup')!='PASS':
   print(run(['logs',name])[-2000:]);print(run(['exec',name,'sh','-c','tail -15 /run/monitoring/tempo.log; tail -10 /run/monitoring/control.log; tail -10 /run/monitoring/watchdog.log']))
  subprocess.run(['docker','rm','-f',name],capture_output=True)
