import asyncio,contextlib,csv,io,gzip,hashlib,hmac,json,os,re,sqlite3,time,zlib,uuid
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import httpx,jsonschema
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import Response,JSONResponse
from prometheus_client import Counter,Gauge,generate_latest,CONTENT_TYPE_LATEST
from google.protobuf.json_format import MessageToDict,ParseDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from croniter import croniter
from configuration import ROOT,load,sid,validate_target
from reliability import eligible_ranges,initialize,record,duration_report,finite,backfill
from probes import assertion as http_assertion
from otlp import ids as otlp_ids
from status import aggregate,project_state
from schedules import latest_due
DATA=Path(os.getenv('MONITORING_DATA','/data/control'));DATA.mkdir(parents=True,exist_ok=True)
SECRETS=Path(os.getenv('MONITORING_SECRETS','/run/secrets'))
CONFIG=os.getenv('MONITORING_CONFIG','/config/inventory.yaml')
DB=sqlite3.connect(DATA/'control.sqlite',check_same_thread=False);DB.row_factory=sqlite3.Row;DB.execute('PRAGMA journal_mode=WAL');DB.execute('PRAGMA busy_timeout=5000')
DB.executescript('''
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied REAL); INSERT OR IGNORE INTO migrations VALUES(1,0);
CREATE TABLE IF NOT EXISTS observations(check_id TEXT,service_id TEXT,instance TEXT,kind TEXT,observed REAL,received REAL,success INTEGER,reason TEXT,PRIMARY KEY(check_id,observed));
CREATE INDEX IF NOT EXISTS observation_time ON observations(service_id,observed);
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,service_id TEXT,project TEXT,service TEXT,environment TEXT,reason TEXT,opened REAL,first_failure REAL,previous_success REAL,last_failure REAL,recovered REAL,acknowledged REAL,policy TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open ON incidents(service_id) WHERE recovered IS NULL;
CREATE TABLE IF NOT EXISTS heartbeats(service_id TEXT,instance TEXT,boot_id TEXT,sequence INTEGER,received REAL,progress INTEGER,active_jobs INTEGER,ready INTEGER,progress_time REAL,PRIMARY KEY(service_id,instance));
CREATE TABLE IF NOT EXISTS retired_boots(service_id TEXT,instance TEXT,boot_id TEXT,PRIMARY KEY(service_id,instance,boot_id));
CREATE TABLE IF NOT EXISTS job_runs(run_id TEXT PRIMARY KEY,service_id TEXT,instance TEXT,state TEXT,started REAL,finished REAL,name TEXT);
CREATE TABLE IF NOT EXISTS jobs(service_id TEXT,instance TEXT,state TEXT,received REAL,name TEXT,PRIMARY KEY(service_id,instance));
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,received REAL,status TEXT,body TEXT);
CREATE TABLE IF NOT EXISTS audit(received REAL,action TEXT,identity TEXT);
CREATE TABLE IF NOT EXISTS metric_dimensions(service_id TEXT,metric TEXT,dimension TEXT,PRIMARY KEY(service_id,metric,dimension));
CREATE TABLE IF NOT EXISTS log_ids(id TEXT PRIMARY KEY,received REAL);
CREATE TABLE IF NOT EXISTS evaluator_state(service_id TEXT PRIMARY KEY,failures INTEGER,recoveries INTEGER);
CREATE TABLE IF NOT EXISTS state(service_id TEXT PRIMARY KEY,value TEXT,reason TEXT,updated REAL);
CREATE TABLE IF NOT EXISTS config_state(checksum TEXT PRIMARY KEY,applied REAL,inventory TEXT);
''');DB.commit();initialize(DB)
columns={r[1] for r in DB.execute('PRAGMA table_info(incidents)')}
for name,kind in [('closed','REAL'),('resolution_kind','TEXT')]:
 if name not in columns:DB.execute('ALTER TABLE incidents ADD COLUMN '+name+' '+kind)
DB.execute('DROP INDEX IF EXISTS one_open');DB.execute('CREATE UNIQUE INDEX one_open ON incidents(service_id) WHERE recovered IS NULL AND closed IS NULL')
DB.execute('CREATE TABLE IF NOT EXISTS heartbeat_source(service_id TEXT,instance TEXT,source_time REAL,received REAL,PRIMARY KEY(service_id,instance))')
DB.execute('CREATE TABLE IF NOT EXISTS job_context(run_id TEXT PRIMARY KEY,boot_id TEXT,source_started REAL,source_finished REAL)')
DB.execute('CREATE TABLE IF NOT EXISTS evaluator_cursors(service_id TEXT PRIMARY KEY,evidence TEXT)')
config=load(CONFIG,SECRETS);config['services']=[s for s in config['services'] if s.get('enabled',True)];expected={sid(s) for s in config['services']};
for row in DB.execute('SELECT id,service_id FROM incidents WHERE recovered IS NULL AND closed IS NULL').fetchall():
 if row['service_id'] not in expected:
  DB.execute('UPDATE incidents SET closed=?,resolution_kind=? WHERE id=?',(time.time(),'retired',row['id']));DB.execute('INSERT OR IGNORE INTO incident_annotations VALUES(?,?,?,?)',('retired:'+row['id'],row['id'],time.time(),'Service retired from expected inventory; recovery was not observed.'))
DB.commit();started=time.time();pipeline=True;states={};freshness={};failure_streak={r['service_id']:r['failures'] for r in DB.execute('SELECT * FROM evaluator_state')};recovery_streak={r['service_id']:r['recoveries'] for r in DB.execute('SELECT * FROM evaluator_state')};client=None;request_reports={};objective_rows=[];last_maintenance_sync=0;last_report_update=0;last_evidence={r['service_id']:json.loads(r['evidence']) for r in DB.execute('SELECT * FROM evaluator_cursors')};instance_freshness={}
backfill(DB,config,sid,time.time())
rejections=Counter('monitoring_ingest_rejected_total','Rejected ingress',['signal'])
partial_rejections=Counter('monitoring_ingest_partial_rejections_total','OTLP upstream partial rejected signal items',['signal'])
accepted=Counter('monitoring_ingest_accepted_total','Accepted ingress',['signal'])
pipeline_g=Gauge('monitoring_pipeline_up','Required backend readiness')
evaluator_g=Gauge('monitoring_evaluator_last_success_seconds','Last completed evaluator iteration')
disk_g=Gauge('monitoring_disk_free_bytes','Monitoring data volume free bytes')
SENSITIVE=re.compile(r'authorization|cookie|password|secret|token|payment|credit.?card|connection.?string|email',re.I)
def redact(v,depth=0):
 if depth>5:return '[depth limit]'
 if isinstance(v,dict):return {k:'[REDACTED]' if SENSITIVE.search(k) else redact(x,depth+1) for k,x in list(v.items())[:32]}
 if isinstance(v,list):return [redact(x,depth+1) for x in v[:256]]
 if isinstance(v,str):return re.sub(r'://[^/@\s]+:[^/@\s]+@','://[REDACTED]@',re.sub(r'(Bearer\s+)\S+',r'\1[REDACTED]',re.sub(r'([?&](?:token|password|key|secret)=)[^&\s]*',r'\1[REDACTED]',v,flags=re.I),flags=re.I))[:4096]
 return v

def token(request):
 a=request.headers.get('authorization','')
 if not a.startswith('Bearer '):raise HTTPException(401,'Bearer credential required')
 return a[7:]
def matches(t,ref):
 try:expected=(SECRETS/ref).read_text().strip()
 except OSError:return False
 digest=hashlib.sha256(t.encode()).hexdigest()
 if DB.execute('SELECT 1 FROM token_revocations WHERE digest=?',(digest,)).fetchone():return False
 if expected.startswith('{'):
  try:
   records=json.loads(expected)['tokens'];now=time.time()
   return any(hmac.compare_digest(digest,r['sha256']) and r.get('notBefore',0)<=now<r['expiresAt'] and not r.get('revoked',False) for r in records)
  except (ValueError,KeyError,TypeError):return False
 return any(hmac.compare_digest(digest,hashlib.sha256(x.encode()).hexdigest()) for x in expected.splitlines())
def authorize(request,resource=None,read=False,admin=False):
 t=token(request)
 if admin:
  if not matches(t,'operator-token'):raise HTTPException(403,'Operator role required')
  return None
 if read and (matches(t,'dashboard-read') or matches(t,'operator-token')):return None
 for s in config['services']:
  if matches(t,s['metrics']['tokenRef']):
   signal=request.url.path.rsplit('/',1)[-1] if hasattr(request,'url') else None
   if signal and signal not in s['metrics'].get('signals',['metrics','traces','logs','heartbeat','job']):raise HTTPException(403,'Signal not authorized')
   if resource and all(resource.get(k)==s[k] for k in ('project','service','environment')) and resource.get('instance') in {i['id'] for i in s['instances']}:return s
 raise HTTPException(403,'Credential not authorized for resource or role')

async def body(request):
 if request.url.path.startswith(('/v1/','/api/ingest/')):
  fs=os.statvfs(DATA)
  if fs.f_bavail*fs.f_frsize<int(os.getenv('MONITORING_MIN_FREE_BYTES',67108864)):raise HTTPException(503,'Monitoring storage admission paused; retry with bounded backoff')
 if request.headers.get('content-length') and int(request.headers['content-length'])>2*1024*1024:raise HTTPException(413,'Batch too large')
 data=bytearray()
 async for chunk in request.stream():
  data.extend(chunk)
  if len(data)>2*1024*1024:raise HTTPException(413,'Batch too large')
 encoding=request.headers.get('content-encoding','identity')
 if encoding=='gzip':
  try:
   decoder=zlib.decompressobj(16+zlib.MAX_WBITS);data=decoder.decompress(bytes(data),2*1024*1024+1)
   if len(data)>2*1024*1024 or decoder.unconsumed_tail or not decoder.eof:raise ValueError()
  except Exception:raise HTTPException(413,'Invalid or oversized compressed batch')
 elif encoding!='identity':raise HTTPException(415,'Unsupported encoding')
 return bytes(data)
def validate(payload,contract):
 try:jsonschema.validate(payload,json.loads((ROOT/'contracts'/contract).read_text()))
 except Exception:raise HTTPException(400,'Payload fails schema validation')

@contextlib.asynccontextmanager
async def lifespan(app):
 global client
 client=httpx.AsyncClient(timeout=5,limits=httpx.Limits(max_connections=32,max_keepalive_connections=16),trust_env=False)
 checksum=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest();DB.execute('INSERT OR IGNORE INTO config_state VALUES(?,?,?)',(checksum,time.time(),json.dumps(config)));DB.commit()
 task=asyncio.create_task(evaluator())
 yield
 task.cancel()
 with contextlib.suppress(asyncio.CancelledError):await task
 await client.aclose();DB.execute('PRAGMA wal_checkpoint(TRUNCATE)');DB.close()
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
@app.exception_handler(HTTPException)
async def reject(request,exc):
 if request.url.path.startswith(('/v1/','/api/ingest/')):
  rejections.labels('ingress').inc();print('Ingress rejected: '+str(exc.status_code)+' '+str(exc.detail),flush=True)
 return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
@app.get('/health')
async def health():return {'status':'ok'}
@app.get('/ready')
async def ready():return JSONResponse({'status':'ok' if pipeline and time.time()-evaluator_g._value.get()<15 else 'unready'},status_code=200 if pipeline and time.time()-evaluator_g._value.get()<15 else 503)
@app.get('/metrics')
async def metrics():
 from prometheus_client import CollectorRegistry
 from prometheus_client.core import GaugeMetricFamily
 registry=CollectorRegistry()
 class Domain:
  def collect(self):
   expected=GaugeMetricFamily('monitoring_expected_instance','Expected inventory',labels=['project','service','environment','instance'])
   state=GaugeMetricFamily('monitoring_service_state','Current state',labels=['project','service','environment','state'])
   fresh=GaugeMetricFamily('monitoring_telemetry_fresh','Fresh application telemetry',labels=['project','service','environment'])
   known=GaugeMetricFamily('monitoring_check_known','Known observations',labels=['project','service','environment'])
   count=GaugeMetricFamily('monitoring_check_expected','Expected observations',labels=['project','service','environment'])
   report_fields={'uptimeSeconds':'monitoring_service_uptime_seconds','downtimeSeconds':'monitoring_service_downtime_seconds','unknownSeconds':'monitoring_service_unknown_seconds','degradedSeconds':'monitoring_service_degraded_seconds','maintenanceSeconds':'monitoring_service_maintenance_seconds','availability':'monitoring_service_availability_ratio','coverage':'monitoring_service_coverage_ratio','incidentCount':'monitoring_service_incidents','activeIncidents':'monitoring_service_active_incidents','mttrSeconds':'monitoring_service_mttr_seconds','errorBudgetConsumed':'monitoring_service_error_budget_consumed_ratio'}
   reports={field:GaugeMetricFamily(name,'Rolling configured objective window; known observation durations',labels=['project','service','environment']) for field,name in report_fields.items()}
   instance_fresh=GaugeMetricFamily('monitoring_instance_telemetry_fresh','Per expected instance freshness',labels=['project','service','environment','instance'])
   check_last=GaugeMetricFamily('monitoring_check_last_observation_seconds','Latest normalized observation source time',labels=['project','service','environment','instance','check'])
   check_success=GaugeMetricFamily('monitoring_check_success','Fresh known check result; unknown is absent',labels=['project','service','environment','instance','check'])
   check_unknown=GaugeMetricFamily('monitoring_check_unknown','Missing or stale normalized check evidence',labels=['project','service','environment','instance','check'])
   replicas=GaugeMetricFamily('monitoring_service_healthy_instances','Healthy whole instances',labels=['project','service','environment'])
   quorum=GaugeMetricFamily('monitoring_service_quorum','Required minimum healthy instances',labels=['project','service','environment'])
   burn=GaugeMetricFamily('monitoring_service_burn_rate','Availability error-budget burn in known duration',labels=['project','service','environment','window'])
   for s in config['services']:
    labels=[s[k] for k in ('project','service','environment')]
    for i in s['instances']:
     expected.add_metric(labels+[i['id']],1);instance_fresh.add_metric(labels+[i['id']],int(instance_freshness.get((sid(s),i['id']),False)))
     kinds=[kind for kind,key in [('health','healthUrl'),('ready','readyUrl'),('tcp','tcpUrl'),('dns','dnsUrl')] if key in i] if s['kind'] in ('http','external') else ['worker']
     for kind in kinds:
      row=DB.execute('SELECT * FROM observations WHERE service_id=? AND instance=? AND kind=? ORDER BY observed DESC LIMIT 1',(sid(s),i['id'],kind)).fetchone();check_labels=labels+[i['id'],kind]
      known_result=bool(row and row['success'] is not None and pipeline and time.time()-row['received']<15)
      check_unknown.add_metric(check_labels,int(not known_result))
      if row:check_last.add_metric(check_labels,row['observed'])
      if known_result:check_success.add_metric(check_labels,row['success'])
    current=states.get(sid(s),{}).get('state','UNKNOWN')
    for value in ('UP','DOWN','DEGRADED','UNKNOWN','MAINTENANCE','DRAINING'):state.add_metric(labels+[value],int(value==current))
    fresh.add_metric(labels,int(freshness.get(sid(s),False)))
    r=objective_report(s);known.add_metric(labels,r['known']);count.add_metric(labels,r['expected'])
    now=time.time();window=s.get('objectives',{}).get('probeAvailability',{}).get('windowDays',30)*86400
    report=duration_report(DB,s,sid(s),now-window,now)
    for field,family in reports.items():
     if report[field] is not None:family.add_metric(labels,report[field])
    replicas.add_metric(labels,states.get(sid(s),{}).get('healthyInstances',0));quorum.add_metric(labels,s.get('quorum',1))
    for seconds,window_name in ((300,'5m'),(1800,'30m'),(3600,'1h'),(21600,'6h')):
     v=duration_report(DB,s,sid(s),now-seconds,now)
     if v['errorBudgetConsumed'] is not None and v['coverage'] is not None and v['coverage']>=.95:burn.add_metric(labels+[window_name],v['errorBudgetConsumed'])
   yield expected;yield state;yield fresh;yield known;yield count;yield replicas;yield quorum;yield burn
   yield instance_fresh;yield check_last;yield check_success;yield check_unknown
   yield from reports.values()
 registry.register(Domain());return Response(generate_latest()+generate_latest(registry),media_type=CONTENT_TYPE_LATEST)

@app.post('/v1/{signal}')
async def otlp(signal:str,request:Request):
 token(request)
 if signal not in ('metrics','traces'):raise HTTPException(404,'Unknown OTLP signal')
 raw=await body(request);binary='application/x-protobuf' in request.headers.get('content-type','')
 cls=ExportMetricsServiceRequest if signal=='metrics' else ExportTraceServiceRequest
 try:
  msg=cls();msg.ParseFromString(raw) if binary else ParseDict(otlp_ids(json.loads(raw),True) if signal=='traces' else json.loads(raw),msg)
  payload=MessageToDict(msg)
  if signal=='traces':payload=otlp_ids(payload,False)
 except Exception:raise HTTPException(400,'Malformed OTLP')
 groups=payload.get('resourceMetrics' if signal=='metrics' else 'resourceSpans',[])
 if not groups or len(groups)>64:raise HTTPException(400,'Invalid resource batch count')
 for group in groups:
  attrs={x['key']:x.get('value',{}).get('stringValue') for x in group.get('resource',{}).get('attributes',[])}
  resource={k:attrs.get(k) or attrs.get({'project':'service.namespace','service':'service.name','environment':'deployment.environment.name','instance':'service.instance.id'}[k]) for k in ('project','service','environment','instance')}
  s=authorize(request,resource)
  for k,v in resource.items():
   if attrs.get(k) and attrs[k]!=v:raise HTTPException(403,'Conflicting identity attributes')
  resource_keys={'project':'service.namespace','service':'service.name','environment':'deployment.environment.name','instance':'service.instance.id'}
  for k,std in resource_keys.items():
   if attrs.get(std) and attrs[std]!=resource[k]:raise HTTPException(403,'Conflicting standard identity')
  group['resource']={'attributes':[{'key':k,'value':{'stringValue':str(v)}} for k,v in {**resource,**{std:resource[k] for k,std in resource_keys.items()}}.items()]}
  scopes=group.get('scopeMetrics' if signal=='metrics' else 'scopeSpans',[])
  for scope in scopes:
   if signal=='metrics':
    if s['metrics']['mode']!='push':raise HTTPException(409,'Instance is configured for pull')
    for metric in scope.get('metrics',[]):
     if not re.fullmatch(r'app_[a-zA-Z0-9_]{1,100}',metric.get('name','')):raise HTTPException(400,'Metric namespace not permitted')
     for variant in ('sum','histogram','gauge','exponentialHistogram'):
      for point in metric.get(variant,{}).get('dataPoints',[]):
       if len(point.get('attributes',[]))>12:raise HTTPException(400,'Too many dimensions')
       allowed={'project','service','environment','instance','method','route','status_class','signal','kind','scope','hostId','build','collector','state'}
       for a in point.get('attributes',[]):
        key=a['key'];val=a.get('value',{}).get('stringValue','')
        if SENSITIVE.search(key) or len(val)>160 or key not in allowed and not metric['name'].startswith('app_business_'):raise HTTPException(400,'Invalid metric dimension')
        if key in resource and val!=resource[key]:raise HTTPException(403,'Metric identity spoofing')
       point.setdefault('attributes',[])
       supplied={a['key'] for a in point['attributes']}
       point['attributes'].extend({'key':k,'value':{'stringValue':v}} for k,v in resource.items() if k not in supplied)
       dimension=hashlib.sha256(json.dumps(sorted(point['attributes'],key=lambda a:a['key']),sort_keys=True).encode()).hexdigest();identity=sid(s)
       exists=DB.execute('SELECT 1 FROM metric_dimensions WHERE service_id=? AND metric=? AND dimension=?',(identity,metric['name'],dimension)).fetchone()
       if not exists:
        if DB.execute('SELECT count(*) FROM metric_dimensions WHERE service_id=? AND metric=?',(identity,metric['name'])).fetchone()[0]>=1000:raise HTTPException(429,'Metric dimension limit reached')
        if DB.execute('SELECT count(distinct metric) FROM metric_dimensions WHERE service_id=?',(identity,)).fetchone()[0]>=64:raise HTTPException(429,'Metric instrument limit reached')
        DB.execute('INSERT OR IGNORE INTO metric_dimensions VALUES(?,?,?)',(identity,metric['name'],dimension))
       if variant=='histogram':
        bounds=point.get('explicitBounds',[]);counts=point.get('bucketCounts',[])
        if len(bounds)>32 or any(finite(v) is None for v in bounds) or any(a>=b for a,b in zip(bounds,bounds[1:])):raise HTTPException(400,'Invalid histogram bounds')
        if len(counts)!=len(bounds)+1 or any(int(v)<0 for v in counts) or sum(int(v) for v in counts)!=int(point.get('count',0)):raise HTTPException(400,'Invalid histogram counts')
       if 'asDouble' in point and finite(point['asDouble']) is None:raise HTTPException(400,'Non-finite measurement')
   else:
    for span in scope.get('spans',[]):
     for a in span.get('attributes',[]):
      if SENSITIVE.search(a['key']) or a['key'] in ('http.url','url.full','db.statement','url.query') :a['value']={'stringValue':'[REDACTED]'}
     for event in span.get('events',[]):
      for a in event.get('attributes',[]):
       if 'stringValue' in a.get('value',{}):a['value']['stringValue']=redact(a['value']['stringValue'])
 response=await client.post('http://127.0.0.1:4318/v1/'+signal,json=payload)
 if response.status_code>=400:raise HTTPException(response.status_code,'Collector rejected telemetry')
 try:
  partial=response.json().get('partialSuccess',{});rejected=int(partial.get('rejectedDataPoints' if signal=='metrics' else 'rejectedSpans',0))
  if rejected>0:partial_rejections.labels(signal).inc(rejected)
 except (ValueError,TypeError):pass
 DB.commit();accepted.labels(signal).inc()
 return Response(response.content,status_code=response.status_code,media_type=response.headers.get('content-type','application/json'))

@app.post('/api/ingest/logs')
async def logs(request:Request):
 try:p=json.loads(await body(request))
 except (ValueError,TypeError):raise HTTPException(400,'Invalid JSON')
 validate(p,'log-batch.schema.json');service_scope=authorize(request,p['resource']);streams=[];ids=[]
 for event in p['events']:
  dedup=sid(service_scope)+':'+p['resource']['instance']+':'+event['eventId']
  if dedup in ids or DB.execute('SELECT 1 FROM log_ids WHERE id=?',(dedup,)).fetchone():continue
  # Explicit keys preserve IDs while recursive user attributes are redacted.
  event['attributes']=redact(event['attributes']);event['message']=redact(event['message'])
  streams.append({'stream':{k:p['resource'][k] for k in ('project','service','environment')},'values':[[str(event['timestamp']*1000000),json.dumps({**event,'instance':p['resource']['instance']},separators=(',',':'))]]});ids.append(dedup)
 if streams:
  r=await client.post('http://127.0.0.1:3500/loki/api/v1/push',json={'streams':streams})
  if r.status_code not in (200,204):raise HTTPException(503,'Log collector unavailable')
  DB.executemany('INSERT OR IGNORE INTO log_ids VALUES(?,?)',[(i,time.time()) for i in ids]);DB.commit()
 accepted.labels('logs').inc(len(ids));return {'accepted':len(ids),'delivery':'collector accepted, best effort'}
@app.post('/api/ingest/heartbeat')
async def heartbeat(request:Request):
 try:p=json.loads(await body(request))
 except (ValueError,TypeError):raise HTTPException(400,'Invalid JSON')
 validate(p,'heartbeat.schema.json');s=authorize(request,p['resource']);now=time.time();identity=sid(s);instance=p['resource']['instance']
 old=DB.execute('SELECT * FROM heartbeats WHERE service_id=? AND instance=?',(identity,instance)).fetchone()
 if abs(now-p['timestamp'])>120:raise HTTPException(409,'Heartbeat clock skew or stale event')
 if old and old['boot_id']==p['bootId'] and p['sequence']<=old['sequence']:raise HTTPException(409,'Replayed heartbeat')
 if DB.execute('SELECT 1 FROM retired_boots WHERE service_id=? AND instance=? AND boot_id=?',(identity,instance,p['bootId'])).fetchone():raise HTTPException(409,'Retired boot cannot resume')
 if old and old['boot_id']!=p['bootId'] and p['sequence']!=1:raise HTTPException(409,'New boot must start at sequence one')
 if old and old['boot_id']!=p['bootId']:DB.execute('INSERT OR IGNORE INTO retired_boots VALUES(?,?,?)',(identity,instance,old['boot_id']))
 DB.execute('INSERT OR REPLACE INTO heartbeat_source VALUES(?,?,?,?)',(identity,instance,p['timestamp'],now))
 if old and old['boot_id']!=p['bootId']:
  DB.execute('UPDATE job_runs SET state=\'interrupted\',finished=? WHERE service_id=? AND instance=? AND state=\'started\' AND run_id IN (SELECT run_id FROM job_context WHERE boot_id=?)',(now,identity,instance,old['boot_id']))
 progress_time=now if not old or old['progress']!=p['progress'] else old['progress_time']
 DB.execute('INSERT OR REPLACE INTO heartbeats VALUES(?,?,?,?,?,?,?,?,?)',(identity,instance,p['bootId'],p['sequence'],now,p['progress'],p['activeJobs'],int(p['ready']),progress_time));DB.commit();accepted.labels('heartbeat').inc();return {'accepted':True}
@app.post('/api/ingest/job')
async def job(request:Request):
 try:p=json.loads(await body(request))
 except (ValueError,TypeError):raise HTTPException(400,'Invalid JSON')
 s=authorize(request,p.get('resource',{}))
 if set(p)-{'resource','state','name','runId','bootId','timestamp'} or p.get('state') not in ('started','completed','failed') or len(p.get('name',''))>64:raise HTTPException(400,'Invalid job event')
 identity=sid(s);instance=p['resource']['instance'];now=time.time();run=p.get('runId')
 if finite(p.get('timestamp')) is None or abs(now-p['timestamp'])>120 or not isinstance(p.get('bootId'),str) or len(p['bootId'])>64:raise HTTPException(409,'Invalid job source clock or boot identity')
 if DB.execute('SELECT 1 FROM retired_boots WHERE service_id=? AND instance=? AND boot_id=?',(identity,instance,p['bootId'])).fetchone():raise HTTPException(409,'Retired job boot')
 if not isinstance(run,str) or len(run)>64:raise HTTPException(400,'Job runId required')
 if p['state']=='started':
  prior=DB.execute('SELECT * FROM job_runs WHERE run_id=?',(run,)).fetchone()
  if prior:
   if prior['service_id']!=identity or prior['instance']!=instance:raise HTTPException(403,'Run belongs to another resource')
   return {'accepted':True,'duplicate':True}
  DB.execute('UPDATE job_runs SET state=\'interrupted\',finished=? WHERE service_id=? AND instance=? AND state=\'started\' AND started<?',(now,identity,instance,now-s.get('jobs',{}).get('maximumRunningSeconds',300)))
  existing=DB.execute('SELECT count(*) FROM job_runs WHERE service_id=? AND instance=? AND state=\'started\'',(identity,instance)).fetchone()[0]
  if existing>=s.get('jobs',{}).get('allowedOverlap',1):raise HTTPException(409,'Job overlap limit')
  DB.execute('INSERT OR IGNORE INTO job_runs VALUES(?,?,?,?,?,?,?)',(run,identity,instance,'started',now,None,p.get('name','job')))
  DB.execute('INSERT OR IGNORE INTO job_context VALUES(?,?,?,?)',(run,p['bootId'],p['timestamp'],None))
 else:
  prior=DB.execute('SELECT * FROM job_runs WHERE run_id=? AND service_id=? AND instance=?',(run,identity,instance)).fetchone()
  if not prior:raise HTTPException(409,'Job start event required')
  context=DB.execute('SELECT boot_id FROM job_context WHERE run_id=?',(run,)).fetchone()
  if context and context['boot_id']!=p['bootId']:raise HTTPException(403,'Job boot identity mismatch')
  if prior['state']!='started':
   if prior['state']==p['state']:return {'accepted':True,'duplicate':True}
   raise HTTPException(409,'Job already terminal')
  DB.execute('UPDATE job_runs SET state=?,finished=? WHERE run_id=?',(p['state'],now,run));DB.execute('UPDATE job_context SET source_finished=? WHERE run_id=?',(p['timestamp'],run))
 DB.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',(identity,instance,p['state'],now,p.get('name','job')));DB.commit();return {'accepted':True}
@app.post('/api/notifications')
async def notification(request:Request):
 authorize(request,admin=True);p=redact(json.loads(await body(request)));DB.execute('INSERT INTO notifications VALUES(?,?,?,?)',(str(uuid.uuid4()),time.time(),p.get('status','test'),json.dumps(p)));DB.commit();return {'accepted':True}
@app.post('/api/tokens/revoke')
async def revoke(request:Request):
 authorize(request,admin=True);p=json.loads(await body(request));digest=p.get('sha256','')
 if not re.fullmatch('[a-f0-9]{64}',digest):raise HTTPException(400,'Token digest required')
 DB.execute('INSERT OR IGNORE INTO token_revocations VALUES(?,?)',(digest,time.time()));DB.execute('INSERT INTO audit VALUES(?,?,?)',(time.time(),'token_revoked',digest));DB.commit();return {'accepted':True}
@app.post('/api/incidents/{incident}/annotations')
async def annotate(incident:str,request:Request):
 authorize(request,admin=True);p=json.loads(await body(request))
 if not DB.execute('SELECT 1 FROM incidents WHERE id=?',(incident,)).fetchone():raise HTTPException(404,'Incident not found')
 note=redact(p.get('note',''))
 if not isinstance(note,str) or not note:raise HTTPException(400,'Note required')
 DB.execute('INSERT INTO incident_annotations VALUES(?,?,?,?)',(str(uuid.uuid4()),incident,time.time(),note));DB.commit();return {'accepted':True}
@app.post('/api/incidents/{incident}/acknowledge')
async def acknowledge(incident:str,request:Request):
 authorize(request,admin=True)
 if not DB.execute('SELECT 1 FROM incidents WHERE id=?',(incident,)).fetchone():raise HTTPException(404,'Incident not found')
 DB.execute('UPDATE incidents SET acknowledged=COALESCE(acknowledged,?) WHERE id=?',(time.time(),incident));DB.execute('INSERT INTO audit VALUES(?,?,?)',(time.time(),'acknowledge',incident));DB.commit();return {'accepted':True}
def filtered(rows,project,service,environment=None,instance=None):
 def match(value,pattern):
  if pattern in (None,'.*','$__all','All'):return True
  if len(pattern)>256:return False
  # Grafana escaped multi-value alternatives; no arbitrary regular-expression operators.
  return value in pattern.replace('\\.','.').strip('()').split('|') or value==pattern
 def selected(x):
  for k,v in [('project',project),('service',service),('environment',environment),('instance',instance)]:
   if k=='instance' and 'instance' not in x and v not in (None,'.*','$__all','All'):
    if not any(match(i['id'],v) for s in config['services'] if s['project']==x.get('project') and s['service']==x.get('service') and s['environment']==x.get('environment') for i in s['instances']):return False
   elif not match(x.get(k),v):return False
  return True
 return [x for x in rows if selected(x)]

@app.get('/api/{collection}')
async def read(collection:str,request:Request,project:str=None,service:str=None,limit:int=200,active:bool=False,environment:str=None,instance:str=None,start:float=None,end:float=None,format:str='json'):
 authorize(request,read=True);limit=max(1,min(limit,1000))
 if any(v is not None and finite(v) is None for v in (start,end)):raise HTTPException(400,'Report timestamps must be finite')
 now=time.time();end=min(now,end/1000 if end and end>1e11 else end or now);start=start/1000 if start and start>1e11 else start or end-86400
 if start>=end or end-start>366*86400:raise HTTPException(400,'Report range must be positive and at most 366 days')
 if collection=='projects':
  rows=[]
  for p in config['projects']:
   members=[v for v in states.values() if v['project']==p['id'] and v['service'] in p.get('criticalServices',[])]
   values=[v['state'] for v in members]
   if len(members)<len(p.get('criticalServices',[])):values.append('UNKNOWN')
   state=project_state(values)
   project_service={'project':p['id'],'service':'project:'+p['id'],'environment':'all','objectives':{'probeAvailability':p.get('objective',{'target':.999})},'maintenance':p.get('maintenance',[])}
   rows.append({**duration_report(DB,project_service,'project:'+p['id'],start,end),'project':p['id'],'state':state,'criticalServices':', '.join(p.get('criticalServices',[])),'healthyCriticalServices':sum(x=='UP' for x in values),'expectedCriticalServices':len(p.get('criticalServices',[]))})
 elif collection=='inventory':rows=[{'project':s['project'],'service':s['service'],'environment':s['environment'],'kind':s['kind'],'owner':s.get('owner',''),'runbook':s.get('runbook',''),'dependencies':', '.join(s.get('dependencies',[])),'quorum':s.get('quorum',1),'instances':len(s['instances'])} for s in config['services']]
 elif collection=='state':rows=[{**v,**{k:x for k,x in duration_report(DB,next(s for s in config['services'] if sid(s)==identity),identity,start,end).items() if k not in ('definition',)}} for identity,v in states.items()]
 elif collection=='instances':rows=[{**{k:s[k] for k in ('project','service','environment')},**dict(r)} for s in config['services'] for r in DB.execute('SELECT instance,state,reason,updated FROM instance_state WHERE service_id=?',(sid(s),))]
 elif collection=='reliability':rows=[{**duration_report(DB,s,sid(s),start,end),**request_reports.get(sid(s),{})} for s in config['services']]
 elif collection=='maintenance':rows=[{**{k:s[k] for k in ('project','service','environment')},**m} for s in config['services'] for m in s.get('maintenance',[])]
 elif collection=='summary':
  selected=filtered(list(states.values()),project,service,environment,instance);values=[r['state'] for r in selected]
  return [{'services':len(values),'unhealthy':sum(x in ('DOWN','DEGRADED','UNKNOWN') for x in values),'healthy':values.count('UP'),'degraded':values.count('DEGRADED'),'down':values.count('DOWN'),'unknown':values.count('UNKNOWN'),'maintenance':values.count('MAINTENANCE'),'draining':values.count('DRAINING'),'activeIncidents':sum(r['recovered'] is None and r['closed'] is None for r in DB.execute('SELECT service,project,recovered,closed FROM incidents') if r['service'] in {v['service'] for v in selected}),'pipeline':int(pipeline)}]
 elif collection=='incidents':
  rows=[dict(x) for x in DB.execute('SELECT * FROM incidents'+(' WHERE recovered IS NULL AND closed IS NULL' if active else '')+' ORDER BY opened DESC LIMIT ?',(limit,))]
  rows=[r for r in rows if r['opened']<end and (r['recovered'] is None or r['recovered']>=start)]
  for row in rows:row.update(durationSeconds=(row['recovered'] or row.get('closed') or end)-row['opened'],recoverySeconds=row['recovered']-row['opened'] if row['recovered'] else None,acknowledgmentSeconds=row['acknowledged']-row['opened'] if row['acknowledged'] else None,outageLowerBoundSeconds=max(0,(row['recovered'] or end)-row['first_failure']),outageUpperBoundSeconds=max(0,(row['recovered'] or end)-(row['previous_success'] or row['first_failure'])),status='RETIRED' if row.get('resolution_kind')=='retired' else 'OPEN' if row['recovered'] is None else 'RESOLVED',openedIso=datetime.fromtimestamp(row['opened'],timezone.utc).isoformat(),recoveredIso=datetime.fromtimestamp(row['recovered'],timezone.utc).isoformat() if row['recovered'] else '')
 elif collection=='notifications':rows=[dict(x) for x in DB.execute('SELECT id,received,status FROM notifications ORDER BY received DESC LIMIT ?',(limit,))]
 elif collection=='objectives':rows=objective_rows
 elif collection=='timeline':rows=[{**{k:s[k] for k in ('project','service','environment')},'time':r['observed']*1000,'state':r['state'],'reason':r['reason']} for s in config['services'] for r in DB.execute('SELECT observed,state,reason FROM service_samples WHERE service_id=? AND observed>=? AND observed<=? ORDER BY observed LIMIT ?',(sid(s),start,end,limit))]
 elif collection=='heartbeats':rows=[{**{k:s[k] for k in ('project','service','environment')},**dict(r)} for s in config['services'] for r in DB.execute('SELECT h.instance,h.sequence,h.ready,h.progress,h.active_jobs,h.received,b.source_time,h.received-b.source_time AS source_lag_seconds FROM heartbeats h LEFT JOIN heartbeat_source b ON h.service_id=b.service_id AND h.instance=b.instance WHERE h.service_id=?',(sid(s),))]
 elif collection=='jobs':rows=[{**{k:s[k] for k in ('project','service','environment')},**dict(r)} for s in config['services'] for r in DB.execute('SELECT j.*,c.boot_id,c.source_started,c.source_finished FROM job_runs j LEFT JOIN job_context c ON j.run_id=c.run_id WHERE service_id=? AND started>=? ORDER BY started DESC LIMIT ?',(sid(s),start,limit))]
 elif collection=='observations':rows=[{**{k:s[k] for k in ('project','service','environment')},**dict(r)} for s in config['services'] for r in DB.execute('SELECT instance,kind,observed,received,success,reason FROM observations WHERE service_id=? AND observed>=? AND observed<=? ORDER BY observed DESC LIMIT ?',(sid(s),start,end,limit))]
 elif collection=='diagnostics':return {'pipeline':pipeline,'evaluatorLastSuccess':evaluator_g._value.get(),'externalNotificationsConfigured':any(n['type']!='local' for n in config.get('notifications',[]))}
 else:raise HTTPException(404,'Unknown read collection')
 rows=filtered(rows,project,service,environment,instance)[:limit]
 if format=='csv':
  buffer=io.StringIO();fields=sorted({k for row in rows for k in row});writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader();writer.writerows(rows)
  return Response(buffer.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="'+collection+'.csv"'})
 if format!='json':raise HTTPException(400,'Supported formats are json and csv')
 return rows

def observe(identity,instance,kind,success,reason,observed=None):
 now=time.time();check=identity+':'+instance+':'+kind
 DB.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?)',(check,identity,instance,kind,observed or now,now,None if success is None else int(success),reason))
 return success

def transition(s,state,reason,now,evidence=None):
 identity=sid(s);evidence=list(evidence) if evidence is not None else None;p=config.get('policies',{});row=DB.execute('SELECT * FROM incidents WHERE service_id=? AND recovered IS NULL AND closed IS NULL',(identity,)).fetchone()
 if evidence is not None and evidence==last_evidence.get(identity):
  failure_streak[identity]=failure_streak.get(identity,0)
 elif state=='DOWN':
  failure_streak[identity]=failure_streak.get(identity,0)+1;recovery_streak[identity]=0
  if not row and failure_streak[identity]>=p.get('failureCount',2):
   previous=DB.execute('SELECT max(observed) FROM observations WHERE service_id=? AND success=1',(identity,)).fetchone()[0]
   first=DB.execute('SELECT min(observed) FROM observations WHERE service_id=? AND success=0 AND observed>?',(identity,previous or started)).fetchone()[0] or now
   DB.execute('INSERT INTO incidents(id,service_id,project,service,environment,reason,opened,first_failure,previous_success,last_failure,recovered,acknowledged,policy) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),identity,s['project'],s['service'],s['environment'],reason,now,first,previous,now,None,None,json.dumps(p)))
  elif row:DB.execute('UPDATE incidents SET last_failure=? WHERE id=?',(now,row['id']))
 elif state in ('UP','DEGRADED'):
  failure_streak[identity]=0;recovery_streak[identity]=recovery_streak.get(identity,0)+1
  if row and recovery_streak[identity]>=p.get('recoveryCount',2):DB.execute('UPDATE incidents SET recovered=? WHERE id=?',(now,row['id']))
 if evidence is not None:
  last_evidence[identity]=evidence;DB.execute('INSERT OR REPLACE INTO evaluator_cursors VALUES(?,?)',(identity,json.dumps(evidence)))
 # UNKNOWN/maintenance do not erase incident evidence or falsely recover.
 DB.execute('INSERT OR REPLACE INTO evaluator_state VALUES(?,?,?)',(identity,failure_streak.get(identity,0),recovery_streak.get(identity,0)))
 DB.execute('INSERT OR REPLACE INTO state VALUES(?,?,?,?)',(identity,state,reason,now))
 states[identity]={k:s[k] for k in ('project','service','environment','kind')};states[identity].update(state=state,reason=reason,updated=now,updatedIso=datetime.fromtimestamp(now,timezone.utc).isoformat(),quorum=s.get('quorum',1),healthyInstances=0,telemetryFresh=freshness.get(identity,False))

def objective_report(s):
 identity=sid(s);now=time.time();window=s.get('objectives',{}).get('probeAvailability',{}).get('windowDays',30)*86400;since=max(started,now-window)
 row=DB.execute('SELECT count(*) total,sum(success IS NOT NULL) known,sum(success=1) successful,sum(success=0) failing FROM observations WHERE service_id=? AND observed>=?',(identity,now-window)).fetchone()
 total,known,success,failing=[x or 0 for x in row];expected=max(total,int((now-since)/max(1,s.get('checks',{}).get('intervalSeconds',5)))*len(s['instances']))
 target=s.get('objectives',{}).get('probeAvailability',{}).get('target',.999);coverage=known/expected if expected else None;sli=success/known if known else None
 return {'project':s['project'],'service':s['service'],'environment':s['environment'],'known':known,'successful':success,'failing':failing,'unknown':max(0,expected-known),'expected':expected,'coverage':coverage,'observedSampledAvailability':sli,'target':target,'errorBudgetConsumed':((1-sli)/(1-target)) if sli is not None and target<1 else None,'compliance':'INSUFFICIENT_DATA' if not coverage or coverage<.95 or known<10 else 'MET' if sli>=target else 'MISSED','partialWindow':now-started<window,'definition':'successful / known samples; separate coverage, not exact wall-clock uptime'}

async def prom(query,at=None):
 r=await client.get('http://127.0.0.1:9090/api/v1/query',params={'query':query,**({'time':at} if at is not None else {})});r.raise_for_status();return r.json()['data']['result']
async def evaluator():
 global pipeline,last_report_update,last_maintenance_sync
 while True:
  try:
   now=time.time();health_urls=['http://127.0.0.1:9090/-/ready','http://127.0.0.1:9115/metrics','http://127.0.0.1:3100/ready','http://127.0.0.1:3200/ready','http://127.0.0.1:12345/-/ready','http://127.0.0.1:3000/api/health']
   checks=await asyncio.gather(*[client.get(u) for u in health_urls],return_exceptions=True);pipeline=all(isinstance(r,httpx.Response) and r.status_code==200 for r in checks);pipeline_g.set(int(pipeline))
   free=os.statvfs(DATA);disk_g.set(free.f_bavail*free.f_frsize)
   probes=await prom('probe_success') if pipeline else [];probe_times=await prom('timestamp(probe_success)') if pipeline else [];metrics=await prom('timestamp(app_process_uptime_seconds)') if pipeline else []
   freshness.clear()
   for s in config['services']:
    identity=sid(s);freshness[identity]=any(all(x['metric'].get(k)==s[k] for k in ('project','service','environment')) and now-float(x['value'][1])<config.get('policies',{}).get('freshnessSeconds',30) for x in metrics)
    outcomes=[];reasons=[];instance_outcomes=[];evidence_times=[];instance_rows=[];dimensions={"health":[],"ready":[]}
    for i in s['instances']:
     instance_freshness[(identity,i['id'])]=any(all(x['metric'].get(k)==s[k] for k in ('project','service','environment')) and x['metric'].get('instance')==i['id'] and now-float(x['value'][1])<config.get('policies',{}).get('freshnessSeconds',30) for x in metrics)
     if i.get('draining'):
      DB.execute('INSERT OR REPLACE INTO instance_state VALUES(?,?,?,?,?)',(identity,i['id'],'DRAINING','operator_draining',now));continue
     offset=len(outcomes)
     if s['kind'] in ('http','external'):
      for kind,key in [('health','healthUrl'),('ready','readyUrl'),('tcp','tcpUrl'),('dns','dnsUrl')]:
       if key not in i:continue
       evidence=[x for x in probes if all(x['metric'].get(k)==s[k] for k in ('project','service','environment')) and x['metric'].get('instance')==i['id'] and x['metric'].get('check')==kind]
       latest=max(evidence,key=lambda x:float(x['value'][0]),default=None)
       success=None;reason='pipeline_unavailable' if not pipeline else 'missing_probe';observed=now
       if pipeline and latest:
        stamp=next((x for x in probe_times if x['metric']=={k:v for k,v in latest['metric'].items() if k!='__name__'} or all(x['metric'].get(k)==v for k,v in latest['metric'].items() if k!='__name__')),None)
        observed=float(stamp['value'][1]) if stamp else 0;age=now-observed
        if age<s.get('checks',{}).get('intervalSeconds',15)*2+5:success=latest['value'][1]=='1';reason='ok' if success else kind+'_failed'
       assertion=s.get('checks',{}).get('bodyAssertion',{})
       if kind in ('health','ready') and pipeline and latest and (assertion.get('mode')=='json-field' or s.get('checks',{}).get('followRedirects')):
        try:success,reason=await http_assertion(i[key],config,s.get('checks',{}),SECRETS);observed=now
        except Exception as exc:success=False;reason='assertion_transport_failed_'+type(exc).__name__;observed=now
       dimensions.setdefault(kind,[]).append(success);outcomes.append(observe(identity,i['id'],kind,success,reason,observed));reasons.append(reason);evidence_times.append(observed)
     else:
      h=DB.execute('SELECT * FROM heartbeats WHERE service_id=? AND instance=?',(identity,i['id'])).fetchone();hcfg=s.get('heartbeat',{});grace=hcfg.get('graceSeconds',15)
      success=None if not pipeline else bool(h and now-h['received']<=grace and h['ready']);reason='pipeline_unavailable' if not pipeline else 'ok' if success else 'worker_unready' if h and now-h['received']<=grace else 'heartbeat_expired'
      if not h and now-started<hcfg.get('startupGraceSeconds',20):success=None;reason='startup_grace'
      if h and h['active_jobs'] and now-h['progress_time']>s.get('jobs',{}).get('maximumRunningSeconds',60):success=False;reason='job_stalled'
      if s['kind']=='scheduled-job':
       j=DB.execute('SELECT * FROM jobs WHERE service_id=? AND instance=?',(identity,i['id'])).fetchone();jc=s.get('jobs',{});due=latest_due(jc.get('schedule','* * * * *'),jc.get('timezone','UTC'),now)
       if j and j['state']=='failed':success=False;reason='job_failed'
       elif now-due<jc.get('completionDeadlineSeconds',30) or due<started:success=True;reason='between_expected_runs'
       elif not j or j['received']<due or j['state']!='completed':success=False;reason='scheduled_deadline_missed'
      outcomes.append(observe(identity,i['id'],'worker',success,reason));reasons.append(reason);evidence_times.append(now)
     values=outcomes[offset:];result=False if False in values else None if not values or any(x is None for x in values) else True;instance_outcomes.append(result)
     DB.execute('INSERT OR REPLACE INTO instance_state VALUES(?,?,?,?,?)',(identity,i['id'],'UNKNOWN' if result is None else 'UP' if result else 'DOWN',next((r for r in reasons[offset:] if r!='ok'),'ok'),now))
     instance_rows.append((i,result))
    state,healthy=aggregate(instance_rows,s.get('quorum',1))
    if not pipeline:state='UNKNOWN'
    raw_state=state
    record(DB,identity+':telemetry','UP' if all(instance_freshness.get((identity,i['id']),False) for i in s['instances'] if not i.get('draining')) else 'UNKNOWN','telemetry_freshness',now)
    record(DB,identity,raw_state,next((r for r in reasons if r!='ok'),'ok'),now)
    if all(i.get('draining') for i in s['instances']):state='DRAINING'
    for m in s.get('maintenance',[]):
     if datetime.fromisoformat(m['start'].replace('Z','+00:00')).timestamp()<=now<datetime.fromisoformat(m['end'].replace('Z','+00:00')).timestamp():state='MAINTENANCE'
    transition(s,raw_state,next((r for r in reasons if r!='ok'),'ok'),now,tuple(evidence_times)+tuple(outcomes));states[identity]['state']=state;states[identity]['healthyInstances']=healthy;states[identity]['availabilityState']=raw_state
    def dimension(values):return 'UNKNOWN' if not pipeline or not values else 'DOWN' if False in values else 'UNKNOWN' if None in values else 'UP'
    states[identity]['externalReachability']=dimension(dimensions['health']) if s['kind'] in ('http','external') else 'NOT_APPLICABLE'
    states[identity]['readiness']=dimension(dimensions['ready']) if s['kind'] in ('http','external') else state
    stats=request_reports.get(identity,{})
    states[identity]['performance']=stats.get('performance','UNKNOWN')
    states[identity]['observationType']=', '.join(sorted({i.get('observationType','heartbeat') for i in s['instances']}))
   for p in config['projects']:
    critical=p.get('criticalServices',[]);members=[states.get(sid(s),{}).get('availabilityState','UNKNOWN') for s in config['services'] if s['project']==p['id'] and s['service'] in critical]
    if len(members)<len(critical):members.append('UNKNOWN')
    record(DB,'project:'+p['id'],project_state(members),'critical_service_policy',now)
   if pipeline and now-last_maintenance_sync>=30:
    await synchronize_maintenance(now);last_maintenance_sync=now
   if pipeline and now-last_report_update>=30:
    await refresh_objectives(now)
   cutoff=now-config.get('retention',{}).get('controlDays',90)*86400
   DB.execute('DELETE FROM observations WHERE observed<?',(cutoff,));DB.execute('DELETE FROM service_samples WHERE observed<?',(cutoff,));DB.execute('DELETE FROM job_runs WHERE finished<?',(cutoff,));DB.execute('DELETE FROM log_ids WHERE received<?',(now-3600,));DB.commit();evaluator_g.set(now)
  except asyncio.CancelledError:raise
  except Exception as exc: pipeline=False;pipeline_g.set(0);print('Evaluator degraded: '+type(exc).__name__,flush=True)
  await asyncio.sleep(5)

async def refresh_objectives(now):
 global objective_rows,last_report_update
 rows=[]
 for s in config['services']:
  identity=sid(s);objectives=s.get('objectives',{})
  for name in ('probeAvailability','workerReliability'):
   if name not in objectives:continue
   o=objectives[name];window=o.get('windowDays',30)*86400;r=duration_report(DB,s,identity,now-window,now)
   rows.append({**r,'objective':name,'route':'all','sli':r['availability'],'budgetRemaining':None if r['errorBudgetConsumed'] is None else max(0,1-r['errorBudgetConsumed'])})
  variants=[('all',objectives)]+[(r['route'],r) for r in s.get('routeObjectives',[])]
  if s['kind'] not in ('http','external'):continue
  for route,definitions in variants:
   for name in ('requestSuccess','requestLatency'):
    if name not in definitions:continue
    o=definitions[name];window=o.get('windowDays',30)*86400;duration=str(int(window))+'s'
    labels={k:s[k] for k in ('project','service','environment')}
    if route!='all':labels['route']=route
    selector=','.join(k+'='+json.dumps(v) for k,v in labels.items())
    try:
     async def increase(metric,extra=''):
      total=0
      for left,right in eligible_ranges(s,now-window,now):
       if right-left<1:continue
       result=await prom('sum(increase('+metric+'{'+selector+extra+'}['+str(int(right-left))+'s]))',right)
       if result:total+=finite(float(result[0]['value'][1])) or 0
      return total
     count=await increase('app_http_requests_total')
     amount=await increase('app_http_requests_total',',status_class="5xx"') if name=='requestSuccess' else await increase('app_http_request_duration_seconds_bucket',',le="'+str(o.get('thresholdSeconds',.5))+'"')
     sli=(1-(amount or 0)/count if name=='requestSuccess' else (amount or 0)/count) if count else None
     telemetry=duration_report(DB,s,identity+':telemetry',now-window,now)
     coverage=telemetry['coverage']
     target=o['target'];burn=(1-sli)/(1-target) if sli is not None and target<1 else None
     row={'project':s['project'],'service':s['service'],'environment':s['environment'],'objective':name,'route':route,'target':target,'sli':sli,'requestCount':count,'windowSeconds':window,'partialWindow':telemetry['partialWindow'],'coverage':coverage,'errorBudgetConsumed':burn,'budgetRemaining':None if burn is None else max(0,1-burn),'compliance':'INSUFFICIENT_DATA' if not count or count<o.get('minimumRequests',100) or coverage is None or coverage<o.get('minimumCoverage',.95) else 'MET' if sli>=target else 'MISSED','definition':'Prometheus extrapolated counter increase, volume guarded; missing data is not zero traffic proof.'}
     rows.append(row)
     if route=='all':request_reports.setdefault(identity,{})[name+'Ratio']=sli;request_reports[identity]['requestCount']=count
    except Exception:rows.append({'project':s['project'],'service':s['service'],'environment':s['environment'],'objective':name,'route':route,'compliance':'INSUFFICIENT_DATA'})
 # Current performance is a short operational window, separate from the SLO window.
 for s in config['services']:
  if s['kind']!='http':continue
  identity=sid(s);selector=','.join(k+'='+json.dumps(s[k]) for k in ('project','service','environment'))
  definitions=s.get('objectives',{});minimum=definitions.get('requestSuccess',{}).get('minimumRequests',100)
  try:
   count_result=await prom('sum(increase(app_http_requests_total{'+selector+'}[5m]))',now);count=float(count_result[0]['value'][1]) if count_result else 0
   errors=await prom('sum(increase(app_http_requests_total{'+selector+',status_class="5xx"}[5m]))',now)
   latency=await prom('histogram_quantile(0.95,sum by(le)(rate(app_http_request_duration_seconds_bucket{'+selector+'}[5m])))',now)
   error_ratio=(float(errors[0]['value'][1]) if errors else 0)/count if count else None
   p95=finite(float(latency[0]['value'][1])) if latency else None
   fresh=all(instance_freshness.get((identity,i['id']),False) for i in s['instances'] if not i.get('draining'))
   performance='UNKNOWN' if not fresh or count<minimum or p95 is None else 'DEGRADED' if error_ratio>1-definitions.get('requestSuccess',{}).get('target',.995) or p95>definitions.get('requestLatency',{}).get('thresholdSeconds',.5) else 'UP'
   request_reports.setdefault(identity,{}).update(performance=performance,currentRequestCount=count,currentErrorRatio=error_ratio,currentP95Seconds=p95,performanceWindowSeconds=300)
  except Exception:request_reports.setdefault(identity,{})['performance']='UNKNOWN'
 objective_rows=rows;last_report_update=now

async def synchronize_maintenance(now):
 policies={}
 for s in config['services']:
  for m in s.get('maintenance',[]):
   if datetime.fromisoformat(m['end'].replace('Z','+00:00')).timestamp()<=now:continue
   key=hashlib.sha256((sid(s)+m['start']+m['end']).encode()).hexdigest();policies[key]=(s,m)
 auth=httpx.BasicAuth('admin',(SECRETS/'grafana-admin').read_text().strip())
 for key,(s,m) in policies.items():
  if DB.execute('SELECT 1 FROM maintenance_silences WHERE policy_id=?',(key,)).fetchone():continue
  payload={'matchers':[{'name':k,'value':s[k],'isRegex':False,'isEqual':True} for k in ('project','service','environment')],'startsAt':m['start'],'endsAt':m['end'],'createdBy':'portable-observability','comment':'Operator-configured maintenance; observations and incident history remain retained.'}
  response=await client.post('http://127.0.0.1:3000/api/alertmanager/grafana/api/v2/silences',auth=auth,json=payload);response.raise_for_status()
  DB.execute('INSERT INTO maintenance_silences VALUES(?,?,?)',(key,response.json()['silenceID'],sid(s)))
 for row in DB.execute('SELECT * FROM maintenance_silences').fetchall():
  if row['policy_id'] in policies:continue
  response=await client.delete('http://127.0.0.1:3000/api/alertmanager/grafana/api/v2/silence/'+row['silence_id'],auth=auth)
  if response.status_code in (200,202,404):DB.execute('DELETE FROM maintenance_silences WHERE policy_id=?',(row['policy_id'],))
 DB.commit()
