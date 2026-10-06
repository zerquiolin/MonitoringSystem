import { fork, type ChildProcess } from 'node:child_process';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  demoRoles,
  isDemoFaultKey,
  isDemoRole,
  isValidFaultValues,
  type DemoFaultState,
  type DemoRole,
} from './demo-config.js';

const tokenFile = fileURLToPath(new URL('../../../monitoring-system/secrets/operator-token', import.meta.url));
const operatorToken = readFileSync(tokenFile, 'utf8').trim();
const children = new Map<DemoRole, ChildProcess>();
const childPath = fileURLToPath(new URL('./bootstrap.js', import.meta.url));

interface FaultControlRequest {
  role: DemoRole;
  action: 'fault' | 'stop' | 'restart' | 'overflow';
  values?: Partial<DemoFaultState>;
}

function isFaultControlRequest(value: unknown): value is FaultControlRequest {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  if (!('role' in value) || !isDemoRole(value.role) || !('action' in value)) return false;
  const action = value.action;
  if (action !== 'fault' && action !== 'stop' && action !== 'restart' && action !== 'overflow') return false;
  if (action === 'fault') return 'values' in value && isValidFaultValues(value.values)
    && Object.keys(value.values).length > 0;
  return !('values' in value) || value.values === undefined;
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(value));
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  let body = '';
  for await (const chunk of request) {
    body += chunk.toString();
    if (body.length > 4_096) throw new Error('Request body is too large');
  }
  return JSON.parse(body) as unknown;
}

function launch(role: DemoRole): void {
  const child = fork(childPath, [], {
    env: { ...process.env, DEMO_ROLE: role },
    stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
  });
  children.set(role, child);
  child.stdout?.on('data', (data: Buffer) => process.stdout.write(`[${role}] ${data}`));
  child.stderr?.on('data', (data: Buffer) => process.stderr.write(`[${role}] ${data}`));
  child.on('message', (message: unknown) => {
    if (isReadyMessage(message)) {
      console.log(`${role} ready${message.port === undefined ? '' : ` on ${message.port}`}`);
    }
  });
  child.on('exit', (code: number | null) => {
    if (children.get(role) === child) children.delete(role);
    console.log(`${role} stopped (${code ?? 'signal'})`);
  });
}

function isReadyMessage(value: unknown): value is { type: 'ready'; port?: number } {
  return typeof value === 'object' && value !== null && 'type' in value && value.type === 'ready'
    && (!('port' in value) || value.port === undefined || typeof value.port === 'number');
}

for (const role of demoRoles) launch(role);

const controlServer = createServer(async (request, response) => {
  if (request.headers.authorization !== `Bearer ${operatorToken}`) {
    sendJson(response, 401, { error: 'Unauthorized' });
    return;
  }
  if (request.method === 'GET') {
    sendJson(response, 200, { roles: [...children.keys()] });
    return;
  }
  if (request.method !== 'POST') {
    response.writeHead(405, { Allow: 'GET, POST' });
    response.end();
    return;
  }

  try {
    const input = await readJson(request);
    if (!isFaultControlRequest(input)) throw new Error('Invalid fault-control request');
    await control(input, response);
  } catch (error: unknown) {
    sendJson(response, 400, { error: error instanceof Error ? error.message : 'Invalid request' });
  }
});
controlServer.listen(4_199, '127.0.0.1');

const trafficTargets = [
  'http://127.0.0.1:4101/orders/demo',
  'http://127.0.0.1:4102/products/demo',
  'http://127.0.0.1:4103/orders/demo',
] as const;
let running = true;
async function generateTraffic(): Promise<void> {
  while (running) {
    await Promise.allSettled(trafficTargets.map((url) => fetch(url)));
    await new Promise<void>((resolve) => setTimeout(resolve, 250));
  }
}
void generateTraffic();

let stopping = false;
function shutdown(): void {
  if (stopping) return;
  stopping = true;
  running = false;
  controlServer.close();
  for (const child of children.values()) child.kill('SIGTERM');
  const deadline = setTimeout(() => {
    for (const child of children.values()) child.kill('SIGKILL');
    process.exit(0);
  }, 10_000);
  deadline.unref();
}
process.once('SIGTERM', shutdown);
process.once('SIGINT', shutdown);
console.log('Dummy workload running. Authenticated fault controls: 127.0.0.1:4199. Press Ctrl+C to stop.');

async function control(input: FaultControlRequest, response: ServerResponse): Promise<void> {
  const child = children.get(input.role);
  switch (input.action) {
    case 'stop':
      child?.kill('SIGTERM');
      break;
    case 'restart':
      if (child) {
        child.once('exit', () => launch(input.role));
        child.kill('SIGTERM');
      } else {
        launch(input.role);
      }
      break;
    case 'overflow':
      child?.send({ type: 'overflow' });
      break;
    case 'fault':
      if (!input.values || !Object.keys(input.values).every(isDemoFaultKey)) {
        throw new Error('Fault names are invalid');
      }
      child?.send({ type: 'fault', values: input.values });
      break;
  }
  sendJson(response, 200, { accepted: true });
}
