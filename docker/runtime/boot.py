import json,os,shutil,subprocess,sys,time
from pathlib import Path
from configuration import load,render
os.environ['MONITORING_RUNTIME']='1'
SECRETS='/run/monitoring/secrets';os.environ['MONITORING_SECRETS']=SECRETS
Path('/run/monitoring/fatal').unlink(missing_ok=True)
try:
 config=load('/config/inventory.yaml',SECRETS)
 stage=Path('/run/monitoring/stage');render(config,stage,SECRETS)
 # Validators that can run without running backends.
 # Prometheus references the final active path, so publish transient validated stage first.
 active=Path('/run/monitoring/active')
 if active.exists():shutil.rmtree(active)
 stage.rename(active)
 for command in [['promtool','check','config',str(active/'prometheus.yaml')],['loki','-config.file='+str(active/'loki.yaml'),'-verify-config=true'],['blackbox_exporter','--config.file=/run/monitoring/active/blackbox.yaml','--config.check'],['tempo','-config.file=/run/monitoring/active/tempo.yaml','-config.verify=true'],['alloy','validate','--stability.level=experimental',str(active/'alloy.alloy')],['nginx','-t','-c',str(active/'nginx.conf')]]:
  subprocess.run(command,check=True)
 state=Path('/data/config-state');pending=state/'pending'
 if pending.exists():shutil.rmtree(pending)
 shutil.copytree(active,pending)
except Exception as exc:
 print('Startup validation failed: '+type(exc).__name__+' '+str(exc)[:250],file=sys.stderr);time.sleep(10);sys.exit(78)
ret=config.get('retention',{});Path('/run/monitoring/supervisord.conf').write_text('''[supervisord]
nodaemon=true
logfile=/dev/null
pidfile=/run/monitoring/supervisor.pid
childlogdir=/run/monitoring
[unix_http_server]
file=/run/monitoring/supervisor.sock
chmod=0600
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix:///run/monitoring/supervisor.sock
'''+''.join(f'''
[program:{name}]
command={cmd}
autostart=true
autorestart=false
startsecs=2
startretries=0
priority={priority}
stopsignal=TERM
stopwaitsecs=15
stopasgroup=true
killasgroup=true
stdout_logfile=/run/monitoring/{name}.log
stdout_logfile_maxbytes=5MB
stdout_logfile_backups=2
redirect_stderr=true
''' for name,cmd,priority in [
('prometheus',f'prometheus --config.file=/run/monitoring/active/prometheus.yaml --storage.tsdb.path=/data/prometheus --storage.tsdb.retention.time={ret.get("metricsDays",7)}d --storage.tsdb.retention.size={ret.get("metricsSize","1GB")} --web.listen-address=127.0.0.1:9090 --web.enable-remote-write-receiver --enable-feature=exemplar-storage',10),
('blackbox','blackbox_exporter --config.file=/run/monitoring/active/blackbox.yaml --web.listen-address=127.0.0.1:9115',10),
('loki','loki -config.file=/run/monitoring/active/loki.yaml',10),
('tempo','tempo -config.file=/run/monitoring/active/tempo.yaml',10),
('alloy','alloy run --stability.level=experimental --server.http.listen-addr=127.0.0.1:12345 --storage.path=/data/alloy /run/monitoring/active/alloy.alloy',20),
('control','uvicorn app:app --host 127.0.0.1 --port 8000 --app-dir /opt/monitoring/docker/control --limit-concurrency 64 --timeout-keep-alive 5 --no-access-log',20),
('grafana','/usr/share/grafana/bin/grafana server --homepath=/usr/share/grafana --config=/run/monitoring/active/grafana.ini',30),
('gateway','nginx -c /run/monitoring/active/nginx.conf -g "daemon off;"',40),
('watchdog','python /opt/monitoring/docker/runtime/watchdog.py',50)
]))
import signal
supervisor=subprocess.Popen(['supervisord','-c','/run/monitoring/supervisord.conf'])
def shutdown(_signal,_frame):
 supervisor.terminate()
signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
code=supervisor.wait()
sys.exit(1 if Path('/run/monitoring/fatal').exists() else code)
