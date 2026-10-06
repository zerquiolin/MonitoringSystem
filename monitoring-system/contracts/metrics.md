# Metric contract

All application families use the `app_` namespace. OTLP cumulative counters/histograms
are canonical; Alloy converts delta streams to cumulative if received. Push uses
exact instrument names with suffix auto-add disabled; the official pull exporter uses
the same names and bucket boundaries. Identity labels are project/service/environment/
instance. Control normalizes those labels after credential resource authorization.
At most 64 instrument names and 1000 dimension sets per service/metric at central
push ingress; SDK custom metrics allow 32 instruments/100 series each with predefined
label values. HTTP templates are capped at 100. Custom business names require
`app_business_`. No raw URL or trace/user/request IDs belong in metric labels.

Canonical instrument names and units/semantics are in docs/metrics-and-reliability.md.
Signal freshness uses actual sample timestamp, not query execution time. Unsupported
collectors publish `app_collector_capability{collector,state}`; no unsupported value
is fabricated as a measured zero. Infinity queries read expected inventory, independent
of disappearing application metric series.
