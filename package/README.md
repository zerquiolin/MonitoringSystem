# @portable-observability/sdk

TypeScript SDK for sending application metrics, logs, traces, heartbeats, and job
events to Portable Application Observability. It instruments application processes;
the central monitoring service is deployed separately.

## Quick start

```ts
import { initializeMonitoring } from '@portable-observability/sdk';

const monitoring = await initializeMonitoring({
  resource: { project: 'commerce', service: 'orders-api', environment: 'demo', instance: 'orders-api-1' },
  endpoint: process.env.MONITORING_ENDPOINT,
  tokenFile: process.env.MONITORING_TOKEN_FILE,
  metrics: { mode: 'push' }, logs: { enabled: true }, traces: { enabled: true },
});

// Initialize before importing the instrumented framework or client.
await import('./server.js');
```

The handle provides Express middleware, a Fastify plugin, native HTTP
instrumentation, health/readiness/pull-metrics handlers, correlated logging, manual
spans, bounded custom instruments, worker/job events, diagnostics, flushing, and
bounded shutdown. The application owns its HTTP server and process lifecycle.

## Documentation

- [Full SDK package reference](https://github.com/zerquiolin/MonitoringSystem/blob/main/docs/package-reference.md)
- [Framework integration examples](https://github.com/zerquiolin/MonitoringSystem/blob/main/docs/sdk-integration.md)
- [Central Grafana service guide](https://github.com/zerquiolin/MonitoringSystem/blob/main/docs/grafana-service.md)

Pull and push metrics are mutually exclusive. Log delivery uses bounded best-effort
queues, not exactly-once durability. Health/readiness do not prove remote dependency
health, and infrastructure metrics reflect only what the process environment exposes.
