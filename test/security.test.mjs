import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Secrets,validateConfig,tokenEquals,validator} from '../src/security.mjs';
const schema={type:'object',required:['score'],properties:{score:{type:'number'}},additionalProperties:false};
const config={stable:{url:'http://n8n:5678/webhook/stable',version:'v1'},candidate:{url:'http://n8n:5678/webhook/candidate',version:'v2'},fallbackMode:'read_only',inputSchema:{type:'object'},outputSchema:schema};
test('authenticated routing buckets are stable and spread traffic',()=>{
 const s=new Secrets('ab'.repeat(32));const buckets=Array.from({length:10000},(_,i)=>s.bucket('r','request-'+i));
 const count=buckets.filter(x=>x<5).length;assert.ok(count>400&&count<600);assert.equal(s.bucket('r','x'),s.bucket('r','x'));
});
test('encrypted retry responses round trip, reject tampering, hide plaintext',()=>{
 const s=new Secrets('ab'.repeat(32));const value={email:'do-not-log@example.test',score:42};const sealed=s.seal(value);
 assert.deepEqual(s.open(sealed),value);assert.ok(!sealed.includes(value.email));assert.notEqual(sealed,s.seal(value));assert.throws(()=>s.open(sealed.replace(/^./,sealed[0]==='a'?'b':'a')));
});
test('tokens require exact bytes',()=>{assert.ok(tokenEquals('x','x'));assert.ok(!tokenEquals('x','y'));assert.ok(!tokenEquals('x','xx'));});
test('upstream credentials, redirects and metadata destinations are rejected at registration',()=>{
 for(const url of ['http://169.254.169.254/latest/meta-data','http://n8n:5678/webhook/x?url=evil','http://user:pw@n8n:5678/webhook/x','http://n8n:5678/webhook/x#fragment','https://evil.test/webhook/x'])
  assert.throws(()=>validateConfig({...config,candidate:{url,version:'v2'}},'http://n8n:5678'));
});
test('workflow arms must be separate, output checks mandatory and probes safe',()=>{
 assert.throws(()=>validateConfig({...config,candidate:config.stable},'http://n8n:5678'));
 assert.throws(()=>validateConfig({...config,fallbackMode:'never'},'http://n8n:5678'));
 assert.throws(()=>validateConfig({...config,outputSchema:{}},'http://n8n:5678'));
 assert.ok(validateConfig(config,'http://n8n:5678'));
});
test('unsafe schema extensions are rejected',()=>assert.throws(()=>validateConfig({...config,outputSchema:{type:'object',properties:{x:{$ref:'http://evil/schema'}}}},'http://n8n:5678')));

test('cross-field business invariant rejects structurally plausible but wrong priority',()=>{
 const c=validateConfig({...config,outputSchema:{type:'object',required:['score','priority'],properties:{score:{type:'number'},priority:{enum:['HIGH','NORMAL']}},allOf:[{if:{type:'object',properties:{score:{type:'number',minimum:70}},required:['score']},then:{type:'object',properties:{priority:{const:'HIGH'}}},else:{type:'object',properties:{priority:{const:'NORMAL'}}}}]}},'http://n8n:5678');
 const check=validator(c.outputSchema);assert.ok(check({score:80,priority:'HIGH'}));assert.ok(!check({score:80,priority:'NORMAL'}));
});
