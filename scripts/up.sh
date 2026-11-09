#!/usr/bin/env bash
# Builds the demo image and deploys everything to the current kubectl context.
# With CREATE_CLUSTER=1 (the default) it first creates a local kind cluster.
# Requires: docker, kubectl, helm, and kind (when creating the cluster).
set -euo pipefail
cd "$(dirname "$0")/.."

CHART_VERSION="${CHART_VERSION:-0.178.2}"   # open-telemetry/opentelemetry-collector
CLUSTER="${CLUSTER:-otel-demo}"

if [[ "${CREATE_CLUSTER:-1}" == "1" ]]; then
  kind get clusters 2>/dev/null | grep -qx "$CLUSTER" || kind create cluster --config kind-config.yaml --wait 120s
fi

echo "==> Building the demo app image"
docker build -t otel-demo-shop:local app
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind load docker-image otel-demo-shop:local --name "$CLUSTER"
fi

echo "==> Deploying backends (Jaeger, Prometheus, Loki, Grafana) and the demo shop"
kubectl apply -k k8s/

echo "==> Installing the OpenTelemetry Collector: gateway, then node agents"
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
helm repo update open-telemetry >/dev/null
helm upgrade --install otel-gateway open-telemetry/opentelemetry-collector \
  --version "$CHART_VERSION" --namespace observability -f helm/otel-gateway-values.yaml --wait --timeout 5m
helm upgrade --install otel-agent open-telemetry/opentelemetry-collector \
  --version "$CHART_VERSION" --namespace observability -f helm/otel-agent-values.yaml --wait --timeout 5m

echo "==> Waiting for everything to be ready"
kubectl -n observability rollout status deploy --timeout=5m
kubectl -n demo rollout status deploy --timeout=5m

cat <<'MSG'

Done. Open the UIs with:
  kubectl -n observability port-forward svc/grafana 3000:3000       # http://localhost:3000
  kubectl -n observability port-forward svc/jaeger 16686:16686      # http://localhost:16686
  kubectl -n observability port-forward svc/prometheus 9090:9090    # http://localhost:9090
Run the end-to-end check with: scripts/smoke_test.sh
MSG
