import {randomBytes} from 'node:crypto';
import {writeFile} from 'node:fs/promises';
const keys=['POSTGRES_PASSWORD','ADMIN_TOKEN','DATA_TOKEN','UPSTREAM_TOKEN','ALERT_TOKEN','RESPONSE_KEY_HEX','N8N_ENCRYPTION_KEY'];
await writeFile('.env',keys.map(k=>k+'='+randomBytes(32).toString('hex')).join('\n')+'\n',{flag:'wx',mode:0o600});
console.log('Created .env. Keep these values persistent; regenerate only in a disposable demo.');
