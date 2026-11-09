#!/usr/bin/env bash
# Port-forwards the backends and the frontend, then runs smoke_test.py.
# On failure, prints collector logs to help debugging.
set -uo pipefail
cd "$(dirname "$0")/.."

pids=()
forward() { kubectl -n "$1" port-forward "svc/$2" "$3" >/dev/null 2>&1 & pids+=($!); }
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT

forward observability jaeger 16686:16686
forward observability prometheus 9090:9090
forward observability loki 3100:3100
forward demo frontend 8080:8080
sleep 5

python3 scripts/smoke_test.py "$@"
status=$?

if [[ $status -ne 0 ]]; then
  echo; echo "==> Gateway collector logs"; kubectl -n observability logs deploy/otel-gateway --tail=60
  echo; echo "==> Agent collector logs";   kubectl -n observability logs -l app.kubernetes.io/instance=otel-agent --tail=80 --prefix
  echo; echo "==> Pods";                   kubectl get pods -A -o wide
fi
exit $status
