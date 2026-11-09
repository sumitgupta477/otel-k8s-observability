#!/usr/bin/env python3
"""End-to-end check that telemetry flows app -> agent -> gateway -> backends.

Run after scripts/up.sh, with port-forwards to the backends (smoke_test.sh
sets them up). Each check retries for up to --timeout seconds, because data
takes a little while to travel through batching in both collectors.

Checks:
  1. Traces:  Jaeger has a trace that spans BOTH services (context propagation
              across HTTP works), including the manual db.insert_order span.
  2. Metrics: Prometheus has the app's business metric (orders_created_total)
              and RED metrics generated from traces by the spanmetrics connector.
  3. K8s:     Prometheus has kubelet pod metrics from the node agents.
  4. Logs:    Loki has demo pod logs collected from the nodes, enriched with
              Kubernetes metadata, and carrying a trace_id.
  5. Correlation: the trace_id found in a Loki log line resolves to a trace
              in Jaeger, so log <-> trace links in Grafana work.
Standard library only.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

JAEGER = "http://localhost:16686"
PROM = "http://localhost:9090"
LOKI = "http://localhost:3100"
FRONTEND = "http://localhost:8080"


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def retry(name, fn, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            ok, detail = fn()
            if ok:
                print(f"PASS  {name}: {detail}")
                return True
            last = detail
        except Exception as e:  # noqa: BLE001 - keep retrying on any error
            last = f"{type(e).__name__}: {e}"
        time.sleep(5)
    print(f"FAIL  {name}: {last}")
    return False


def check_distributed_trace():
    data = get_json(f"{JAEGER}/api/traces?service=frontend&limit=50&lookback=1h")["data"]
    for t in data:
        services = {p["serviceName"] for p in t["processes"].values()}
        ops = {s["operationName"] for s in t["spans"]}
        if {"frontend", "orders"} <= services and "db.insert_order" in ops:
            return True, f"trace {t['traceID']} has {len(t['spans'])} spans across {sorted(services)}"
    return False, f"{len(data)} frontend traces found, none spanning frontend+orders with a db span yet"


def prom_value(query):
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    result = get_json(url)["data"]["result"]
    return float(result[0]["value"][1]) if result else None


def check_prom(query):
    def fn():
        v = prom_value(query)
        return (v is not None and v > 0), f"{query} = {v}"
    return fn


def loki_lines(query, minutes=30):
    now = time.time_ns()
    params = urllib.parse.urlencode({
        "query": query, "start": now - minutes * 60 * 10**9, "end": now, "limit": 200,
    })
    streams = get_json(f"{LOKI}/loki/api/v1/query_range?{params}")["data"]["result"]
    return [(s["stream"], line) for s in streams for _, line in s["values"]]


found_trace_ids = []


def check_loki_logs():
    lines = loki_lines('{k8s_namespace_name="demo"} |= "trace_id="')
    for labels, line in lines:
        m = re.search(r"trace_id=([0-9a-f]{32})", line)
        if m and m.group(1) != "0" * 32:
            found_trace_ids.append(m.group(1))
    if not found_trace_ids:
        return False, f"{len(lines)} demo log lines, none with a trace_id yet"
    labels = lines[0][0]
    has_k8s = any(k.startswith("k8s_") for k in labels)
    return has_k8s, f"{len(lines)} lines with trace IDs; labels include {sorted(labels)[:6]}"


def check_correlation():
    for tid in reversed(found_trace_ids[-20:]):
        try:
            data = get_json(f"{JAEGER}/api/traces/{tid}")["data"]
        except Exception:  # noqa: BLE001 - trace may not be flushed yet
            continue
        if data:
            return True, f"log trace_id {tid} -> Jaeger trace with {len(data[0]['spans'])} spans"
    return False, "no log trace_id found in Jaeger yet"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timeout", type=int, default=180, help="seconds to wait for each check")
    args = p.parse_args()

    # Make sure there is fresh traffic, in addition to the load generator.
    for _ in range(20):
        try:
            urllib.request.urlopen(f"{FRONTEND}/checkout", timeout=5).read()
        except Exception:  # noqa: BLE001 - some requests fail by design (5% errors)
            pass

    checks = [
        ("distributed trace across services", check_distributed_trace),
        ("app business metric", check_prom("sum(orders_created_total)")),
        ("RED metrics from spanmetrics connector", check_prom("sum(traces_span_metrics_calls_total)")),
        ("kubelet pod metrics from node agents", check_prom('count({__name__=~"k8s_pod_.+"})')),
        ("pod logs in Loki with k8s labels and trace_id", check_loki_logs),
        ("log -> trace correlation", check_correlation),
    ]
    results = [retry(name, fn, args.timeout) for name, fn in checks]
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
