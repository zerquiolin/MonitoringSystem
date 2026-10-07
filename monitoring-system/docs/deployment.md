# Production deployment

The `deploy-monitoring.yml` workflow deploys only the monitoring service directory
from this repository. It runs after the `Verify portable monitoring` workflow passes
on `main`, or can be started manually from `main`. It transfers the operational
inventory and application files, preserves the server's `secrets/` and monitoring
data, validates the inventory against the server, then builds and starts the service.

## GitHub Actions settings

The workflow uses these repository secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_KNOWN_HOSTS`
- `DEPLOY_PATH` — the server directory where `scripts/`, `config/`, and `docker/`
  should live, for example `/root/monitoring-system`.

These are SSH deployment credentials. The workflow creates Grafana/operator
credentials and the two application ingest tokens on the server during first deploy;
it never prints or overwrites existing values. The app tokens are stored at
`$DEPLOY_PATH/secrets/mimunicipio-prod` and `mimunicipio-qa`. Read them over SSH and
add them to the matching Vercel environment as `MONITORING_TOKEN`. The generated
Grafana admin password is stored in `$DEPLOY_PATH/secrets/grafana-admin`.

The workflow uses the server's existing Certbot installation and webroot to obtain a
trusted certificate for `monitoring.macondosoftwares.com` on first deploy. The DNS
record alone does not create this certificate; the hostname must resolve to the
server and inbound HTTP challenge traffic must reach Nginx. The workflow installs a
Certbot deploy hook that refreshes the gateway's protected certificate copy and
reloads both TLS consumers after scheduled renewals.

## One-time Nginx route

The production Compose overlay attaches the gateway to the existing
`soporte_toka_default` Docker network. This lets the Nginx container proxy to the
service by its Docker DNS name without exposing the gateway's TLS port publicly.
That network must already exist.

The deployment workflow installs the temporary HTTP challenge vhost when no
certificate exists, obtains the certificate with the server's Certbot webroot
(`/root/Soporte_Toka/certbot-webroot`), then installs the final HTTPS vhost. The final
file proxies traffic to `https://monitoring:8443`. The monitoring container joins the
existing `soporte_toka_default` Docker network so Nginx can resolve `monitoring`.

## First deployment

1. Ensure the DNS A record points to the monitoring server and issue the TLS
   certificate through the existing Certbot setup.
2. Install and reload the Nginx route above.
3. Push the workflow, inventory, and monitoring-system changes to `main`.
4. Wait for verification to pass, then check the deployment workflow's readiness
   result.
5. Read each generated app token over SSH and set it in Vercel for the matching
   environment. Configure `MONITORING_ENDPOINT` as
   `https://monitoring.macondosoftwares.com` and set the project/service/environment/
   instance identity to match `config/inventory.operational.yaml`.

The operational inventory is source-controlled and intentionally separate from
`config/inventory.yaml`, which remains the local demo configuration. Do not commit
the server's `secrets/`, generated configuration, or persistent data.
