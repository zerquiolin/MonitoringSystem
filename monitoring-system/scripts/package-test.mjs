import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const dir = mkdtempSync(join(tmpdir(), 'sdk-consumer-'));
function run(command, args) {
  const result = spawnSync(command, args, { cwd: dir, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} failed`);
}
try {
  writeFileSync(join(dir, 'package.json'), JSON.stringify({ name: 'sdk-consumer', private: true }));
  run('npm', ['install', resolve(repoRoot, 'monitoring-system/artifacts/portable-observability-sdk-1.0.0.tgz'), '--ignore-scripts', '--no-audit', '--cache', join(tmpdir(), 'monitoring-npm-cache')]);
  run(process.execPath, ['-e', "const s=require('@portable-observability/sdk');if(typeof s.initializeMonitoring!=='function')process.exit(1)"]);
  run(process.execPath, ['--input-type=module', '-e', "import {initializeMonitoring} from '@portable-observability/sdk';if(typeof initializeMonitoring!=='function')process.exit(1)"]);
  writeFileSync(join(dir, 'consumer.ts'), "import {initializeMonitoring, type MonitoringConfig} from '@portable-observability/sdk'; const c: MonitoringConfig={resource:{project:'p',service:'s',environment:'e',instance:'i'},endpoint:'https://monitor.example',token:'x'};initializeMonitoring(c).then(m=>m.withSpan('op',{},async()=>42));");
  run(resolve(repoRoot, 'node_modules/.bin/tsc'), ['--noEmit', '--strict', '--skipLibCheck', '--module', 'NodeNext', '--target', 'ES2022', join(dir, 'consumer.ts')]);
  console.log('Installed tarball CJS, ESM, and TypeScript consumers passed');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
