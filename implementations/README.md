# SDK implementations

This folder contains runnable applications that use the reusable SDK in
[`../package/`](../package/). The included [`dummy-servers/`](dummy-servers/README.md)
workload demonstrates an Express API, a Fastify API, HTTP and SQLite dependency
tracing, replicas, a worker, a scheduled job, structured logs, and controlled faults.

Run from the repository root after the monitoring system is configured and started:

```sh
npm ci
npm run build
npm run demo
```

The demo reads its generated local credentials from
`monitoring-system/secrets/`. Use the demo only with the local profile; create a
separate operational inventory and application credentials for real services. See
[`dummy-servers/README.md`](dummy-servers/README.md) for fault controls and the
[SDK integration guide](../package/docs/sdk-integration.md) for application patterns.
