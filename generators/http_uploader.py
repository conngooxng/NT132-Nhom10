#!/usr/bin/env python3
"""
http_uploader.py - pushes payloads straight into NiFi over HTTP.

Demonstrates NiFi's *file server* capability from the client side:
the HTTP-INGEST process group runs a ListenHTTP processor on port 8081
inside the container (published as localhost:8081). Any HTTP client can
POST a body to /ingest and NiFi turns the raw bytes into a FlowFile.

This uploader POSTs:
    1. a JSON status payload   (application/json)
    2. a small binary file     (application/octet-stream)

Equivalent curl one-liners are in README section 5.

Usage:
    python generators/http_uploader.py
"""

import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

NIFI_LISTENHTTP = os.environ.get("NIFI_LISTENHTTP", "http://localhost:8081/ingest")


def post(path: str, body: bytes, content_type: str) -> None:
    req = urllib.request.Request(
        path, data=body, method="POST", headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"[http_uploader] {content_type} -> HTTP {resp.status} "
              f"({len(body)} bytes)")


def main() -> None:
    try:
        # 1. JSON device status payload
        status = {
            "device_id": "gw-001",
            "status": "ok",
            "queued_batches": 3,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        post(NIFI_LISTENHTTP,
             json.dumps(status).encode(),
             "application/json")

        # 2. arbitrary binary blob (in production this could be a firmware image)
        blob = bytes(random.randrange(256) for _ in range(2048))
        post(NIFI_LISTENHTTP, blob, "application/octet-stream")
    except (urllib.error.URLError, OSError) as exc:
        print(
            f"[http_uploader] unable to reach NiFi at {NIFI_LISTENHTTP}: {exc}\n"
            "This usually means the ListenHTTP processor is not running or the NiFi flow is not imported/enabled.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
