import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'docker/control'))
from otlp import ids
class OtlpIdentifiers(unittest.TestCase):
 def test_json_and_binary_roundtrip(self):
  p={'resourceSpans':[{'scopeSpans':[{'spans':[{'traceId':'11'*16,'spanId':'22'*8,'parentSpanId':'33'*8,'links':[{'traceId':'44'*16,'spanId':'55'*8}]}]}]}]}
  self.assertEqual(ids(ids(copy.deepcopy(p),True),False),p)
 def test_invalid_length_rejected(self):
  with self.assertRaises(ValueError):ids({'resourceSpans':[{'scopeSpans':[{'spans':[{'traceId':'00'}]}]}]},True)
