import { readFile,readdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
for(const file of await readdir(new URL('../workflows/',import.meta.url))){
 if(!file.endsWith('.json'))continue;
 const w=JSON.parse(await readFile(new URL('../workflows/'+file,import.meta.url),'utf8'));
 assert.equal(w.active,false);assert.ok(!Object.keys(w.pinData||{}).length);
 const names=new Set(w.nodes.map(n=>n.name));assert.equal(names.size,w.nodes.length);
 for(const [name,c] of Object.entries(w.connections)){
  assert.ok(names.has(name));for(const branch of c.main)for(const t of branch)assert.ok(names.has(t.node));
 }
 for(const n of w.nodes){if(n.type.endsWith('.respondToWebhook')){const code=n.parameters.options?.responseCode;assert.ok(typeof code==='number'||typeof code==='string'&&code.startsWith('={{'),'response codes must be integers or numeric expressions');}assert.ok(n.type.startsWith('n8n-nodes-base.'));assert.ok(!n.credentials,'template must contain no credential bindings');}
 assert.ok(w.nodes.some(n=>n.type.endsWith('.stickyNote')));
 console.log('PASS import structure, credential hygiene, node connectivity: '+file);
}
