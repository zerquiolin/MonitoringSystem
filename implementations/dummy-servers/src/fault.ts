import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  isDemoRole,
  isDemoFaultKey,
  parseFaultValue,
  type DemoFaultKey,
  type DemoRole,
} from './demo-config.js';

type FaultAction = 'fault' | 'stop' | 'restart' | 'overflow';

interface FaultRequest {
  role: DemoRole;
  action: FaultAction;
  values?: Partial<Record<DemoFaultKey, boolean | number>>;
}

const [roleArg, actionArg, keyArg, valueArg] = process.argv.slice(2);
if (!isDemoRole(roleArg)) throw new Error('Choose one of: orders, orders2, catalog, worker, scheduler');
if (!isAction(actionArg)) throw new Error('Choose one of: fault, stop, restart, overflow');

const request: FaultRequest = { role: roleArg, action: actionArg };
if (actionArg === 'fault') {
  if (!isDemoFaultKey(keyArg) || valueArg === undefined) {
    throw new Error('Fault syntax: fault ROLE fault FAULT_NAME VALUE');
  }
  request.values = { [keyArg]: parseFaultValue(keyArg, valueArg) } as Partial<Record<DemoFaultKey, boolean | number>>;
} else if (keyArg !== undefined) {
  throw new Error(`Action '${actionArg}' does not take a fault name or value`);
}

const tokenFile = fileURLToPath(new URL('../../../monitoring-system/secrets/operator-token', import.meta.url));
const token = readFileSync(tokenFile, 'utf8').trim();
const response = await fetch('http://127.0.0.1:4199', {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify(request),
});
if (!response.ok) throw new Error(`Fault request rejected: HTTP ${response.status} ${await response.text()}`);
console.log(await response.text());

function isAction(value: string | undefined): value is FaultAction {
  return value === 'fault' || value === 'stop' || value === 'restart' || value === 'overflow';
}
