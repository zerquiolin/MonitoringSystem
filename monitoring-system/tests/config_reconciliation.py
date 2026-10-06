"""Live apply/rollback and removed-resource cleanup. Always restores original inventory."""
from acceptance import ROOT,host,wait
import subprocess,tempfile,yaml,json,base64,urllib.request,time
operator=(ROOT/'secrets/operator-token').read_text().strip();path=ROOT/'config/inventory.yaml';original=path.read_bytes()
credentials='Basic '+base64.b64encode(('admin:'+(ROOT/'secrets/grafana-admin').read_text().strip()).encode()).decode()
def rules():
 with urllib.request.urlopen(urllib.request.Request('http://localhost:8080/api/v1/provisioning/alert-rules',headers={'Authorization':credentials}),timeout=10) as r:return json.load(r)
before={r['uid'] for r in rules()};inventory=yaml.safe_load(original);inventory['services']=[s for s in inventory['services'] if s['service']!='nightly-job']
try:
 with tempfile.TemporaryDirectory() as d:
  candidate=__import__('pathlib').Path(d)/'inventory.yaml';candidate.write_text(yaml.safe_dump(inventory))
  subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/monitoring.py'),'apply','--config',str(candidate)],check=True,capture_output=True)
  wait(lambda:len(host('/control/state',operator))==3)
  after={r['uid'] for r in rules()};assert before-after,'Removed service owned alert rules survived'
  candidate.write_text('profile: invalid\n');result=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/monitoring.py'),'apply','--config',str(candidate)],capture_output=True);assert result.returncode!=0;assert len(host('/control/state',operator))==3
  subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/monitoring.py'),'rollback'],check=True,capture_output=True);wait(lambda:len(host('/control/state',operator))==4)
 (ROOT/'artifacts/reconciliation.json').write_text(json.dumps({'status':'PASS','removedOwnedRules':len(before-after),'invalidApplyPreservedActiveInventory':True,'rollbackRestoredExpectedInventory':True},indent=2));print('PASS real apply cleanup, rejected candidate and rollback')
finally:
 if path.read_bytes()!=original:
  path.write_bytes(original);subprocess.run(['docker','compose','-f',str(ROOT/'docker/compose.yaml'),'restart','monitoring'],check=True,capture_output=True)
