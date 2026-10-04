nginx is rendered by `control/configuration.py`. Local HTTP is loopback-published;
operational TLS uses mounted secret certificate/key references. Ingress limits:
2 MiB body, 10-second body deadline, 100 requests/sec per client with 200 burst,
32 concurrent ingestion connections. Control validates resource-level identity;
backend/admin/prober APIs are never directly routed.
