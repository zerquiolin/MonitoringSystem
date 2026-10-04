import {readFile} from 'node:fs/promises';
/** Cgroup v2 measurements are container scope; absent/unlimited values are omitted. */
export async function collectCgroup():Promise<Record<string,number>> {
 const current=Number((await readFile('/sys/fs/cgroup/memory.current','utf8')).trim());
 const limit=(await readFile('/sys/fs/cgroup/memory.max','utf8')).trim();
 const [quota,period]=(await readFile('/sys/fs/cgroup/cpu.max','utf8')).trim().split(' ');
 const stat=(await readFile('/sys/fs/cgroup/cpu.stat','utf8')).trim().split('\n').map(line=>line.split(/\s+/));
 const values:Record<string,number>={app_container_memory_used_bytes:current};
 if(limit!=='max')values.app_container_memory_limit_bytes=Number(limit);
 if(quota!=='max')values.app_container_cpu_limit_cores=Number(quota)/Number(period);
 const cpu=Object.fromEntries(stat);
 if(cpu.throttled_usec)values.app_container_cpu_throttled_seconds=Number(cpu.throttled_usec)/1e6;
 if(cpu.usage_usec)values.app_container_cpu_seconds=Number(cpu.usage_usec)/1e6;
 return values;
}
