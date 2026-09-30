import {readFile} from 'node:fs/promises';
import {Secrets} from '../src/security.mjs';
const base=process.env.GUARD_URL||'http://127.0.0.1:8080';
const spec=JSON.parse(await readFile(process.argv[2]||'config/demo-release.json','utf8'));
const tests=[];const check=(name,pass,detail)=>tests.push({name,result:pass?'PASS':'BLOCKED',detail});
for(const k of ['ADMIN_TOKEN','DATA_TOKEN','RESPONSE_KEY_HEX'])check(k,!!process.env[k],'Required local environment value; never printed.');
if(tests.some(x=>x.result==='BLOCKED')){console.log(JSON.stringify({verdict:'BLOCKED',tests},null,2));process.exit(1);}
const secrets=new Secrets(process.env.RESPONSE_KEY_HEX);
const health=await fetch(base+'/readyz');check('Persistent state and singleton controller',health.ok,'readyz must return 200');
const release=await fetch(base+'/v1/releases/'+spec.id,{headers:{authorization:'Bearer '+process.env.ADMIN_TOKEN}});
const {release:r,localFence}=await release.json();
check('Registered release with live lease',!!r&&r.leaseUntil>Date.now()&&!localFence,'Register the release before exposing ingress traffic.');
check('Scope',spec.config.fallbackMode==='read_only','Review actual workflows: a configuration declaration cannot prove absence of side effects.');
if(r&&!localFence){
 for(const arm of ['stable','candidate']){
  let key;for(let i=0;;i++){key='doctor-'+Date.now()+'-'+i;const chosen=secrets.bucket(spec.id,key)<r.candidatePct?'candidate':'stable';if(chosen===arm||r.candidatePct===0||r.candidatePct===100)break;}
  const res=await fetch(base+'/v1/execute/'+spec.id,{method:'POST',headers:{authorization:'Bearer '+process.env.DATA_TOKEN,'content-type':'application/json','x-request-id':key},body:JSON.stringify({leadId:'DOCTOR-DEMO',score:70})});
  const body=await res.json();check(arm+' contract smoke test',res.ok&&body.servedBy===arm&&!body.fallback,'Adapt the smoke payload for your real output contract.');
  if(r.candidatePct===0&&arm==='stable')break;
 }
}
const pass=tests.every(x=>x.result==='PASS');console.log(JSON.stringify({verdict:pass?'READY_FOR_CANARY':'BLOCKED',tests,
 meaning:'Setup verification only. This is not a production certification or evidence of paid demand.'},null,2));if(!pass)process.exitCode=1;
