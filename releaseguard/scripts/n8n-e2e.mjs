// Disposable CI environment only: boots real n8n, imports JSON, publishes each flow,
// runs the fault matrix through its production webhooks, and captures real UI evidence.
import {execFileSync} from 'node:child_process';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {Secrets} from '../src/security.mjs';
const env=process.env, n8n='http://127.0.0.1:5678', api='http://127.0.0.1:8080';
const secrets=new Secrets(env.RESPONSE_KEY_HEX);const results=[];
const docker=(args)=>execFileSync('docker',args,{stdio:['ignore','pipe','pipe'],timeout:180000}).toString();
async function wait(url){for(let i=0;i<120;i++){try{if((await fetch(url)).ok)return;}catch{}await new Promise(r=>setTimeout(r,1000));}throw Error('not ready: '+url);}
async function call(path,{method='POST',data,headers={}}={}){
 const res=await fetch(api+path,{method,headers:{'content-type':'application/json',authorization:'Bearer '+env.ADMIN_TOKEN,...headers},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(30000)});
 const body=await res.json();return {status:res.status,body};
}
const config=(p={})=>({stable:{url:n8n+'/webhook/releaseguard-stable',version:'stable-v1'},candidate:{url:n8n+'/webhook/releaseguard-candidate',version:'candidate-v1'},fallbackMode:'read_only',
 inputSchema:{"type":"object","required":["leadId"],"additionalProperties":false,"properties":{"leadId":{"type":"string","minLength":1,"maxLength":200},"score":{"type":"number","minimum":0,"maximum":100},"sequence":{"type":"integer","minimum":0},"faultCandidate":{"type":"string","enum":["none","error","partial","latency","invalid","semantic"]},"faultStable":{"type":"string","enum":["none","error","partial","latency","invalid","semantic"]}}},outputSchema:JSON.parse(demoSchema()),policy:p});
function demoSchema(){return JSON.stringify({allOf:[{"if":{"type":"object","required":["score"],"properties":{"score":{"type":"number","minimum":70}}},"then":{"type":"object","properties":{"priority":{"const":"HIGH"}}},"else":{"type":"object","properties":{"priority":{"const":"NORMAL"}}}}],type:'object',required:['leadId','score','priority','engine'],additionalProperties:false,properties:{leadId:{type:'string',minLength:1},score:{type:'number',minimum:0,maximum:100},priority:{type:'string',enum:['HIGH','NORMAL']},engine:{type:'string',enum:['stable','candidate']}}});}
async function create(id,p={}){const x=await call('/v1/releases',{data:{id,config:config(p)}});assert.equal(x.status,201,JSON.stringify(x));}
async function execute(id,key,payload){return call('/v1/execute/'+id,{headers:{authorization:'Bearer '+env.DATA_TOKEN,'x-request-id':key},data:payload});}
function requestKey(id,pct,candidate=true,start=0,probe=false){for(let i=start;;i++){const key='e2e-'+i;if((secrets.bucket(id,key)<pct)===candidate&&(!probe||secrets.bucket(id,key,'probe')<10))return {key,next:i+1};}}
async function snapshot(id,label){const r=await call('/v1/releases/'+id,{method:'GET'}),e=await call('/v1/releases/'+id+'/evidence',{method:'GET'});results.push({label,...r.body,...e.body});return r.body.release;}
const owner={email:'releaseguard-test@example.test',firstName:'ReleaseGuard',lastName:'CI',password:'ReleaseGuard-Test-Only-2026!'};
await mkdir('tmp/n8n',{recursive:true});await mkdir('evidence',{recursive:true});
const creds=[
 {id:'rgupstreamcred01',name:'ReleaseGuard upstream',type:'httpHeaderAuth',data:{name:'x-releaseguard-upstream',value:env.UPSTREAM_TOKEN}},
 {id:'rgclientcred01',name:'ReleaseGuard client',type:'httpHeaderAuth',data:{name:'x-releaseguard-client',value:'ci-client-secret-'+'z'.repeat(32)}},
 {id:'rgdatacred01',name:'ReleaseGuard data',type:'httpHeaderAuth',data:{name:'Authorization',value:'Bearer '+env.DATA_TOKEN}},
 {id:'rgalertcred01',name:'ReleaseGuard alerts',type:'httpHeaderAuth',data:{name:'x-releaseguard-alert',value:env.ALERT_TOKEN}}
];
await writeFile('tmp/n8n/credentials.json',JSON.stringify(creds),{mode:0o644});
const workflows=[];
for(const name of ['stable','candidate','gateway','alerts']){
 const w=JSON.parse(await readFile('workflows/'+name+'.json','utf8'));
 for(const node of w.nodes){
  if(node.type==='n8n-nodes-base.webhook'){
   const c=creds.find(c=>c.id===({stable:'rgupstreamcred01',candidate:'rgupstreamcred01',gateway:'rgclientcred01',alerts:'rgalertcred01'}[name]));
   node.credentials={httpHeaderAuth:{id:c.id,name:c.name}};
  }
  if(node.type==='n8n-nodes-base.httpRequest')node.credentials={httpHeaderAuth:{id:'rgdatacred01',name:'ReleaseGuard data'}};
  if(node.name==='Validate and identify request')node.parameters.jsCode=node.parameters.jsCode.replace('http://releaseguard:8080','http://host.docker.internal:8080');
 }
 workflows.push(w);
}
await writeFile('tmp/n8n/workflows.json',JSON.stringify(workflows));
const container='releaseguard-n8n-e2e';
docker(['run','-d','--name',container,'--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:5678:5678',
 '-e','N8N_DIAGNOSTICS_ENABLED=false','-e','N8N_PERSONALIZATION_ENABLED=false','-e','N8N_SECURE_COOKIE=false',
 '-e','N8N_ENCRYPTION_KEY=rg-test-only-persistent-key-'+'x'.repeat(32),
 '-v','rg-n8n-e2e:/home/node/.n8n','-v',process.cwd()+'/tmp/n8n:/fixtures:ro',
 'docker.n8n.io/n8nio/n8n:2.41.4']);
try{
 await wait(n8n+'/healthz/readiness');
 const setup=await fetch(n8n+'/rest/owner/setup',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(owner)});
 assert.ok(setup.ok,'fresh n8n owner setup failed: '+setup.status+' '+await setup.text());
 docker(['exec',container,'n8n','import:credentials','--input=/fixtures/credentials.json']);
 docker(['exec',container,'n8n','import:workflow','--input=/fixtures/workflows.json']);
 for(const w of workflows)docker(['exec',container,'n8n','publish:workflow','--id='+w.id]);
 docker(['restart',container]);await wait(n8n+'/healthz/readiness');await wait(api+'/healthz');
 // Actual ingress → sidecar → Candidate → Stable fallback → actual ingress response.
 await create('demo');const selected=requestKey('demo',5).key;
 const r=await fetch(n8n+'/webhook/releaseguard',{method:'POST',headers:{'content-type':'application/json','x-releaseguard-client':creds[1].data.value,'x-request-id':selected},body:JSON.stringify({leadId:'LEAD-1042',score:81,faultCandidate:'invalid'})});
 const raw=await r.text();
 if(!r.headers.get('content-type')?.includes('json'))throw Error('Gateway returned '+r.status+' '+r.headers.get('content-type')+' '+raw.slice(0,1800));
 const b=JSON.parse(raw);assert.equal(r.status,200,JSON.stringify(b));assert.equal(b.servedBy,'stable');assert.equal(b.fallback,true);assert.equal(b.result.score,81);
 assert.equal((await snapshot('demo','REAL N8N INGRESS: invalid output → fallback → rollback')).status,'ROLLED_BACK');
 const next=await execute('demo','after-rollback',{leadId:'LEAD-1043',score:81});assert.equal(next.body.servedBy,'stable');
 console.log('PASS real n8n gateway, schema failure detection, request fallback, automatic rollback, next-request Stable routing');
 await create('real-semantic');
 const semanticKey=requestKey('real-semantic',5).key;
 const semantic=await execute('real-semantic',semanticKey,{leadId:'SEM-1',score:81,faultCandidate:'semantic'});
 assert.equal(semantic.body.servedBy,'stable');assert.equal(semantic.body.result.priority,'HIGH');
 assert.equal((await snapshot('real-semantic','REAL N8N cross-field business invariant failure')).status,'ROLLED_BACK');
 console.log('PASS real n8n business invariant: plausible but inconsistent output is rejected');
 // Full/partial failures and latency are produced inside the imported Candidate Code node.
 for(const fault of ['error','partial','latency']){
  const id='real-'+fault;await create(id,{earlyMin:fault==='partial'?8:4,earlyErrorRate:.20,maxP95Ms:250});
  let start=0;for(let i=0;i<(fault==='partial'?8:4);i++){
   const k=requestKey(id,5,true,start);start=k.next;
   await execute(id,k.key,{leadId:'FAULT-'+i,score:50,faultCandidate:fault,sequence:i});
  }
  await call('/v1/releases/'+id+'/evaluate');
  assert.equal((await snapshot(id,'REAL N8N Candidate '+fault)).status,'ROLLED_BACK');
  console.log('PASS real n8n '+fault+' regression');
 }
 // Accelerated test policy; production defaults still require 200 per arm, two windows, 5-minute dwell.
 const healthyPolicy={minCandidate:20,minStable:20,minStageMs:1,healthyWindows:1,freshBatch:10,maxErrorRate:.20,maxErrorDelta:.20,maxMetricAgeMs:300000};
 await create('real-healthy',healthyPolicy);let cursor=0;
 for(let stage=0;stage<4;stage++){
  const pct=[5,25,50,100][stage];
  for(const arm of pct===100?['candidate']:['stable','candidate']){
   for(let i=0;i<20;i++){
    const k=requestKey('real-healthy',pct,arm==='candidate',cursor,pct===100);cursor=k.next;
    const x=await execute('real-healthy',k.key,{leadId:'H-'+stage+'-'+arm+'-'+i,score:75});assert.equal(x.status,200,JSON.stringify(x));
   }
  }
  const d=await call('/v1/releases/real-healthy/evaluate');
  assert.equal(d.body.after.stage,Math.min(stage+1,3),JSON.stringify(d));
 }
 assert.equal((await snapshot('real-healthy','REAL N8N 5→25→50→100→verified (accelerated policy)')).status,'COMPLETED');
 console.log('PASS real n8n progressive promotion with live Stable probes at 100%');
 // Show a genuine failure in Stable; do not let a healthy Candidate conceal it.
 await create('real-stablebad',{earlyMin:4});let s=0;
 for(let i=0;i<4;i++){const k=requestKey('real-stablebad',5,false,s);s=k.next;assert.equal((await execute('real-stablebad',k.key,{leadId:'S-'+i,faultStable:'error'})).status,503);}
 await call('/v1/releases/real-stablebad/evaluate');assert.equal((await call('/v1/releases/real-stablebad',{method:'GET'})).body.release.status,'PAUSED');
 await snapshot('real-stablebad','REAL N8N Stable failure');
 console.log('PASS real n8n Stable failure is visible; no promotion');
 // Tamper evidence is validated using exactly the server's canonical hashing.
 const {digest}=await import('../src/store.mjs');
 for(const x of results){let previous='';for(const e of x.evidence){assert.equal(e.previousHash,previous);assert.equal(e.hash,digest({previousHash:previous,record:e.record}));previous=e.hash;}assert.equal(previous,x.release.auditHead);}
 await writeFile('evidence/n8n-e2e-results.json',JSON.stringify({n8nVersion:'2.41.4',runtime:'actual n8n production webhooks + Node HTTP + PostgreSQL',gatewayResponse:b,cases:results},null,2));
 // Actual browser screenshots, never invented or generated product claims.
 const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
 const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1100}});
 try{
  const page=await context.newPage();await page.goto(api);await page.fill('#token',env.ADMIN_TOKEN);await page.fill('#release','demo');await page.click('#load');
  await page.waitForFunction(()=>document.querySelector('#integrity').textContent.includes('verified'));
  await page.screenshot({path:'evidence/01-real-rollback-dashboard.png',fullPage:true});
  await page.fill('#release','real-healthy');await page.click('#load');await page.waitForFunction(()=>document.querySelector('#state').textContent==='COMPLETED');
  await page.screenshot({path:'evidence/02-real-promotion-dashboard.png',fullPage:true});
  const login=await context.request.post(n8n+'/rest/login',{data:{emailOrLdapLoginId:owner.email,password:owner.password}});
  assert.ok(login.ok(),'n8n screenshot login failed');
  await page.goto(n8n+'/workflow/rg-gateway');await page.waitForTimeout(3500);
  await page.screenshot({path:'evidence/03-real-n8n-gateway-canvas.png',fullPage:true});
  console.log('PASS actual browser captures: rollback, verified promotion, n8n gateway canvas');
 }finally{await browser.close();}
}catch(e){console.error('N8N_RUNTIME_DIAGNOSTIC\n'+docker(['logs',container]).slice(-14000));throw e;}
finally{
 await writeFile('evidence/n8n-runtime.log',docker(['logs',container]).replaceAll(env.UPSTREAM_TOKEN,'[redacted]').replaceAll(env.DATA_TOKEN,'[redacted]'));
 docker(['rm','-f',container]);
}
