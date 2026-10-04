Provisioning ownership is in `control/configuration.py` and dashboard source in
`control/dashboards.py`. Startup renders secret-bearing provisioning under
`/run/monitoring/active/provisioning`; it is never committed in this folder.
Built-in Prometheus/Loki/Tempo plus Infinity 3.7.3 installed at image build time.
Runtime plugin preinstallation is disabled. Dashboard UIDs are stable.
