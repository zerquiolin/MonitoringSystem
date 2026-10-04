import unittest,time,json,tempfile,hashlib
from pathlib import Path
from test_domain import app
class Credentials(unittest.TestCase):
 def test_expiry_overlap_and_revocation(self):
  now=time.time();token='unit-example-not-credential';digest=hashlib.sha256(token.encode()).hexdigest()
  original=app.SECRETS
  with tempfile.TemporaryDirectory() as d:
   app.SECRETS=Path(d)
   try:
    f=Path(d)/'scope';f.write_text(json.dumps({'tokens':[{'sha256':digest,'expiresAt':now-1}]}));self.assertFalse(app.matches(token,'scope'))
    f.write_text(json.dumps({'tokens':[{'sha256':digest,'notBefore':now+60,'expiresAt':now+120}]}));self.assertFalse(app.matches(token,'scope'))
    f.write_text(json.dumps({'tokens':[{'sha256':digest,'expiresAt':now+120}]}));self.assertTrue(app.matches(token,'scope'))
    app.DB.execute('INSERT INTO token_revocations VALUES(?,?)',(digest,now));self.assertFalse(app.matches(token,'scope'))
   finally:app.SECRETS=original;app.DB.execute('DELETE FROM token_revocations WHERE digest=?',(digest,))
