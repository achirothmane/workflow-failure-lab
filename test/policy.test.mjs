import { test } from 'node:test';
import assert from 'node:assert/strict';
import { policy,decide,wilson,summarize } from '../src/policy.mjs';
const now=1000000;
const p=policy({minStageMs:1000,minCandidate:200,minStable:200,windowMs:100000,maxMetricAgeMs:10000});
const state={status:'RUNNING',stage:0,revision:1,stageSince:now-2000,healthyWindows:1,lastCandidateN:100,lastStableN:100};
const good=(n=200,latency=100)=>({started:n,settled:n,complete:n,errors:0,invalid:0,p95Ms:latency,lastAt:now});
const d=(c=good(),s=good(),st=state)=>decide({state:st,candidate:c,stable:s,now,p});
test('healthy, independent fresh samples permit stage advancement',()=>assert.equal(d().action,'ADVANCE'));
test('all stages advance; 100% has its own evidence gate',()=>{
 for(let stage=0;stage<4;stage++) assert.equal(d(good(),good(),{...state,stage}).action,stage===3?'COMPLETE':'ADVANCE');
});
test('increased error rate rolls back before full sample',()=>assert.equal(d({...good(20),errors:8}).decision,'ROLLBACK'));
test('partial failures cannot hide behind successes',()=>assert.equal(d({...good(),errors:14}).decision,'ROLLBACK'));
test('absolute latency regression rolls back',()=>assert.equal(d(good(20,3500)).reason,'CANDIDATE_LATENCY_SLO'));
test('relative latency regression rolls back',()=>assert.equal(d(good(200,450)).reason,'CANDIDATE_LATENCY_REGRESSION'));
test('invalid output rolls back despite HTTP 200',()=>assert.equal(d({...good(1),invalid:1}).decision,'ROLLBACK'));
test('missing metrics close candidate admission',()=>assert.equal(d({...good(),complete:199}).action,'PAUSE'));
test('insufficient sample never promotes',()=>assert.equal(d(good(10)).reason,'INSUFFICIENT_SAMPLES'));
test('confidence blocks misleading zero-failure tiny samples',()=> {
 const q=policy({...p,minCandidate:5,minStable:5,freshBatch:1});
 assert.equal(decide({state,stable:good(5),candidate:good(5),now,p:q}).reason,'ERROR_CONFIDENCE_INSUFFICIENT');
});
test('unhealthy stable prevents opportunistic promotion',()=>assert.equal(d(good(),{...good(),errors:20}).reason,'STABLE_UNHEALTHY'));
test('invalid stable prevents promotion',()=>assert.equal(d(good(),{...good(),invalid:1}).action,'PAUSE'));
test('slow stable prevents promotion',()=>assert.equal(d(good(),good(200,6000)).reason,'STABLE_UNHEALTHY'));
test('stale evidence is a safety hold',()=>assert.equal(d({...good(),lastAt:now-20000}).reason,'STALE_METRICS'));
test('non-finite latency is invalid evidence',()=>assert.equal(d({...good(),p95Ms:NaN}).reason,'METRICS_INVALID'));
test('minimum dwell blocks promotion',()=>assert.equal(d(good(),good(),{...state,stageSince:now}).reason,'MINIMUM_DWELL'));
test('repeated evaluation cannot recycle a batch',()=>assert.equal(d(good(),good(),{...state,lastCandidateN:200,lastStableN:200}).reason,'NO_FRESH_BATCH'));
test('pending requests cannot be discarded to improve rates',()=>assert.equal(d({...good(),started:201}).reason,'IN_FLIGHT_REQUESTS'));
test('inactive release cannot restart from old evidence',()=>assert.equal(d(good(),good(),{...state,status:'ROLLED_BACK'}).reason,'RELEASE_INACTIVE'));
test('invalid stage is a safety hold',()=>assert.equal(d(good(),good(),{...state,stage:9}).action,'PAUSE'));
test('policy rejects unsound traffic, thresholds, missing-data forgiveness',()=> {
 for(const x of [{stages:[25,5,100]},{maxErrorRate:NaN},{maxErrorRate:-1},{minCompleteness:.99},{leaseMs:10},{stages:[5,50]},{hello:1}]) assert.throws(()=>policy(x));
});
test('same evidence gives byte-identical decision',()=>assert.deepEqual(d(),d()));
test('Wilson bound declines with sample evidence',()=>assert.ok(wilson(0,200).high<wilson(0,20).high));
test('fallback observations cannot overwrite raw candidate failures',()=>{
 const m=summarize([{settled:true,ok:false,valid:true,latencyMs:10,at:now},{settled:true,ok:true,valid:true,latencyMs:20,at:now}],now);
 assert.equal(m.errors,1);
});
test('all single-corruption variants prevent promotion',()=>{
 for(const key of ['started','settled','complete','errors','invalid','p95Ms','lastAt'])
  for(const value of [NaN,Infinity,-1,'200',null])
   assert.notEqual(d({...good(),[key]:value}).decision,'PROMOTE');
});

test('failure budget bounds exposure even before a full sample',()=>assert.equal(d({...good(5),errors:5}).reason,'CANDIDATE_FAILURE_BUDGET'));
