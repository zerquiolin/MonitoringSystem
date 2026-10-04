# Portable application observability

A portable observability stack for multiple applications and microservices. One
central Docker container runs Grafana, Prometheus, Blackbox Exporter, Loki, Tempo,
Alloy, the scoped control API and SQLite incident ledger, nginx, and process
supervision. Applications use the separate Node.js/TypeScript SDK. The
[`dummy-servers/`](dummy-servers/README.md) demo generates real traffic, logs, traces,
heartbeats, scheduled work, and controllable failures.

## Quick start

Requirements: Docker with 4 GiB of memory available, Node.js 22+, npm, and Python
3.11+. From the repository root:

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r docker/control/requirements.lock.txt
npm ci
python3 scripts/monitoring.py init --profile local
python3 scripts/monitoring.py validate --config config/inventory.yaml
python3 scripts/monitoring.py render --config config/inventory.yaml
npm run build
npm test
docker compose -f docker/compose.yaml up --build -d
npm run demo
```

Keep `npm run demo` running. Open [Grafana](http://localhost:8080/d/overview/overview)
and sign in as `admin` with the generated password in `secrets/grafana-admin`. The
Observability folder has eight provisioned dashboards. Live request metrics arrive
immediately; logs, traces, and reliability observations follow as the demo runs.
The second orders replica demonstrates quorum and partial failure. See the
[dummy-server guide](dummy-servers/README.md) for fault controls and recovery.

To stop the demo, press Ctrl+C in its terminal. Stop the central service with
`docker compose -f docker/compose.yaml stop`; its persistent volume retains data.

## Dashboards and reliability

The [Grafana service guide](docs/grafana-service.md) explains provisioning, data
sources, dashboard navigation, alerts, credentials, and troubleshooting. The
[dashboard guide](docs/dashboards.md) defines the reliability measurements. Uptime,
downtime, unknown time, availability, and observation coverage use the selected time
range; process uptime is a separate measure. Reports preserve missing evidence as
unknown instead of counting it as successful uptime. The service and incident report
APIs export JSON or CSV under the authenticated control API.

## Application SDK

The [`package/`](package/) directory is the independently installable TypeScript SDK.
See the [package reference](docs/package-reference.md) for setup, configuration,
metrics, health/readiness, logging, tracing, workers, shutdown, and limits; the
[integration guide](docs/sdk-integration.md) provides framework examples. Build and
test it with `npm run build`, `npm test`, then create an installable tarball with
`npm run pack`.

## Configuration, operation, and tests

`python3 scripts/monitoring.py --help` lists configuration validation/render/diff,
apply/rollback, token rotation/revocation, backup/restore, diagnostics, and
notification tests. Read [operations](docs/operations.md), [architecture](docs/architecture.md),
[metrics and reliability definitions](docs/metrics-and-reliability.md), and the
[acceptance audit](docs/acceptance.md) before operational deployment.

Useful local checks:

```sh
npm run test:integration
npm run test:acceptance
python3 tests/dashboard_queries.py
python3 tests/reliability_live.py
python3 scripts/monitoring.py diagnose
python3 scripts/monitoring.py notification-test
```

## Build and export images

The repository builds images locally; the large prebuilt image archive is kept out
of Git. Build the native architecture with Compose:

```sh
docker compose -f docker/compose.yaml build monitoring
```

Build AMD64 and ARM64 variants with Docker Buildx when needed:

```sh
docker buildx build --platform linux/amd64 -f docker/Dockerfile -t portable-observability:amd64 --load .
docker buildx build --platform linux/arm64 -f docker/Dockerfile -t portable-observability:arm64 --load .
```

Export locally with `docker save portable-observability:local -o monitoring-image.tar`
and load it on a compatible host with `docker load -i monitoring-image.tar`. Runtime
startup requires no package or plugin downloads.

## Operational deployment

The local profile binds HTTP to host loopback and generates private credentials. An
operational deployment needs a verified TLS certificate/key, an HTTPS `publicUrl`,
approved application networks, reachable probe targets, and configured notification
destinations and credentials. Configure and test these with the actual deployment
environment. This single-container design shares one host failure domain and cannot
run alerting while that host is unavailable.
