# Dummy servers

Run `npm run demo` from the repository root after the SDK build and monitoring start.
This launches independent processes: Express orders API with replicas (4101 and 4103), Fastify catalog API
(4102), a billing worker, and a scheduled job. Traffic continues four times per second.
Orders calls catalog over instrumented HTTP; catalog queries a real in-memory SQLite
fixture inside a manual dependency span. Logs contain the active trace ID.

All services bind for the monitoring container to reach them through
`host.docker.internal`. Fault administration binds only to loopback and requires the
operator secret. These are deliberately faultable demo applications.

Run these from the repository root:

```sh
node implementations/dummy-servers/fault.mjs catalog fault dependency true
node implementations/dummy-servers/fault.mjs catalog fault dependency false
node implementations/dummy-servers/fault.mjs orders fault slowMs 1200
node implementations/dummy-servers/fault.mjs catalog fault dependencySlowMs 800
node implementations/dummy-servers/fault.mjs orders fault error true
node implementations/dummy-servers/fault.mjs orders fault error false
node implementations/dummy-servers/fault.mjs worker fault heartbeatLoss true
node implementations/dummy-servers/fault.mjs scheduler fault missSchedule true
node implementations/dummy-servers/fault.mjs orders fault drain true
node implementations/dummy-servers/fault.mjs orders overflow
node implementations/dummy-servers/fault.mjs orders2 stop
node implementations/dummy-servers/fault.mjs orders2 restart
node implementations/dummy-servers/fault.mjs catalog stop
node implementations/dummy-servers/fault.mjs catalog restart
```

Reset each fault with `false` or `0`; restarting restores all defaults. `/error`
produces a caught exception. Disconnect a client from `/stream` to create an aborted
response. Low-disk fixtures belong on a disposable bounded test filesystem; do not
fill your machine's disk. See the acceptance report for exercised fault coverage.

## Reporting and operational fixtures

The continuously running demo populates [Overview](http://localhost:8080/d/overview),
[Service detail](http://localhost:8080/d/service), and
[Uptime & reliability](http://localhost:8080/d/incidents). Readiness failure produces
known downtime; an unavailable monitoring pipeline produces unknown time. Process
uptime is a separate metric. Use the selected time range to compare recovery and
maintenance; long SLO windows initially show insufficient coverage.

Additional self-contained fixtures from the repository root:

```sh
monitoring-system/.venv/bin/python monitoring-system/tests/reliability_live.py
monitoring-system/.venv/bin/python monitoring-system/tests/native_notifications.py
monitoring-system/.venv/bin/python monitoring-system/tests/metric_contract.py
monitoring-system/.venv/bin/python monitoring-system/tests/storage_guard.py
monitoring-system/.venv/bin/python monitoring-system/tests/offline_lifecycle.py
monitoring-system/.venv/bin/python monitoring-system/tests/oom_fixture.py
```

Native receiver fixtures bind only to loopback and use generated demo data. Storage,
OOM and offline fixtures use labelled isolated containers/volumes. They do not fill
or remove the central data volume. Operational TLS, backup/restore and architecture
fixtures temporarily stop the main stack and restore it afterwards; run them when an
observation gap is acceptable. Restore the ordinary demo after each fault test.
