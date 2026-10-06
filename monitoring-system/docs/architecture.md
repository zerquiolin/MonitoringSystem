# Architecture and decisions

One central Linux container owns Grafana, Prometheus, Blackbox Exporter, Loki,
Tempo, Alloy, nginx, FastAPI/SQLite, Supervisor, and a watchdog. The dummy processes
are application workloads; the reusable SDK has no central server or mandatory
sidecar. Every backend binds loopback. Only nginx is published, on host loopback
for the local profile. Internal listeners are not an organizational tenant boundary:
all users of one Grafana organization must be trusted. Use Grafana Viewer/Editor
roles for users; the internal Infinity credential is read-only.

Signal paths:

* HTTP probes: Prometheus → Blackbox → configured application health/readiness URLs.
* Metrics: official OpenTelemetry HTTP JSON exporter → authenticated control ingress
  → Alloy → Prometheus remote write. Resource identity and metric dimensions are
  validated before forwarding. Binary OTLP uses generated official protobuf messages.
* Logs: Pino stdout and a bounded direct-export adapter → scoped ingress → Alloy
  Loki receiver and WAL → Loki. Do not also scrape stdout into Loki.
* Traces: OTel automatic HTTP instrumentation plus manual operation/job spans →
  scoped ingress → Alloy → Tempo monolith. Tempo emits separate service graph metrics.
* Workers: receipt-time heartbeats and job events → SQLite → evaluator and self metrics.
* Grafana Infinity: internal read-only API → persistent expected inventory and ledger.

Tempo 2.10.7 is deliberately pinned: the portable local-storage configuration is a
2.x monolith, avoiding Tempo 3's ingestion architecture and Kafka requirement.
Alloy's delta-to-cumulative processor requires its experimental feature level in
this pinned version. The SDK defaults to cumulative metrics. Keep these decisions
when upgrading and exercise real configurations. Node runtime and HTTP automatic
metrics are disabled; the SDK owns canonical application request metrics once.

Supervision starts storage before forwarding, control, UI, and gateway. Readiness
checks every backend and evaluator freshness. A crash or repeated hang writes a
fatal marker and stops supervision; the wrapper returns a failed exit so Docker's
restart policy can recover. Supervisor reaps children; Tini forwards signals. Service
processes run as UID 10001 after private secret copies and data ownership setup.
Generated configuration is transient; durable last-known-good metadata is under
`/data/config-state`. Configuration changes use a controlled restart, not an atomic
hot-reload claim across unrelated backends. Operator-created Grafana resources should
use separate folders and UIDs.

The container and host are one shared failure domain. Host loss also loses alert
execution until recovery. Use an independently hosted watchdog against `/ready`.
Local filesystem storage has no replication and competes for one disk. Docker
Desktop observations describe its Linux VM or the SDK's own OS-visible environment,
not inaccessible macOS/Windows host resources.

This is a single-node application monitor. Defaults allocate 4 GiB RAM and 4 CPU
cores, 1 GiB Prometheus TSDB, seven-day metrics/logs, two-day traces, and 90-day
control observations. WAL/index/active blocks require additional disk; retention
settings do not cap the entire volume. See actual test evidence and capacity limits.
