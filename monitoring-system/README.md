# Monitoring system

This is the self-contained Docker project for the central observability service: Grafana dashboards, Prometheus, Blackbox Exporter, Loki, Tempo, Alloy, the scoped control API and incident ledger, configuration, and operational tooling. Its image builds only from this folder and does not depend on the SDK or demo applications.

## Requirements and deployment

For image build, export, initialization, and Compose startup, the host needs Docker Engine, Docker Compose, and Docker Buildx. Python and Node.js are installed or run inside containers when needed; no host Python environment is required for a normal deployment.

From an SSH clone, run:

```sh
cd MonitoringSystem/monitoring-system
scripts/container-cli.sh init --profile local
docker compose -f docker/compose.yaml up --build -d
```

Open [Grafana](http://localhost:8080). The generated administrator password is in `secrets/grafana-admin`. To stop the service, run `docker compose -f docker/compose.yaml down` from this folder.

The `local` profile is for evaluation. Before production, use an operational inventory with verified TLS, target allowlists, secret references, durable storage, and tested notification destinations. Follow [operations](docs/operations.md) and keep secrets, generated configuration, data, and backups out of source control.

## Build and export the image

Compose uses this folder as its Docker build context:

```sh
docker compose -f docker/compose.yaml build monitoring
```

For an explicit architecture build, run from this folder:

```sh
docker buildx build --platform linux/amd64 -f docker/Dockerfile -t portable-observability:amd64 --load .
docker save portable-observability:amd64 -o portable-observability-amd64.tar
```

The Dockerfile installs its Python virtual environment and locked control API dependencies inside the image. The large prebuilt image archive is not stored in Git. Docker build inputs and the runtime are all within this project folder.

## Host-side operational CLI

The Python virtual environment is optional and only needed when running the host CLI directly for operations such as `apply`, `rollback`, or backup management. You can instead use the container helper for `init`, `validate`, `render`, and `diff`:

```sh
scripts/container-cli.sh validate --config config/inventory.yaml
```

For direct host-side Python commands, create the environment described in [operations](docs/operations.md).

## Guides

- [Grafana and dashboards](docs/grafana-service.md)
- [Operations and deployment](docs/operations.md)
- [GitHub Actions production deployment](docs/deployment.md)
- [Architecture](docs/architecture.md)
- [Uptime and reliability definitions](docs/dashboards.md)
- [Metrics and signal semantics](docs/metrics-and-reliability.md)
- [Acceptance evidence](docs/acceptance.md)
