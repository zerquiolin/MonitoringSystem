import unittest,sys,json,copy,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'docker/control'))
from configuration import load,sid,render,validate_target
import yaml
class ConfigurationTests(unittest.TestCase):
 def setUp(self):self.c=load(ROOT/'config/inventory.yaml',ROOT/'secrets')
 def validate(self,c):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'inventory.yaml';p.write_text(yaml.safe_dump(c));return load(p)
 def test_unknown_keys(self):
  self.c['surprise']=True
  with self.assertRaises(Exception):self.validate(self.c)
 def test_duplicate_instances(self):
  self.c['services'][0]['instances']*=2
  with self.assertRaises(ValueError):self.validate(self.c)
 def test_impossible_quorum(self):
  self.c['services'][0]['quorum']=5
  with self.assertRaises(ValueError):self.validate(self.c)
 def test_cycle(self):
  self.c['services'][1]['dependencies']=['orders-api']
  with self.assertRaises(ValueError):self.validate(self.c)
 def test_stable_ids(self):
  a={s['service']:sid(s) for s in self.c['services']};self.c['services'].reverse();self.assertEqual(a,{s['service']:sid(s) for s in self.c['services']})
 def test_metadata_and_unapproved_targets(self):
  for url in ['http://169.254.169.254/latest','http://localhost:9090','file:///etc/passwd','http://user:password@host.docker.internal']:
   with self.assertRaises(ValueError):validate_target(url,self.c,False)
 def test_reorder_generates_same_probes(self):
  with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
   render(self.c,a,ROOT/'secrets');self.c['services'].reverse();render(self.c,b,ROOT/'secrets');self.assertEqual((Path(a)/'prometheus.yaml').read_bytes(),(Path(b)/'prometheus.yaml').read_bytes())
if __name__=='__main__':unittest.main()
