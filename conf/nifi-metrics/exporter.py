"""
exporter.py - Prometheus exporter sidecar for NiFi 2.x.

WHY this exists: NiFi 2.x removed the PrometheusMetricsReportingTask (the
classic NiFi 1.x way to expose metrics on port 9092). Metrics are only
available through the authenticated REST endpoint
    GET /nifi-api/flow/metrics/prometheus
which requires a bearer token from  POST /nifi-api/access/token. Prometheus
cannot perform that login flow, and pasting a static token into prometheus.yml
would die within ~12h when the JWT expires. This tiny sidecar therefore logs
in with stable credentials (token cached in a module var, re-login on 401) and
re-serves the metrics body verbatim on http://nifi-metrics:9092/metrics so
Prometheus can scrape it like any plain exporter.

TLS note: NiFi's docker self-signed cert is CN=localhost and the compose file
sets NIFI_WEB_PROXY_HOST=localhost:8443, so Jetty rejects SNI/Host "nifi" with
"400 Invalid SNI". We therefore connect by the resolved IP (Python sends no
SNI for IP literals) and send an explicit Host header (NIFI_HOST_HEADER).

Stdlib http.server + requests only. One log line per request on stderr.
"""

import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

NIFI_URL = os.environ.get("NIFI_URL", "https://nifi:8443").rstrip("/")
NIFI_USER = os.environ.get("NIFI_USER", "admin")
NIFI_PASSWORD = os.environ.get("NIFI_PASSWORD", "changemeNifi2026")
NIFI_HOST_HEADER = os.environ.get("NIFI_HOST_HEADER", "localhost:8443")

_p = urlparse(NIFI_URL)
NIFI_BASE = (
    f"{_p.scheme}://{socket.gethostbyname(_p.hostname)}:{_p.port or 443}")
API = f"{NIFI_BASE}/nifi-api"
HOST_HEADER = {"Host": NIFI_HOST_HEADER}

CLIENT = requests.Session()
CLIENT.verify = False  # NiFi docker image ships a self-signed certificate

TOKEN = {"value": None}


def get_token() -> str:
    """Login and cache the bearer token (module-level cache)."""
    resp = CLIENT.post(
        f"{API}/access/token",
        data={"username": NIFI_USER, "password": NIFI_PASSWORD},
        headers=HOST_HEADER, timeout=30)
    if resp.status_code not in (200, 201) or not resp.text.strip():
        raise RuntimeError(
            f"login failed: HTTP {resp.status_code}: {resp.text[:200]}")
    TOKEN["value"] = resp.text.strip()
    return TOKEN["value"]


def fetch_metrics() -> str:
    """GET the prometheus metrics body, re-login once on 401."""
    if TOKEN["value"] is None:
        get_token()
    resp = CLIENT.get(
        f"{API}/flow/metrics/prometheus",
        headers={**HOST_HEADER,
                 "Authorization": f"Bearer {TOKEN['value']}"},
        timeout=30)
    if resp.status_code == 401:  # token expired -> re-login and retry once
        get_token()
        resp = CLIENT.get(
            f"{API}/flow/metrics/prometheus",
            headers={**HOST_HEADER,
                     "Authorization": f"Bearer {TOKEN['value']}"},
            timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(
            f"upstream metrics endpoint -> HTTP {resp.status_code}: "
            f"{resp.text[:200]}")
    return resp.text


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404, "not found, metrics live at /metrics")
            return
        try:
            body = fetch_metrics()
        except RuntimeError as exc:
            msg = str(exc).encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            print(f"[{self.path}] 502 {exc}", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001
            msg = f"internal error: {exc}".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            print(f"[{self.path}] 500 {exc!r}", file=sys.stderr)
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        print(f"[{self.path}] 200 {len(data)} bytes", file=sys.stderr)

    def log_message(self, *args):  # silence the default access log
        pass


if __name__ == "__main__":
    print(f"nifi-metrics exporter on :9092 -> {NIFI_URL} "
          f"(Host: {NIFI_HOST_HEADER})", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", 9092), Handler).serve_forever()