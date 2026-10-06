# Versioned multi-architecture upstream images supply binaries; no runtime downloads.
FROM prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e AS prometheus
FROM prom/blackbox-exporter:v0.28.0@sha256:e753ff9f3fc458d02cca5eddab5a77e1c175eee484a8925ac7d524f04366c2fc AS blackbox
FROM grafana/loki:3.7.8@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193 AS loki
# Tempo 2 monolith deliberately avoids Tempo 3's Kafka-based architecture.
FROM grafana/tempo:2.10.7@sha256:032b3acb51ed02c4b801473d54bb63e9e9f13738d215126d9843c30283794f4b AS tempo
FROM grafana/alloy:v1.20.1@sha256:2aa2099af76c0098d4af7a4d6e48f86cb66dc1a000222ad927a1c67c6542d13f AS alloy
FROM grafana/grafana:13.2.3-ubuntu@sha256:efa8e935921096c08e4636c320d2f955cb843fa0889f471022e0d568af780d3f
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv nginx supervisor tini gosu ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=prometheus /bin/prometheus /bin/promtool /usr/local/bin/
COPY --from=blackbox /bin/blackbox_exporter /usr/local/bin/
COPY --from=loki /usr/bin/loki /usr/local/bin/loki
COPY --from=tempo /tempo /usr/local/bin/tempo
COPY --from=alloy /bin/alloy /usr/local/bin/alloy
COPY monitoring-system/docker/control/requirements.lock.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
RUN mkdir -p /opt/grafana-plugins && grafana cli --pluginsDir /opt/grafana-plugins plugins install yesoreyeram-infinity-datasource 3.7.3
COPY monitoring-system/docker /opt/monitoring/docker
COPY monitoring-system/contracts /opt/monitoring/contracts
COPY monitoring-system/scripts /opt/monitoring/scripts
COPY LICENSE NOTICE.md /opt/monitoring/
RUN useradd --uid 10001 --home /data --no-create-home monitoring && mkdir -p /run/monitoring /data && chown monitoring:monitoring /run/monitoring /data && chmod +x /opt/monitoring/docker/runtime/entrypoint.sh
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH="/opt/monitoring/docker/control" PYTHONUNBUFFERED=1
ENV GF_PATHS_DATA=/data/grafana GF_PATHS_LOGS=/data/grafana/logs GF_PATHS_PLUGINS=/opt/grafana-plugins GF_PATHS_PROVISIONING=/run/monitoring/active/provisioning GF_PATHS_CONFIG=/run/monitoring/active/grafana.ini
EXPOSE 8080 8443
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=150s --retries=3 CMD python /opt/monitoring/docker/runtime/healthcheck.py
ENTRYPOINT ["/usr/bin/tini","--","/opt/monitoring/docker/runtime/entrypoint.sh"]
