import sqlite3,unittest,sys,json,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'docker/control'))
from reliability import initialize,record,duration_report,eligible_ranges
class Reliability(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.executescript('CREATE TABLE migrations(version INTEGER PRIMARY KEY,applied REAL); CREATE TABLE incidents(id TEXT,service_id TEXT,opened REAL,recovered REAL,acknowledged REAL);')
  initialize(self.db);self.s={'project':'p','service':'s','environment':'test','objectives':{'probeAvailability':{'target':.9}}}
 def test_elapsed_duration_gap_and_quorum(self):
  for t,state in [(100,'UP'),(110,'DOWN'),(120,'DEGRADED'),(130,'UP')]:record(self.db,'s',state,'',t,10)
  r=duration_report(self.db,self.s,'s',90,150)
  self.assertEqual((r['uptimeSeconds'],r['downtimeSeconds'],r['unknownSeconds'],r['degradedSeconds']),(30,10,20,10))
  self.assertAlmostEqual(r['availability'],.75);self.assertAlmostEqual(r['coverage'],2/3)
  self.assertEqual(r['compliance'],'INSUFFICIENT_DATA')
 def test_maintenance_partition_no_double_subtraction(self):
  self.s['maintenance']=[{'start':'1970-01-01T00:01:45Z','end':'1970-01-01T00:01:55Z','excludeFromSlo':True},{'start':'1970-01-01T00:01:50Z','end':'1970-01-01T00:02:00Z','excludeFromSlo':True}]
  record(self.db,'s','DOWN','',100,30);r=duration_report(self.db,self.s,'s',100,130)
  self.assertEqual(r['maintenanceSeconds'],15);self.assertEqual(r['downtimeSeconds'],15);self.assertEqual(r['eligibleSeconds'],15);self.assertEqual(r['coverage'],1)
 def test_detection_recovery_acknowledgment(self):
  self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?)',('i','s',100,130,105));self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?)',('j','s',110,None,None))
  r=duration_report(self.db,self.s,'s',90,140)
  self.assertEqual(r['mttrSeconds'],30);self.assertEqual(r['meanAcknowledgmentSeconds'],5);self.assertEqual(r['activeIncidents'],1)
 def test_restart_never_extends_stale_success(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.sqlite';db=sqlite3.connect(p);db.executescript('CREATE TABLE migrations(version INTEGER PRIMARY KEY,applied REAL);CREATE TABLE incidents(id TEXT,service_id TEXT,opened REAL,recovered REAL,acknowledged REAL);');initialize(db);record(db,'s','UP','',100,10);db.commit();db.close();db=sqlite3.connect(p);db.row_factory=sqlite3.Row
   r=duration_report(db,self.s,'s',100,140);self.assertEqual(r['uptimeSeconds'],10);self.assertEqual(r['unknownSeconds'],30)
 def test_no_evidence_is_not_uptime(self):
  r=duration_report(self.db,self.s,'s',100,200);self.assertIsNone(r['availability']);self.assertEqual(r['unknownSeconds'],100)

 def test_request_maintenance_ranges_are_disjoint(self):
  self.s['maintenance']=[{'start':'1970-01-01T00:01:45Z','end':'1970-01-01T00:01:55Z'},{'start':'1970-01-01T00:01:50Z','end':'1970-01-01T00:02:00Z'}]
  self.assertEqual(eligible_ranges(self.s,100,130),[(100,105),(120,130)])
