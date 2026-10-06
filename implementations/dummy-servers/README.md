# Typed demo applications

These strict TypeScript applications show how a service integrates the SDK. They
include an Express orders API, a Fastify catalog API backed by an in-memory SQLite
fixture, two orders replicas, a billing worker, a scheduled job, and authenticated
fault controls. The demo continually sends requests to make the Grafana views useful.

## Build and start

Run from the repository root after the monitoring system has been initialized:

```sh
npm ci
python3 monitoring-system/scripts/monitoring.py init --profile local
npm run build
npm run typecheck:demo
docker compose -f monitoring-system/docker/compose.yaml up --build -d
npm run demo
```

`npm run build` compiles the SDK and these applications into ignored `dist/` output.
The `demo` command runs the compiled JavaScript. Source remains in `src/` and uses
strict TypeScript options including exact optional properties and unchecked-index
checks.

## How each app is configured

[`src/bootstrap.ts`](src/bootstrap.ts) initializes monitoring before it dynamically
imports Express, Fastify, or application HTTP code. The shared configuration is in
[`src/demo-config.ts`](src/demo-config.ts), checked against the SDK's exported
`MonitoringConfig` type. Its example enables:

- required project, service, environment, and instance identity plus build/host labels;
- push metrics every two seconds;
- central logs with a bounded 500-event queue and no duplicate stdout output;
- traces;
- readiness with a 500 ms dependency check;
- OS-visible host, filesystem-visible, and cgroup capability measurements for one
  designated publisher.

Each role picks a typed service definition and a generated local token reference. For
a real application, replace the demo resource identity, endpoint, token file, signal
options, readiness dependency checks, and infrastructure scope with values for that
service. Keep credentials in a secret manager or protected file; never add them to the
TypeScript config or repository. The complete option descriptions and shutdown pattern
are in the [SDK package reference](../../package/docs/package-reference.md).

## Exercise the signals

After `npm run build`, use the compiled and type-checked fault controller from the repo
root:

```sh
node implementations/dummy-servers/dist/fault.js catalog fault dependency true
node implementations/dummy-servers/dist/fault.js catalog fault dependency false
node implementations/dummy-servers/dist/fault.js orders fault slowMs 1200
node implementations/dummy-servers/dist/fault.js orders fault error true
node implementations/dummy-servers/dist/fault.js worker fault heartbeatLoss true
node implementations/dummy-servers/dist/fault.js worker fault heartbeatLoss false
node implementations/dummy-servers/dist/fault.js orders2 stop
node implementations/dummy-servers/dist/fault.js orders2 restart
```

Other supported fault keys are `dependencySlowMs`, `stall`, `missSchedule`, and
`drain`; `overflow` produces a bounded log burst. Values are validated both in the
CLI and the loopback control server. Reset booleans to `false` and numeric values to
`0`. The demo token protects fault control; the server listens only on loopback.

See [Grafana's service guide](../../monitoring-system/docs/grafana-service.md) for the
dashboard map and [uptime definitions](../../monitoring-system/docs/dashboards.md)
for availability, downtime, unknown time, and coverage semantics.
