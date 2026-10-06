import unittest,tempfile,os,sys,time,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'docker/control'))
fixture=tempfile.TemporaryDirectory();os.environ['MONITORING_DATA']=fixture.name;os.environ['MONITORING_CONFIG']=str(ROOT/'config/inventory.yaml');os.environ['MONITORING_SECRETS']=str(ROOT/'secrets')
import app
class Domain(unittest.TestCase):
 def setUp(self):
  self.service=copy.deepcopy(app.config['services'][0]);self.identity=app.sid(self.service)
  for table in ['observations','incidents','state','evaluator_state']:app.DB.execute('DELETE FROM '+table)
  app.DB.commit();app.failure_streak.clear();app.recovery_streak.clear()
 def test_debounce_dedup_unknown_and_recovery(self):
  now=time.time();app.observe(self.identity,'one','health',True,'ok',now-20)
  app.observe(self.identity,'one','health',False,'health_failed',now-10);app.transition(self.service,'DOWN','health_failed',now-10)
  self.assertEqual(app.DB.execute('SELECT count(*) FROM incidents').fetchone()[0],0)
  app.transition(self.service,'DOWN','health_failed',now-5);app.transition(self.service,'DOWN','health_failed',now)
  self.assertEqual(app.DB.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
  app.transition(self.service,'UNKNOWN','pipeline',now+1);self.assertIsNone(app.DB.execute('SELECT recovered FROM incidents').fetchone()[0])
  app.transition(self.service,'UP','ok',now+2);self.assertIsNone(app.DB.execute('SELECT recovered FROM incidents').fetchone()[0])
  app.transition(self.service,'UP','ok',now+3);self.assertEqual(app.DB.execute('SELECT recovered FROM incidents').fetchone()[0],now+3)
 def test_no_observation_not_proven_compliance(self):
  r=app.objective_report(self.service);self.assertIsNone(r['observedSampledAvailability']);self.assertEqual(r['compliance'],'INSUFFICIENT_DATA')
 def test_unknown_is_separate_from_failed(self):
  now=time.time();app.observe(self.identity,'one','health',True,'ok',now-2);app.observe(self.identity,'one','health',False,'failed',now-1);app.observe(self.identity,'one','health',None,'unknown',now)
  r=app.objective_report(self.service);self.assertEqual(r['known'],2);self.assertEqual(r['failing'],1);self.assertEqual(r['observedSampledAvailability'],.5);self.assertGreaterEqual(r['unknown'],1)
 def test_role_scope(self):
  class Request:
   def __init__(self,token):self.headers={'authorization':'Bearer '+token}
  read=(ROOT/'secrets/dashboard-read').read_text().strip();r=Request(read)
  app.authorize(r,read=True)
  with self.assertRaises(app.HTTPException):app.authorize(r,admin=True)
  resource={**{k:self.service[k] for k in ['project','service','environment']},'instance':self.service['instances'][0]['id']}
  token=(ROOT/'secrets'/self.service['metrics']['tokenRef']).read_text().strip();app.authorize(Request(token),resource)
  resource['service']='spoof'
  with self.assertRaises(app.HTTPException):app.authorize(Request(token),resource)
 def test_redaction_recursive(self):
  value=app.redact({'password':'sensitive','child':{'authorization':'Bearer secret','url':'https://x/?token=sensitive'}});self.assertNotIn('sensitive',json.dumps(value))
