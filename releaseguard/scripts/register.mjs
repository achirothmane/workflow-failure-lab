import {readFile} from 'node:fs/promises';
const path=process.argv[2]||'config/demo-release.json';
const config=JSON.parse(await readFile(path,'utf8'));
const response=await fetch((process.env.GUARD_URL||'http://127.0.0.1:8080')+'/v1/releases',{
 method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+process.env.ADMIN_TOKEN},body:JSON.stringify(config)});
const result=await response.json();if(!response.ok)throw Error(JSON.stringify(result));
console.log(JSON.stringify({registered:result.id,candidatePct:result.candidatePct,policy:result.policy},null,2));
