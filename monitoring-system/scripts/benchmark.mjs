import { spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const systemRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const rows = [];
for (const enabled of [false, true]) {
  const fixture = resolve(systemRoot, 'tests/benchmark-fixture.mjs');
  const result = spawnSync(process.execPath, [fixture, String(enabled)], {
    cwd: systemRoot, encoding: 'utf8', timeout: 60000,
  });
  if (result.status !== 0) throw new Error(result.stderr);
  rows.push(JSON.parse(result.stdout));
}
const baseline = rows[0], monitored = rows[1];
const report = {
  workload: '3000 native HTTP requests, 20 concurrent clients, pull reader, traces/log export disabled; SDK process collectors enabled',
  results: rows,
  throughputRatio: monitored.requestsPerSecond / baseline.requestsPerSecond,
  latencyRatio: monitored.meanMilliseconds / baseline.meanMilliseconds,
  scope: 'Local microbenchmark. Not a full-stack sustainable capacity measurement.',
  budget: { minimumThroughputRatio: 0.7, maximumMeanLatencyRatio: 1.5 },
};
report.passed = report.throughputRatio >= report.budget.minimumThroughputRatio && report.latencyRatio <= report.budget.maximumMeanLatencyRatio;
writeFileSync(resolve(systemRoot, 'artifacts/benchmark.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
