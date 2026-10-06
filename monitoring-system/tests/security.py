import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.prefix!=str(ROOT/'.venv'):os.execv(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),__file__])
import json,time,urllib.request,urllib.error,gzip
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
credentials=(ROOT/'secrets/demo-orders').read_text().strip()
def send(path,payload,content='application/json',token=credentials,encoding=None):
 headers={'Content-Type':content}
 if token:headers['Authorization']='Bearer '+token
 if encoding:headers['Content-Encoding']=encoding
 req=urllib.request.Request('http://localhost:8080'+path,headers=headers,method='POST',data=payload)
 try:
  with urllib.request.urlopen(req,timeout=10) as r:return r.status
 except urllib.error.HTTPError as e:return e.code
msg=ExportMetricsServiceRequest();r=msg.resource_metrics.add()
for k,v in {'project':'commerce','service':'orders-api','environment':'demo','instance':'orders-api-1'}.items():a=r.resource.attributes.add();a.key=k;a.value.string_value=v
scope=r.scope_metrics.add();scope.scope.name='security-fixture';metric=scope.metrics.add();metric.name='app_business_security_fixture';metric.sum.aggregation_temporality=2;metric.sum.is_monotonic=True;p=metric.sum.data_points.add();p.as_int=1;p.time_unix_nano=int(time.time()*1e9);p.start_time_unix_nano=p.time_unix_nano-1000000000
assert send('/v1/metrics',msg.SerializeToString(),'application/x-protobuf')==200
assert send('/v1/metrics',gzip.compress(json.dumps(MessageToDict(msg)).encode()),encoding='gzip')==200
for a in r.resource.attributes:
 if a.key=='service':a.value.string_value='catalog-api'
assert send('/v1/metrics',msg.SerializeToString(),'application/x-protobuf')==403
assert send('/v1/metrics',b'{bad json')==400
assert send('/v1/metrics',gzip.compress(b'a'*3_000_000),encoding='gzip')==413
assert send('/v1/metrics',b'a'*2_100_000)==413
assert send('/v1/metrics',b'{}',token=None)==401
report={'binaryAuthorized':'PASS','gzipAuthorized':'PASS','binaryIdentitySpoof':'REJECTED','malformedPayload':'REJECTED','compressionBomb':'REJECTED','oversizedBody':'REJECTED','anonymous':'REJECTED'}
(ROOT/'artifacts/security.json').write_text(json.dumps(report,indent=2));print('Binary/JSON gzip authorization and ingress limit assertions passed')
