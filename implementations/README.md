# SDK implementations

This project contains runnable applications using the reusable SDK in [`../package/`](../package/). The [`dummy-servers/`](dummy-servers/README.md) workload demonstrates Express and Fastify APIs, HTTP and SQLite dependency tracing, replicas, a worker, a scheduled job, structured logs, and controlled faults.

The monitoring service must be running first. From this folder, install and build the SDK dependency and the demo apps:

```sh
cd ../package
npm ci
npm run build
cd ../implementations
npm ci
npm run build
npm test
npm run demo
```

The demo reads generated local credentials from `monitoring-system/secrets/`. Use the local profile only for the sample services; create a separate operational inventory and credentials for real services. See [`dummy-servers/README.md`](dummy-servers/README.md) for scenarios and controls, and the [SDK integration guide](../package/docs/sdk-integration.md) for application patterns.
