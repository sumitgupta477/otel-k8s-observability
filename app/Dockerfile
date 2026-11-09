FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
USER 65534:65534

# opentelemetry-instrument wires up tracing, metrics and log correlation for
# Flask, requests and logging without code changes. All settings come from
# OTEL_* environment variables (see k8s/demo/shop.yaml).
ENTRYPOINT ["opentelemetry-instrument", "python", "app.py"]
