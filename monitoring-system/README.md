# Monitoring system

This folder contains the central observability service: Grafana dashboards, backend
configuration, inventory and schemas, the Python control API and operations CLI,
container definition, and service-level tests. The reusable SDK is maintained
separately in [`../package/`](../package/); runnable SDK consumers are in
[`../implementations/`](../implementations/).

## Local setup

Run commands from the repository root unless noted:

```sh
python3 -m venv monitoring-system/.venv
monitoring-system/.venv/bin/pip install -r monitoring-system/docker/control/requirements.lock.txt
python3 monitoring-system/scripts/monitoring.py init --profile local
python3 monitoring-system/scripts/monitoring.py validate --config monitoring-system/config/inventory.yaml
npm ci
npm run build
npm test
docker compose -f monitoring-system/docker/compose.yaml up --build -d
npm run demo
```

Open Grafana at [http://localhost:8080](http://localhost:8080). The generated admin
password is in the ignored `monitoring-system/secrets/grafana-admin` file.

## Guides

- [Grafana and dashboards](docs/grafana-service.md)
- [Operations and deployment](docs/operations.md)
- [Architecture](docs/architecture.md)
- [Uptime and reliability definitions](docs/dashboards.md)
- [Metrics and signal semantics](docs/metrics-and-reliability.md)
- [Acceptance evidence](docs/acceptance.md)

For DevOps deployment, use the operational profile with verified TLS, production
inventory and target allowlists, secret references, durable storage, and tested
notification destinations. Keep `secrets/`, generated configuration, runtime data,
and backups out of source control. See [operations](docs/operations.md) for
configuration changes, credential rotation, backup/restore, retention, and recovery.


## Build and export the container image

From the repository root, build the native architecture with Compose:

```sh
docker compose -f monitoring-system/docker/compose.yaml build monitoring
```

For an explicit multi-architecture build, use Docker Buildx:

```sh
docker buildx build --platform linux/amd64 -f monitoring-system/docker/Dockerfile -t portable-observability:amd64 --load .
docker buildx build --platform linux/arm64 -f monitoring-system/docker/Dockerfile -t portable-observability:arm64 --load .
```

The Docker build context is the repository root. Source-controlled Docker inputs stay
in this folder; SDK sources and demo applications are excluded from the monitoring
image. The large prebuilt image archive is intentionally not in Git.
