"""Runs only in a --network none container with bounded disposable tmpfs."""
import json,subprocess,time,urllib.request,urllib.parse,urllib.error,yaml,os
from pathlib import Path
ROOT=Path('/opt/monitoring');DATA=Path('/test-data');DATA.mkdir(exist_ok=True);processes=[];report={}
def launch(binary,arguments):
 log=open(DATA/(binary+'.log'),'w');p=subprocess.Popen([binary,*arguments],stdout=log,stderr=subprocess.STDOUT);processes.append(p);return p
def request(url,payload=None):
 req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=5) as r:
  raw=r.read();return json.loads(raw) if raw and raw.startswith(b'{') else raw.decode()
def wait(f,deadline=150):
 end=time.monotonic()+deadline;last=None
 while time.monotonic()<end:
  try:
   result=f()
   if result:return result
  except Exception as e:last=e
  if any(p.poll() is not None for p in processes):raise RuntimeError('Backend exited')
  time.sleep(1)
 raise AssertionError('Deadline: '+str(last))
def prometheus():
 now=time.time();directory=DATA/'prometheus';directory.mkdir()
 for age,ts in [('old',now-5*3600),('recent',now-60)]:
  f=DATA/(age+'.om');f.write_text('# TYPE fixture_metric gauge\nfixture_metric{age="'+age+'"} 1 '+str(ts)+'\n# EOF\n')
  subprocess.run(['promtool','tsdb','create-blocks-from','openmetrics',str(f),str(directory)],check=True,capture_output=True)
 blocks={p.name:json.loads((p/'meta.json').read_text()) for p in directory.iterdir() if (p/'meta.json').exists()};old=[id for id,m in blocks.items() if m['maxTime']<now*1000-3600000];assert old
 config=DATA/'prometheus.yaml';config.write_text('global:\n  scrape_interval: 5s\nscrape_configs: []\n')
 launch('prometheus',['--config.file='+str(config),'--storage.tsdb.path='+str(directory),'--storage.tsdb.retention.time=1h','--web.listen-address=127.0.0.1:19090'])
 wait(lambda:request('http://127.0.0.1:19090/-/ready'))
 wait(lambda:all(not (directory/id).exists() for id in old),160)
 query=request('http://127.0.0.1:19090/api/v1/query?'+urllib.parse.urlencode({'query':'fixture_metric','time':now}));assert any(r['metric'].get('age')=='recent' for r in query['data']['result']);assert not any(r['metric'].get('age')=='old' for r in query['data']['result'])
 return {'status':'PASS','oldBlocksPhysicallyDeleted':len(old),'recentSampleRetained':True}
def loki():
 c=yaml.safe_load((ROOT/'docker/templates/loki.yaml').read_text());directory=DATA/'loki';raw=yaml.safe_dump(c).replace('/data/loki',str(directory));c=yaml.safe_load(raw)
 c['server']['http_listen_port']=13100;c['server']['grpc_listen_port']=19095;c['compactor'].update(compaction_interval='2s',apply_retention_interval='4s',retention_delete_delay='1s',retention_delete_worker_count=2)
 c['limits_config'].update(retention_period='24h',reject_old_samples=False)
 c['querier']={'query_ingesters_within':'0s'}
 c['query_range']={'cache_results':False}
 c['ingester']={'chunk_idle_period':'1s','max_chunk_age':'1s','flush_check_period':'1s','chunk_retain_period':'0s'}
 c['storage_config']['tsdb_shipper']['resync_interval']='2s';file=DATA/'loki.yaml';file.write_text(yaml.safe_dump(c));loki_process=launch('loki',['-config.file='+str(file)])
 wait(lambda:request('http://127.0.0.1:13100/ready'),60);now=time.time();old=now-49*3600
 payload={'streams':[{'stream':{'fixture':'retention','age':age},'values':[[str(int(ts*1e9)),age+' retention fixture']]} for age,ts in [('old',old),('recent',now)]]}
 request('http://127.0.0.1:13100/loki/api/v1/push',payload)
 def query(age,ts):return request('http://127.0.0.1:13100/loki/api/v1/query_range?'+urllib.parse.urlencode({'query':'{fixture="retention",age="'+age+'"}','start':str(int((ts-10)*1e9)),'end':str(int((ts+10)*1e9))}))['data']['result']
 wait(lambda:query('old',old),20)
 def chunks():return {str(p) for p in (directory/'chunks'/'fake').rglob('*') if p.is_file()}
 before=wait(lambda:chunks() if len(chunks())>=2 else None,90)
 loki_process.terminate();loki_process.wait(30);processes.remove(loki_process);launch('loki',['-config.file='+str(file)]);wait(lambda:request('http://127.0.0.1:13100/ready'),60)
 try:wait(lambda:bool(before-chunks()),180)
 except Exception:
  print('Retention chunks: '+repr(before)+' -> '+repr(chunks()),flush=True);raise
 assert query('recent',now)
 return {'status':'PASS','oldQueryableBeforeRetention':True,'queryCacheVisibility':'Stored chunks are physically deleted; cached reads may linger until cache refresh.','physicallyDeletedChunks':len(before-chunks()),'recentLogRetained':True}
def tempo():
 c=yaml.safe_load((ROOT/'docker/templates/tempo.yaml').read_text());c=yaml.safe_load(yaml.safe_dump(c).replace('/data/tempo',str(DATA/'tempo')))
 c['server']['http_listen_port']=13200;c['server']['grpc_listen_port']=19096;c['distributor']['receivers']['otlp']['protocols']={'http':{'endpoint':'127.0.0.1:14319'}}
 c.pop('metrics_generator',None);c['overrides']={'defaults':{}}
 c['ingester'].update(trace_idle_period='1s',max_block_duration='2s',flush_check_period='1s',complete_block_timeout='2s')
 c['storage']['trace']['blocklist_poll']='1s';c['compactor']['compaction'].update(block_retention='30s',compacted_block_retention='2s',compaction_cycle='1s')
 file=DATA/'tempo.yaml';file.write_text(yaml.safe_dump(c));launch('tempo',['-config.file='+str(file)]);wait(lambda:request('http://127.0.0.1:13200/ready'),60)
 from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
 from google.protobuf.json_format import MessageToDict
 now=time.time();old_id='11'*16;new_id='22'*16
 for identity,ts in [(old_id,now-120),(new_id,now)]:
  message=ExportTraceServiceRequest();r=message.resource_spans.add();span=r.scope_spans.add().spans.add();span.trace_id=bytes.fromhex(identity);span.span_id=bytes.fromhex('33'*8);span.name='retention-fixture';span.start_time_unix_nano=int(ts*1e9);span.end_time_unix_nano=int((ts+.01)*1e9)
  payload=MessageToDict(message);encoded=payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0];encoded['traceId']=identity;encoded['spanId']='33'*8;request('http://127.0.0.1:14319/v1/traces',payload)
 assert request('http://127.0.0.1:13200/api/traces/'+old_id)
 blocks=DATA/'tempo'/'blocks'
 before=wait(lambda:{str(p.parent) for p in blocks.rglob('meta.json')} or None,60)
 def gone():
  try:request('http://127.0.0.1:13200/api/traces/'+old_id);return False
  except urllib.error.HTTPError as e:return e.code==404
 wait(gone,90)
 # Both spans may share a block; block retention follows newest span and physically expires it.
 wait(lambda:any(not Path(p).exists() for p in before),90)
 return {'status':'PASS','traceQueryableBeforeRetention':True,'traceNotQueryableAfter':True,'expiredBlocksPhysicallyDeleted':True}
try:
 for name,test in [('prometheus',prometheus),('loki',loki),('tempo',tempo)]:
  print('Running '+name+' retention',flush=True);report[name]=test();print('PASS '+name,flush=True)
 Path('/output/retention.json').write_text(json.dumps(report,indent=2))
except Exception as exc:
 if isinstance(exc,subprocess.CalledProcessError):print(str(exc.stdout)+str(exc.stderr),flush=True)
 for log in DATA.glob('*.log'):print(log.name+'\n'+log.read_text()[-6000:],flush=True)
 raise
finally:
 for p in processes:p.terminate()
 for p in processes:
  try:p.wait(15)
  except subprocess.TimeoutExpired:p.kill()
