import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'docker/control'))
from status import aggregate,project_state
class Status(unittest.TestCase):
 def test_known_quorum_with_unknown_optional_replica(self):self.assertEqual(aggregate([({},True),({},None)],1),('DEGRADED',1))
 def test_unknown_can_change_quorum(self):self.assertEqual(aggregate([({},False),({},None)],1),('UNKNOWN',0))
 def test_proven_quorum_failure_even_with_unknown(self):self.assertEqual(aggregate([({},False),({},False),({},None)],2),('DOWN',0))
 def test_required_instance_failure(self):self.assertEqual(aggregate([({},True),({'required':True},False)],1),('DOWN',1))
 def test_draining_does_not_count_as_failed(self):self.assertEqual(aggregate([({},True),({'draining':True},False)],1),('UP',1))
 def test_critical_failure_is_project_failure(self):self.assertEqual(project_state(['DOWN','UNKNOWN']),'DOWN')
