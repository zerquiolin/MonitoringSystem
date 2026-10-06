// Runs before framework and HTTP modules are loaded. Each service owns one SDK.
import {initializeMonitoring} from '@portable-observability/sdk';
import {fileURLToPath} from 'node:url';
import {readFileSync} from 'node:fs';
const definitions={orders:['orders-api','demo-orders',4101],orders2:['orders-api','demo-orders',4103],catalog:['catalog-api','demo-catalog',4102],worker:['billing-worker','demo-worker'],scheduler:['nightly-job','demo-scheduler']};
const role=process.env.DEMO_ROLE??'orders';const [service,ref,port]=definitions[role];
const state={dependency:false,slowMs:0,dependencySlowMs:0,error:false,heartbeatLoss:false,stall:false,missSchedule:false};
const tokenFile=fileURLToPath(new URL('../../monitoring-system/secrets/'+ref,import.meta.url));
const monitoring=await initializeMonitoring({resource:{project:'commerce',service,environment:'demo',instance:service+(role==='orders2'?'-2':'-1'),hostId:'demo-local',buildId:'demo-1'},endpoint:process.env.MONITORING_ENDPOINT??'http://localhost:8080',tokenFile,metrics:{mode:'push',intervalMs:2000},logs:{enabled:true,stdout:false,queueSize:500},traces:{enabled:true},readiness:{timeoutMs:500,checks:{dependency:{check:async()=>!state.dependency}}},infrastructure:{hostPublisher:role==='orders',filesystemPaths:role==='orders'?['.']:[],cgroup:true}});
process.on('message',async message=>{if(message.type==='fault'){Object.assign(state,message.values);if('drain'in message.values)monitoring.setReady(!message.values.drain);}if(message.type==='overflow'){for(let i=0;i<2000;i++)monitoring.logger.info('Burst fixture',{index:i,password:'SENSITIVE_FIXTURE'});}});
let server;let timer;let stalled=false;
if(role==='orders'||role==='orders2'||role==='catalog'){
 const {start}=await import('./http-services.mjs');server=await start(role==='orders2'?'orders':role,port,monitoring,state);
}else{
 timer=setInterval(async()=>{
  if(!state.heartbeatLoss)await monitoring.heartbeat();
  if(role==='worker'&&state.stall&&!stalled){stalled=true;void monitoring.instrumentJob('stalled',async()=>{while(state.stall)await new Promise(r=>setTimeout(r,500));stalled=false;});}
  if(role==='worker'&&!state.stall)await monitoring.instrumentJob('billing',async()=>{await new Promise(r=>setTimeout(r,50));monitoring.reportProgress();monitoring.logger.info('Billing job completed',{operation:'bill'});});
 },3000);
 if(role==='scheduler'){
  let lastMinute=-1;
  const scheduled=setInterval(async()=>{const minute=Math.floor(Date.now()/60000);if(minute!==lastMinute&&!state.missSchedule){lastMinute=minute;await monitoring.instrumentJob('nightly-summary',async()=>monitoring.logger.info('Scheduled report generated'));}},1000);
  process.once('SIGTERM',()=>clearInterval(scheduled));
 }
}
let ending=false;
async function stop(){if(ending)return;ending=true;monitoring.setReady(false);clearInterval(timer);const deadline=setTimeout(()=>process.exit(1),8000);if(server)await Promise.race([new Promise(r=>server.close(r)),new Promise(r=>setTimeout(r,3000))]);await monitoring.shutdown({timeoutMs:4000});clearTimeout(deadline);process.exit(0);}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
process.send?.({type:'ready',role,port});
