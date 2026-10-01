const $=id=>document.getElementById(id);
const text=(id,value)=>$(id).textContent=value;
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v))))).map(x=>x.toString(16).padStart(2,'0')).join('');
async function call(path,method='GET'){const r=await fetch('/v1/'+path,{method,headers:{authorization:'Bearer '+$('token').value}});const b=await r.json();if(!r.ok)throw Error(b.error||'Request failed');return b;}
async function load(){
 try{
  const id=encodeURIComponent($('release').value);
  const {release:r,localFence}=await call('releases/'+id);if(!r)throw Error('Release not found');
  let after=0,xs=[];
  for(let page=0;page<50;page++){const b=await call('releases/'+id+'/evidence?after='+after);xs.push(...b.evidence);if(b.evidence.length<100)break;after=b.evidence.at(-1).seq;}
  const last=xs.at(-1)?.record;const m=[...xs].reverse().find(x=>x.record.evidence)?.record.evidence;
  text('traffic',(localFence?0:r.candidatePct)+'%');text('state',localFence?'FENCED':r.status);text('revision','Revision '+r.revision+' · Epoch '+r.epoch);
  text('errors',m?.candidate.settled?(100*m.candidate.errors/m.candidate.settled).toFixed(1)+'%':'—');
  text('samples',m?m.candidate.settled+' Candidate observations':'No Candidate observations');
  text('latency',m?.candidate.p95Ms!=null?Math.round(m.candidate.p95Ms)+' ms':'—');
  text('slo','Budget '+r.policy.maxP95Ms+' ms · ratio '+r.policy.maxLatencyRatio+'×');
  text('banner',localFence?'Safety fence active. Rollback is unconfirmed. Inspect the database before clearing this incident.':r.candidatePct===0?'Candidate admission closed. '+(r.lastReason||last?.reason||'Lease expired'):'Canary is active at '+r.candidatePct+'%. Promotion requires fresh evidence.');
  $('stages').replaceChildren(...r.policy.stages.map((pct,i)=>{const el=document.createElement('div');el.className='stage'+(i<r.stage?' done':i===r.stage?' current':'');el.textContent=pct+'%';return el;}));
  $('metrics').replaceChildren(...['stable','candidate'].map(arm=>{const tr=document.createElement('tr');const a=m?.[arm];for(const v of [arm,a?.settled??'—',a?.complete??'—',a?.errors??'—',a?.p95Ms!=null?Math.round(a.p95Ms)+' ms':'—']){const td=document.createElement('td');td.textContent=v;tr.append(td);}return tr;}));
  text('reason',last?last.decision+' / '+last.reason+'\nRouting: '+(last.routingConfirmed||'INITIAL_CANARY')+'\nConfig: '+r.configHash.slice(0,16)+'…':'No decision');
  let prev='',valid=xs.length===r.auditSeq;
  for(const x of xs){if(x.previousHash!==prev||x.hash!==await hash({previousHash:prev,record:x.record})){valid=false;break;}prev=x.hash;}
  text('integrity',valid&&prev===r.auditHead?'✓ Audit chain verified · '+xs.length+' records':'Audit verification incomplete or failed');$('integrity').className=valid?'':'error';
  $('evidence').replaceChildren(...xs.slice(-12).reverse().map(x=>{const li=document.createElement('li');li.textContent='#'+x.seq+'  '+x.record.decision+'  '+x.record.reason;const s=document.createElement('span');s.textContent=new Date(x.record.at).toISOString()+' · '+x.hash.slice(0,18)+'…';li.append(s);return li;}));
 }catch(e){text('banner',e.message);}
}
$('load').onclick=load;
$('evaluate').onclick=async()=>{try{await call('releases/'+encodeURIComponent($('release').value)+'/evaluate','POST');await load();}catch(e){text('banner',e.message);}};
$('rollback').onclick=async()=>{try{await call('releases/'+encodeURIComponent($('release').value)+'/rollback','POST');await load();}catch(e){text('banner',e.message);}};
