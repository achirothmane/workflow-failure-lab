import { randomUUID } from 'node:crypto';
import { validator } from './security.mjs';
import { transport as defaultTransport } from './transport.mjs';
export class ReleaseGuard {
 constructor({store,secrets,upstreamToken,transport=defaultTransport,log=console.error}) {
  this.store=store;this.secrets=secrets;this.upstreamToken=upstreamToken;this.transport=transport;
  this.log=log;this.owner=randomUUID();this.blocked=new Map();this.inflight=new Map();
 }
 trip(id,reason){this.blocked.set(id,{reason,at:Date.now()});this.abort(id);this.log(JSON.stringify({event:'RELEASEGUARD_FAIL_CLOSED',releaseId:id,reason,at:Date.now()}));}
 abort(id){for(const x of this.inflight.values())if(x.releaseId===id&&x.arm==='candidate')x.controller.abort();}
 async evaluate(id) {
  if(this.blocked.has(id))return {decision:'HOLD',reason:'LOCAL_SAFETY_FENCE',routingConfirmed:'DENIED'};
  try {const d=await this.store.evaluate(id);if(['STOP','PAUSE'].includes(d.action))this.abort(id);return d;}
  catch {this.trip(id,'EVALUATION_OR_ROLLBACK_COMMIT_FAILED');return {decision:'HOLD',reason:'ROLLBACK_UNCONFIRMED',routingConfirmed:'DENIED'};}
 }
 async rollback(id) {
  this.trip(id,'OPERATOR_STOP_PENDING');
  try {const d=await this.store.rollback(id);this.blocked.delete(id);return d;}
  catch {return {decision:'HOLD',reason:'ROLLBACK_UNCONFIRMED',routingConfirmed:'DENIED'};}
 }
 async attempt(ticket,payload,config) {
  if(ticket.arm==='candidate'&&this.blocked.has(ticket.releaseId))return {cancelled:true};
  const allowed=await this.store.fence(ticket);if(!allowed)return {cancelled:true};
  const controller=new AbortController();this.inflight.set(ticket.id,{releaseId:ticket.releaseId,arm:ticket.arm,controller});
  try {
   const outcome=await this.transport({endpoint:config[ticket.arm],payload,requestId:ticket.requestId,
    timeoutMs:config.policy.requestTimeoutMs,token:this.upstreamToken,validate:validator(config.outputSchema),signal:controller.signal});
   await this.store.settle(ticket,outcome);return outcome;
  } finally {this.inflight.delete(ticket.id);}
 }
 async execute(id,requestId,payload) {
  if(this.blocked.has(id))return {status:503,body:{error:'RELEASE_SAFETY_FENCE',releaseId:id}};
  const fingerprint=this.secrets.fingerprint(payload);
  try {
   const r=await this.store.reserve(id,requestId,fingerprint,this.owner,this.secrets.bucket(id,requestId),this.secrets.bucket(id,requestId,'probe'));
   if(r.duplicate){
    if(r.duplicate.fingerprint!==fingerprint)return {status:409,body:{error:'REQUEST_ID_PAYLOAD_MISMATCH'}};
    if(r.duplicate.status==='DONE'&&r.duplicate.sealed_response)return {status:r.duplicate.http_status,body:this.secrets.open(r.duplicate.sealed_response),replayed:true};
    return {status:409,body:{error:'REQUEST_IN_PROGRESS_OR_UNKNOWN',requestId}};
   }
   let arm=r.ticket.arm, fallback=false,primary;
   const probe=r.probe?this.attempt(r.probe,payload,r.config):Promise.resolve(null);
   // Attach rejection handler immediately to avoid an unhandled rejection if primary is slow.
   const probeResult=probe.then(x=>({value:x}),e=>({error:e}));
   primary=await this.attempt(r.ticket,payload,r.config);
   if(primary.cancelled || arm==='candidate'&&(!primary.ok||!primary.valid)){
    if(!primary.cancelled)await this.evaluate(id);
    if(r.config.fallbackMode==='read_only'&&!this.blocked.has(id)) {
     const t=await this.store.fallback(r.ticket);primary=await this.attempt(t,payload,r.config);
     arm='stable';fallback=true;
    } else primary={ok:false,valid:true,reason:'FALLBACK_FORBIDDEN'};
   }
   const pr=await probeResult;if(pr.error)throw pr.error;
   if(pr.value&&(!pr.value.ok||!pr.value.valid))await this.evaluate(id);
   const successful=primary.ok&&primary.valid;
   const response={status:successful?200:503,body:successful?
    {requestId,releaseId:id,servedBy:arm,fallback,result:primary.result}:
    {requestId,releaseId:id,error:'NO_VALID_WORKFLOW_RESULT',reason:primary.reason}};
   await this.store.finish(id,requestId,response.status,this.secrets.seal(response.body));
   // Measured failures stop exposure promptly; good traffic relies on the evaluator heartbeat.
   if(!successful)await this.evaluate(id);
   return response;
  } catch(e) {
   if(e.status===404)return {status:404,body:{error:'RELEASE_NOT_FOUND'}};
   this.trip(id,'STATE_OR_OBSERVATION_UNAVAILABLE');
   return {status:503,body:{error:'STATE_UNAVAILABLE',releaseId:id,requestId}};
  }
 }
}
