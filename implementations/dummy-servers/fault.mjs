import {readFileSync} from 'node:fs';
const [role,action,key,value]=process.argv.slice(2);
const response=await fetch('http://127.0.0.1:4199',{method:'POST',headers:{Authorization:'Bearer '+readFileSync(new URL('../secrets/operator-token',import.meta.url),'utf8').trim()},body:JSON.stringify({role,action,values:key?{[key]:value==='true'?true:value==='false'?false:Number(value)}:{}})});
if(!response.ok)throw new Error('Fault rejected: '+response.status);console.log(await response.text());
