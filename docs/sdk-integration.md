# Application integration

Build and pack the package, then install `artifacts/portable-observability-sdk-1.0.0.tgz`
in another application. Node 22 or newer is required. No servers or process handlers
start merely by importing the module. Bootstrap runs before framework/client imports:

```js
import {initializeMonitoring} from '@portable-observability/sdk';
await initializeMonitoring({
  resource: {project:'commerce', service:'orders-api', environment:'demo', instance:'orders-api-1'},
  endpoint: 'http://localhost:8080',
  tokenFile: './private/orders-ingest',
  metrics: {mode:'push'},
  logs: {enabled:true},
  traces: {enabled:true},
  readiness: {checks: {database: {check: async signal => {
    const response = await fetch('https://your-approved-dependency/health', {signal});
    return response.ok;
  }}}}
});
await import('./server.js');
```

For CommonJS, use an async bootstrap `require('@portable-observability/sdk')`, await
initialization, then require application modules. Explicit early loading is needed
for automatic HTTP spans. Manual spans work with ESM/CJS; framework auto-span hooks
can depend on the framework module loader. The demo proves connected HTTP and
manual SQLite dependency spans.

Express uses `app.use(m.middleware())`, `/health` with `m.healthHandler`, `/ready`
with `m.readyHandler`, and `m.errorMiddleware()` before your normal error handler.
Use `m.middleware('/safe/template/:id')` when nested routers cannot expose a complete
safe template. Fastify uses `await m.fastifyPlugin(app)` before registering routes;
wrap health/readiness raw response handlers with `reply.hijack()`. Native HTTP uses
`m.instrumentNative(req,res,'/route/:id')`. Nest's Express adapter can install the same
middleware before the Nest routes; its Fastify adapter can call the plugin before
route registration. Avoid instrumenting the same process under conflicting SDK
configurations; reinitialization with conflicting settings throws.

Pull mode uses `metrics:{mode:'pull'}` and `m.metricsHandler` on your own `/metrics`
route, preferably with `readiness.token` and a separate inventory scrape credential.
Prometheus must reach every scrape endpoint. Exactly one metric reader is enabled.
Logs, traces, and worker events still leave through authenticated push.

`withSpan(name, attributes, async callback)`, `recordException(error, context)`, and
`instrumentJob(name, callback)` preserve thrown errors and context. Heartbeats need
explicit scheduling or `heartbeatIntervalMs`; `reportProgress()` describes meaningful
progress, not idle activity. Custom metrics use `app_business_` names and declared,
bounded dimension values. No request ID/user ID/raw URL is a metric label.

Existing Pino loggers can write to `m.createPinoStream()`; Winston loggers can add
`m.createWinstonTransport()`. Both feed the same sanitizer and bounded export queue.

Logs use `logger.info(message, attributes)` and the other severity methods. Recursive
redaction applies before stdout and export. Avoid sensitive free-form message text:
key-based redaction cannot infer every human-readable secret. Direct delivery is best
effort with capped jittered retries, 1000 queued events by default, 128 per batch,
and visible overflow counters. A response acknowledges Alloy receiver acceptance,
not universal exactly-once durability. Event-ID deduplication covers retry windows.
Metric and trace exporter delivery follows the official OTel exporter behavior.

Readiness checks share a deadline and cached/coalesced execution. An unresolved
callback is quarantined until it settles, preventing subsequent checks from spawning
unlimited hangs. Supply AbortSignal-aware dependency clients. Empty checks only
prove local readiness/drain state. Optional checks do not make the process unready.

`setReady(false)` begins drain. Stop HTTP acceptance, await bounded in-flight drain,
call `shutdown({timeoutMs:5000})`, and let the application own process termination.
No global uncaught-exception handler is installed. `diagnostics()` exposes queue/drop
state and available collector scope. Host/OS collection is opt-in; use one designated
`hostPublisher` per host. Cgroup v2 degrades gracefully when unavailable. Filesystem
metrics refer only to configured visible paths; no privileged mounts are requested.

Dynamic Express mount templates are not exposed reliably at response completion.
Use an explicit full route template inside a mounted router:

```js
router.use(monitoring.middleware('/accounts/:account/items/:id'));
router.get('/items/:id', handler);
app.use('/accounts/:account', router);
```

The adapter retains this override even when application-level middleware registered
first. It never copies resolved `baseUrl` values into metric labels. Nested mounts
without an override use the safely bounded leaf template. Fetch/Undici instrumentation
is enabled for traces; its automatic metrics are dropped to retain one canonical HTTP
metric producer. SDK export failures and last-success timestamps are signal-specific;
log/trace queue gauges and dropped-data counters expose bounded buffering.

An SDK handle owns process-wide OpenTelemetry providers. Repeated compatible initialization
returns that handle; conflicting settings throw. After final shutdown, start a new process
rather than reinstalling global providers in the same process. `recordJobRetry()` records
an application-owned retry without changing retry policy.
