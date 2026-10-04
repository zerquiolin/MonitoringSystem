import unittest,asyncio,json,time,uuid
from test_domain import app
from schedules import latest_due
from datetime import datetime
class Request:
 def __init__(self,p,path,token):self.p=p;self.url=type('URL',(),{'path':path})();self.headers={'authorization':'Bearer '+token}
 async def stream(self):yield json.dumps(self.p).encode()
class WorkerContracts(unittest.TestCase):
 def setUp(self):
  self.s=next(s for s in app.config['services'] if s['kind']=='worker');self.sid=app.sid(self.s);self.resource={**{k:self.s[k] for k in ('project','service','environment')},'instance':self.s['instances'][0]['id']};self.token=(app.SECRETS/self.s['metrics']['tokenRef']).read_text().strip();self.boot=str(uuid.uuid4())
  for table in ['job_runs','job_context','jobs','heartbeats','heartbeat_source','retired_boots']:app.DB.execute('DELETE FROM '+table)
  app.DB.commit()
 def event(self,state,run=None,**kw):return {'resource':self.resource,'state':state,'name':'fixture','runId':run or str(uuid.uuid4()),'bootId':self.boot,'timestamp':time.time(),**kw}
 def job(self,p):return asyncio.run(app.job(Request(p,'/api/ingest/job',self.token)))
 def test_idempotency_overlap_and_terminal(self):
  p=self.event('started');self.job(p);self.assertTrue(self.job(p)['duplicate'])
  with self.assertRaises(app.HTTPException) as e:self.job(self.event('started'))
  self.assertEqual(e.exception.status_code,409);p['state']='completed';self.job(p);self.assertTrue(self.job(p)['duplicate']);p['state']='failed'
  with self.assertRaises(app.HTTPException):self.job(p)
 def test_terminal_without_start_and_skew(self):
  for p in [self.event('completed'),self.event('started',timestamp=time.time()-300)]:
   with self.assertRaises(app.HTTPException):self.job(p)
 def test_stale_running_job_becomes_interrupted(self):
  p=self.event('started');self.job(p);app.DB.execute('UPDATE job_runs SET started=?',(time.time()-400,));app.DB.commit();self.job(self.event('started'));self.assertEqual(app.DB.execute('SELECT state FROM job_runs WHERE run_id=?',(p['runId'],)).fetchone()[0],'interrupted')
 def test_heartbeat_replay_retired_boot_and_source(self):
  p={'resource':self.resource,'bootId':self.boot,'sequence':1,'ready':True,'activeJobs':0,'progress':0,'timestamp':time.time()}
  def beat():return asyncio.run(app.heartbeat(Request(p,'/api/ingest/heartbeat',self.token)))
  beat();self.assertEqual(app.DB.execute('SELECT source_time FROM heartbeat_source').fetchone()[0],p['timestamp'])
  with self.assertRaises(app.HTTPException):beat()
  old=p['bootId'];p['bootId']=str(uuid.uuid4());beat();p['bootId']=old;p['sequence']=2
  with self.assertRaises(app.HTTPException):beat()
 def test_dst_occurrences_are_not_future_or_naive(self):
  for stamp in ['2026-03-08T08:00:00+00:00','2026-11-01T07:00:00+00:00']:
   now=datetime.fromisoformat(stamp).timestamp();due=latest_due('30 1 * * *','America/New_York',now);self.assertLess(due,now);self.assertLess(now-due,86400)
