import { performance } from 'node:perf_hooks';
export async function transport({endpoint,payload,requestId,timeoutMs,token,validate,signal}) {
 const started=performance.now();let ok=false,valid=true,reason='UPSTREAM_ERROR',result;
 const deadline=AbortSignal.timeout(timeoutMs);
 try {
  const response=await fetch(endpoint.url,{method:'POST',headers:{'content-type':'application/json',
   'x-releaseguard-upstream':token,'x-request-id':requestId},
   body:JSON.stringify(payload),redirect:'manual',signal:signal?AbortSignal.any([signal,deadline]):deadline});
  ok=response.status>=200&&response.status<300;
  if(!ok)return {ok:false,valid:true,latencyMs:performance.now()-started,reason:'HTTP_'+response.status};
  let bytes=0;const chunks=[];
  for await(const chunk of response.body){bytes+=chunk.byteLength;if(bytes>1048576){await response.body.cancel().catch(()=>{});throw Error('OUTPUT_TOO_LARGE');}chunks.push(chunk);}
  let body;try{body=JSON.parse(Buffer.concat(chunks).toString('utf8'));}
  catch {return {ok:true,valid:false,latencyMs:performance.now()-started,reason:'INVALID_JSON'};}
  valid=body?.releaseguardVersion===endpoint.version&&validate(body?.result);
  reason=valid?'VALID':'OUTPUT_CONTRACT_FAILED';result=valid?body.result:undefined;
 } catch(e) { ok=false;valid=true;reason=signal?.aborted?'REVISION_REVOKED':deadline.aborted?'TIMEOUT':'TRANSPORT_ERROR'; }
 return {ok,valid,reason,result,latencyMs:performance.now()-started};
}
