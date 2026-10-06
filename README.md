# Portable application observability

A multi-service observability stack with a standalone Node.js/TypeScript SDK and
runnable application examples. The repository is separated by responsibility:

```text
monitoring-system/          Central monitoring service, configuration, dashboards, operations, tests
package/                    Installable @portable-observability/sdk
implementations/            Demo applications built with the SDK
```

The central service runs Grafana, Prometheus, Blackbox Exporter, Loki, Tempo, Alloy,
the scoped control API and SQLite incident ledger, nginx, and process supervision in
one Docker container. The SDK exports application metrics, logs, traces, heartbeats,
and job events. The demo applications are strict TypeScript consumers of the SDK;
they generate traffic and controllable failures.

## Quick start

Requirements: Docker with 4 GiB of memory available, Node.js 22+, npm, and Python
3.11+. Run the following from the repository root:

```sh
python3 -m venv monitoring-system/.venv
monitoring-system/.venv/bin/pip install -r monitoring-system/docker/control/requirements.lock.txt
npm ci
python3 monitoring-system/scripts/monitoring.py init --profile local
python3 monitoring-system/scripts/monitoring.py validate --config monitoring-system/config/inventory.yaml
npm run build
npm test
docker compose -f monitoring-system/docker/compose.yaml up --build -d
npm run demo
```

Keep `npm run demo` running. Open [Grafana](http://localhost:8080/d/overview/overview)
and sign in as `admin` with the generated password in
`monitoring-system/secrets/grafana-admin`. The eight dashboards are provisioned
under the Observability folder. See the
[implementation guide](implementations/README.md) for demo scenarios and controls.

## Documentation

- [Monitoring system and Grafana](monitoring-system/docs/grafana-service.md)
- [Operations and deployment](monitoring-system/docs/operations.md)
- [Architecture and signal flow](monitoring-system/docs/architecture.md)
- [Uptime and reliability definitions](monitoring-system/docs/dashboards.md)
- [SDK package reference](package/docs/package-reference.md)
- [SDK integration examples](package/docs/sdk-integration.md)

Reliability views distinguish uptime, downtime, degraded, unknown, maintenance,
availability, and observation coverage. Missing telemetry is not counted as uptime.
Process uptime is a separate measure from service availability.

## Build and test

The npm workspace at the repository root coordinates the independent SDK and typed
demo implementations. `npm run build` compiles both, and `npm test` checks the SDK,
type-checks the demo sources, and runs the central service's unit suite. The central
service tests and operational tools are in `monitoring-system/`. Useful checks are:

```sh
npm run test:integration
npm run test:acceptance
docker compose -f monitoring-system/docker/compose.yaml stop
```

The container image is built from source; the large prebuilt archive is not stored in
Git. Image build and export instructions are in
[monitoring-system/README.md](monitoring-system/README.md).

## Repository boundaries

`monitoring-system/` owns the Grafana service, inventory, data contracts, dashboards,
operations scripts, and service tests. `package/` owns the reusable SDK and its
package documentation. `implementations/` contains sample applications that consume
the SDK. Root `package.json` and `package-lock.json` manage the npm workspaces only.
Credentials, generated configuration, virtual environments, and runtime data stay
outside source control.
