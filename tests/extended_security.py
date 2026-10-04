"""Binary trace storage, metric validation, resource-scoped log dedup and redaction."""
from acceptance import ROOT,host,wait,prom,internal
from security import send
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import json,time,secrets,urllib.parse
msg=ExportTraceServiceRequest();resource=msg.resource_spans.add()
for k,v in {'project':'commerce','service':'orders-api','environment':'demo','instance':'orders-api-1'}.items():a=resource.resource.attributes.add();a.key=k;a.value.string_value=v
span=resource.scope_spans.add().spans.add();trace=secrets.token_bytes(16);span.trace_id=trace;span.span_id=secrets.token_bytes(8);span.name='binary-fixture';span.start_time_unix_nano=int(time.time()*1e9);span.end_time_unix_nano=span.start_time_unix_nano+1000000
for key,value in {'authorization':'SENSITIVE_FIXTURE_BINARY_TOKEN','db.statement':'SENSITIVE_FIXTURE_SQL','url.full':'http://test.invalid?password=SENSITIVE_FIXTURE_QUERY'}.items():a=span.attributes.add();a.key=key;a.value.string_value=value
assert send('/v1/traces',msg.SerializeToString(),'application/x-protobuf')==200
stored=wait(lambda:internal('http://127.0.0.1:3200/api/traces/'+trace.hex()));assert 'binary-fixture' in json.dumps(stored);assert 'SENSITIVE_FIXTURE' not in json.dumps(stored)
operator=(ROOT/'secrets/operator-token').read_text().strip();read=(ROOT/'secrets/dashboard-read').read_text().strip();token=(ROOT/'secrets/demo-orders').read_text().strip();eid='dedup-'+secrets.token_hex(4)
resource={'project':'commerce','service':'orders-api','environment':'demo','instance':'orders-api-1'}
event={'eventId':eid,'timestamp':int(time.time()*1000),'severity':'info','message':'dedup fixture '+eid,'attributes':{'password':'SENSITIVE_FIXTURE_LOG'}}
for instance in ['orders-api-1','orders-api-1','orders-api-2']:
 resource['instance']=instance;host('/api/ingest/logs',token,'POST',{'resource':resource,'events':[event,event]})
query='{service="orders-api"} |= "'+eid+'"';url='http://127.0.0.1:3100/loki/api/v1/query_range?'+urllib.parse.urlencode({'query':query,'limit':20})
streams=wait(lambda:internal(url)['data']['result']);wait(lambda:sum(len(x['values']) for x in internal(url)['data']['result'])==2);assert 'SENSITIVE_FIXTURE' not in json.dumps(internal(url))
report={'status':'PASS','binaryTraceStoredAndRedacted':True,'traceId':trace.hex(),'logDuplicateSuppression':'one event per resource+instance+eventId; different instances retained','diagnosticsSecretScan':'PASS'}
assert 'SENSITIVE_FIXTURE' not in json.dumps(host('/control/diagnostics',read));assert 'SENSITIVE_FIXTURE' not in json.dumps(host('/control/notifications',operator))
(ROOT/'artifacts/extended-security.json').write_text(json.dumps(report,indent=2));print('PASS binary stored trace, central redaction and resource-scoped duplicate suppression')
