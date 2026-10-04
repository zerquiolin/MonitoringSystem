"""OTLP JSON specifies hex trace/span IDs; protobuf JSON uses base64 bytes."""
import base64,re

def ids(payload,encode):
 for resource in payload.get('resourceSpans',[]):
  for scope in resource.get('scopeSpans',[]):
   for span in scope.get('spans',[]):
    for record in [span,*span.get('links',[])]:
     for key,length in [('traceId',16),('spanId',8),('parentSpanId',8)]:
      if not record.get(key):continue
      value=record[key]
      if encode:
       if not isinstance(value,str) or not re.fullmatch('[a-fA-F0-9]{'+str(length*2)+'}',value):raise ValueError('Invalid OTLP identifier')
       record[key]=base64.b64encode(bytes.fromhex(value)).decode()
      else:
       raw=base64.b64decode(value,validate=True)
       if len(raw)!=length:raise ValueError('Invalid protobuf identifier length')
       record[key]=raw.hex()
 return payload
