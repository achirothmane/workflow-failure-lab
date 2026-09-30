import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { Store } from './store.mjs';
import { Secrets,tokenEquals,validateConfig } from './security.mjs';
import { ReleaseGuard } from './guard.mjs';
const env=process.env;
for(const k of ['DATABASE_URL','RESPONSE_KEY_HEX','DATA_TOKEN','ADMIN_TOKEN','UPSTREAM_TOKEN','ALLOWED_UPSTREAM_ORIGIN'])
 if(!env[k])throw Error('required: '+k);
for(const k of ['DATA_TOKEN','ADMIN_TOKEN','UPSTREAM_TOKEN'])if(env[k].length<32)throw Error(k+' must be >=32 characters');
if(env.DATA_TOKEN===env.ADMIN_TOKEN)throw Error('admin/data tokens must differ');
const store=new Store(env.DATABASE_URL);await store.init();await store.claim();
const secrets=new Secrets(env.RESPONSE_KEY_HEX);
const guard=new ReleaseGuard({store,secrets,upstreamToken:env.UPSTREAM_TOKEN});
const send=(res,status,body)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store','x-content-type-options':'nosniff'});res.end(JSON.stringify(body));};
async function body(req) {
 let size=0;const chunks=[];
 for await(const chunk of req){size+=chunk.length;if(size>262144){const e=Error('payload too large');e.status=413;throw e;}chunks.push(chunk);}
 try{return JSON.parse(Buffer.concat(chunks).toString('utf8')||'{}');}catch{const e=Error('invalid JSON');e.status=400;throw e;}
}
const server=http.createServer(async(req,res)=>{
 try {
  const url=new URL(req.url,'http://localhost');
  if(req.method==='GET'&&url.pathname==='/healthz')return send(res,200,{live:true});
  if(req.method==='GET'&&url.pathname==='/readyz'){await store.ready();return send(res,guard.blocked.size?503:200,{ready:guard.blocked.size===0,blockedReleases:[...guard.blocked.keys()]});}
  if(req.method==='GET'&&url.pathname==='/'){
   res.writeHead(200,{'content-type':'text/html; charset=utf-8','content-security-policy':"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"});return res.end(await readFile(new URL('../web/index.html',import.meta.url),'utf8'));
  }
  if(req.method==='GET'&&url.pathname==='/app.js'){res.writeHead(200,{'content-type':'text/javascript'});return res.end(await readFile(new URL('../web/app.js',import.meta.url),'utf8'));}
  const execution=/^\/v1\/execute\/([A-Za-z0-9_-]{1,80})$/.exec(url.pathname);
  const admin=tokenEquals(req.headers.authorization,'Bearer '+env.ADMIN_TOKEN);
  if(execution&&req.method==='POST'){
   if(!tokenEquals(req.headers.authorization,'Bearer '+env.DATA_TOKEN))return send(res,401,{error:'UNAUTHORIZED'});
   const id=req.headers['x-request-id']||randomUUID();
   if(typeof id!=='string'||!/^[A-Za-z0-9._-]{1,120}$/.test(id))return send(res,400,{error:'INVALID_REQUEST_ID'});
   const x=await guard.execute(execution[1],id,await body(req));return send(res,x.status,x.body);
  }
  if(!admin)return send(res,401,{error:'UNAUTHORIZED'});
  if(req.method==='POST'&&url.pathname==='/v1/releases'){
   const x=await body(req);if(!/^[A-Za-z0-9_-]{1,80}$/.test(x.id||''))return send(res,400,{error:'INVALID_RELEASE_ID'});
   let config;try{config=validateConfig(x.config,env.ALLOWED_UPSTREAM_ORIGIN);}catch(e){return send(res,400,{error:e.message});}
   return send(res,201,await store.create(x.id,config));
  }
  if(req.method==='POST'&&url.pathname==='/v1/evaluate'){
   const results=[];for(const id of await store.list())results.push({id,...await guard.evaluate(id)});return send(res,200,results);
  }
  const path=/^\/v1\/releases\/([A-Za-z0-9_-]{1,80})(?:\/(evaluate|rollback|evidence))?$/.exec(url.pathname);
  if(path){
   const [,id,action]=path;
   if(req.method==='GET'&&!action)return send(res,200,{release:await store.get(id),localFence:guard.blocked.get(id)||null});
   if(req.method==='GET'&&action==='evidence'){
    const after=Number(url.searchParams.get('after')||0);if(!Number.isSafeInteger(after)||after<0)return send(res,400,{error:'INVALID_CURSOR'});
    return send(res,200,{evidence:await store.evidence(id,after)});
   }
   if(req.method==='POST'&&action==='evaluate')return send(res,200,await guard.evaluate(id));
   if(req.method==='POST'&&action==='rollback')return send(res,200,await guard.rollback(id));
  }
  return send(res,404,{error:'NOT_FOUND'});
 }catch(e){send(res,e.status||503,{error:e.code==='23505'?'RELEASE_EXISTS':e.status?e.message:'OPERATION_UNAVAILABLE'});}
});
server.requestTimeout=15000;server.headersTimeout=10000;server.maxHeadersCount=30;

let ticking=false;
async function tick(){
 if(ticking)return;ticking=true;
 try {
  for(const id of await store.list())await guard.evaluate(id);
  for(const x of await store.outbox()){
   if(!env.ALERT_URL)continue;
   try {
    const response=await fetch(env.ALERT_URL,{method:'POST',redirect:'manual',signal:AbortSignal.timeout(5000),
     headers:{'content-type':'application/json','x-releaseguard-alert':env.ALERT_TOKEN||''},body:JSON.stringify(x.body)});
    if(!response.ok)throw Error('alert rejected');await store.delivered(x.release_id,x.seq);
   }catch{await store.deliveryFailed(x.release_id,x.seq,x.attempts);}
  }
 }catch{console.error(JSON.stringify({event:'EVALUATOR_UNAVAILABLE',at:Date.now()}));}
 finally{ticking=false;}
}
await tick();
server.listen(Number(env.PORT||8080),'0.0.0.0',()=>console.log(JSON.stringify({event:'RELEASEGUARD_STARTED',port:Number(env.PORT||8080),version:'0.1.0'})));
const timer=setInterval(tick,5000);
async function stop(){clearInterval(timer);for(const id of await store.list().catch(()=>[]))guard.abort(id);server.close(async()=>{await store.close();process.exit(0);});setTimeout(()=>process.exit(1),12000).unref();}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
