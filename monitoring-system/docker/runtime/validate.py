"""Preflight backend syntax in the assembled image before changing the live inventory."""
import os,shutil,subprocess
from pathlib import Path
from configuration import load,render
os.environ['MONITORING_RUNTIME']='1'
Path('/run/monitoring').mkdir(exist_ok=True)
shutil.copytree('/run/secrets','/run/monitoring/secrets',dirs_exist_ok=True)
c=load('/config/inventory.yaml','/run/monitoring/secrets');render(c,'/run/monitoring/active','/run/monitoring/secrets')
for cmd in [['promtool','check','config','/run/monitoring/active/prometheus.yaml'],['loki','-config.file=/run/monitoring/active/loki.yaml','-verify-config=true'],['blackbox_exporter','--config.file=/run/monitoring/active/blackbox.yaml','--config.check'],['tempo','-config.file=/run/monitoring/active/tempo.yaml','-config.verify=true'],['alloy','validate','--stability.level=experimental','/run/monitoring/active/alloy.alloy'],['nginx','-t','-c','/run/monitoring/active/nginx.conf']]:subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('Assembled-image backend preflight passed.')
