# Operator procedures

Run commands from `monitoring-system/`, or invoke the Python CLI by absolute path.
The CLI resolves its files relative to this folder. `init` never overwrites existing operator
configuration/secrets. Secret files are mode 0600; the containing directory is 0700.
Do not commit or distribute `secrets/`, generated provisioning, data volumes, or backups.
Admin password is in `secrets/grafana-admin`; do not put it in shell arguments/history.

Local profile publishes HTTP only on host loopback. Operational inventory requires
an HTTPS public URL and private mounted certificate/key references. The gateway then
listens on 8443. For remote deployment, explicitly bind only the TLS gateway port in
your deployment configuration and update DNS/firewall rules. Use a verified CA in
applications; never disable verification. Automated public certificates are not
assumed. SMTP settings and native Slack/Teams/webhook destinations are configuration
choices with secret references, destination allowlists, and explicit contact tests.
`notification-test --destination NAME` exercises Grafana's actual native integration.
Local receiver delivery is not external Slack/email delivery.

Inside a container, localhost is that container. Docker Desktop's
`host.docker.internal` reaches applications running on the development machine;
Linux Compose adds the host-gateway mapping. Remote/private applications require
reachable URLs and approved networks/VPN routes. Push telemetry needs outbound
access to the HTTPS gateway; it does not make external probes reachable. Target hosts
and private CIDRs must be explicitly allowlisted. Startup pins probe DNS results to
approved IP addresses, preserving HTTP Host and TLS server name. Redirects remain
blocked to avoid destination escape. Raw Blackbox arbitrary-target APIs stay private.

Use `validate`, `render`, and `diff --config FILE` before `apply --config FILE`.
Diff reports changed file names without printing secret values. Apply validates all
references, saves the previous inventory, publishes source configuration, and restarts
the container. `rollback` restores the prior validated inventory and restarts. Do not
change component versions with live persistent data without checking backend schema
migration compatibility and taking a backup. Generated source dashboards are owned;
make unrelated custom dashboards in another folder.

Use the expiring hash-based credential rotation and immediate revocation commands
below. Legacy plaintext tokens remain a local onboarding option.

`python3 scripts/monitoring.py diagnose` reports backend/evaluator readiness and
whether external notifications are configured. Per-component bounded logs live at
`/run/monitoring/COMPONENT.log` inside the container; inspect with Docker exec. Do not
include secrets or production telemetry in diagnostic bundles. Pipeline outages show
UNKNOWN service observations and separate monitoring alerts. Expected worker expiry
means `heartbeat_expired`, not proof of a process or host crash.

Back up with `backup --output /private/path/backup.tar.gz`. This deliberately stops
the stack for consistency, saves every durable backend directory and config-state,
and includes source inventory/secrets (including Grafana encryption key). Archives
are sensitive and mode 0600. The stack restarts afterwards; this causes an observation
gap. Restore uses `restore --archive FILE --volume NEW_NAME --confirm-empty-volume`;
an existing volume name is refused. Start an isolated container with that volume and
the archived inventory/secrets, then verify queries/ledger/credentials before replacing
an operational deployment. Restoring data alone with a new Grafana key cannot decrypt
saved credentials. Never use `docker compose down -v` as ordinary cleanup.

TSDB time/size retention, Loki compactor deletion, Tempo compactor retention, and
control observation pruning are separate. Keep sufficient space for WALs, active blocks,
and compaction work. Filesystem free bytes and backend health are visible. Incident
summaries are retained; deleting historical observations reduces reporting coverage.
An independent watchdog and offline backups mitigate, but cannot remove, the single
container/host failure domain. The image has no runtime package/plugin downloads.

## Credential lifecycle

Ingestion credentials may use a protected JSON verifier file with `tokens` records
containing `sha256`, `notBefore`, `expiresAt`, and optional `revoked`. Verification
checks wall-clock expiry on every request. Legacy private token files remain accepted
for local onboarding; rotate them to expiring verifiers for operational deployment.

```
python3 scripts/monitoring.py token-rotate --ref demo-orders --output /private/path/new-application-token --ttl-seconds 2592000 --overlap-seconds 300
python3 scripts/monitoring.py token-revoke --token-file /private/path/retired-application-token
```

Rotation writes only a hash to the central verifier file and saves the new application
credential at the specified private path. Existing credentials expire after bounded
operator-configured overlap (at most one hour). Update the application token file and
restart its SDK process before overlap expires. Revocation is immediate and durable in
SQLite. The dashboard read credential cannot rotate, revoke, ingest, or acknowledge.
A restart installs changed secret mounts; rollback does not resurrect a revoked hash.

`apply` now runs backend preflight in the assembled image before publishing inventory.
It waits for full readiness and restores/checks the previous inventory on failure.
Last-known-good runtime state is promoted only after complete readiness. Removed owned
alert rules are explicitly deleted; dashboard provisioning removes absent owned files.

## Tested operating envelope and storage admission

See `../artifacts/capacity.json` for the ten-minute full trace/log/metric workload and
`../artifacts/benchmark.json` for the isolated SDK comparison. These are measured local
budgets, not universal sizing promises. Reserve disk for WALs, indices and compaction.
Ingress returns 503 below 64 MiB available control-volume space; configure
`MONITORING_MIN_FREE_BYTES` to raise this reserve. SDK retry/queue budgets still apply.
The low-space fixture uses an isolated 16 MiB tmpfs and never fills a production disk.

`watchdog` inventory settings configure startup grace, readiness failure count,
check interval and final shutdown budget. Allow actual backend warmup: the demo default
is 150 seconds. Intentional Docker stop/kill disables automatic restart until explicit
start; unexpected component failure causes a failed exit and Docker policy recovery.

Worker/job source clocks outside 120 seconds are rejected, while receipt time drives
expiration. Source timestamps remain diagnostic metadata. Keep host clocks synchronized.
Cron evaluation uses central receipt time and the configured IANA timezone via pinned
croniter/zoneinfo: DST boundaries follow that library's aware-occurrence policy; inspect
expected windows around timezone changes. New boots retire old heartbeat sequences and
interrupt runs owned by the old boot. Completion requires an accepted start; duplicate
terminal events are idempotent, overlap is enforced, and stale runs become interrupted.
`recordJobRetry()` counts an application-owned retry; the SDK does not choose job retry policy.

Tempo's singleton rings use explicit loopback addresses so disconnected startup does
not require an external interface; see [Tempo configuration](https://grafana.com/docs/tempo/latest/configuration/).
