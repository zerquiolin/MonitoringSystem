"""Exit entire supervised stack on crash or repeated backend readiness failure."""
import os,signal,time,urllib.request,xmlrpc.client,http.client,shutil,yaml
from pathlib import Path
class UnixConnection(http.client.HTTPConnection):
 def connect(self):
  import socket
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.connect('/run/monitoring/supervisor.sock')
class UnixTransport(xmlrpc.client.Transport):
 def make_connection(self,host):return UnixConnection(host)
server=xmlrpc.client.ServerProxy('http://localhost',transport=UnixTransport())
policy=yaml.safe_load(Path('/config/inventory.yaml').read_text()).get('watchdog',{})
start=time.monotonic();failures=0;seen=set()
while True:
 time.sleep(policy.get('intervalSeconds',5))
 try:
  states=server.supervisor.getAllProcessInfo()
  for p in states:
   if p['statename']=='RUNNING':seen.add(p['name'])
  critical=[p for p in states if p['name']!='watchdog' and (p['statename'] in ('EXITED','FATAL','BACKOFF') or p['name'] in seen and p['statename']!='RUNNING')]
  if critical:raise RuntimeError('critical process exited: '+critical[0]['name'])
  try:
   with urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3) as r:healthy=r.status==200
  except Exception:healthy=False
  if healthy and Path('/data/config-state/pending').exists():
   directory=Path('/data/config-state');old=directory/'previous';active=directory/'last-known-good'
   if old.exists():shutil.rmtree(old)
   if active.exists():active.rename(old)
   (directory/'pending').rename(active)
  failures=0 if healthy else failures+1
  if time.monotonic()-start>policy.get('startupGraceSeconds',150) and failures>=policy.get('failureCount',6):raise RuntimeError('readiness deadline exceeded')
 except Exception as exc:
  print('Watchdog stopping stack: '+str(exc),flush=True)
  open('/run/monitoring/fatal','w').write(type(exc).__name__);pid=int(open('/run/monitoring/supervisor.pid').read());os.kill(pid,signal.SIGTERM)
  # Supervisor exits cleanly on SIGTERM; fail the parent PID1 after bounded drain.
  time.sleep(policy.get('shutdownBudgetSeconds',35));os.kill(1,signal.SIGKILL);break
