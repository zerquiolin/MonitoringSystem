#!/bin/sh
set -eu
for component in grafana prometheus loki tempo alloy control config-state gateway; do
 mkdir -p "/data/$component"
done
chown -R monitoring:monitoring /data /run/monitoring
# Secrets are mounted read-only and private. Root reads them into a private runtime
# directory before dropping privileges; mounted source files are never chmod'ed.
mkdir -p /run/monitoring/secrets
cp /run/secrets/* /run/monitoring/secrets/
chmod 700 /run/monitoring/secrets
chmod 600 /run/monitoring/secrets/*
chown -R monitoring:monitoring /run/monitoring/secrets
exec gosu monitoring python /opt/monitoring/docker/runtime/boot.py
