"""Real kernel OOM in an isolated bounded container, followed by sufficient-budget recovery."""
from acceptance import ROOT,wait
import subprocess,tempfile,time,json,yaml
from pathlib import Path
name='portable-oom-fixture-'+str(int(time.time()));volume=name+'-data'
def run(args):return subprocess.check_output(['docker',*args],text=True)
def inspect():return json.loads(run(['inspect',name]))[0]
with tempfile.TemporaryDirectory() as d:
 path=Path(d);c=yaml.safe_load((ROOT/'config/inventory.yaml').read_text());c['services']=[];c['projects']=[{'id':'oom','criticalServices':[]}];(path/'inventory.yaml').write_text(yaml.safe_dump(c))
 try:
  run(['run','-d','--name',name,'--label','portable-observability.test=true','--network','none','--memory','192m','--memory-swap','192m','--cpus','1','-v',str(path)+':/config:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','-v',volume+':/data','portable-observability:local'])
  wait(lambda:inspect()['State']['OOMKilled'],120);wait(lambda:not inspect()['State']['Running'],90);run(['update','--memory','3g','--memory-swap','3g',name]);run(['start',name]);wait(lambda:inspect()['State']['Health']['Status']=='healthy',180)
  (ROOT/'artifacts/oom.json').write_text(json.dumps({'status':'PASS','fault':'actual cgroup kernel OOM at 192 MiB','recovery':'same isolated volume, restarted at 3 GiB','network':'none','productionResourcesChanged':False},indent=2));print('PASS actual isolated kernel OOM and healthy recovery with adequate budget')
 finally:
  if not (ROOT/'artifacts/oom.json').exists():print(run(['logs',name])[-2000:])
  subprocess.run(['docker','rm','-f',name],capture_output=True)
