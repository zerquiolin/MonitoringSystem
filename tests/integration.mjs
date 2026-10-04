import {spawnSync} from 'node:child_process';import assert from 'node:assert/strict';
const p=spawnSync(process.execPath,['tests/framework-fixture.mjs'],{cwd:new URL('../',import.meta.url),encoding:'utf8',timeout:20000});process.stdout.write(p.stdout);assert.equal(p.status,0,p.stderr);
