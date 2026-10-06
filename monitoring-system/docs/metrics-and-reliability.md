# Measurements and interpretation

Identity maps project/service/environment/instance to explicit bounded metric labels
and OTel service namespace/name/environment/instance attributes. Loki indexes only
project/service/environment; instance and trace IDs stay in its JSON event body.
Build ID is only `app_build_info` metadata. Counters reset at process restart.

`app_http_requests_total` counts completed responses once, with method, safe route,
and status class. `app_http_request_duration_seconds` observes completed requests
at .005/.01/.025/.05/.1/.25/.5/1/2.5/5/10 seconds plus infinity. Client disconnects
before finish count only in `app_http_requests_aborted_total`; in-flight decrements
once even when close follows finish. `/health`, `/ready`, and `/metrics` are excluded.
Sum compatible histogram buckets across instances, then use `histogram_quantile`;
never average instance p95. CPU counter rate is CPU cores consumed; RSS/heap belong
to one Node process. OS-visible RAM is not a cgroup denominator. Container and visible
filesystem metrics have explicit scope labels and may be unsupported.

Inventory persists when a signal disappears. The evaluator uses received heartbeat
time and actual Prometheus sample freshness, not an eternally cached success.
Instance quorum applies to whole instances, including their required readiness checks.
Logical states include UP/DOWN/DEGRADED/UNKNOWN/MAINTENANCE/DRAINING; raw recent
observations and debounced incidents differ. UNKNOWN never fabricates recovery. Maintenance suppresses delivery; raw outage
observations and incidents continue. Retirement does not count as recovery. Downtime onset lies between previous success and first failure; detection
is when the consecutive-failure policy opens the incident. `recovered` is confirmed
recovery after consecutive successes. Incident IDs, active ledger, and debounce state
survive restart. Dependencies indicate declared relationships, not proven root cause.

Observed availability is available duration divided by known duration. Uptime includes
quorum-preserving DEGRADED duration; downtime includes known DOWN duration. UNKNOWN,
maintenance and draining remain separate. Coverage is known / eligible elapsed time,
with operator-selected maintenance exclusion. Request success and latency objectives
use independently configured windows (default 30 days), route templates, volume and
coverage guards. Current request performance uses five minutes. Partial windows are
labelled; these measurements are observed estimates, not exact contractual SLAs.

The eight dashboards separate expected state, request metrics, scope-aware resource
metrics, logs, traces, incident/objective history, and the monitoring pipeline.
Grafana offers built-in trace/log links; shipped dashboards and data sources are
provisioned at startup. Control data uses the bundled Infinity backend with a private
read-only credential. Keep organizational Grafana roles; label selectors are not
multi-tenant authorization.

## Durable time measurements

The control service publishes `monitoring_service_uptime_seconds`,
`monitoring_service_downtime_seconds`, `monitoring_service_unknown_seconds`,
`monitoring_service_degraded_seconds`, `monitoring_service_maintenance_seconds`,
`monitoring_service_availability_ratio`, `monitoring_service_coverage_ratio`,
`monitoring_service_incidents`, `monitoring_service_active_incidents`,
`monitoring_service_mttr_seconds`, and `monitoring_service_error_budget_consumed_ratio`.
These gauges describe rolling configured windows; they are not cumulative counters.
The JSON/CSV report API also supports arbitrary bounded dashboard ranges.

`monitoring_service_burn_rate` uses known duration failure / allowed failure fraction,
with 5m, 30m, 1h and 6h windows and a 95% coverage guard. Fast/slow alert pairs require
both their long and short windows to burn before firing. Missing coverage is absent.

Request SLOs use their configured window and route template, volume guards and fresh
telemetry coverage. Prometheus counter increases can be fractional because the backend
extrapolates sampled boundaries. The report does not claim exact billing counts.
Upstream OTLP partial rejection is exported separately from accepted batch counts;
the maintained SDK logs its standard partial-success warning rather than retrying
already accepted items as if the whole batch failed.
