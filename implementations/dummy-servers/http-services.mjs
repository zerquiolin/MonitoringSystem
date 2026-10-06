import http from 'node:http';
import express from 'express';
import Fastify from 'fastify';
import {DatabaseSync} from 'node:sqlite';
const database=new DatabaseSync(':memory:');database.exec("CREATE TABLE products(id TEXT PRIMARY KEY, price INTEGER); INSERT INTO products VALUES('demo',42)");
function requestJson(url){return new Promise((resolve,reject)=>{const req=http.get(url,{timeout:2000},res=>{let body='';res.on('data',d=>body+=d);res.on('end',()=>{try{resolve(JSON.parse(body));}catch(e){reject(e);}});});req.on('error',reject);req.on('timeout',()=>req.destroy(new Error('dependency deadline')));});}
export async function start(role,port,m,state){
 if(role==='orders'){
  const app=express();app.use(m.middleware());app.get('/health',m.healthHandler);app.get('/ready',m.readyHandler);
  app.get('/orders/:id',async(req,res,next)=>{try{await m.withSpan('orders.lookup',{},async()=>{if(state.slowMs)await new Promise(r=>setTimeout(r,state.slowMs));if(state.error)throw new Error('Injected order failure');const item=await requestJson('http://127.0.0.1:4102/products/demo');m.logger.info('Order lookup completed',{operation:'lookup',password:'SENSITIVE_FIXTURE',item});res.json({status:'ok',item});});}catch(e){next(e);}});
  app.get('/slow',async(_req,res)=>{await new Promise(r=>setTimeout(r,state.slowMs||1000));res.json({status:'ok'});});
  app.get('/error',(_req,_res,next)=>next(new TypeError('Injected caught exception')));
  app.get('/stream',(_req,res)=>{res.write('started\n');setTimeout(()=>res.end('finished\n'),1000);});
  app.use(m.errorMiddleware());app.use((_e,_req,res,_next)=>res.status(500).json({status:'error'}));
  return await new Promise(resolve=>{const server=app.listen(port,'0.0.0.0',()=>resolve(server));});
 }
 const app=Fastify();await m.fastifyPlugin(app);
 app.get('/health',(req,res)=>m.healthHandler(req.raw,res.raw));app.get('/ready',async(req,res)=>{res.hijack();await m.readyHandler(req.raw,res.raw);});
 app.get('/products/:id',async()=>m.withSpan('catalog.database.select',{operation:'select'},async()=>{if(state.dependencySlowMs)await new Promise(r=>setTimeout(r,state.dependencySlowMs));if(state.dependency)throw new Error('Database fixture unavailable');const result=database.prepare('SELECT price FROM products WHERE id=?').get('demo');m.logger.info('Catalog database query completed',{operation:'select'});return {status:'ok',price:result.price};}));
 await app.listen({host:'0.0.0.0',port});return {close:callback=>app.close().then(callback)};
}
