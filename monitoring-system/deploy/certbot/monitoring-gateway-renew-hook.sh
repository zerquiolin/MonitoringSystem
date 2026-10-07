#!/usr/bin/env bash
set -euo pipefail

path_file=/etc/monitoring-system-deploy-path
test -s "$path_file" || { echo 'Monitoring deploy path file is missing.' >&2; exit 1; }
IFS= read -r deploy_path < "$path_file"
test -d "$deploy_path/secrets" || { echo 'Monitoring secrets directory is missing.' >&2; exit 1; }

cert_dir=/etc/letsencrypt/live/monitoring.macondosoftwares.com
install -m 0600 "$cert_dir/fullchain.pem" "$deploy_path/secrets/tls-cert"
install -m 0600 "$cert_dir/privkey.pem" "$deploy_path/secrets/tls-key"
docker compose -f "$deploy_path/docker/compose.yaml" \
  -f "$deploy_path/docker/compose.production.yaml" restart monitoring
docker exec soporte_toka-nginx-1 nginx -t
docker exec soporte_toka-nginx-1 nginx -s reload
