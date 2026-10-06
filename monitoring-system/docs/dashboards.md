# Reading the dashboards

Overview starts with expected service count, healthy services, services needing
attention, and open incidents. Its compact service table shows current health,
availability, downtime, coverage, and open incidents; click a service for details.
All eight pages preserve project/service/environment and the selected time range.
Units and signal scope appear in each panel title or hover description.

Uptime & reliability reports wall-clock estimates for the selected Grafana range:

- **Uptime** is known time meeting quorum (UP or DEGRADED).
- **Downtime** is known time failing quorum or an explicitly required instance.
- **Degraded** is the available subset with partial failure.
- **Unknown** is missing, stale, or unavailable monitoring evidence. It is not uptime.
- **Maintenance** is configured scheduled time. Overlapping exclusions count once.
- **Availability** is uptime / known eligible time; **coverage** is known / eligible time.
- **Process uptime** on Service detail is Node's time since startup, a different measure.
- **MTTR** is mean confirmed recovery time from detection, for incidents resolved in range.
- **Acknowledgment** is measured only when an operator acknowledges an incident.

Before sufficient coverage, an observed availability percentage can exist but the SLO
result is INSUFFICIENT_DATA. No requests or insufficient request/telemetry coverage
never proves a successful request SLO. Objective tables use their configured windows,
shown in the Window column; the duration tables use the dashboard range.

SQLite preserves status samples across restarts. A known state is carried forward at
most 15 seconds. Longer gaps become UNKNOWN. Earlier records from the original demo
are reconstructed only from persisted check observations, grouped by receipt second;
no missing history is invented. Incident timing includes probe uncertainty bounds.

Service detail includes reachability/readiness, replica quorum, requests, p95,
errors/aborts, process CPU/RSS/heap/uptime, event-loop delay/utilization, GC and jobs.
Infrastructure shows OS-visible publisher data separately from container limits and
configured filesystem capacity. Unsupported cgroups on macOS remain unsupported.

Read API export examples (private bearer credential required):

```
GET /control/reliability?service=orders-api&start=<unix seconds>&end=<unix seconds>&format=csv
GET /control/incidents?project=commerce&format=csv
GET /control/objectives?service=orders-api
```

Report ranges are bounded to 366 days, pages to 1,000 records. API timestamps accept
seconds or Grafana's millisecond timestamps. OpenAPI and TypeScript contracts are in
`contracts/control-api.openapi.json` and `contracts/control-api.ts`.
