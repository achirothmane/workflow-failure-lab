import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { Store,digest } from '../../src/store.mjs';
import { Secrets,validateConfig } from '../../src/security.mjs';
import { ReleaseGuard } from '../../src/guard.mjs';
const store=new Store(process.env.DATABASE_URL);await store.init();
const secrets=new Secrets('ab'.repeat(32));
const evidence=[];const logs=[];let calls={stable:0,candidate:0};
const upstream=http.createServer(async(req,res)=>{
 const arm=req.url.includes('candidate')?'candidate':'stable';calls[arm]++;
 const chunks=[];for await(const c of req)chunks.push(c);const p=JSON.parse(Buffer.concat(chunks));
 const fault=p[arm]||'none';
 if(fault==='delay')await new Promise(r=>setTimeout(r,120));
 if(fault==='error'||fault==='partial'&&p.sequence%4===0){res.writeHead(500);return res.end('broken');}
 if(fault==='redirect'){res.writeHead(302,{location:'http://169.254.169.254/'});return res.end();}
 if(fault==='malformed'){res.writeHead(200);return res.end('not-json');}
 const result={score:fault==='invalid'?'bad':75,engine:arm};
 res.writeHead(200,{'content-type':'application/json'});
 res.end(JSON.stringify({releaseguardVersion:fault==='version'?'unexpected':arm+'-v1',result}));
});
upstream.listen(0,'127.0.0.1');await once(upstream,'listening');
const origin='http://127.0.0.1:'+upstream.address().port;
const makeConfig=(override={})=>validateConfig({stable:{url:origin+'/webhook/stable',version:'stable-v1'},candidate:{url:origin+'/webhook/candidate',version:'candidate-v1'},fallbackMode:'read_only',outputSchema:{type:'object',required:['score','engine'],additionalProperties:false,properties:{score:{type:'number',minimum:0,maximum:100},engine:{type:'string'}}},
 policy:{minStageMs:1,windowMs:1800000,maxMetricAgeMs:60000,...override}},origin);
const guard=new ReleaseGuard({store,secrets,upstreamToken:'test'.repeat(12),log:x=>logs.push(JSON.parse(x))});
function key(id,arm='candidate'){for(let i=0;;i++){const s='req-'+i;if((secrets.bucket(id,s)<5)===(arm==='candidate'))return s;}}
async function create(id,p={}){return store.create(id,makeConfig(p));}
async function seed(id,arm,n,{errors=0,invalid=0,latency=100,incomplete=0}={}){
 const {rows:[r]}=await store.pool.query('SELECT epoch,revision FROM rg_releases WHERE id=$1',[id]);
 await store.pool.query("INSERT INTO rg_requests(release_id,id,fingerprint,owner,status) VALUES($1,$2,'seed','test','DONE') ON CONFLICT DO NOTHING",[id,'seed']);
 await store.pool.query("INSERT INTO rg_attempts(id,release_id,request_id,epoch,revision,arm,source,dispatched,settled,ok,valid,latency_ms,finished_at) SELECT gen_random_uuid(),$1,'seed',$2,$3,$4,'route',true,true,(i>$6),(i>$7),CASE WHEN i<=$8 THEN NULL ELSE $9::float8 END,clock_timestamp() FROM generate_series(1,$5::integer) i",
 [id,r.epoch,r.revision,arm,n,errors,invalid,incomplete,latency]);
}
async function record(id,label){evidence.push({label,release:await store.get(id),audit:await store.evidence(id,0,1000)});}
try{
 await test('invalid Candidate is detected through actual HTTP, falls back, and routes the next request to Stable',async()=>{
  await create('invalid');const x=await guard.execute('invalid',key('invalid'),{candidate:'invalid'});
  assert.equal(x.status,200);assert.equal(x.body.servedBy,'stable');assert.equal(x.body.fallback,true);
  assert.equal((await store.get('invalid')).status,'ROLLED_BACK');const before=calls.candidate;
  const next=await guard.execute('invalid','next',{candidate:'none'});assert.equal(next.body.servedBy,'stable');assert.equal(calls.candidate,before);
  const {rows}=await store.pool.query("SELECT arm,source,ok,valid FROM rg_attempts WHERE release_id='invalid'");
  assert.ok(rows.some(x=>x.arm==='candidate'&&x.ok===true&&x.valid===false));
  assert.ok(rows.some(x=>x.source==='fallback'&&x.ok&&x.valid));await record('invalid','HTTP invalid-output rollback');
 });
 await test('partial Candidate HTTP failures cannot be masked by successful fallback',async()=>{
  await create('partial');let seq=0;
  for(let i=0;i<200&&(await store.get('partial')).status==='RUNNING';i++){
   const id='partial-'+i;if(secrets.bucket('partial',id)>=5)continue;
   await guard.execute('partial',id,{candidate:'partial',sequence:seq++});
  }
  // Use selected request IDs to ensure the early window has at least 20 real executions.
  for(let i=200;seq<24&&(await store.get('partial')).status==='RUNNING';i++){
   const id='partial-'+i;if(secrets.bucket('partial',id)>=5)continue;
   await guard.execute('partial',id,{candidate:'partial',sequence:seq++});
  }
  assert.equal((await store.get('partial')).status,'ROLLED_BACK');await record('partial','partial HTTP failures');
 });
 await test('latency regression uses measured wall time, not workflow supplied metrics',async()=>{
  await create('latency',{earlyMin:4,maxP95Ms:80,requestTimeoutMs:1000,leaseMs:30000});
  for(let i=0,n=0;n<4;i++){const id='slow-'+i;if(secrets.bucket('latency',id)>=5)continue;await guard.execute('latency',id,{candidate:'delay'});n++;}
  const d=await guard.evaluate('latency');assert.equal(d.decision,'ROLLBACK');assert.equal(d.reason,'CANDIDATE_LATENCY_SLO');await record('latency','measured HTTP latency');
 });
 await test('missing observations produce HOLD and close Candidate admission',async()=>{
  await create('missing');await seed('missing','stable',200);await seed('missing','candidate',200,{incomplete:1});
  const d=await guard.evaluate('missing');assert.equal(d.reason,'METRICS_INCOMPLETE');assert.equal(d.after.candidatePct,0);await record('missing','incomplete metrics');
 });
 await test('insufficient evidence never promotes and keeps current bounded sample traffic',async()=>{
  await create('insufficient');await seed('insufficient','stable',4);await seed('insufficient','candidate',3);
  const d=await guard.evaluate('insufficient');assert.equal(d.reason,'INSUFFICIENT_SAMPLES');assert.equal(d.after.stage,0);assert.equal(d.after.candidatePct,5);
 });
 await test('Stable failures cause HOLD rather than accidental Candidate promotion',async()=>{
  await create('stablebad');await seed('stablebad','stable',200,{errors:30});await seed('stablebad','candidate',200);
  const d=await guard.evaluate('stablebad');assert.equal(d.reason,'STABLE_UNHEALTHY');assert.equal(d.after.status,'PAUSED');
  const x=await guard.execute('stablebad','affected',{stable:'error'});assert.equal(x.status,503);await record('stablebad','Stable incident');
 });
 await test('all four progressive stages require new evidence and final 100% verification',async()=>{
  await create('healthy',{healthyWindows:1});
  for(let stage=0;stage<4;stage++){
   await seed('healthy','stable',200);await seed('healthy','candidate',200);
   const d=await guard.evaluate('healthy');assert.equal(d.decision,'PROMOTE');assert.equal(d.after.stage,Math.min(stage+1,3));
  }
  assert.equal((await store.get('healthy')).status,'COMPLETED');await record('healthy','5→25→50→100→verified');
 });
 await test('100% continues Stable control probes and post-promotion regression protection',async()=>{
  let id;for(let i=0;;i++){id='probe-'+i;if(secrets.bucket('healthy',id,'probe')<10)break;}
  const x=await guard.execute('healthy',id,{});assert.equal(x.body.servedBy,'candidate');
  const {rows}=await store.pool.query("SELECT arm,source FROM rg_attempts WHERE release_id='healthy' AND request_id=$1",[id]);
  assert.ok(rows.some(x=>x.arm==='stable'&&x.source==='probe'));
  const bad=await guard.execute('healthy','post-promotion',{candidate:'invalid'});assert.equal(bad.body.servedBy,'stable');assert.equal((await store.get('healthy')).status,'ROLLED_BACK');
 });
 await test('concurrent evaluations cannot double promote or reuse evidence',async()=>{
  await create('concurrent',{healthyWindows:1});await seed('concurrent','stable',200);await seed('concurrent','candidate',200);
  const ds=await Promise.all(Array.from({length:8},()=>guard.evaluate('concurrent')));
  assert.equal(ds.filter(x=>x.decision==='PROMOTE').length,1);assert.equal((await store.get('concurrent')).stage,1);
 });
 await test('a ticket reserved before rollback is fenced before upstream dispatch',async()=>{
  await create('fenced');const id=key('fenced');const r=await store.reserve('fenced',id,'fp','owner',0,99);
  await guard.rollback('fenced');assert.equal(await store.fence(r.ticket),false);
 });
 await test('rollback commit failure never claims success and rejects subsequent Candidate traffic',async()=>{
  await create('failedrollback');
  await store.pool.query("CREATE OR REPLACE FUNCTION rg_test_reject_rollback() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id='failedrollback' AND NEW.status='ROLLED_BACK' THEN RAISE EXCEPTION 'injected commit failure'; END IF;RETURN NEW;END $$");
  await store.pool.query('CREATE TRIGGER rg_reject BEFORE UPDATE ON rg_releases FOR EACH ROW EXECUTE FUNCTION rg_test_reject_rollback()');
  try{
   const x=await guard.execute('failedrollback',key('failedrollback'),{candidate:'invalid'});
   assert.equal(x.status,503);assert.equal((await store.get('failedrollback')).status,'RUNNING');
   const count=calls.candidate;const next=await guard.execute('failedrollback','next',{});assert.equal(next.status,503);assert.equal(calls.candidate,count);
   assert.ok(logs.some(x=>x.reason==='EVALUATION_OR_ROLLBACK_COMMIT_FAILED'));
  }finally{await store.pool.query('DROP TRIGGER rg_reject ON rg_releases');await store.pool.query('DROP FUNCTION rg_test_reject_rollback()');}
  const recovery=await guard.rollback('failedrollback');assert.equal(recovery.after.status,'ROLLED_BACK');await record('failedrollback','failed commit and recovery');
 });
 await test('automatic rollback raises admission fence before the safety mutation is confirmed',async()=>{
  await create('autofence');await seed('autofence','candidate',1,{invalid:1});
  const original=store.evaluate.bind(store);let sawFence=false;
  store.evaluate=async(id,callback)=>original(id,d=>{callback(d);sawFence=guard.admissionPaused.has(id);});
  try{const d=await guard.evaluate('autofence');assert.equal(d.decision,'ROLLBACK');assert.equal(sawFence,true);assert.equal(guard.admissionPaused.has('autofence'),false);}
  finally{store.evaluate=original;}
 });
 await test('delayed rollback immediately fences this single process before database commit',async()=>{
  await create('delayed');const c=await store.pool.connect();await c.query('BEGIN');await c.query("SELECT id FROM rg_releases WHERE id='delayed' FOR UPDATE");
  const pending=guard.rollback('delayed');const before=calls.candidate;
  const x=await guard.execute('delayed',key('delayed'),{});assert.equal(x.status,503);assert.equal(calls.candidate,before);
  await new Promise(r=>setTimeout(r,80));await c.query('ROLLBACK');c.release();assert.equal((await pending).after.status,'ROLLED_BACK');
 });
 await test('expired evaluator lease routes to Stable without a working heartbeat',async()=>{
  await create('expired');await store.pool.query("UPDATE rg_releases SET lease_until=clock_timestamp()-interval '1 second' WHERE id='expired'");
  const x=await guard.execute('expired',key('expired'),{});assert.equal(x.body.servedBy,'stable');
 });
 await test('request retries replay encrypted response without another workflow execution',async()=>{
  await create('retry');const id=key('retry','stable');const before=calls.stable;
  const first=await guard.execute('retry',id,{x:1});const second=await guard.execute('retry',id,{x:1});
  assert.deepEqual(second.body,first.body);assert.equal(second.replayed,true);assert.equal(calls.stable,before+1);
  assert.equal((await guard.execute('retry',id,{x:2})).status,409);
 });
 await test('concurrent duplicate request does not execute twice',async()=>{
  await create('dupe');const id=key('dupe','stable');const before=calls.stable;
  const [a,b]=await Promise.all([guard.execute('dupe',id,{stable:'delay'}),guard.execute('dupe',id,{stable:'delay'})]);
  assert.deepEqual([a.status,b.status].sort(),[200,409]);assert.equal(calls.stable,before+1);
 });
 await test('version mismatch and malformed output both roll back',async()=>{
  for(const fault of ['version','malformed']){await create(fault);const x=await guard.execute(fault,key(fault),{candidate:fault});assert.equal(x.body.servedBy,'stable');assert.equal((await store.get(fault)).status,'ROLLED_BACK');}
 });
 await test('redirects are not followed and stay observed as errors',async()=>{
  await create('redirect');const x=await guard.execute('redirect',key('redirect'),{candidate:'redirect'});assert.equal(x.body.servedBy,'stable');
  const {rows:[a]}=await store.pool.query("SELECT reason FROM rg_attempts WHERE release_id='redirect' AND arm='candidate'");assert.equal(a.reason,'HTTP_302');
 });
 await test('audit chain is verifiable and decision, revision, and config are bound',async()=>{
  for(const id of ['invalid','healthy','failedrollback']){
   const xs=await store.evidence(id,0,1000);let prev='';
   for(const x of xs){assert.equal(x.previousHash,prev);assert.equal(x.hash,digest({previousHash:prev,record:x.record}));prev=x.hash;}
   assert.equal((await store.get(id)).auditHead,prev);
  }
 });
 await test('second controller is rejected by the database singleton lock',async()=>{
  await store.claim();const second=new Store(process.env.DATABASE_URL);
  try{await assert.rejects(()=>second.claim(),/one ReleaseGuard process/);}finally{await second.close();}
 });
 await test('alerts survive receiver downtime in a transactional outbox',async()=>{
  const xs=await store.outbox();assert.ok(xs.some(x=>x.body.decision==='ROLLBACK'));const a=xs[0];
  await store.deliveryFailed(a.release_id,a.seq,a.attempts);
  const {rows:[r]}=await store.pool.query('SELECT attempts,delivered_at,next_at FROM rg_outbox WHERE release_id=$1 AND seq=$2',[a.release_id,a.seq]);
  assert.equal(r.attempts,1);assert.equal(r.delivered_at,null);
 });
 const {mkdir,writeFile}=await import('node:fs/promises');await mkdir('evidence',{recursive:true});
 await writeFile('evidence/adversarial-results.json',JSON.stringify({runtime:'Node HTTP + PostgreSQL (not mocks)',cases:evidence,failClosedEvents:logs},null,2));
}finally{await store.close();upstream.close();}
