# Portable application observability

A repository containing three separately operated projects:

- [`monitoring-system/`](monitoring-system/README.md): the Dockerized Grafana monitoring service and its Python control tooling.
- [`package/`](package/README.md): the independently installable TypeScript SDK, `@portable-observability/sdk`.
- [`implementations/`](implementations/README.md): typed demo services that consume the SDK.

The monitoring service has no build or runtime dependency on the SDK or demo applications. The demos consume the SDK as a local package dependency so you can inspect its configuration and integration clearly.

## Deploy the monitoring system

For the container build, export, and normal Compose startup, the host needs Docker Engine with Compose and Buildx; Python, Node.js, and npm are not required. From a fresh SSH clone:

```sh
git clone git@github.com:zerquiolin/MonitoringSystem.git
cd MonitoringSystem/monitoring-system
scripts/container-cli.sh init --profile local
docker compose -f docker/compose.yaml up --build -d
```

The helper runs initialization and validation inside the monitoring image. The local profile is for evaluation. Before production, configure an operational inventory, TLS, secrets, persistent storage, and alert destinations as described in [deployment operations](monitoring-system/docs/operations.md). Open [Grafana](http://localhost:8080); the generated administrator password is in `monitoring-system/secrets/grafana-admin`.

## Build the SDK and demo projects

These Node.js projects are independent of the monitoring container. Run each setup from its own folder:

```sh
cd package
npm ci
npm run build
npm test

cd ../implementations
npm ci
npm run build
npm test
npm run demo
```

The demo sends metrics, logs, traces, heartbeats, and job events to the local monitoring service. Keep it running while exploring Grafana. See the [implementation guide](implementations/README.md) for configuration and fault controls.

## Documentation

- [Monitoring and Grafana service](monitoring-system/docs/grafana-service.md)
- [Operations and deployment](monitoring-system/docs/operations.md)
- [Architecture and signal flow](monitoring-system/docs/architecture.md)
- [Uptime and reliability definitions](monitoring-system/docs/dashboards.md)
- [SDK package reference](package/docs/package-reference.md)
- [SDK integration guide](package/docs/sdk-integration.md)

Uptime, downtime, degraded, unknown, maintenance, availability, and observation coverage are defined separately in the dashboards guide. Missing telemetry is not counted as uptime; process uptime is separate from service availability.
