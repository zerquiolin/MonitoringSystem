import assert from 'node:assert/strict';
import {initializeMonitoring} from '../package/dist/index.js';
// SDK boot precedes HTTP modules; sink fails, then recovers without blocking the app.
const m=await initializeMonitoring({resource:{project:'test',service:'outage',environment:'test',instance:'one'},endpoint:'http://127.0.0.1:18419',token:'fixture',metrics:{mode:'push',intervalMs:1000},traces:{enabled:true},logs:{stdout:false,queueSize:50,batchSize:10}});
const http=await import('node:http');let fail=true;const ids=new Set();
const sink=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{if(fail){res.writeHead(503).end('{}');return;}if(req.url==='/api/ingest/logs')for(const event of JSON.parse(body).events)ids.add(event.eventId);res.writeHead(200,{'Content-Type':'application/json'}).end('{}');});});
await new Promise(r=>sink.listen(18419,'127.0.0.1',r));
const server=http.createServer((req,res)=>{m.instrumentNative(req,res,'/fixture');res.end('ok');});await new Promise(r=>server.listen(0,'127.0.0.1',r));
for(let i=0;i<1000;i++)m.logger.info('outage fixture',{password:'sensitive'});
const before=process.memoryUsage().rss;const began=performance.now();
for(let i=0;i<100;i++)await new Promise((r,j)=>http.get('http://127.0.0.1:'+server.address().port,res=>{res.resume();res.on('end',r);}).on('error',j));
assert.ok(performance.now()-began<3000,'requests blocked by exporter');await new Promise(r=>setTimeout(r,6000));
assert.ok(m.diagnostics().logQueue<=50);assert.ok(m.diagnostics().dropped>=950);assert.ok(m.diagnostics().signalFailures.metrics>0);
assert.ok(process.memoryUsage().rss-before<64*1024*1024,'unbounded SDK buffer');
fail=false;await m.forceFlush();assert.equal(m.diagnostics().logQueue,0);assert.ok(ids.size>0);
await m.shutdown({timeoutMs:4000});await new Promise(r=>server.close(r));await new Promise(r=>sink.close(r));
console.log('PASS bounded real exporter outage, request handling, diagnostics, queue overflow and recovery');
