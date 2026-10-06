"""Real generated Blackbox TCP/DNS modules using the assembled image and private destinations."""
from acceptance import ROOT,internal,prom,wait
import sys,tempfile,subprocess,os,json
sys.path.insert(0,str(ROOT/'docker/control'))
from configuration import load,render
c=load(ROOT/'config/inventory.yaml',ROOT/'secrets');s=c['services'][0];s['instances'][0]['tcpUrl']='tcp://host.docker.internal:4101';s['instances'][0]['dnsUrl']='dns://127.0.0.11:53';s['instances'][0]['dnsQuery']='host.docker.internal';c['network']['allowedHosts'].append('127.0.0.11');c['network']['allowedCidrs'].append('127.0.0.11/32')
# Render test module config in a disposable running instance, not modify live inventory.
with tempfile.TemporaryDirectory() as temp:
 import yaml
 file=__import__('pathlib').Path(temp)/'inventory.yaml';file.write_text(yaml.safe_dump(c));name='portable-probe-fixture'
 subprocess.run(['docker','run','-d','--name',name,'--network','portable-observability_default','--add-host','host.docker.internal:host-gateway','--entrypoint','python','-v',str(file)+':/config/inventory.yaml:ro','-v',str(ROOT/'secrets')+':/run/secrets:ro','portable-observability:local','-c','import os,shutil,subprocess;from configuration import load,render;os.environ["MONITORING_RUNTIME"]="1";shutil.copytree("/run/secrets","/run/monitoring/secrets");render(load("/config/inventory.yaml","/run/secrets"),"/run/monitoring/active","/run/secrets");subprocess.run(["blackbox_exporter","--web.listen-address=127.0.0.1:9115","--config.file=/run/monitoring/active/blackbox.yaml"],check=True)'],check=True,capture_output=True)
 try:
  from configuration import sid
  reports={}
  for kind,target in [('tcp','host.docker.internal:4101'),('dns','127.0.0.11:53')]:
   module='probe_'+sid(s)+'_'+kind+'_orders-api-1'
   code='import urllib.request;print(urllib.request.urlopen('+repr('http://127.0.0.1:9115/probe?target='+target+'&module='+module)+',timeout=10).read().decode())'
   output=wait(lambda:subprocess.check_output(['docker','exec',name,'python','-c',code],text=True),30);assert '\nprobe_success 1' in output,output;reports[kind]='PASS'
  (ROOT/'artifacts/network-probes.json').write_text(json.dumps(reports,indent=2));print('PASS real TCP and DNS probe modules')
 finally:subprocess.run(['docker','rm','-f',name],check=False,capture_output=True)
