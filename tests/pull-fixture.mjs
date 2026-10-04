import {initializeMonitoring} from '@portable-observability/sdk';
import {readFileSync} from 'node:fs';
const m=await initializeMonitoring({resource:{project:'commerce',service:'orders-api',environment:'demo',instance:'orders-api-2'},endpoint:'http://localhost:8080',token:readFileSync('secrets/demo-orders','utf8').trim(),metrics:{mode:'pull'},traces:{enabled:false},logs:{enabled:false},heartbeatIntervalMs:60000});
const http=await import('node:http');const server=http.createServer((req,res)=>{if(req.url==='/metrics')return m.metricsHandler(req,res);m.instrumentNative(req,res,()=>'/pull/:id');res.end('ok');});server.listen(4202,'127.0.0.1');process.on('SIGTERM',async()=>{server.close();await m.shutdown();process.exit(0);});
