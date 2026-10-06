# Grafana service guide

This guide explains how to operate the Grafana experience shipped with Portable
Application Observability. The service is provisioned from repository configuration
and starts with the central monitoring container.

## Access and startup

For a local demo, follow the root [README](../README.md). The gateway is published
on `127.0.0.1:8080`; open [Grafana](http://localhost:8080). The local admin password
is generated in `secrets/grafana-admin`. Operational deployments use TLS on port
8443 and the configured `publicUrl`. Grafana, Prometheus, Loki, Tempo, and the
control API are not published as independent host ports.

Grafana and its data sources are provisioned at startup. Source-controlled
provisioning is generated from inventory and files under `docker/`. Edit those
inputs and use the validate/render/apply workflow; do not edit generated runtime
files inside a running container. Dashboards reconcile on restart. Keep
operator-created dashboards in a separate folder with distinct UIDs.

## Data sources and signal flow

| Source | UID | Contents |
| --- | --- | --- |
| Prometheus | `prometheus` | SDK metrics, probes, monitoring health, reliability-window gauges |
| Loki | `loki` | Structured application logs with project/service/environment labels |
| Tempo | `tempo` | Distributed traces and service dependency views |
| Control API | `control` | Expected inventory, current status, incidents, bounded reliability reports |

Applications send authenticated metrics, logs, traces, heartbeats, and job events
through the gateway. Blackbox Exporter probes configured HTTP endpoints. The control
service evaluates observations and stores durable status/incident history in SQLite.
Grafana combines these sources; missing signals are not treated as healthy. The
Control API source uses a private read-only credential. Grafana dashboard variables
are filters, not tenant authorization; restrict organization access to trusted users.

## Dashboard map

The **Observability** folder contains eight provisioned dashboards:

1. **Global overview** — expected service count, health/attention counts, incidents,
   and a compact availability/downtime table with service drill-down.
2. **Projects** — project health, service state, and incident rollups.
3. **Service detail** — reachability/readiness, replica quorum, request rate, errors,
   aborts, latency, process metrics, and recent incidents.
4. **Infrastructure** — OS-visible, filesystem-visible, and container/cgroup readings
   with explicit scope labels.
5. **Logs & errors** — application events and errors with trace correlation.
6. **Traces & dependencies** — trace search, service graph, and dependency context.
7. **Uptime & reliability** — uptime, downtime, degraded, unknown, and maintenance
   durations; availability, coverage, objectives, error budget, burn, and incident
   recovery measurements.
8. **Monitoring health** — probe/export pipeline health, collector capabilities,
   stale signals, and backend readiness.

Variables filter project, service, environment, instance, and (where useful) host.
The time picker controls the report range, and linked dashboards preserve filters.
Start at Global overview, then drill into Service detail or Uptime & reliability.
Panel titles and descriptions identify units and scope. Use the panel menu to inspect
PromQL/LogQL or report queries when validating a result.

## Uptime, downtime, and missing data

Time reports use the selected dashboard range. **Uptime** is known time meeting
configured instance quorum; a quorum-preserving partial failure is **degraded** time.
**Downtime** is known time failing quorum or a required-instance rule. **Unknown**
means evidence is absent, stale, or the monitoring pipeline cannot establish state.
Unknown time is never counted as uptime. **Coverage** is known eligible time divided
by eligible elapsed time. **Availability** is uptime divided by known eligible time.
Scheduled maintenance is separate and can optionally be excluded from eligible time.
The Service detail process-uptime panel means time since that process started; it is
not service availability. See [dashboard measurement definitions](dashboards.md) and
[signal semantics](metrics-and-reliability.md) for formulas, quorum, freshness, and
objective coverage rules.

Some Prometheus reliability gauges represent configured rolling windows, while the
Control API reports bounded arbitrary ranges. Check the Window column and selected
Grafana range before comparing values. MTTR is based on confirmed recovery of
incidents resolved in the selected interval. Acknowledgment time only exists when an
operator acknowledges an incident.

## Alerts and notifications

Provisioned alert rules cover service reachability and quorum, stale monitoring,
pipeline/backend health, resource pressure, objectives, and multi-window burn rates.
Missing coverage is surfaced as insufficient evidence rather than success.
Maintenance can silence delivery while observations continue. Configure receivers,
secret references, and routing in inventory, apply, then run
`python3 scripts/monitoring.py notification-test --destination NAME` to test the
Grafana integration. A local receiver confirms local routing only, not external
email/chat delivery.

## Reports and API

The control API exposes authenticated JSON/CSV exports. Its bearer credential is in
the private `secrets/dashboard-read` file; never paste it into a URL, dashboard, or
shell history. Example paths:

```text
/control/reliability?service=orders-api&start=<unix-seconds>&end=<unix-seconds>&format=csv
/control/incidents?project=commerce&format=json
/control/objectives?service=orders-api
```

Ranges are bounded to 366 days and pages to 1,000 records. OpenAPI and TypeScript
contracts are in `contracts/`. Timestamps accept Unix seconds or Grafana milliseconds.
Reports use persisted receipt-time observations and explicit unknown intervals; they
do not invent history before the first retained observation.

## Troubleshooting

- **No services appear:** check active project/environment variables, inventory,
  control-source health, and whether the demo/application registered its inventory.
- **Metrics missing:** inspect Monitoring health, `app_collector_capability`, export
  failures, and last-success signals. Verify gateway reachability, identity, and token.
- **Logs or traces missing:** verify SDK options and collector capability, expand the
  time range, and check project/service/environment filters.
- **Unknown instead of down/up:** inspect probe reachability, sample freshness, and
  pipeline health. UNKNOWN differs deliberately from a confirmed application outage.
- **Dashboard changed unexpectedly:** update the source-controlled provisioned
  dashboard and apply/restart. Keep manual dashboards in a separate folder.
- **No external notification:** validate receiver credentials and routing, then test
  the destination. A firing rule and successful external delivery are separate checks.

For network boundaries, backup/restore, retention, TLS, and lifecycle, see
[operator procedures](operations.md) and [architecture](architecture.md).
