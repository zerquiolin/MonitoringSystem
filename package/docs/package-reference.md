# Node.js SDK package reference

`package/` contains the independently installable `@portable-observability/sdk`
TypeScript package. It instruments application processes and exports telemetry to
the central monitoring service. It does not start Grafana, Prometheus, or an
application HTTP server. The root [README](../README.md) describes the complete
stack; the [SDK integration guide](sdk-integration.md) has framework recipes.

## Install and initialize

Install the published package or build a local tarball from this repository. To
work on the package from this repository, use its project folder and lockfile:

```sh
cd package
npm ci
npm run build
npm test
npm pack --pack-destination ../monitoring-system/artifacts
```

The monitoring system and demo projects have their own environments. The
application must reach the central gateway and read its private token. Initialize
once, before importing libraries that need automatic instrumentation:

```ts
import { initializeMonitoring } from '@portable-observability/sdk';

const monitoring = await initializeMonitoring({
  resource: {
    project: 'commerce', service: 'orders-api', environment: 'production',
    instance: process.env.INSTANCE_ID ?? 'orders-api-1',
  },
  endpoint: process.env.MONITORING_ENDPOINT!,
  tokenFile: process.env.MONITORING_TOKEN_FILE!,
  metrics: { mode: 'push', intervalMs: 5_000 },
  logs: { enabled: true },
  traces: { enabled: true, sampleRatio: 1 },
});

// Import the instrumented framework/client after initialization.
await import('./server.js');
```

Do not embed ingestion tokens in source, images, or command-line arguments. Give
each application instance its own inventory identity and credential. Resource
identity is bounded to project/service/environment/instance and optional build/host
metadata. Do not put user IDs, request IDs, full URLs, or other unbounded values in
metric dimensions.

## Configuration

| Option | Purpose |
| --- | --- |
| `resource` | Required project/service/environment/instance identity; optional build and host metadata |
| `endpoint` | Central gateway base URL, including scheme and port |
| `tokenFile` | Private file containing the application ingestion credential |
| `metrics.mode` | `push` (default) exports periodically; `pull` exposes an authenticated scrape handler |
| `metrics.intervalMs` | Push interval; defaults to 5 seconds |
| `logs.enabled` / `logs.stdout` | Enable central log export and local structured stdout independently |
| `logs.queueSize` / `logs.batchSize` | Bound in-memory queue and batch size |
| `logs.redact` | Additional redaction patterns for messages and attributes |
| `traces.enabled` / `traces.sampleRatio` | Enable tracing and set root trace sampling probability |
| `heartbeatIntervalMs` | Publish liveness/readiness/progress/job heartbeat at this interval |
| `readiness` | Configure readiness and optional protection for local handlers |
| `infrastructure` | Opt into OS-visible host, filesystem-visible, or cgroup-v2 readings |

The endpoint protocol, token, and identity are validated during setup. Push and pull
metrics modes are mutually exclusive. Initialization is idempotent for the same
configuration and rejects conflicting repeated initialization. Importing the package
alone does not create servers or install global process termination handlers.

## Metrics and HTTP instrumentation

The SDK instruments supported native Node HTTP requests and provides Express
middleware/error middleware and a Fastify plugin. Register route-aware instrumentation
so route templates, not raw paths, become metric labels. Health, readiness, and
metrics endpoints are excluded by default.

Core measurements include completed/aborted/in-flight HTTP requests and duration;
deduplicated application exceptions; process RSS, heap, CPU, start time and uptime;
event-loop delay/utilization and garbage collection; telemetry export failures,
drops, last successful export, queue depth, and collector capability; and job
completion/failure/retry/in-flight counts and duration.

Request duration histograms use explicit bucket boundaries. To calculate fleet p95,
aggregate compatible histogram buckets across instances before applying
`histogram_quantile`; do not average per-instance percentiles. Aborted requests are
separate from completed responses. Metric labels use bounded method, route template,
status class, and resource identity. Unknown/high-cardinality routes map to
`unmatched` or `other`.

Custom instruments are restricted to the `app_business_*` namespace, approved label
values, at most five label keys, 32 instrument names, and 100 series per instrument.
Use `customCounter`, `customGauge`, or `customHistogram`; never use customer values as
labels. See the [metric contract](../../monitoring-system/contracts/metrics.md) for names and units.

## Health and readiness

The returned handle supplies `healthHandler`, `readyHandler`, and (in pull mode)
`metricsHandler`. Mount them on the application-owned server at configured paths.
Health reports process liveness. Readiness reports the application's readiness flag;
it does not independently prove every downstream dependency is healthy. Protect
handlers with the optional readiness token when exposing them beyond a trusted probe
network. Handlers allow GET/HEAD and do not record their own requests.

Heartbeat observations use receipt time and include boot identity, sequence,
readiness, progress, active jobs, and timestamp. An expired heartbeat means evidence
is stale; it is not definitive proof that a host or process crashed.

## Logs and trace correlation

Structured logs can go to stdout and the central service. Adapters are provided for
Pino and Winston; the logger API can also be used directly. Events include resource
identity, severity, timestamp, and active trace/span IDs when available. The
asynchronous queue and batch sizes are bounded. Transient server/rate-limit errors
retry with capped backoff; permanent rejections are dropped and reflected in drop
counters. Delivery is best-effort, not exactly-once durable. Keep stdout collection
consistent with the central pipeline to avoid duplicate ingestion.

Automatic HTTP tracing and manual `withSpan(name, attributes, callback)` spans share
context. Use manual spans around meaningful business operations and jobs. Full URL
fields are redacted and attribute redaction is configurable. Root traces default to
sample ratio 1; tune this for production traffic and storage budgets.

## Workers and background jobs

`instrumentJob(name, callback)` tracks active work, duration, completion/failure,
trace context, and job lifecycle events. `recordJobRetry()` records an
application-owned retry; `reportProgress()` advances heartbeat progress. Use
`setReady(false)` during startup or drain and restore readiness once the application
can serve traffic. The SDK reports job events but does not choose scheduling, retry,
or concurrency policy. The evaluator detects expired heartbeats and stale/interrupted
jobs from receipt time and boot identity.

## Infrastructure scope

Infrastructure sampling is opt-in. `hostPublisher` describes the operating system
visible to Node; in containers or Docker Desktop, this may describe a VM or container,
not the physical host. Filesystem values describe configured paths visible to the
process. Cgroup-v2 readings are emitted only when supported. Capability gauges make
unsupported readings explicit; zero does not stand in for a missing measurement.
Compare only measurements with matching `scope` labels.

## Shutdown, performance, and limitations

The application owns server startup, signal handling, and termination. During
graceful shutdown, stop accepting requests, set readiness false, drain in-flight work,
then call `forceFlush()` and `shutdown({ timeoutMs })` within the termination budget.
Shutdown flushes bounded log queues and OpenTelemetry readers best-effort; forced
termination can lose queued telemetry.

The SDK uses timers for export, optional heartbeat, event-loop/GC observation, and
infrastructure sampling. Export requests have timeouts; queues, batches, custom
series, and trace spans are capped. Telemetry should not block request handling.
Metric counters reset on process restart; central reliability history is persisted
separately. OS/container measurements describe only what the runtime can observe.
The single-node central monitoring system shares its host failure domain.

## Build, test, and consume locally

From the repository root:

```sh
npm ci
npm run build
npm test
npm run pack
```

The tarball is written under `monitoring-system/artifacts/` and can be installed into a demo application
with `npm install /path/to/portable-observability-sdk-1.0.0.tgz`. Public entry points
support ESM, CommonJS, and TypeScript. See the [integration guide](sdk-integration.md),
[dashboard definitions](../../monitoring-system/docs/dashboards.md), and [complete metric contract](../../monitoring-system/contracts/metrics.md).
