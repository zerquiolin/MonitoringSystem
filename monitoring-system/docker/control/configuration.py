"""Shared strict validation and deterministic provisioning. Never executes operator text."""
import hashlib,json,os,ipaddress,socket,re,urllib.parse
from pathlib import Path
from datetime import datetime
import yaml,jsonschema
from croniter import croniter
ROOT=Path(__file__).resolve().parents[2]
def sid(s):return hashlib.sha256('|'.join(str(s[k]) for k in ('project','service','environment')).encode()).hexdigest()[:16]
def load(path,secrets=None):
 c=yaml.safe_load(Path(path).read_text());schema=json.loads((ROOT/'contracts/inventory.schema.json').read_text());jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker()).validate(c)
 projects={p['id'] for p in c['projects']};keys=set();names={(s['project'],s['environment'],s['service']) for s in c['services']}
 if len(projects)!=len(c['projects']):raise ValueError('Duplicate project identity')
 for s in c['services']:
  key=(s['project'],s['service'],s['environment'])
  if key in keys:raise ValueError('Duplicate service identity')
  keys.add(key)
  if s['project'] not in projects:raise ValueError('Unknown project')
  instances=s['instances']
  if not instances or len({i['id'] for i in instances})!=len(instances):raise ValueError('Invalid or duplicate instances')
  if s.get('quorum',1)>len([i for i in instances if not i.get('draining')]):raise ValueError('Impossible quorum')
  if s['metrics']['mode']=='pull' and any('scrapeUrl' not in i for i in instances):raise ValueError('Pull requires scrapeUrl per instance')
  if s.get('checks',{}).get('timeoutSeconds',5)>=s.get('checks',{}).get('intervalSeconds',15):raise ValueError('Probe timeout must be below interval')
  if any(i.get('dnsUrl') and not i.get('dnsQuery') for i in instances):raise ValueError('DNS probe requires query name')
  if any((s['project'],s['environment'],d) not in names for d in s.get('dependencies',[])):raise ValueError('Unknown dependency')
  for i in instances:
   for k in ('healthUrl','readyUrl','scrapeUrl','tcpUrl','dnsUrl'):
    if k in i:
     validate_target(i[k],c,resolve=False)
     if urllib.parse.urlsplit(i[k]).scheme not in (('tcp',) if k=='tcpUrl' else ('dns',) if k=='dnsUrl' else ('http','https')):raise ValueError('Probe scheme does not match its declared type')
  for o in list(s.get('objectives',{}).values())+[o for r in s.get('routeObjectives',[]) for k,o in r.items() if k!='route']:
   if o.get('windowDays',30)>365:raise ValueError('Objective window too large')
   if o.get('thresholdSeconds',.5) not in [.005,.01,.025,.05,.1,.25,.5,1,2.5,5,10]:raise ValueError('Latency threshold must match a canonical histogram bucket')
  if len({r['route'] for r in s.get('routeObjectives',[])})!=len(s.get('routeObjectives',[])):raise ValueError('Duplicate route objective')
  for m in s.get('maintenance',[]):
   if datetime.fromisoformat(m['end'].replace('Z','+00:00'))<=datetime.fromisoformat(m['start'].replace('Z','+00:00')):raise ValueError('Invalid maintenance interval')
  j=s.get('jobs',{})
  if 'schedule' in j:
   from zoneinfo import ZoneInfo
   ZoneInfo(j.get('timezone','UTC'))
   if not croniter.is_valid(j['schedule']):raise ValueError('Invalid schedule')
 visited=set();visiting=set();edges={(s['project'],s['environment'],s['service']):[(s['project'],s['environment'],d) for d in s.get('dependencies',[])] for s in c['services']}
 def visit(n):
  if n in visiting:raise ValueError('Dependency cycle')
  if n in visited:return
  visiting.add(n)
  for d in edges[n]:visit(d)
  visiting.remove(n);visited.add(n)
 for n in edges:visit(n)
 if c['profile']=='operational' and (not c.get('tls') or not c.get('publicUrl','').startswith('https://')):raise ValueError('Operational profile requires TLS certificate/key and HTTPS publicUrl')
 if any(n['type']=='email' for n in c.get('notifications',[])) and not c.get('smtp'):raise ValueError('Email contact requires smtp configuration')
 if secrets:
  refs={s['metrics']['tokenRef'] for s in c['services']}|{'grafana-admin','grafana-key','dashboard-read','operator-token'}
  for s in c['services']:
   refs.update(s.get('checks',{}).get('headerSecretRefs',{}).values())
   for k in ('caRef',):
    if k in s.get('checks',{}):refs.add(s['checks'][k])
   if s['metrics'].get('scrapeTokenRef'):refs.add(s['metrics']['scrapeTokenRef'])
  refs.update(v for k,v in c.get('smtp',{}).items() if k.endswith('Ref'));refs.update(c.get('tls',{}).values());refs.update(n['secretRef'] for n in c.get('notifications',[]) if n.get('secretRef'))
  for ref in refs:
   p=Path(secrets)/ref
   if not p.is_file() or not p.read_text().strip():raise ValueError(f'Missing secret file: {ref}')
   if p.stat().st_mode&0o077:raise ValueError(f'Secret permissions must be 0600: {ref}')
 return c

def validate_target(url,c,resolve=True):
 u=urllib.parse.urlsplit(url)
 if u.scheme not in ('http','https','tcp','dns') or u.username or u.password or not u.hostname:raise ValueError('Unsafe target URL')
 if u.hostname in ('metadata.google.internal','169.254.169.254','100.100.100.200'):raise ValueError('Metadata target prohibited')
 hosts=c.get('network',{}).get('allowedHosts',[]);nets=[ipaddress.ip_network(x) for x in c.get('network',{}).get('allowedCidrs',[])]
 if u.hostname not in hosts:raise ValueError('Target host not allowlisted')
 if resolve:
  addresses=socket.getaddrinfo(u.hostname,u.port or (443 if u.scheme=='https' else 80),family=socket.AF_INET,type=socket.SOCK_STREAM)
  for a in addresses:
   ip=ipaddress.ip_address(a[4][0])
   if str(ip) in ('169.254.169.254','100.100.100.200') or (ip.is_private or ip.is_loopback or ip.is_link_local) and not any(ip in net for net in nets):raise ValueError('Destination IP not allowlisted')
 return url

def write(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data);path.chmod(0o600)
def yamlwrite(path,data):write(path,yaml.safe_dump(data,sort_keys=False))
def render(c,destination,secrets):
 d=Path(destination);d.mkdir(parents=True,exist_ok=True);secrets=Path(secrets)
 def secret(ref):return (secrets/ref).read_text().strip()
 for f in (ROOT/'docker/templates').iterdir():
  if f.is_file():write(d/f.name,f.read_text())
 jobs=[{'job_name':'central','scrape_interval':'5s','static_configs':[{'targets':['127.0.0.1:9090','127.0.0.1:9115','127.0.0.1:3100','127.0.0.1:3200','127.0.0.1:12345','127.0.0.1:8000','127.0.0.1:3000']}]}]
 modules={}
 for s in sorted(c['services'],key=sid):
  if not s.get('enabled',True):continue
  for i in s['instances']:
   labels={k:s[k] for k in ('project','service','environment')};labels['instance']=i['id']
   for kind,key in [('health','healthUrl'),('ready','readyUrl'),('tcp','tcpUrl'),('dns','dnsUrl')]:
    if key not in i:continue
    module='probe_'+sid(s)+'_'+kind+'_'+i['id'];check=s.get('checks',{});assertion=check.get('bodyAssertion',{})
    http={'valid_status_codes':[check.get('expectedStatus',200)],'follow_redirects':False,'preferred_ip_protocol':'ip4'}
    headers=check.get('headers',{}).copy()
    for header,ref in check.get('headerSecretRefs',{}).items():headers[header]=secret(ref)
    if headers:http['headers']=headers
    if check.get('caRef'):http['tls_config']={'ca_file':'/run/monitoring/secrets/'+check['caRef']}
    target=i[key]
    if os.getenv('MONITORING_RUNTIME')=='1':
     validate_target(target,c,resolve=True)
     original=urllib.parse.urlsplit(target);ip=socket.getaddrinfo(original.hostname,original.port or (443 if original.scheme=='https' else 80),family=socket.AF_INET,type=socket.SOCK_STREAM)[0][4][0]
     target=urllib.parse.urlunsplit((original.scheme,ip+(':'+str(original.port) if original.port else ''),original.path,original.query,''))
     http.setdefault('headers',{})['Host']=original.netloc
     if original.scheme=='https':http.setdefault('tls_config',{})['server_name']=original.hostname
    if assertion.get('mode')=='regex':http['fail_if_body_not_matches_regexp']=[assertion['pattern']]
    if kind in ('tcp','dns'):
     original=urllib.parse.urlsplit(i[key]);validate_target(i[key],c,resolve=os.getenv('MONITORING_RUNTIME')=='1')
     host=socket.getaddrinfo(original.hostname,original.port or 53,family=socket.AF_INET,type=socket.SOCK_STREAM)[0][4][0] if os.getenv('MONITORING_RUNTIME')=='1' else original.hostname
     target=host+':'+str(original.port or (53 if kind=='dns' else 80))
     modules[module]={'prober':kind,'timeout':str(check.get('timeoutSeconds',5))+'s',kind:{'query_name':i.get('dnsQuery',original.hostname),'query_type':'A','valid_rcodes':['NOERROR'],'preferred_ip_protocol':'ip4'} if kind=='dns' else {'preferred_ip_protocol':'ip4'}}
    else:modules[module]={'prober':'http','timeout':str(check.get('timeoutSeconds',5))+'s','http':http}
    jobs.append({'job_name':module+'_'+i['id'],'scrape_interval':str(check.get('intervalSeconds',15))+'s','metrics_path':'/probe','params':{'module':[module]},'static_configs':[{'targets':[target],'labels':{**labels,'check':kind,'check_id':module+'_'+i['id']}}],'relabel_configs':[{'source_labels':['__address__'],'target_label':'__param_target'},{'target_label':'__address__','replacement':'127.0.0.1:9115'}]})
   if s['metrics']['mode']=='pull':
    u=urllib.parse.urlsplit(i['scrapeUrl']);job={'job_name':'pull_'+sid(s)+'_'+i['id'],'metrics_path':u.path or '/metrics','scheme':u.scheme,'static_configs':[{'targets':[u.netloc],'labels':labels}],'honor_labels':True}
    if s['metrics'].get('scrapeTokenRef'):job['authorization']={'credentials':secret(s['metrics']['scrapeTokenRef'])}
    jobs.append(job)
 yamlwrite(d/'prometheus.yaml',{'global':{'scrape_interval':'15s','evaluation_interval':'15s'},'rule_files':['/run/monitoring/active/recording.yaml'],'scrape_configs':jobs})
 yamlwrite(d/'blackbox.yaml',{'modules':modules or {'http':{'prober':'http'}}})
 yamlwrite(d/'recording.yaml',{'groups':[{'name':'application','rules':[{'record':'app:http_request_p95_seconds','expr':'histogram_quantile(0.95, sum by (le,project,service,environment) (rate(app_http_request_duration_seconds_bucket[5m])))'},{'record':'app:http_error_ratio','expr':'sum by(project,service,environment)(rate(app_http_requests_total{status_class="5xx"}[5m])) / sum by(project,service,environment)(rate(app_http_requests_total[5m]))'}]}]})
 retention=c.get('retention',{})
 loki=yaml.safe_load((d/'loki.yaml').read_text());loki['limits_config']['retention_period']=str(retention.get('logsDays',7)*24)+'h';loki['limits_config']['max_query_lookback']=loki['limits_config']['retention_period'];yamlwrite(d/'loki.yaml',loki)
 tempo=yaml.safe_load((d/'tempo.yaml').read_text());tempo['compactor']['compaction']['block_retention']=str(retention.get('tracesHours',48))+'h';yamlwrite(d/'tempo.yaml',tempo)
 ds=[{'name':'Prometheus','uid':'prometheus','type':'prometheus','url':'http://127.0.0.1:9090','access':'proxy','isDefault':True,'jsonData':{'httpMethod':'POST','exemplarTraceIdDestinations':[{'name':'trace_id','datasourceUid':'tempo'}]}},{'name':'Loki','uid':'loki','type':'loki','url':'http://127.0.0.1:3100','access':'proxy','jsonData':{'derivedFields':[{'name':'TraceID','matcherRegex':'"traceId":"([a-f0-9]{32})"','datasourceUid':'tempo','url':'$${__value.raw}'}]}},{'name':'Tempo','uid':'tempo','type':'tempo','url':'http://127.0.0.1:3200','access':'proxy','jsonData':{'tracesToLogsV2':{'datasourceUid':'loki','tags':[{'key':'service.name','value':'service'},{'key':'project','value':'project'}],'spanStartTimeShift':'-5m','spanEndTimeShift':'5m','filterByTraceID':True},'tracesToMetrics':{'datasourceUid':'prometheus','tags':[{'key':'service.name','value':'service'}],'queries':[{'name':'Request rate','query':'sum(rate(app_http_requests_total{$$__tags}[5m]))'}]},'serviceMap':{'datasourceUid':'prometheus'},'nodeGraph':{'enabled':True}}},{'name':'Control','uid':'control','type':'yesoreyeram-infinity-datasource','url':'http://127.0.0.1:8000','access':'proxy','jsonData':{'auth_method':'bearerToken','allowedHosts':['http://127.0.0.1:8000']},'secureJsonData':{'bearerToken':secret('dashboard-read').replace('$','$$')}}]
 yamlwrite(d/'provisioning/datasources/datasources.yaml',{'apiVersion':1,'datasources':ds})
 yamlwrite(d/'provisioning/dashboards/dashboards.yaml',{'apiVersion':1,'providers':[{'name':'portable-observability','orgId':1,'folder':'Observability','type':'file','disableDeletion':False,'allowUiUpdates':False,'options':{'path':'/run/monitoring/active/dashboards'}}]})
 from dashboards import generate
 for dashboard in generate():write(d/f'dashboards/{dashboard["uid"]}.json',json.dumps(dashboard))
 # Native contact-point types; each destination remains independently configured.
 contacts=[]
 for n in c.get('notifications',[{'name':'local','type':'local'}]):
  typ=n['type'];settings={}
  if typ=='local':typ='webhook';settings={'url':'http://127.0.0.1:8000/api/notifications','authorization_scheme':'Bearer','authorization_credentials':secret('operator-token')}
  elif typ=='email':settings={'addresses':n.get('addresses','')}
  else:
   url=secret(n['secretRef']);validate_target(url,c,resolve=False);settings={'url':url}
  contacts.append({'name':n['name'],'receivers':[{'uid':'notify-'+n['name'],'type':typ,'settings':settings,'disableResolveMessage':False}]})
 prior_contacts=Path('/data/config-state/last-known-good/provisioning/alerting/contacts.yaml');prior=yaml.safe_load(prior_contacts.read_text()) if prior_contacts.exists() else {};owned_contacts={r['uid'] for n in prior.get('contactPoints',[]) for r in n.get('receivers',[])};current_contacts={r['uid'] for n in contacts for r in n['receivers']}
 yamlwrite(d/'provisioning/alerting/contacts.yaml',{'apiVersion':1,'deleteContactPoints':[{'orgId':1,'uid':uid} for uid in sorted(owned_contacts-current_contacts)],'contactPoints':contacts,'policies':[{'orgId':1,'receiver':contacts[0]['name'] if contacts else 'local','group_by':['grafana_folder','alertname','project','service'],'group_wait':'10s','group_interval':'30s','repeat_interval':'1h','routes':[{'receiver':n['name'],'continue':True,'object_matchers':[[k,'=',n[k]] for k in ['project','severity'] if k in n],'repeat_interval':n.get('repeatInterval','1h')} for n in c.get('notifications',[])]}]})
 expressions=[('service-down','Service observation failing','monitoring_service_state{state="DOWN"} > 0'),('pipeline','Monitoring pipeline unavailable','monitoring_pipeline_up == bool 0'),('telemetry','Expected telemetry missing','monitoring_instance_telemetry_fresh == bool 0'),('errors','Request errors with volume guard','app:http_error_ratio > 0.05 and on(project,service,environment) sum by(project,service,environment)(increase(app_http_requests_total[5m])) > 100'),('latency','Request p95 above 500ms','app:http_request_p95_seconds > 0.5'),('drops','Telemetry drops','sum by(project,service)(rate(app_telemetry_dropped_total[5m])) > 0'),('disk','Visible filesystem free below 10 percent','app_filesystem_0_free_bytes / app_filesystem_0_total_bytes < 0.1'),('tls','TLS certificate expires within 14 days','probe_ssl_earliest_cert_expiry - time() < 1209600')]
 expressions += [('backend','Central backend not responding','up{job="central"} == bool 0'),('replicas','Insufficient healthy replicas','monitoring_service_healthy_instances < bool monitoring_service_quorum'),('burn-fast','Availability error budget burn · fast','monitoring_service_burn_rate{window="1h"} > 14.4 and ignoring(window) monitoring_service_burn_rate{window="5m"} > 14.4'),('burn-slow','Availability error budget burn · slow','monitoring_service_burn_rate{window="6h"} > 6 and ignoring(window) monitoring_service_burn_rate{window="30m"} > 6'),('cpu','Process CPU pressure · over one core','rate(app_process_cpu_seconds_total[5m]) > 1'),('memory','Container memory pressure','app_container_memory_used_bytes / app_container_memory_limit_bytes > 0.85'),('control-age','Control evaluator stale','time()-monitoring_evaluator_last_success_seconds > 20'),('central-disk','Monitoring storage free below 1 GiB','monitoring_disk_free_bytes < 1073741824')]
 rules=[]
 for uid,title,expr in expressions:

  if uid in ('service-down','replicas','errors','latency'):continue
  rules.append({'uid':uid,'title':title,'condition':'B','for':str(c.get('policies',{}).get('alertPendingSeconds',15))+'s','noDataState':'OK','execErrState':'Error','annotations':{'summary':title,'description':'Inspect fresh observations and incident evidence in Observability dashboards.'},'labels':{'severity':'warning','owner':'monitoring'},'data':[{'refId':'A','relativeTimeRange':{'from':60,'to':0},'datasourceUid':'prometheus','model':{'refId':'A','expr':expr,'instant':True,'range':False,'intervalMs':1000,'maxDataPoints':43200}},{'refId':'B','relativeTimeRange':{'from':0,'to':0},'datasourceUid':'__expr__','model':{'type':'threshold','refId':'B','expression':'A','conditions':[{'evaluator':{'type':'gt','params':[0]},'operator':{'type':'and'},'reducer':{'type':'last','params':[]},'type':'query'}]}}]})
 # Per-service rules carry stable identity, ownership, configured targets and runbook context.
 for service in c['services']:
  if not service.get('enabled',True):continue
  identity=sid(service);selector=','.join(k+'='+json.dumps(service[k]) for k in ('project','service','environment'))
  objective=service.get('objectives',{})
  definitions=[('availability','Service availability failing','monitoring_service_state{'+selector+',state="DOWN"} > 0'),('replicas','Replica quorum failing','monitoring_service_healthy_instances{'+selector+'} < bool monitoring_service_quorum{'+selector+'}')]
  if service['kind']=='http':
   target=objective.get('requestSuccess',{}).get('target',.995);minimum=objective.get('requestSuccess',{}).get('minimumRequests',100);threshold=objective.get('requestLatency',{}).get('thresholdSeconds',.5)
   definitions.extend([('errors','Request success objective at risk','app:http_error_ratio{'+selector+'} > '+str(1-target)+' and on(project,service,environment) sum by(project,service,environment)(increase(app_http_requests_total{'+selector+'}[5m])) >= '+str(minimum)),('latency','Request latency threshold exceeded','app:http_request_p95_seconds{'+selector+'} > '+str(threshold)+' and on(project,service,environment) sum by(project,service,environment)(increase(app_http_requests_total{'+selector+'}[5m])) >= '+str(minimum))])
  for name,title,expr in definitions:
   prototype=json.loads(json.dumps(rules[0]));prototype.update(uid=identity+'-'+name,title=service['service']+' · '+title,labels={'project':service['project'],'service':service['service'],'environment':service['environment'],'owner':service.get('owner','unassigned'),'severity':'critical' if service.get('criticality')=='critical' else 'warning'},annotations={'summary':title,'description':'Inspect fresh observations, configured quorum and durable incident evidence. Value: {{ $values.A.Value }}','runbook_url':service.get('runbook',''),'__dashboardUid__':'service','__panelId__':'1','dashboard':'/d/service?var-project='+service['project']+'&var-service='+service['service']})
   prototype['data'][0]['model']['expr']=expr;rules.append(prototype)
 previous=Path('/data/config-state/last-known-good/provisioning/alerting/rules.yaml');old=yaml.safe_load(previous.read_text()) if previous.exists() else {};owned={r['uid'] for g in old.get('groups',[]) for r in g['rules']}|{'service-down','replicas','errors','latency'}
 yamlwrite(d/'provisioning/alerting/rules.yaml',{'apiVersion':1,'deleteRules':[{'orgId':1,'uid':uid} for uid in sorted(owned-{r['uid'] for r in rules})],'groups':[{'orgId':1,'name':'monitoring','folder':'Observability','interval':'10s','rules':rules}]})
 port=8080;tls=c['profile']=='operational';listen='listen 8443 ssl;' if tls else 'listen 8080;'
 tlsblock=f'ssl_certificate /run/monitoring/secrets/{c.get("tls",{}).get("certificateRef","")}; ssl_certificate_key /run/monitoring/secrets/{c.get("tls",{}).get("keyRef","")};' if tls else ''
 write(d/'nginx.conf',f'''pid /run/monitoring/nginx.pid;
error_log /run/monitoring/nginx.log warn;
worker_processes 2;
events {{ worker_connections 1024; }}
http {{
 access_log off;
 client_body_temp_path /run/monitoring/body;
 proxy_temp_path /run/monitoring/proxy;
 fastcgi_temp_path /run/monitoring/fastcgi;
 uwsgi_temp_path /run/monitoring/uwsgi;
 scgi_temp_path /run/monitoring/scgi;
 limit_req_zone $binary_remote_addr zone=ingest:10m rate=100r/s;
 limit_conn_zone $binary_remote_addr zone=connections:10m;
 server {{ {listen} {tlsblock}
 client_max_body_size 2m; client_body_timeout 10s; keepalive_timeout 15s;
 add_header X-Content-Type-Options nosniff always;
 location = /ready {{ proxy_pass http://127.0.0.1:8000/ready; }}
 location /v1/ {{ limit_req zone=ingest burst=200 nodelay; limit_conn connections 32; proxy_pass http://127.0.0.1:8000; proxy_read_timeout 10s; }}
 location /api/ingest/ {{ limit_req zone=ingest burst=200 nodelay; limit_conn connections 32; proxy_pass http://127.0.0.1:8000; }}
 location /control/ {{ rewrite ^/control/(.*)$ /api/$1 break; proxy_pass http://127.0.0.1:8000; }}
 location / {{ proxy_pass http://127.0.0.1:3000; proxy_set_header Host $http_host; proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }}
 }}
}}
''')
 write(d/'grafana.ini',f'''[paths]
data = /data/grafana
logs = /data/grafana/logs
plugins = /opt/grafana-plugins
provisioning = /run/monitoring/active/provisioning
[server]
http_addr = 127.0.0.1
http_port = 3000
root_url = {c.get('publicUrl','http://localhost:8080')}
[security]
admin_user = admin
admin_password = $__file{{/run/monitoring/secrets/grafana-admin}}
secret_key = $__file{{/run/monitoring/secrets/grafana-key}}
cookie_secure = {'true' if tls else 'false'}
[auth.anonymous]
enabled = false
[users]
allow_sign_up = false
[analytics]
reporting_enabled = false
check_for_updates = false
[metrics]
enabled = true
[plugins]
preinstall_disabled = true
[unified_alerting]
enabled = true
min_interval = 10s
''')
 if c.get('smtp'):
  smtp=c['smtp'];settings='\n[smtp]\nenabled = true\nhost = '+smtp['host']+'\nfrom_address = '+smtp['fromAddress']+'\nstartTLS_policy = '+smtp.get('startTLSPolicy','MandatoryStartTLS')+'\n'
  for k in ('user','password'):
   if smtp.get(k+'Ref'):settings+=k+' = $__file{/run/monitoring/secrets/'+smtp[k+'Ref']+'}\n'
  with (d/'grafana.ini').open('a') as f:f.write(settings)
 write(d/'inventory.json',json.dumps(c));write(d/'checksum',hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest())
 return d
