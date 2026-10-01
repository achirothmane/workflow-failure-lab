import pg from 'pg';
import { randomUUID,createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { decide } from './policy.mjs';
const { Pool }=pg;
export const canonical = v => {
 if (Array.isArray(v)) return '['+v.map(canonical).join(',')+']';
 if (v && typeof v==='object') return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
 return JSON.stringify(v);
};
export const digest = v => createHash('sha256').update(canonical(v)).digest('hex');
const stateOf=r=>({status:r.status,stage:r.stage,epoch:r.epoch,revision:r.revision,
 stageSince:+new Date(r.stage_since),leaseUntil:+new Date(r.lease_until),
 healthyWindows:r.healthy_windows,lastCandidateN:r.last_candidate_n,lastStableN:r.last_stable_n});
export class Store {
 constructor(connectionString) { this.pool=new Pool({connectionString,max:12,connectionTimeoutMillis:3000,query_timeout:5000}); }
 async init() { await this.pool.query(await readFile(new URL('../sql/schema.sql',import.meta.url),'utf8')); }
 async claim(){ this.leader=await this.pool.connect();const {rows}=await this.leader.query('SELECT pg_try_advisory_lock(7492371901) AS acquired');if(!rows[0].acquired){this.leader.release();this.leader=null;throw Error('v1 requires one ReleaseGuard process per database');} }
 async close(){ if(this.leader){await this.leader.query('SELECT pg_advisory_unlock(7492371901)').catch(()=>{});this.leader.release();this.leader=null;}await this.pool.end(); }
 async tx(fn) {
  const c=await this.pool.connect();
  try { await c.query('BEGIN'); await c.query("SET LOCAL lock_timeout='3s'");const x=await fn(c);await c.query('COMMIT');return x; }
  catch(e) { await c.query('ROLLBACK').catch(()=>{});throw e; }
  finally { c.release(); }
 }
 async row(c,id) {
  const {rows}=await c.query('SELECT *,extract(epoch from clock_timestamp())*1000 AS now_ms FROM rg_releases WHERE id=$1 FOR UPDATE',[id]);
  if(!rows[0]) { const e=Error('release not found');e.status=404;throw e; }
  return rows[0];
 }
 async append(c,r,record,alert=false) {
  const seq=r.audit_seq+1;
  const rec={...record,releaseId:r.id,seq,configHash:r.config_hash,at:+new Date(record.at??Date.now())};
  const hash=digest({previousHash:r.audit_head,record:rec});
  await c.query('INSERT INTO rg_evidence(release_id,seq,record,previous_hash,hash) VALUES($1,$2,$3,$4,$5)',
   [r.id,seq,rec,r.audit_head,hash]);
  await c.query('UPDATE rg_releases SET audit_seq=$2,audit_head=$3 WHERE id=$1',[r.id,seq,hash]);
  if(alert) await c.query('INSERT INTO rg_outbox(release_id,seq,body) VALUES($1,$2,$3)',[r.id,seq,{eventId:r.id+':'+seq,...rec,hash}]);
  r.audit_seq=seq;r.audit_head=hash;
  return {record:rec,hash};
 }
 async create(id,config) {
  return this.tx(async c=>{
   await c.query('INSERT INTO rg_releases(id,config,config_hash,lease_until) VALUES($1,$2,$3,clock_timestamp()+($4*interval \'1 millisecond\'))',
    [id,config,digest(config),config.policy.leaseMs]);
   const r=await this.row(c,id);
   await this.append(c,r,{decision:'HOLD',reason:'INITIAL_CANARY',candidatePct:config.policy.stages[0],state:stateOf(r)});
   return this.public(r);
  });
 }
 public(r) {
  const state=stateOf(r);
  return {id:r.id,...state,candidatePct:['RUNNING','COMPLETED'].includes(r.status) &&
    state.leaseUntil>Date.now()?r.config.policy.stages[r.stage]:0,lastReason:r.last_reason,
    configHash:r.config_hash,auditHead:r.audit_head,auditSeq:r.audit_seq,
    stableVersion:r.config.stable.version,candidateVersion:r.config.candidate.version,policy:r.config.policy};
 }
 async get(id) { const {rows}=await this.pool.query('SELECT * FROM rg_releases WHERE id=$1',[id]);if(!rows[0])return null;return this.public(rows[0]); }
 async list() {const {rows}=await this.pool.query("SELECT id FROM rg_releases WHERE status IN ('RUNNING','COMPLETED')");return rows.map(x=>x.id);}
 async reserve(id,requestId,fingerprint,owner,bucket,probeBucket) {
  return this.tx(async c=>{
   const r=await this.row(c,id);const now=Number(r.now_ms);const state=stateOf(r);
   const {rows}=await c.query('SELECT * FROM rg_requests WHERE release_id=$1 AND id=$2',[id,requestId]);
   if(rows[0])return {duplicate:rows[0],config:r.config,state};
   await c.query('INSERT INTO rg_requests(release_id,id,fingerprint,owner) VALUES($1,$2,$3,$4)',[id,requestId,fingerprint,owner]);
   const active=['RUNNING','COMPLETED'].includes(r.status)&&state.leaseUntil>now;
   const pct=active?r.config.policy.stages[r.stage]:0;
   const arm=bucket<pct?'candidate':'stable';
   const ticket={id:randomUUID(),releaseId:id,requestId,epoch:r.epoch,revision:r.revision,arm,source:'route'};
   await this.insertAttempt(c,ticket);
   let probe;
   if(arm==='candidate'&&pct===100&&probeBucket<r.config.policy.baselineProbePct&&r.config.fallbackMode==='read_only') {
    probe={...ticket,id:randomUUID(),arm:'stable',source:'probe'};
    await this.insertAttempt(c,probe);
   }
   return {ticket,probe,config:r.config,state};
  });
 }
 async insertAttempt(c,t) {
  await c.query('INSERT INTO rg_attempts(id,release_id,request_id,epoch,revision,arm,source) VALUES($1,$2,$3,$4,$5,$6,$7)',
   [t.id,t.releaseId,t.requestId,t.epoch,t.revision,t.arm,t.source]);
 }
 async fence(ticket) {
  return this.tx(async c=>{
   const r=await this.row(c,ticket.releaseId);const st=stateOf(r);
   const eligible=ticket.arm==='stable'||(['RUNNING','COMPLETED'].includes(r.status)&&r.revision===ticket.revision&&st.leaseUntil>Number(r.now_ms));
   if(!eligible){ await c.query("UPDATE rg_attempts SET dispatched=false,settled=true,finished_at=clock_timestamp(),reason='ADMISSION_REVOKED' WHERE id=$1 AND dispatched=false",[ticket.id]);return false; }
   const {rowCount}=await c.query('UPDATE rg_attempts SET dispatched=true,started_at=clock_timestamp() WHERE id=$1 AND dispatched=false AND settled=false',[ticket.id]);
   return rowCount===1;
  });
 }
 async cancel(ticket) { await this.pool.query("UPDATE rg_attempts SET dispatched=false,settled=true,finished_at=clock_timestamp(),reason='ADMISSION_REVOKED' WHERE id=$1 AND settled=false",[ticket.id]); }
 async fallback(ticket) {
  return this.tx(async c=>{
   const r=await this.row(c,ticket.releaseId);
   const t={...ticket,id:randomUUID(),arm:'stable',source:'fallback',epoch:r.epoch,revision:r.revision};
   await this.insertAttempt(c,t);return t;
  });
 }
 async settle(ticket,outcome) {
  await this.tx(async c=>{
   await this.row(c,ticket.releaseId);
   const {rowCount}=await c.query('UPDATE rg_attempts SET settled=true,finished_at=clock_timestamp(),ok=$2,valid=$3,latency_ms=$4,reason=$5 WHERE id=$1 AND dispatched=true AND settled=false',
    [ticket.id,outcome.ok,outcome.valid,outcome.latencyMs,outcome.reason]);
   if(rowCount!==1)throw Error('attempt already settled or absent');
  });
 }
 async finish(id,requestId,httpStatus,sealedResponse) {
  const {rowCount}=await this.pool.query("UPDATE rg_requests SET status='DONE',http_status=$3,sealed_response=$4,finished_at=clock_timestamp() WHERE release_id=$1 AND id=$2 AND status='PENDING'",
   [id,requestId,httpStatus,sealedResponse]);
  if(rowCount!==1)throw Error('request already finished or absent');
 }
 async metrics(c,r) {
  const timeout=r.config.policy.requestTimeoutMs;
  await c.query("UPDATE rg_attempts SET settled=true,finished_at=clock_timestamp(),ok=false,valid=NULL,latency_ms=NULL,reason='OBSERVATION_LOST' WHERE release_id=$1 AND dispatched=true AND settled=false AND started_at<clock_timestamp()-($2*interval '1 millisecond')",
   [r.id,timeout+5000]);
  const {rows}=await c.query("SELECT arm,\n count(*)::integer AS started,count(*) FILTER(WHERE settled)::integer AS settled,\n count(*) FILTER(WHERE settled AND ok IS NOT NULL AND valid IS NOT NULL AND latency_ms>=0 AND latency_ms<'Infinity'::float8)::integer AS complete,\n count(*) FILTER(WHERE ok=false)::integer AS errors,\n count(*) FILTER(WHERE ok=true AND valid=false)::integer AS invalid,\n percentile_disc(0.95) WITHIN GROUP(ORDER BY latency_ms) FILTER(WHERE settled AND ok IS NOT NULL AND valid IS NOT NULL AND latency_ms>=0 AND latency_ms<'Infinity'::float8) AS p95_ms,\n extract(epoch from max(finished_at) FILTER(WHERE settled AND valid IS NOT NULL AND latency_ms IS NOT NULL))*1000 AS last_at\n FROM rg_attempts WHERE release_id=$1 AND epoch=$2 AND dispatched=true AND source IN ('route','probe')\n AND started_at>clock_timestamp()-($3*interval '1 millisecond') GROUP BY arm",[r.id,r.epoch,r.config.policy.windowMs]);
  const empty=()=>({started:0,settled:0,complete:0,errors:0,invalid:0,p95Ms:null,lastAt:null});
  const m={stable:empty(),candidate:empty()};
  for(const x of rows)m[x.arm]={started:x.started,settled:x.settled,complete:x.complete,errors:x.errors,invalid:x.invalid,p95Ms:x.p95_ms===null?null:Number(x.p95_ms),lastAt:x.last_at===null?null:Number(x.last_at)};
  return m;
 }
 async evaluate(id,onSafetyChange=()=>{}) {
  return this.tx(async c=>{
   const r=await this.row(c,id);const before=stateOf(r);const m=await this.metrics(c,r);
   const d=decide({state:before,...m,now:Number(r.now_ms),p:r.config.policy});
   if(['STOP','PAUSE'].includes(d.action))onSafetyChange(d);
   if(d.action==='STOP'||d.action==='PAUSE') {
    r.status=d.action==='STOP'?'ROLLED_BACK':'PAUSED';r.revision++;r.healthy_windows=0;
   } else if(d.action==='ADVANCE') {
    r.stage++;r.epoch++;r.revision++;r.stage_since=new Date(Number(r.now_ms));
    r.healthy_windows=0;r.last_candidate_n=0;r.last_stable_n=0;
   } else if(d.action==='COMPLETE'){r.status='COMPLETED';r.revision++;r.healthy_windows=0;}
   else if(d.action==='CHECKPOINT') {r.healthy_windows=d.windows;r.last_candidate_n=m.candidate.settled;r.last_stable_n=m.stable.settled;}
   const active=['RUNNING','COMPLETED'].includes(r.status);
   r.lease_until=new Date(Number(r.now_ms)+(active?r.config.policy.leaseMs:0));
   const previousReason=r.last_reason;r.last_reason=d.reason;
   await c.query('UPDATE rg_releases SET status=$2,stage=$3,epoch=$4,revision=$5,stage_since=$6,lease_until=$7,healthy_windows=$8,last_candidate_n=$9,last_stable_n=$10,last_reason=$11 WHERE id=$1',
    [id,r.status,r.stage,r.epoch,r.revision,r.stage_since,r.lease_until,r.healthy_windows,r.last_candidate_n,r.last_stable_n,r.last_reason]);
   const alert=d.decision==='ROLLBACK'||d.decision==='HOLD'&&previousReason!==d.reason&&d.reason!=='RELEASE_INACTIVE';
   const evidence=await this.append(c,r,{...d,before,after:stateOf(r),routingConfirmed:active?'CANARY_ACTIVE':'STABLE_ONLY'},alert);
   return {...d,after:this.public(r),...evidence};
  });
 }
 async rollback(id,reason='OPERATOR_ROLLBACK') {
  return this.tx(async c=>{
   const r=await this.row(c,id);const before=stateOf(r);
   r.status='ROLLED_BACK';r.revision++;r.lease_until=new Date(0);
   await c.query("UPDATE rg_releases SET status='ROLLED_BACK',revision=$2,lease_until=to_timestamp(0),last_reason=$3 WHERE id=$1",[id,r.revision,reason]);
   const evidence=await this.append(c,r,{decision:'ROLLBACK',reason,before,after:stateOf(r),routingConfirmed:'STABLE_ONLY'},true);
   return {decision:'ROLLBACK',reason,after:this.public(r),...evidence};
  });
 }
 async evidence(id,after=0,limit=100){const {rows}=await this.pool.query('SELECT seq,record,previous_hash AS "previousHash",hash FROM rg_evidence WHERE release_id=$1 AND seq>$2 ORDER BY seq LIMIT $3',[id,after,limit]);return rows;}
 async outbox(){const {rows}=await this.pool.query('SELECT release_id,seq,body,attempts FROM rg_outbox WHERE delivered_at IS NULL AND next_at<=clock_timestamp() ORDER BY next_at LIMIT 25');return rows;}
 async delivered(id,seq){await this.pool.query('UPDATE rg_outbox SET delivered_at=clock_timestamp() WHERE release_id=$1 AND seq=$2',[id,seq]);}
 async deliveryFailed(id,seq,attempts){await this.pool.query("UPDATE rg_outbox SET attempts=attempts+1,next_at=clock_timestamp()+($3*interval '1 second') WHERE release_id=$1 AND seq=$2",[id,seq,Math.min(300,2**Math.min(attempts+1,8))]);}
 async ready(){await this.pool.query('SELECT 1');return true;}
}
