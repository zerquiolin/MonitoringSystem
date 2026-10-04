import { context, trace, SpanStatusCode, metrics } from '@opentelemetry/api';
import { BatchSpanProcessor, ParentBasedSampler, TraceIdRatioBasedSampler } from '@opentelemetry/sdk-trace-base';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { PeriodicExportingMetricReader, AggregationType } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { PrometheusExporter } from '@opentelemetry/exporter-prometheus';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import pino from 'pino';
import Transport from 'winston-transport';
import {collectCgroup} from './runtime/cgroup.js';
import {expressRoute} from './adapters/route.js';
import { readFileSync } from 'node:fs';
import { statfs, readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { Writable } from 'node:stream';
import os from 'node:os';
import { monitorEventLoopDelay, performance, PerformanceObserver } from 'node:perf_hooks';
import type { IncomingMessage, ServerResponse } from 'node:http';
import {REQUEST_HISTOGRAM_BOUNDS,BOUNDED_HTTP_METHODS} from './metrics/contract.js';
import {resourceAttributes} from './tracing/resource.js';
export type {Heartbeat,JobEvent,WorkerResource} from './workers/contracts.js';
import { sanitize } from './logging/redaction.js';
import { Readiness, type Check } from './health/readiness.js';
export { sanitize } from './logging/redaction.js';
export interface MonitoringConfig {
 resource: { project: string; service: string; environment: string; instance: string; hostId?: string; buildId?: string };
 endpoint: string; token?: string; tokenFile?: string;
 metrics?: { mode: 'push'|'pull'; intervalMs?: number };
 logs?: { enabled?: boolean; redact?: string[]; queueSize?: number; batchSize?: number; stdout?: boolean };
 traces?: { enabled?: boolean; sampleRatio?: number };
 readiness?: { timeoutMs?: number; cacheMs?: number; checks?: Record<string,Check>; healthPath?: string; readyPath?: string; metricsPath?: string; token?: string };
 infrastructure?: { hostPublisher?: boolean; filesystemPaths?: string[]; cgroup?: boolean };
 heartbeatIntervalMs?: number;
}
let handle: Monitoring | undefined; let signature: string | undefined; let lifecycleClosed=false;
const idPattern = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/;
export async function initializeMonitoring(config: MonitoringConfig): Promise<Monitoring> {
 if(lifecycleClosed)throw new Error('Monitoring providers are shut down; restart the process to initialize again');
 const key = JSON.stringify({...config,readiness:{...config.readiness,checks:Object.keys(config.readiness?.checks ?? {})}});
 if (handle) { if (key !== signature) throw new Error('Conflicting monitoring initialization'); return handle; }
 for (const k of ['project','service','environment','instance'] as const) if (!idPattern.test(config.resource[k])) throw new Error(`Invalid resource ${k}`);
 const endpoint = new URL(config.endpoint); if (!['http:','https:'].includes(endpoint.protocol)) throw new Error('Invalid monitoring endpoint');
 if (endpoint.protocol === 'http:' && !['localhost','127.0.0.1','host.docker.internal'].includes(endpoint.hostname)) throw new Error('HTTP is allowed only for local demonstration');
 if (config.metrics?.mode && !['push','pull'].includes(config.metrics.mode)) throw new Error('Invalid metrics mode');
 const paths=[config.readiness?.healthPath ?? '/health',config.readiness?.readyPath ?? '/ready',config.readiness?.metricsPath ?? '/metrics'];
 if(new Set(paths).size!==3) throw new Error('Monitoring paths conflict');
 handle = new Monitoring(config); signature = key;try{await handle.start();return handle;}catch(e){handle=undefined;signature=undefined;throw e;}
}
export function getMonitoring(): Monitoring { if (!handle) throw new Error('Monitoring must be initialized before importing the application'); return handle; }
export class Monitoring {
 private sdk!: NodeSDK; private pull?: PrometheusExporter; private reader!: PeriodicExportingMetricReader | PrometheusExporter;
 private meter!: ReturnType<typeof metrics.getMeter>; private tracer!: ReturnType<typeof trace.getTracer>;
 private instruments: Record<string,any> = {}; private intervals: NodeJS.Timeout[] = [];
 private queue: any[] = []; private exporting = false; private retryAt = 0; private attempts = 0;
 private startTime=Date.now()/1000-process.uptime();private stopped = false; private token: string; private readiness: Readiness; private errors = new WeakSet<object>();
 private attached = new WeakSet<object>(); private custom = new Map<string,any>(); private customSeries=new Map<string,Set<string>>();
 private bootId = randomUUID(); private sequence = 0; private progress = 0; private activeJobs = 0;
 private pendingSpans=0;private signalFailures:Record<string,number>={metrics:0,traces:0,logs:0,heartbeat:0,jobs:0};private signalSuccess:Record<string,number>={};private cpuSnapshot?:{total:number,idle:number};
 private failures = 0; private drops = 0; private lastExport?: number; private inflight = 0;
 private stdout = pino({level:'debug'}); private capabilities: Record<string,string> = {process:'SUPPORTED',host:'DISABLED',filesystem:'DISABLED',cgroup:'DISABLED'};
 logger: Record<'debug'|'info'|'warn'|'error'|'fatal',(message:string,attributes?:Record<string,unknown>)=>void>;
 constructor(private config: MonitoringConfig) {
  this.token = config.token ?? (config.tokenFile ? readFileSync(config.tokenFile,'utf8').trim() : '');
  if (!this.token) throw new Error('An ingestion token or tokenFile is required');
  this.readiness = new Readiness(config.readiness?.checks ?? {},config.readiness?.timeoutMs,config.readiness?.cacheMs);
  this.logger = Object.fromEntries(['debug','info','warn','error','fatal'].map(level => [level,(message:string,attributes:Record<string,unknown>={}) => this.log(level,message,attributes)])) as any;
 }
 async start() {
  const r = this.config.resource;
  const resource = resourceFromAttributes(resourceAttributes(r));
  const headers = {Authorization:`Bearer ${this.token}`};
  const owner=this;
  class MetricExporter extends OTLPMetricExporter {export(data:any,callback:any){super.export(data,result=>{owner.exportResult('metrics',result.code);callback(result);});}}
  class TraceExporter extends OTLPTraceExporter {export(data:any,callback:any){super.export(data,result=>{owner.pendingSpans=Math.max(0,owner.pendingSpans-data.length);owner.exportResult('traces',result.code);callback(result);});}}
  if(this.config.metrics?.mode === 'pull') this.reader = this.pull = new PrometheusExporter({preventServerStart:true,withoutScopeInfo:true,withoutTargetInfo:true});
  else this.reader = new PeriodicExportingMetricReader({exporter:new MetricExporter({url:this.config.endpoint+'/v1/metrics',headers,temporalityPreference:1,timeoutMillis:3000}),exportIntervalMillis:this.config.metrics?.intervalMs ?? 5000,exportTimeoutMillis:Math.min(1500,this.config.metrics?.intervalMs??5000)});
  const traceExporter=new TraceExporter({url:this.config.endpoint+'/v1/traces',headers,timeoutMillis:3000});
  const batch=new BatchSpanProcessor(traceExporter,{maxQueueSize:2048,maxExportBatchSize:512,scheduledDelayMillis:2000,exportTimeoutMillis:3500});
  const boundedProcessor={onStart:(span:any,parent:any)=>batch.onStart(span,parent),onEnd:(span:any)=>{if(this.pendingSpans>=2048){this.add('app_telemetry_dropped_total',1,{signal:'traces'});return;}this.pendingSpans++;batch.onEnd(span);},forceFlush:()=>batch.forceFlush(),shutdown:()=>batch.shutdown()};
  this.sdk = new NodeSDK({resource,sampler:new ParentBasedSampler({root:new TraceIdRatioBasedSampler(this.config.traces?.sampleRatio??1)}),metricReaders:[this.reader],spanProcessors:this.config.traces?.enabled===false?[]:[boundedProcessor],traceExporter:this.config.traces?.enabled === false ? undefined : new TraceExporter({url:this.config.endpoint+'/v1/traces',headers,timeoutMillis:3000}),instrumentations:this.config.traces?.enabled === false ? [] : [getNodeAutoInstrumentations({'@opentelemetry/instrumentation-fs':{enabled:false},'@opentelemetry/instrumentation-runtime-node':{enabled:false},'@opentelemetry/instrumentation-http':{ignoreIncomingRequestHook:req=>[this.config.readiness?.healthPath??'/health',this.config.readiness?.readyPath??'/ready',this.config.readiness?.metricsPath??'/metrics'].includes((req.url??'').split('?')[0]),ignoreOutgoingRequestHook:req=>String(req.hostname??req.host)===new URL(this.config.endpoint).hostname && Number(req.port??80)===Number(new URL(this.config.endpoint).port|| (new URL(this.config.endpoint).protocol==='https:'?443:80)) && (String(req.path??'').startsWith('/v1/') || String(req.path??'').startsWith('/api/ingest/')),requestHook:span=>{span.setAttribute('http.url','[redacted]');span.setAttribute('url.full','[redacted]');}},'@opentelemetry/instrumentation-undici':{enabled:true,ignoreRequestHook:req=>req.origin===new URL(this.config.endpoint).origin && (req.path.startsWith('/v1/')||req.path.startsWith('/api/ingest/')),requestHook:span=>{span.setAttribute('url.full','[redacted]');span.setAttribute('url.query','[redacted]');}}})],views:[{meterName:'@opentelemetry/instrumentation-undici',aggregation:{type:AggregationType.DROP}},{meterName:'@opentelemetry/instrumentation-http',aggregation:{type:AggregationType.DROP}},{instrumentName:'app_http_request_duration_seconds',aggregation:{type:AggregationType.EXPLICIT_BUCKET_HISTOGRAM,options:{boundaries:REQUEST_HISTOGRAM_BOUNDS}}}]});
  this.sdk.start(); this.meter=metrics.getMeter('portable-observability'); this.tracer=trace.getTracer('portable-observability');
  for(const n of ['app_http_requests_total','app_http_requests_aborted_total','app_errors_total','app_telemetry_export_failures_total','app_telemetry_dropped_total','app_jobs_completed_total','app_jobs_failed_total','app_jobs_retried_total']) this.instruments[n]=this.meter.createCounter(n);
  this.instruments.duration=this.meter.createHistogram('app_http_request_duration_seconds');
  this.instruments.jobsDuration=this.meter.createHistogram('app_job_duration_seconds');
  const base=this.labels();
  const gauge=(name:string,fn:()=>number)=>this.meter.createObservableGauge(name).addCallback(o=>o.observe(fn(),base));
  gauge('app_trace_queue_spans',()=>this.pendingSpans);
  gauge('app_log_queue_events',()=>this.queue.length);
  this.meter.createObservableGauge('app_telemetry_last_success_seconds').addCallback(o=>{for(const [signal,value] of Object.entries(this.signalSuccess))o.observe(value,{...base,signal});});
  gauge('app_http_requests_in_flight',()=>this.inflight);gauge('app_jobs_in_flight',()=>this.activeJobs);
  gauge('app_process_resident_memory_bytes',()=>process.memoryUsage().rss);gauge('app_process_heap_used_bytes',()=>process.memoryUsage().heapUsed);gauge('app_process_heap_total_bytes',()=>process.memoryUsage().heapTotal);gauge('app_process_uptime_seconds',()=>process.uptime());gauge('app_process_start_time_seconds',()=>this.startTime);
  this.meter.createObservableCounter('app_process_cpu_seconds_total').addCallback(o=>{const u=process.cpuUsage();o.observe((u.user+u.system)/1e6,base);});
  const delay=monitorEventLoopDelay({resolution:20});delay.enable();let elu=performance.eventLoopUtilization();let utilization=0;
  gauge('app_event_loop_delay_seconds',()=>Number.isFinite(delay.mean)?delay.mean/1e9:0);gauge('app_event_loop_utilization_ratio',()=>utilization);
  const gc=this.meter.createHistogram('app_gc_duration_seconds');const gcCount=this.meter.createCounter('app_gc_collections_total');const observer=new PerformanceObserver(list=>{for(const e of list.getEntries()){const attrs={...base,kind:String((e as any).detail?.kind??'unknown')};gc.record(e.duration/1000,attrs);gcCount.add(1,attrs);}});observer.observe({entryTypes:['gc']});
  this.cleanup=()=>{delay.disable();observer.disconnect();};
  this.intervals.push(setInterval(()=>{const next=performance.eventLoopUtilization();utilization=performance.eventLoopUtilization(next,elu).utilization;elu=next;},5000));
  const capability=this.meter.createObservableGauge('app_collector_capability');capability.addCallback(o=>{for(const [collector,state]of Object.entries(this.capabilities))o.observe(1,{...base,collector,state});});
  const build=this.meter.createObservableGauge('app_build_info');build.addCallback(o=>o.observe(1,{...base,build:this.config.resource.buildId??'development'}));
  this.intervals.push(setInterval(()=>void this.exportLogs(),1000));
  this.intervals.push(setInterval(()=>void this.sampleInfrastructure(),5000));void this.sampleInfrastructure();
  if(this.config.heartbeatIntervalMs) this.intervals.push(setInterval(()=>void this.heartbeat(),this.config.heartbeatIntervalMs));
  for(const t of this.intervals)t.unref();
 }
 createWinstonTransport(){const monitor=this;return new class extends Transport {log(info:any,callback:()=>void){const level=['debug','info','warn','error','fatal'].includes(info.level)?info.level:'info';monitor.log(level,String(info.message??'Application log'),info);this.emit('logged',info);callback();}}();}
 createPinoStream(){return new Writable({write:(chunk,_encoding,done)=>{try{const event=JSON.parse(String(chunk));const severity=event.level>=50?'error':event.level>=40?'warn':event.level>=30?'info':'debug';this.log(severity,event.msg??'Application log',event);done();}catch{done();}}});}
 private cleanup=()=>{};
 private labels(){const {project,service,environment,instance}=this.config.resource;return {project,service,environment,instance};}
 private add(name:string,value=1,attrs:Record<string,string>={}){this.instruments[name]?.add(value,{...attrs,...this.labels()});}
 private log(severity:string,message:string,attributes:Record<string,unknown>) {
  const s=trace.getSpan(context.active())?.spanContext();
  const event={eventId:randomUUID(),timestamp:Date.now(),severity,message:sanitize(message,0,this.config.logs?.redact),attributes:sanitize(attributes,0,this.config.logs?.redact),...(s?{traceId:s.traceId,spanId:s.spanId}:{})};
  if(this.config.logs?.stdout!==false)(this.stdout as any)[severity]({...event,resource:this.labels()},event.message);
  if(this.config.logs?.enabled===false || this.stopped)return;
  if(this.queue.length >= (this.config.logs?.queueSize??1000)){this.drops++;this.add('app_telemetry_dropped_total',1,{signal:'logs'});return;}this.queue.push(event);
 }
 private async post(path:string,body:unknown){return fetch(this.config.endpoint+path,{method:'POST',headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(3000)});}
 private async exportLogs(){
  if(this.exporting||!this.queue.length||Date.now()<this.retryAt)return;this.exporting=true;
  const batch=this.queue.splice(0,this.config.logs?.batchSize??128);
  try{const response=await this.post('/api/ingest/logs',{resource:this.labels(),events:batch});
   if(!response.ok){if(response.status>=500||response.status===429)throw new Error('retryable');this.drops+=batch.length;this.add('app_telemetry_dropped_total',batch.length,{signal:'logs'});}
   else {this.lastExport=Date.now();this.attempts=0;}
  }catch{this.failures++;this.add('app_telemetry_export_failures_total',1,{signal:'logs'});const room=Math.max(0,(this.config.logs?.queueSize??1000)-this.queue.length);this.queue.unshift(...batch.slice(0,room));this.drops+=batch.length-room;this.add('app_telemetry_dropped_total',batch.length-room,{signal:'logs'});this.retryAt=Date.now()+Math.min(30000,500*2**Math.min(++this.attempts,6))*(.75+Math.random()*.5);}
  finally{this.exporting=false;}
 }
 healthHandler=(_req:any,res:any)=>this.respond(_req,res,true);
 readyHandler=async(req:any,res:any)=>this.respond(req,res,await this.readiness.evaluate());
 metricsHandler=(req:any,res:any)=>{if(!this.authorized(req,res))return;if(!this.pull){res.statusCode=404;res.end();return;}this.pull.getMetricsRequestHandler(req,res);};
 private authorized(req:any,res:any){res.setHeader('Cache-Control','no-store');if(!['GET','HEAD'].includes(req.method)){res.statusCode=405;res.setHeader('Allow','GET, HEAD');res.end();return false;}if(this.config.readiness?.token&&req.headers.authorization!==`Bearer ${this.config.readiness.token}`){res.statusCode=401;res.end();return false;}return true;}
 private respond(req:any,res:any,ok:boolean){if(!this.authorized(req,res))return;res.statusCode=ok?200:503;res.setHeader('Content-Type','application/json');res.end(req.method==='HEAD'?undefined:JSON.stringify({status:ok?'ok':'unready'}));}
 observeRequest(method:string,route:string,status:number,durationSeconds:number,aborted=false){
  const attrs={method:BOUNDED_HTTP_METHODS.includes(method)?method:'OTHER',route:this.safeRoute(route),status_class:`${Math.floor(status/100)}xx`};
  if(aborted)this.add('app_http_requests_aborted_total',1,{method:attrs.method,route:attrs.route});else{this.add('app_http_requests_total',1,attrs);this.instruments.duration.record(durationSeconds,{...attrs,...this.labels()});}
 }
 private routes=new Set<string>();
 private safeRoute(route:string){if(!route.startsWith('/')||route.includes('?')||route.length>160||/[0-9]{3,}/.test(route))return 'unmatched';if(!this.routes.has(route)&&this.routes.size>=100)return 'other';this.routes.add(route);return route;}
 private routeOverrides=new WeakMap<object,string>();
 middleware(routeOverride?:string){return (req:any,res:any,next:()=>void)=>{if(routeOverride)this.routeOverrides.set(req,routeOverride);this.instrumentNative(req,res,()=>this.routeOverrides.get(req)??expressRoute(req));next();};}
 instrumentNative(req:IncomingMessage,res:ServerResponse,route:string|(()=>string)='unmatched'){
  const excluded=[this.config.readiness?.healthPath??'/health',this.config.readiness?.readyPath??'/ready',this.config.readiness?.metricsPath??'/metrics'];
  if(excluded.includes((req.url??'').split('?')[0])||this.attached.has(res))return false;this.attached.add(res);this.inflight++;const started=performance.now();let done=false;
  const finish=(aborted:boolean)=>{if(done)return;done=true;this.inflight--;this.observeRequest(req.method??'OTHER',typeof route==='function'?route():route,res.statusCode,(performance.now()-started)/1000,aborted);};res.once('finish',()=>finish(false));res.once('close',()=>finish(!res.writableFinished));return true;
 }
 errorMiddleware(){return (err:any,_req:any,_res:any,next:(e:any)=>void)=>{this.recordException(err);next(err);};}
 fastifyPlugin=async(app:any)=>{app.addHook('onRequest',(req:any,res:any,done:()=>void)=>{this.instrumentNative(req.raw,res.raw,()=>req.routeOptions?.url??'unmatched');done();});app.addHook('onError',(_req:any,_res:any,error:any,done:()=>void)=>{this.recordException(error);done();});};
 recordException(error:unknown,attrs:Record<string,unknown>={}){if(error&&typeof error==='object'){if(this.errors.has(error))return;this.errors.add(error);}this.add('app_errors_total',1,{kind:error instanceof TypeError?'type_error':'application_error'});const span=trace.getSpan(context.active());span?.recordException({name:error instanceof Error?error.name:'Error',message:sanitize(error instanceof Error?error.message:String(error))});span?.setStatus({code:SpanStatusCode.ERROR});this.logger.error('Application exception',{...attrs,error:sanitize(error instanceof Error?{name:error.name,message:error.message,stack:error.stack}:error)});}
 async withSpan<T>(name:string,attrs:Record<string,unknown>,callback:()=>Promise<T>):Promise<T>{return this.tracer.startActiveSpan(name.slice(0,128),{attributes:sanitize(attrs)},async span=>{try{return await callback();}catch(e){this.recordException(e);throw e;}finally{span.end();}});}
 customCounter(name:string,allowedLabels:Record<string,string[]>={}){return this.customInstrument('counter',name,allowedLabels);}
 customGauge(name:string,allowedLabels:Record<string,string[]>={}){return this.customInstrument('gauge',name,allowedLabels);}
 customHistogram(name:string,allowedLabels:Record<string,string[]>={}){return this.customInstrument('histogram',name,allowedLabels);}
 private customInstrument(kind:string,name:string,allowed:Record<string,string[]>){if(!/^app_business_[a-z_]{1,64}$/.test(name)||Object.keys(allowed).length>5||Object.values(allowed).some(v=>v.length>20))throw new Error('Custom instrument namespace or dimensions invalid');if(this.custom.size>=32&&!this.custom.has(name))throw new Error('Instrument limit');if(!this.custom.has(name))this.custom.set(name,kind==='counter'?this.meter.createCounter(name):kind==='gauge'?this.meter.createGauge(name):this.meter.createHistogram(name));const i=this.custom.get(name);return (value:number,labels:Record<string,string>={})=>{if(!Number.isFinite(value)||kind==='counter'&&value<0||Object.entries(labels).some(([k,v])=>!allowed[k]?.includes(v)))throw new Error('Unapproved metric dimension');const series=this.customSeries.get(name)??new Set<string>();const key=JSON.stringify(Object.entries(labels).sort());if(!series.has(key)&&series.size>=100)throw new Error('Custom series limit');series.add(key);this.customSeries.set(name,series);(kind==='counter'?i.add.bind(i):i.record.bind(i))(value,{...labels,...this.labels()});};}
 async heartbeat(){if(this.stopped)return;try{const r=await this.post('/api/ingest/heartbeat',{resource:this.labels(),bootId:this.bootId,sequence:++this.sequence,ready:this.readiness.ready,progress:this.progress,activeJobs:this.activeJobs,timestamp:Date.now()/1000});if(!r.ok)throw new Error('rejected');}catch{this.add('app_telemetry_export_failures_total',1,{signal:'heartbeat'});}}
 recordJobRetry(){this.add('app_jobs_retried_total');}
 reportProgress(){this.progress++;}
 async instrumentJob<T>(name:string,callback:()=>Promise<T>):Promise<T>{this.activeJobs++;const start=performance.now();const runId=randomUUID();await this.jobEvent('started',name,runId);try{const result=await this.withSpan('job.'+name,{},callback);this.add('app_jobs_completed_total');this.progress++;await this.jobEvent('completed',name,runId);return result;}catch(e){this.add('app_jobs_failed_total');await this.jobEvent('failed',name,runId);throw e;}finally{this.activeJobs--;this.instruments.jobsDuration.record((performance.now()-start)/1000,this.labels());}}
 private async jobEvent(state:string,name:string,runId:string){try{const response=await this.post('/api/ingest/job',{resource:this.labels(),state,name:name.slice(0,64),runId,bootId:this.bootId,timestamp:Date.now()/1000});if(!response.ok)throw new Error('Job event rejected');}catch{this.add('app_telemetry_export_failures_total',1,{signal:'jobs'});}}
 setReady(value:boolean){this.readiness.ready=value;}
 private exportResult(signal:string,code:number){if(code===0)this.signalSuccess[signal]=Date.now()/1000;else{this.signalFailures[signal]=(this.signalFailures[signal]??0)+1;this.add('app_telemetry_export_failures_total',1,{signal});}}
 diagnostics(){return {signalFailures:{...this.signalFailures},lastSuccessfulExports:{...this.signalSuccess},logQueue:this.queue.length,failures:this.failures,dropped:this.drops,lastSuccessfulLogExport:this.lastExport,capabilities:{...this.capabilities},mode:this.config.metrics?.mode??'push'};}
 private sampling=false;private infra:Record<string,number>={};private infraGauges=new Set<string>();
 private publish(name:string,value:number,scope:string){this.infra[name]=value;if(!this.infraGauges.has(name)){this.infraGauges.add(name);this.meter.createObservableGauge(name).addCallback(o=>{if(Number.isFinite(this.infra[name]))o.observe(this.infra[name],{...this.labels(),scope,hostId:this.config.resource.hostId??this.config.resource.instance});});}}
 private async sampleInfrastructure(){const c=this.config.infrastructure;if(!c||this.sampling||this.stopped)return;this.sampling=true;try{
  if(c.hostPublisher){const cpus=os.cpus();const times=cpus.reduce((a,c)=>({total:a.total+Object.values(c.times).reduce((x,y)=>x+y,0),idle:a.idle+c.times.idle}),{total:0,idle:0});if(this.cpuSnapshot&&times.total>this.cpuSnapshot.total)this.publish('app_host_cpu_utilization_ratio',1-(times.idle-this.cpuSnapshot.idle)/(times.total-this.cpuSnapshot.total),'os-visible');this.cpuSnapshot=times;this.capabilities.host='SUPPORTED';this.publish('app_host_cpu_cores',os.cpus().length,'os-visible');this.publish('app_host_memory_total_bytes',os.totalmem(),'os-visible');this.publish('app_host_memory_available_bytes',os.freemem(),'os-visible');this.publish('app_host_load_average',os.loadavg()[0],'os-visible');}
  if(c.filesystemPaths?.length){this.capabilities.filesystem='SUPPORTED';for(const [i,path]of c.filesystemPaths.slice(0,4).entries())try{const f=await statfs(path);this.publish(`app_filesystem_${i}_total_bytes`,f.blocks*f.bsize,'filesystem-visible');this.publish(`app_filesystem_${i}_free_bytes`,f.bavail*f.bsize,'filesystem-visible');}catch{this.capabilities.filesystem='UNSUPPORTED';delete this.infra[`app_filesystem_${i}_total_bytes`];delete this.infra[`app_filesystem_${i}_free_bytes`];}}
  if(c.cgroup){try{const values=await collectCgroup();this.capabilities.cgroup='SUPPORTED';for(const [name,value] of Object.entries(values))this.publish(name,value,'cgroup-v2');}catch{this.capabilities.cgroup='UNSUPPORTED';for(const key of Object.keys(this.infra))if(key.startsWith('app_container_'))delete this.infra[key];}}
 }finally{this.sampling=false;} }
 async forceFlush(){this.retryAt=0;const deadline=Date.now()+3000;while(this.queue.length&&Date.now()<deadline&&!this.stopped){const before=this.queue.length;await this.exportLogs();if(this.queue.length>=before)break;}await this.reader.forceFlush();}
 async shutdown(options:{timeoutMs?:number}={}){this.readiness.ready=false;for(const t of this.intervals)clearInterval(t);this.cleanup();await Promise.race([(async()=>{await this.forceFlush();this.stopped=true;await this.sdk.shutdown();})(),new Promise<void>(r=>{const t=setTimeout(()=>{this.stopped=true;r();},options.timeoutMs??5000);t.unref();})]);handle=undefined;signature=undefined;lifecycleClosed=true;}
}
