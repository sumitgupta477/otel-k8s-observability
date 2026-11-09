#!/usr/bin/env bash
# Deletes the local kind cluster created by up.sh.
set -euo pipefail
kind delete cluster --name "${CLUSTER:-otel-demo}"
