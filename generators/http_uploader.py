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
    python generators/http_uploader.py                          # upload every 1.5s
    python generators/http_uploader.py --count 1                # one upload batch
    python generators/http_uploader.py --count 5 --interval 10  # five batches, 10s apart
"""

import argparse
import json
import os
import random
import sys
import time
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


def upload_batch() -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload sample payloads to NiFi")
    parser.add_argument("--count", type=int, default=0,
                        help="number of upload batches (0 = run forever)")
    parser.add_argument("--interval", type=float, default=1.5,
                        help="seconds between upload batches (default: 1.5)")
    args = parser.parse_args()

    if args.count < 0:
        parser.error("--count must be zero or greater")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    uploaded = 0
    try:
        while args.count == 0 or uploaded < args.count:
            upload_batch()
            uploaded += 1
            if args.count == 0 or uploaded < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"[http_uploader] stopped after {uploaded} batches")
    except (urllib.error.URLError, OSError) as exc:
        print(
            f"[http_uploader] unable to reach NiFi at {NIFI_LISTENHTTP}: {exc}\n"
            "This usually means the ListenHTTP processor is not running or the NiFi flow is not imported/enabled.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    else:
        print(f"[http_uploader] finished after {uploaded} batches")


if __name__ == "__main__":
    main()
