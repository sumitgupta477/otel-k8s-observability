"""Two-service demo shop, instrumented with OpenTelemetry.

The same image runs as either service, chosen by SERVICE_ROLE:
  frontend  GET /checkout -> calls the orders service, returns the order
  orders    POST /orders  -> "saves" an order (simulated DB latency, ~5% errors)

Tracing, HTTP metrics and log correlation come from zero-code
auto-instrumentation (`opentelemetry-instrument`, see the Dockerfile).
This file only adds what auto-instrumentation can't know about:
a business metric (orders created) and a span for the database step.
"""

import logging
import os
import random
import time
import uuid

import requests
from flask import Flask, jsonify
from opentelemetry import metrics, trace

ROLE = os.environ.get("SERVICE_ROLE", "frontend")
ORDERS_URL = os.environ.get("ORDERS_URL", "http://orders:8080")
ERROR_RATE = float(os.environ.get("ERROR_RATE", "0.05"))

app = Flask(__name__)
log = logging.getLogger("shop")
tracer = trace.get_tracer("shop")
meter = metrics.get_meter("shop")
orders_created = meter.create_counter(
    "orders.created", unit="{order}", description="Orders successfully created"
)


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/checkout")
def checkout():
    # The requests instrumentation injects the W3C `traceparent` header, so the
    # orders service continues this same trace.
    resp = requests.post(f"{ORDERS_URL}/orders", json={"items": random.randint(1, 5)}, timeout=5)
    if resp.status_code >= 500:
        log.error("checkout failed: orders service returned %s", resp.status_code)
        return jsonify(error="order failed"), 502
    order = resp.json()
    log.info("checkout completed order_id=%s", order["order_id"])
    return jsonify(order)


@app.post("/orders")
def create_order():
    order_id = uuid.uuid4().hex[:8]
    with tracer.start_as_current_span("db.insert_order") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("order.id", order_id)
        time.sleep(random.uniform(0.02, 0.15))  # simulated database latency
        if random.random() < ERROR_RATE:
            span.set_status(trace.Status(trace.StatusCode.ERROR, "deadlock detected"))
            log.error("order insert failed order_id=%s: deadlock detected", order_id)
            return jsonify(error="database error"), 500
    orders_created.add(1, {"channel": "web"})
    log.info("order created order_id=%s", order_id)
    return jsonify(order_id=order_id, status="created")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
