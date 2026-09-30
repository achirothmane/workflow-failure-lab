import { createHmac,randomBytes,createCipheriv,createDecipheriv,timingSafeEqual } from 'node:crypto';
import { canonical } from './store.mjs';
import { policy } from './policy.mjs';
import Ajv from 'ajv';
const ajv=new Ajv({strict:true,allErrors:false,validateFormats:false});
const compiled=new Map();
export function validateConfig(input,allowedOrigin) {
 if(!input||typeof input!=='object'||Array.isArray(input))throw Error('invalid release config');
 const u=new URL(allowedOrigin);
 if(u.username||u.password||u.search||u.hash||!['http:','https:'].includes(u.protocol))throw Error('invalid allowed origin');
 const endpoints={};
 for(const arm of ['stable','candidate']){
  const x=input[arm];if(!x||typeof x.version!=='string'||!/^[A-Za-z0-9._-]{1,100}$/.test(x.version))throw Error('invalid workflow version');
  const url=new URL(x.url);
  if(url.origin!==u.origin||url.username||url.password||url.search||url.hash||
   !/^\/webhook\/[A-Za-z0-9/_-]+$/.test(url.pathname))throw Error('upstream must be an allowlisted production webhook');
  endpoints[arm]={url:url.href,version:x.version};
 }
 if(endpoints.stable.url===endpoints.candidate.url)throw Error('stable and candidate must be separate workflows');
 const mode=input.fallbackMode||'never';
 if(!['never','read_only'].includes(mode))throw Error('unsupported fallback mode');
 const p=policy(input.policy);
 if(p.stages.includes(100)&&mode!=='read_only')throw Error('v1 requires read_only workflows for contemporaneous baseline probes');
 if(!input.outputSchema||input.outputSchema.type!=='object')throw Error('outputSchema must describe an object');
 // Schemas are operator configuration; refs cannot fetch URLs or execute code.
 const schemaText=JSON.stringify(input.outputSchema);
 if(schemaText.length>20000||schemaText.includes('"$ref"')||schemaText.includes('"pattern"'))throw Error('external refs/regex are not supported in v1');
 if(!input.inputSchema||input.inputSchema.type!=='object')throw Error('inputSchema must describe an object');
 const inputText=JSON.stringify(input.inputSchema);
 if(inputText.length>20000||inputText.includes('"$ref"')||inputText.includes('"pattern"'))throw Error('unsafe inputSchema');
 validator(input.outputSchema);validator(input.inputSchema);
 return {...endpoints,fallbackMode:mode,inputSchema:input.inputSchema,outputSchema:input.outputSchema,policy:p};
}
export class Secrets {
 constructor(hex) { if(!/^[a-fA-F0-9]{64}$/.test(hex||''))throw Error('RESPONSE_KEY_HEX must be a persistent 32-byte hex key');this.key=Buffer.from(hex,'hex'); }
 fingerprint(body){return this.hmac('payload:'+canonical(body));}
 hmac(value){return createHmac('sha256',this.key).update(value).digest('hex');}
 bucket(release,id,kind='route'){const n=parseInt(this.hmac(kind+':'+release+':'+id).slice(0,8),16);return n/0x100000000*100;}
 seal(value) {const iv=randomBytes(12);const c=createCipheriv('aes-256-gcm',this.key,iv);
  const raw=Buffer.concat([c.update(JSON.stringify(value),'utf8'),c.final()]);
  return [iv.toString('hex'),c.getAuthTag().toString('hex'),raw.toString('base64')].join('.');}
 open(value){const [iv,tag,data]=value.split('.');const c=createDecipheriv('aes-256-gcm',this.key,Buffer.from(iv,'hex'));
  c.setAuthTag(Buffer.from(tag,'hex'));return JSON.parse(Buffer.concat([c.update(Buffer.from(data,'base64')),c.final()]).toString('utf8'));}
}
export const tokenEquals=(a,b)=>{
 if(typeof a!=='string'||typeof b!=='string')return false;
 const aa=Buffer.from(a),bb=Buffer.from(b);return aa.length===bb.length&&timingSafeEqual(aa,bb);
};
export function validator(schema){
 const key=canonical(schema);let check=compiled.get(key);
 if(!check){check=ajv.compile(schema);ajv.removeSchema(schema);if(compiled.size>=128)compiled.delete(compiled.keys().next().value);compiled.set(key,check);}
 return value=>!!check(value);
}
