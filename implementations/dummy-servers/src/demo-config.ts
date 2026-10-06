import type { MonitoringConfig } from '@portable-observability/sdk';

export const demoRoles = ['orders', 'orders2', 'catalog', 'worker', 'scheduler'] as const;
export type DemoRole = (typeof demoRoles)[number];

export interface DemoServiceDefinition {
  readonly service: string;
  readonly tokenRef: string;
  readonly port?: number;
}

export const serviceDefinitions: Record<DemoRole, DemoServiceDefinition> = {
  orders: { service: 'orders-api', tokenRef: 'demo-orders', port: 4101 },
  orders2: { service: 'orders-api', tokenRef: 'demo-orders', port: 4103 },
  catalog: { service: 'catalog-api', tokenRef: 'demo-catalog', port: 4102 },
  worker: { service: 'billing-worker', tokenRef: 'demo-worker' },
  scheduler: { service: 'nightly-job', tokenRef: 'demo-scheduler' },
};

export interface DemoFaultState {
  dependency: boolean;
  slowMs: number;
  dependencySlowMs: number;
  error: boolean;
  heartbeatLoss: boolean;
  stall: boolean;
  missSchedule: boolean;
  drain: boolean;
}

export type DemoFaultKey = keyof DemoFaultState;
export type DemoFaultValue = DemoFaultState[DemoFaultKey];

export const initialFaultState = (): DemoFaultState => ({
  dependency: false,
  slowMs: 0,
  dependencySlowMs: 0,
  error: false,
  heartbeatLoss: false,
  stall: false,
  missSchedule: false,
  drain: false,
});

const booleanFaults = new Set<DemoFaultKey>([
  'dependency', 'error', 'heartbeatLoss', 'stall', 'missSchedule', 'drain',
]);
const numericFaults = new Set<DemoFaultKey>(['slowMs', 'dependencySlowMs']);

export function isDemoRole(value: unknown): value is DemoRole {
  return typeof value === 'string' && (demoRoles as readonly string[]).includes(value);
}

export function isDemoFaultKey(value: unknown): value is DemoFaultKey {
  return typeof value === 'string' && (booleanFaults.has(value as DemoFaultKey) || numericFaults.has(value as DemoFaultKey));
}

export function parseFaultValue(key: DemoFaultKey, value: string): DemoFaultValue {
  if (booleanFaults.has(key)) {
    if (value === 'true') return true;
    if (value === 'false') return false;
    throw new Error(`Fault '${key}' expects true or false`);
  }

  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 60_000) {
    throw new Error(`Fault '${key}' expects a number from 0 to 60000`);
  }
  return parsed;
}

export function isValidFaultValues(value: unknown): value is Partial<DemoFaultState> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  return Object.entries(value).every(([key, entry]) => {
    if (!isDemoFaultKey(key)) return false;
    return booleanFaults.has(key) ? typeof entry === 'boolean'
      : typeof entry === 'number' && Number.isFinite(entry) && entry >= 0 && entry <= 60_000;
  });
}

export function createMonitoringConfig(
  role: DemoRole,
  state: DemoFaultState,
  tokenFile: string,
  endpoint = process.env.MONITORING_ENDPOINT ?? 'http://localhost:8080',
): MonitoringConfig {
  const definition = serviceDefinitions[role];
  return {
    resource: {
      project: 'commerce',
      service: definition.service,
      environment: 'demo',
      instance: `${definition.service}${role === 'orders2' ? '-2' : '-1'}`,
      hostId: 'demo-local',
      buildId: 'demo-1',
    },
    endpoint,
    tokenFile,
    metrics: { mode: 'push', intervalMs: 2_000 },
    logs: { enabled: true, stdout: false, queueSize: 500 },
    traces: { enabled: true },
    readiness: {
      timeoutMs: 500,
      checks: {
        dependency: { check: async () => !state.dependency },
      },
    },
    infrastructure: {
      hostPublisher: role === 'orders',
      filesystemPaths: role === 'orders' ? ['.'] : [],
      cgroup: true,
    },
  };
}
