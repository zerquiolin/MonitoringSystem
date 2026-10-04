"""Provisioned, consistently filtered Grafana interface with explicit signal units."""
import json
SECTIONS=[('overview','Overview'),('project','Projects'),('service','Service detail'),('infrastructure','Infrastructure'),('logs','Logs & errors'),('traces','Traces & dependencies'),('incidents','Uptime & reliability'),('monitoring','Monitoring health')]
FILTER='project=~"$project",service=~"$service",environment=~"$environment",instance=~"$instance"'
SVC='project=~"$project",service=~"$service",environment=~"$environment"'
COLORS={'UP':'green','DOWN':'red','DEGRADED':'orange','UNKNOWN':'gray','MAINTENANCE':'blue','DRAINING':'purple','RETIRED':'gray','OPEN':'red','RESOLVED':'green','MET':'green','MISSED':'red','INSUFFICIENT_DATA':'gray','SUPPORTED':'green','UNSUPPORTED':'gray','DISABLED':'gray'}
TITLES={'service':'Service','project':'Project','environment':'Environment','state':'Status','availability':'Availability','uptimeSeconds':'Uptime','downtimeSeconds':'Downtime','degradedSeconds':'Degraded','unknownSeconds':'Unknown','coverage':'Coverage','incidentCount':'Incidents','activeIncidents':'Open incidents','mttrSeconds':'Mean recovery','meanAcknowledgmentSeconds':'Mean acknowledgment','maintenanceSeconds':'Maintenance','healthyInstances':'Healthy replicas','quorum':'Quorum','instance':'Instance','performance':'Performance','readiness':'Readiness','externalReachability':'Reachability','reason':'Reason','telemetryFresh':'Telemetry fresh','objective':'Objective','target':'Target','sli':'Measured','compliance':'Result','errorBudgetConsumed':'Budget consumed','budgetRemaining':'Budget remaining','route':'Route','windowSeconds':'Window','durationSeconds':'Duration','openedIso':'Detected','recoveredIso':'Recovered','outageLowerBoundSeconds':'Outage lower bound','outageUpperBoundSeconds':'Outage upper bound','owner':'Owner','status':'Status','acknowledgmentSeconds':'Acknowledgment','recoverySeconds':'Recovery','requestCount':'Requests'}
RATIOS={'availability','coverage','target','sli','errorBudgetConsumed','budgetRemaining'}
NUMBERS={'healthyInstances','quorum','incidentCount','activeIncidents','requestCount','services','healthy','degraded','down','unknown','pipeline','instances','received','unhealthy'}

def unit(field):return 'percentunit' if field in RATIOS else 's' if field.endswith('Seconds') else 'short'
def mappings():return [{'type':'value','options':{k:{'text':k,'color':v,'index':n} for n,(k,v) in enumerate(COLORS.items())}},{'type':'special','options':{'match':'null','result':{'text':'No data','color':'gray'}}}]
def generate():
 for uid,title in SECTIONS:
  panels=[];y=0;x=0
  def add(label,query,kind='timeseries',width=12,height=7,fields=None,collection=None,units='short',desc=None,legend='{{service}} · {{instance}}',color=None):
   nonlocal y,x
   if x+width>24:y+=height;x=0
   source='control' if collection else 'loki' if kind=='logs' else 'tempo' if kind=='traces' else 'prometheus'
   dtype={'control':'yesoreyeram-infinity-datasource','prometheus':'prometheus','loki':'loki','tempo':'tempo'}[source]
   target={'refId':'A','datasource':{'uid':source,'type':dtype}}
   if collection:
    if kind=='table' and 'service' in (fields or []):fields=list(fields)+[f for f in ('project','environment') if f not in fields]
    target.update(type='json',source='url',url='http://127.0.0.1:8000/api/'+collection+'?project=${project:regex}&service=${service:regex}&environment=${environment:regex}&instance=${instance:regex}&start=${__from}&end=${__to}'+('&active=true' if label=='Active incidents' else ''),url_options={'method':'GET','data':'','headers':[],'params':[]},parser='backend',format='table',root_selector='',columns=[{'selector':f,'text':f,'type':'number' if f in NUMBERS or f in RATIOS or f.endswith('Seconds') else 'string'} for f in fields or []])
   elif source=='tempo':target.update(queryType='traceql',query=query,limit=30)
   else:target.update(expr=query,legendFormat=legend,range=kind!='stat',instant=kind=='stat')
   defaults={'unit':units,'decimals':2,'noValue':'No data','color':{'mode':'palette-classic'},'custom':{'lineWidth':2,'fillOpacity':8,'showPoints':'never','spanNulls':False},'links':[]}
   if source=='prometheus' and 'service' in query:defaults['links']=[{'title':'Service detail','url':'/d/service?${project:queryparam}&var-service=${__field.labels.service}&${environment:queryparam}&${instance:queryparam}&from=${__from}&to=${__to}'},{'title':'Logs for this service','url':'/d/logs?${project:queryparam}&var-service=${__field.labels.service}&${environment:queryparam}&from=${__from}&to=${__to}'}]
   options={'legend':{'displayMode':'table','placement':'bottom','calcs':['lastNotNull']},'tooltip':{'mode':'multi','sort':'desc'}}
   overrides=[];transformations=[]
   if kind=='table':
    defaults={'noValue':'No active incidents' if label=='Active incidents' else '—','decimals':2,'custom':{'align':'left','cellOptions':{'type':'auto'},'filterable':True}}
    options={'showHeader':True,'cellHeight':'sm','sortBy':[{'displayName':'Service','desc':False}],'footer':{'show':False}}
    transformations=[{'id':'organize','options':{'indexByName':{f:n for n,f in enumerate(fields)},'renameByName':{f:TITLES.get(f,f) for f in fields}}}]
    for f in fields:
     props=[{'id':'unit','value':unit(f)},{'id':'decimals','value':0 if f in NUMBERS or f.endswith('Seconds') else 2}]
     if f.endswith('Seconds'):props.append({'id':'custom.width','value':95})
     if f=='unknownSeconds':props.append({'id':'custom.width','value':90})
     if f in RATIOS:props.extend([{'id':'decimals','value':2},{'id':'custom.width','value':100}])
     if f in ('state','status','compliance','performance','readiness','externalReachability'):
      props.extend([{'id':'mappings','value':mappings()},{'id':'custom.cellOptions','value':{'type':'color-text'}},{'id':'custom.width','value':170 if f=='compliance' else 105}])
     if f in ('openedIso','recoveredIso'):props.append({'id':'custom.width','value':185})
     if f=='reason':props.append({'id':'custom.width','value':180})
     if f in ('project','environment') and kind=='table' and label not in ('Critical service health',):props.append({'id':'custom.hidden','value':True})
     if f=='service':props.extend([{'id':'custom.width','value':140},{'id':'links','value':[{'title':'Service detail','url':'/d/service?var-project=${__data.fields.Project}&var-service=${__value.raw}&var-environment=${__data.fields.Environment}&from=${__from}&to=${__to}'}]}])
     overrides.append({'matcher':{'id':'byName','options':TITLES.get(f,f)},'properties':props})
   if kind=='stat':
    defaults.update(color={'mode':'fixed','fixedColor':color or 'blue'},decimals=0 if units=='short' else 2)
    options={'reduceOptions':{'values':False,'calcs':['lastNotNull'],'fields':''},'orientation':'auto','textMode':'value','colorMode':'value','graphMode':'none','justifyMode':'center'}
   if kind=='logs':options={'showTime':True,'showLabels':False,'showCommonLabels':False,'wrapLogMessage':True,'enableLogDetails':True,'prettifyLogMessage':True,'sortOrder':'Descending','dedupStrategy':'none'}
   panels.append({'id':len(panels)+1,'title':label,'type':kind,'description':desc or 'Filtered by project, service, environment and instance. Missing observations show No data.','gridPos':{'x':x,'y':y,'w':width,'h':height},'datasource':target['datasource'],'targets':[target],'fieldConfig':{'defaults':defaults,'overrides':overrides},'options':options,'transformations':transformations})
   x+=width
   if x==24:x=0;y+=height
  def table(label,collection,fields,height=8):add(label,'','table',24,height,fields,collection)
  def summary():
   for label,field,color in [('Services','services','blue'),('Healthy','healthy','green'),('Needs attention','unhealthy','orange'),('Open incidents','activeIncidents','red')]:add(label,'','stat',6,4,[field],'summary',color=color)
  def traffic():
   add('Request rate',f'sum by(service)(rate(app_http_requests_total{{{FILTER}}}[$__rate_interval]))',units='reqps',legend='{{service}}')
   add('Request p95',f'histogram_quantile(0.95,sum by(le,service)(rate(app_http_request_duration_seconds_bucket{{{FILTER}}}[$__rate_interval])))',units='s',legend='{{service}}',desc='Completed request duration; compatible replica histogram buckets are summed before calculating p95. No observations means No data.')
  if uid=='overview':
   summary()
   table('Availability · selected time range','state',['service','state','availability','uptimeSeconds','downtimeSeconds','unknownSeconds','coverage'],6)
   traffic()
  elif uid=='project':
   table('Critical service health','projects',['project','state','availability','downtimeSeconds','coverage','criticalServices'],6)
   table('Service availability','state',['service','state','availability','uptimeSeconds','downtimeSeconds','unknownSeconds','coverage'],8)
   traffic();table('Objectives','objectives',['service','objective','route','sli','target','compliance','budgetRemaining'],8)
   table('Ownership & dependencies','inventory',['service','owner','dependencies','quorum','instances','runbook'],6)
  elif uid=='service':
   table('Health & readiness','state',['service','state','externalReachability','readiness','performance','telemetryFresh'],6)
   table('Observed uptime & downtime · selected range','reliability',['service','availability','uptimeSeconds','downtimeSeconds','degradedSeconds','unknownSeconds','coverage'],6)
   table('Replica observations','instances',['service','instance','state','reason'],6)
   traffic()
   add('Request failures · 5xx',f'sum by(service)(rate(app_http_requests_total{{{FILTER},status_class="5xx"}}[$__rate_interval])) / sum by(service)(rate(app_http_requests_total{{{FILTER}}}[$__rate_interval]))',units='percentunit',legend='{{service}}')
   add('Active requests',f'app_http_requests_in_flight{{{FILTER}}}',legend='{{service}} · {{instance}} in flight')
   add('Process uptime',f'app_process_uptime_seconds{{{FILTER}}}',units='s',desc='Time since this Node process started; separate from externally observed service availability.')
   add('Process RSS',f'app_process_resident_memory_bytes{{{FILTER}}}',units='bytes')
   add('Process CPU · cores used',f'rate(app_process_cpu_seconds_total{{{FILTER}}}[$__rate_interval])',units='short')
   add('V8 heap used',f'app_process_heap_used_bytes{{{FILTER}}}',units='bytes')
   add('Event-loop delay · mean',f'app_event_loop_delay_seconds{{{FILTER}}}',units='s')
   add('Event-loop utilization',f'app_event_loop_utilization_ratio{{{FILTER}}}',units='percentunit')
   add('GC duration p95',f'histogram_quantile(0.95,sum by(le,service)(rate(app_gc_duration_seconds_bucket{{{FILTER}}}[$__rate_interval])))',units='s',legend='{{service}}')
   add('Jobs in flight',f'app_jobs_in_flight{{{FILTER}}}')
   add('Completed jobs / second',f'sum by(service)(rate(app_jobs_completed_total{{{FILTER}}}[$__rate_interval]))',units='ops',legend='{{service}}')
   add('Failed jobs / second',f'sum by(service)(rate(app_jobs_failed_total{{{FILTER}}}[$__rate_interval]))',units='ops',legend='{{service}}')
   add('Aborted requests / second',f'sum by(service)(rate(app_http_requests_aborted_total{{{FILTER}}}[$__rate_interval]))',units='reqps',legend='{{service}}')
   add('Readiness probe duration',f'probe_duration_seconds{{{FILTER},check="ready"}}',units='s')
  elif uid=='incidents':
   table('Uptime, downtime & observation coverage','reliability',['service','availability','uptimeSeconds','downtimeSeconds','unknownSeconds','maintenanceSeconds','coverage'],8)
   table('Incidents & recovery','reliability',['service','incidentCount','activeIncidents','mttrSeconds','meanAcknowledgmentSeconds','degradedSeconds'],6)
   table('SLOs & error budgets · configured windows','objectives',['service','objective','route','sli','target','compliance'],8)
   table('Remaining error budgets','objectives',['service','objective','route','budgetRemaining','windowSeconds'],7)
   add('Service state history',f'monitoring_service_state{{{SVC}}} == 1',legend='{{service}} · {{state}}',desc='Raw observations before incident debounce. UNKNOWN is distinct from DOWN.')
   add('Availability budget burn · 1h and 6h',f'monitoring_service_burn_rate{{{SVC},window=~"1h|6h"}}',legend='{{service}} · {{window}}',desc='Failure fraction / allowed error fraction. Requires at least 95% known coverage; missing coverage is not compliance.')
   table('Incident history','incidents',['service','status','reason','openedIso','durationSeconds'],8)
   table('Recovery & outage timing bounds','incidents',['service','recoveredIso','recoverySeconds','outageLowerBoundSeconds','outageUpperBoundSeconds'],7)
   table('Scheduled maintenance','maintenance',['service','start','end','excludeFromSlo'],5)
   table('Notification delivery','notifications',['status','received','id'],5)
  elif uid=='infrastructure':
   add('OS-visible RAM available · host publisher','max by(hostId)(app_host_memory_available_bytes{hostId=~"$host"})',units='bytes',legend='{{hostId}}',desc='One designated host publisher; OS-visible scope, not remote physical host guarantees.')
   add('OS-visible RAM utilization','1 - max by(hostId)(app_host_memory_available_bytes{hostId=~"$host"}) / max by(hostId)(app_host_memory_total_bytes{hostId=~"$host"})',units='percentunit',legend='{{hostId}}')
   add('Container memory used',f'app_container_memory_used_bytes{{{FILTER}}}',units='bytes')
   add('Container memory limit',f'app_container_memory_limit_bytes{{{FILTER}}}',units='bytes')
   add('Filesystem free · configured path 0',f'app_filesystem_0_free_bytes{{{FILTER}}}',units='bytes',desc='Filesystem visible to the application at explicitly configured path 0.')
   add('Filesystem utilization · configured path 0',f'1-app_filesystem_0_free_bytes{{{FILTER}}}/app_filesystem_0_total_bytes{{{FILTER}}}',units='percentunit')
   add('OS-visible CPU utilization','max by(hostId)(app_host_cpu_utilization_ratio{hostId=~"$host"})',units='percentunit',legend='{{hostId}}')
   add('CPU capacity · OS-visible','max by(hostId)(app_host_cpu_cores{hostId=~"$host"})',legend='{{hostId}}')
   add('Collector capability · 1 means named state',f'app_collector_capability{{{FILTER}}}',legend='{{service}} · {{collector}} · {{state}}',desc='UNSUPPORTED/DISABLED are capability states, never zero capacity or zero utilization.')
  elif uid=='logs':
   add('Application logs · newest first','{project=~"$project",service=~"$service",service=~".+",environment=~"$environment"} | json | severity =~ "$severity"','logs',24,14)
   add('Application exceptions',f'sum by(service)(rate(app_errors_total{{{FILTER}}}[$__rate_interval]))',units='ops',legend='{{service}}')
   add('Dropped log events',f'sum by(service)(increase(app_telemetry_dropped_total{{{FILTER},signal="logs"}}[$__range]))',legend='{{service}}')
   add('Log export failures',f'sum by(service)(rate(app_telemetry_export_failures_total{{{FILTER},signal="logs"}}[$__rate_interval]))',legend='{{service}}')
  elif uid=='traces':
   add('Stored trace search','{ resource.project =~ "$project" && resource.service.name =~ "$service" }','traces',24,12)
   add('Observed calls / second','sum by(client,server)(rate(traces_service_graph_request_total[$__rate_interval]))',legend='{{client}} → {{server}}',desc='Trace-derived observed relationships, separate from declared inventory. A slow span does not establish root cause.')
   add('Observed failed calls / second','sum by(client,server)(rate(traces_service_graph_request_failed_total[$__rate_interval]))',legend='{{client}} → {{server}}')
   table('Declared dependencies','inventory',['service','dependencies','owner','runbook'],6)
  elif uid=='monitoring':
   add('Pipeline ready','monitoring_pipeline_up','stat',6,4,color='green')
   add('Evaluator age','time()-monitoring_evaluator_last_success_seconds','stat',6,4,units='s')
   add('Storage free','monitoring_disk_free_bytes','stat',6,4,units='bytes')
   add('Ingress rejections','sum(increase(monitoring_ingest_rejected_total[$__range]))','stat',6,4,color='orange')
   add('Backend health','up{job="central"}',legend='{{instance}}')
   add('Telemetry freshness',f'monitoring_telemetry_fresh{{{SVC}}}',legend='{{service}}')
   add('Upstream partially rejected telemetry','monitoring_ingest_partial_rejections_total',legend='{{signal}}')
   add('Native notification failures','sum by(integration)(rate(alertmanager_notifications_failed_total[$__rate_interval]))',legend='{{integration}}')
   add('Alloy exporter queue','otelcol_exporter_queue_size',legend='{{exporter}}')
   add('SDK export failures',f'sum by(service,signal)(rate(app_telemetry_export_failures_total{{{FILTER}}}[$__rate_interval]))',legend='{{service}} · {{signal}}')
   add('SDK dropped data',f'sum by(service,signal)(rate(app_telemetry_dropped_total{{{FILTER}}}[$__rate_interval]))',legend='{{service}} · {{signal}}')
   add('SDK queued log events',f'app_log_queue_events{{{FILTER}}}')
   add('Monitoring volume free','monitoring_disk_free_bytes',units='bytes',legend='Monitoring volume')
  variables=[]
  for label in ['project','service','environment','instance','host']:
   query='label_values(app_host_memory_total_bytes,hostId)' if label=='host' else f'label_values(monitoring_expected_instance,{label})'
   variables.append({'name':label,'label':label.title(),'type':'query','datasource':{'uid':'prometheus','type':'prometheus'},'query':query,'refresh':1,'includeAll':True,'allValue':'.*','multi':True,'hide':2 if label=='instance' and uid not in ('service','infrastructure') else 0 if label!='host' or uid=='infrastructure' else 2,'current':{'text':'All','value':'$__all'}})
  if uid=='logs':variables.append({'name':'severity','label':'Severity','type':'custom','query':'trace,debug,info,warn,error,fatal','includeAll':True,'allValue':'.*','multi':True,'current':{'text':'All','value':'$__all'}})
  yield {'uid':uid,'title':title,'description':'Portable observability · Expected inventory, explicit coverage and scope. Uptime/downtime reports follow the selected time range.','schemaVersion':40,'version':2,'tags':['portable-observability'],'editable':False,'time':{'from':'now-1h','to':'now'},'refresh':'15s','tooltip':1,'templating':{'list':variables},'links':[{'title':t,'url':'/d/'+u,'type':'link','includeVars':True,'keepTime':True} for u,t in SECTIONS],'panels':panels}
