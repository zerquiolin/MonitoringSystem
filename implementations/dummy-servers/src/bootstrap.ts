// Initialize telemetry before dynamically importing Express, Fastify, or HTTP clients.
import { initializeMonitoring, type Monitoring } from '@portable-observability/sdk';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  createMonitoringConfig,
  initialFaultState,
  isDemoRole,
  serviceDefinitions,
  type DemoFaultState,
  type DemoRole,
} from './demo-config.js';
import { start, type DemoServer } from './http-services.js';

interface FaultMessage {
  type: 'fault';
  values: Partial<DemoFaultState>;
}

interface OverflowMessage {
  type: 'overflow';
}

type WorkerMessage = FaultMessage | OverflowMessage;

const roleInput: unknown = process.env.DEMO_ROLE ?? 'orders';
if (!isDemoRole(roleInput)) throw new Error(`Unknown demo role: ${String(roleInput)}`);
const role: DemoRole = roleInput;
const definition = serviceDefinitions[role];
const state = initialFaultState();
const tokenFile = fileURLToPath(new URL(`../../../monitoring-system/secrets/${definition.tokenRef}`, import.meta.url));
const config = createMonitoringConfig(role, state, tokenFile);
const monitoring = await initializeMonitoring(config);

function isWorkerMessage(value: unknown): value is WorkerMessage {
  if (typeof value !== 'object' || value === null || !('type' in value)) return false;
  if (value.type === 'overflow') return true;
  return value.type === 'fault' && 'values' in value && typeof value.values === 'object' && value.values !== null;
}

process.on('message', (message: unknown) => {
  if (!isWorkerMessage(message)) return;
  if (message.type === 'overflow') {
    for (let index = 0; index < 2_000; index += 1) {
      monitoring.logger.info('Burst fixture', { index, password: 'SENSITIVE_FIXTURE' });
    }
    return;
  }

  Object.assign(state, message.values);
  if (message.values.drain !== undefined) monitoring.setReady(!message.values.drain);
});

let server: DemoServer | undefined;
let workerTimer: NodeJS.Timeout | undefined;
let scheduleTimer: NodeJS.Timeout | undefined;
let stalled = false;

if (definition.port !== undefined) {
  const appRole = role === 'orders2' ? 'orders' : role;
  if (appRole !== 'orders' && appRole !== 'catalog') throw new Error(`Unexpected HTTP service role: ${appRole}`);
  server = await start(appRole, definition.port, monitoring, state);
} else {
  workerTimer = setInterval(() => {
    void runWorkerTick(role, state, monitoring, () => { stalled = true; }, () => { stalled = false; }, () => stalled);
  }, 3_000);

  if (role === 'scheduler') {
    let lastMinute = -1;
    scheduleTimer = setInterval(() => {
      const minute = Math.floor(Date.now() / 60_000);
      if (minute !== lastMinute && !state.missSchedule) {
        lastMinute = minute;
        void monitoring.instrumentJob('nightly-summary', async () => {
          monitoring.logger.info('Scheduled report generated');
        });
      }
    }, 1_000);
  }
}

async function runWorkerTick(
  currentRole: DemoRole,
  fault: DemoFaultState,
  client: Monitoring,
  markStalled: () => void,
  clearStalled: () => void,
  isStalled: () => boolean,
): Promise<void> {
  if (!fault.heartbeatLoss) await client.heartbeat();
  if (currentRole === 'worker' && fault.stall && !isStalled()) {
    markStalled();
    void client.instrumentJob('stalled', async () => {
      while (fault.stall) await new Promise<void>((resolve) => setTimeout(resolve, 500));
      clearStalled();
    });
  }
  if (currentRole === 'worker' && !fault.stall) {
    await client.instrumentJob('billing', async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 50));
      client.reportProgress();
      client.logger.info('Billing job completed', { operation: 'bill' });
    });
  }
}

let ending = false;
async function stop(): Promise<void> {
  if (ending) return;
  ending = true;
  monitoring.setReady(false);
  if (workerTimer) clearInterval(workerTimer);
  if (scheduleTimer) clearInterval(scheduleTimer);

  const deadline = setTimeout(() => process.exit(1), 8_000);
  if (server) {
    await Promise.race([
      server.close(),
      new Promise<void>((resolve) => setTimeout(resolve, 3_000)),
    ]);
  }
  await monitoring.shutdown({ timeoutMs: 4_000 });
  clearTimeout(deadline);
  process.exit(0);
}

process.once('SIGTERM', () => { void stop(); });
process.once('SIGINT', () => { void stop(); });
process.send?.({ type: 'ready', role, port: definition.port });
