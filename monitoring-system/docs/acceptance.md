# Delivery and executed acceptance

The portable project includes the single central image, independently installable SDK,
separate dummy servers, schemas, configuration/credential tools, eight provisioned
Grafana dashboards, native alert integrations, durable reliability reports and
operational documentation. Evidence below is from real local containers and fixtures.
The original handoff remains reference material; this document records implementation
and evidence, without treating its instructions as authorization for external deployment.

## Reliability and interface

Uptime and downtime are elapsed observed seconds, distinct from process uptime.
DEGRADED means service quorum remains available. Expired evidence and monitoring gaps
are UNKNOWN. Availability divides available by known time; coverage separately measures
known time against eligible time. Maintenance exclusions are explicit and overlap is
counted once. Request objectives use independently configured windows and route templates;
maintenance is removed from counter-query intervals too. Volume/coverage guards prevent
zero traffic or incomplete history from proving compliance. Short-window request
performance is separate from long-window objective compliance.

Incident history persists detection, uncertainty bounds, confirmed recovery,
acknowledgment and annotations. Retirement is recorded separately from recovery.
Delivery and silence do not remove incidents. JSON/CSV reports follow the dashboard
range; configured SLO reports retain their own windows. Four summary cards, compact
service tables, readable units and separate reliability, resource, log, trace and
monitoring pages keep operational views concise.

## Executed evidence

| Evidence | What was asserted |
|---|---|
| `acceptance.json` | Nine supervised components in one container, real telemetry/probes/log-trace correlation, provisioning, fault recovery and native notification self-test |
| `dashboard-queries.json` | Every provisioned panel queried through Grafana's actual data sources, with no backend query error |
| `reliability.json`, `unit-tests.log` | Elapsed uptime/downtime, unknown gaps, maintenance arithmetic, quorum, coverage, MTTR/acknowledgment, restart durability, configured route/window validation, worker source/replay/overlap/DST contracts |
| `reconciliation.json` | Real removed-rule cleanup, invalid candidate preserving active inventory and rollback restoring inventory |
| `operational-tls.json` | Verified HTTPS gateway, authenticated custom-CA JSON probe, untrusted certificate rejection, expiring hashed credentials, immediate durable revocation and read-only boundaries |
| `network-probes.json` | Real TCP and DNS modules |
| `security.json`, `extended-security.json` | Binary/JSON/gzip authorization, scope spoofing, body/compression limits, actual binary trace storage/redaction and resource-scoped log duplicate suppression |
| `metric-pipeline.json`, `metric-contract.json` | Outbound-only application, delta conversion, actual histogram buckets, real Prometheus pull identity/names, cumulative reset and invalid histogram rejection |
| `framework-tests.log`, `package-tests.log` | Real Express/Fastify/native lifecycle, nested templates, abort/stream/error/drain, independently installed CJS/ESM/TypeScript SDK tarball |
| `exporter-outage.log` | Real failed maintained exporters, bounded queues/visible drops, continued requests and recovery |
| `replicas.json`, `workers.json` | Replica/quorum and heartbeat/progress/scheduled-deadline faults with recovery |
| `native-notifications.json`, `alert-lifecycle.json` | Native email/Slack/Teams/webhook local firing/resolved payloads, multiple routes, maintenance suppression, retained incident evidence and acknowledgment |
| `persistence.json` | Offline backup restored into an isolated empty volume: metrics, logs, trace, dashboards, credentials, inventory and ongoing incident |
| `retention.json`, `control-retention.json`, `storage-guard.json` | Actual Prometheus/Loki/Tempo deletion, expired control-event pruning retaining incident summaries, low-space rejection on isolated bounded tmpfs |
| `offline-lifecycle.json`, `oom.json`, `watchdog.json` | Disconnected fresh startup, stopped/killed backend, graceful/forced stop, actual isolated kernel OOM and adequate-budget recovery |
| `platform-amd64.json`, build logs | Native ARM64 and rebuilt/emulated AMD64 runtime configurations and all-component readiness |
| `benchmark.json`, `capacity.json` | SDK overhead comparison and a measured ten-minute complete telemetry workload, including central CPU/RAM and request latency |

A successful query may return no frames when a feature has no observations; this is
shown as No data, not zero use or compliance. Native notification fixtures validate
Grafana's adapters and payloads locally; they are not real provider-account delivery.
The capacity measurement is the tested envelope on this Docker Desktop host, not a
maximum throughput claim or an indefinite-load guarantee. AMD64 execution was emulated.

Loki retention proof checks physical expired chunk deletion. Cached/index query results
can briefly outlive deleted chunks; configured maximum query lookback also bounds the
production query horizon. Tempo retention is block based, so mixed-age spans expire
according to block retention. Retention does not cap every WAL/index/active-block byte.
Stopped-stack backup creates an observation gap, explicitly recorded as unknown.
Manual Docker stop/kill requires explicit start; unexpected child faults use the restart
policy. Incident summaries are retained when detailed observations expire.

## External deployment checks

The self-contained demonstration is deployable without cloud accounts. Production
acceptance still requires the actual deployment host, endpoints/repositories, approved
private networks, trusted TLS files, notification accounts and private credentials.
Verify destinations with those credentials before accepting external alert delivery.
Native AMD64 production performance, real host failover and provider availability were
not tested. The one-container design intentionally has one host/failure domain; it
cannot alert after its own entire host loses power. No production data or credentials
are included in distributable source, SDK or image archives.

See `../artifacts/completion-matrix.json` for criterion-specific evidence. The project
owner keeps distributable checksums alongside the source archive.
