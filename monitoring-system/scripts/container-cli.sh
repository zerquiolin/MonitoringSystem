#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: scripts/container-cli.sh init|validate|render|diff [options]" >&2
  exit 2
fi
command="$1"
case "$command" in
  init|validate|render|diff) ;;
  *)
    echo "The container helper supports init, validate, render, and diff. Apply/rollback require the host Docker CLI and Python tooling." >&2
    exit 2
    ;;
esac

system_root="$(cd "$(dirname "$0")/.." && pwd)"
compose=(docker compose -f "$system_root/docker/compose.yaml")
"${compose[@]}" build monitoring
"${compose[@]}" run --rm --no-deps \
  --volume "$system_root:/workspace" \
  --workdir /workspace \
  --env MONITORING_SKIP_VENV=1 \
  --entrypoint /opt/venv/bin/python \
  monitoring "/workspace/scripts/monitoring.py" "$@"
