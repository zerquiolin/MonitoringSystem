import {fork} from 'node:child_process';
import http from 'node:http';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const secret=readFileSync(new URL('../secrets/operator-token',import.meta.url),'utf8').trim();
const children=new Map();const roles=['orders','orders2','catalog','worker','scheduler'];const logs=[];
function launch(role){const child=fork(fileURLToPath(new URL('./bootstrap.mjs',import.meta.url)),[],{env:{...process.env,DEMO_ROLE:role},stdio:['ignore','pipe','pipe','ipc']});children.set(role,child);child.stdout.on('data',d=>{logs.push(String(d));if(logs.length>100)logs.shift();});child.stderr.on('data',d=>process.stderr.write(role+': '+d));child.on('message',m=>{if(m.type==='ready')console.log(role+' ready'+(m.port?' on '+m.port:''));});child.on('exit',code=>{if(children.get(role)===child)children.delete(role);console.log(role+' stopped ('+code+')');});}
for(const role of roles)launch(role);
const control=http.createServer(async(req,res)=>{
 if(req.headers.authorization!==`Bearer ${secret}`){res.writeHead(401);res.end();return;}
 if(req.method==='GET'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({roles:[...children.keys()]}));return;}
 let body='';for await(const chunk of req){body+=chunk;if(body.length>4096){res.writeHead(413);res.end();return;}}
 try{const p=JSON.parse(body);if(!roles.includes(p.role))throw new Error('Unknown role');
  if(p.action==='stop')children.get(p.role)?.kill('SIGTERM');
  else if(p.action==='restart'){const c=children.get(p.role);if(c){c.once('exit',()=>launch(p.role));c.kill('SIGTERM');}else launch(p.role);}
  else if(p.action==='overflow')children.get(p.role)?.send({type:'overflow'});
  else children.get(p.role)?.send({type:'fault',values:p.values??{}});
  res.end(JSON.stringify({accepted:true}));
 }catch(e){res.writeHead(400);res.end(JSON.stringify({error:e.message}));}
});control.listen(4199,'127.0.0.1');
let running=true;async function traffic(){while(running){await Promise.allSettled([fetch('http://127.0.0.1:4101/orders/demo'),fetch('http://127.0.0.1:4102/products/demo'),fetch('http://127.0.0.1:4103/orders/demo')]);await new Promise(r=>setTimeout(r,250));}}void traffic();
function shutdown(){if(!running)return;running=false;control.close();for(const child of children.values())child.kill('SIGTERM');const t=setTimeout(()=>{for(const child of children.values())child.kill('SIGKILL');process.exit(0);},10000);t.unref();}
process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
console.log('Dummy workload running. Authenticated fault controls: 127.0.0.1:4199. Press Ctrl+C to stop.');
