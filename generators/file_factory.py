#!/usr/bin/env python3
"""
file_factory.py - drops structured files into the NiFi watch folder.

NiFi's GetFile processor polls ./data/drop (mounted at /data/drop inside the
container) and picks up:

    data/drop/legacy/readings_YYYYmmdd-HHMMSS.csv  (legacy CSV batch export)
    data/drop/logs/gw-001_YYYYmmdd-HHMMSS.log      (unstructured device log)

Each run generates one file of each type with plausible contents:
  * CSV - 20 rows of sensor readings (deliberately legacy batch format)
  * LOG - mixed INFO/WARN/ERROR lines, unstructured text

Usage:
    python generators/file_factory.py              # one drop of each type
    python generators/file_factory.py --loop 30    # drop every 30 seconds
"""

import argparse
import csv
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DROP_ROOT = Path(__file__).resolve().parents[1] / "data" / "drop"


def resolve_drop_root() -> Path:
    override = os.environ.get("DROP_ROOT")
    candidates = [Path(override).expanduser() if override else DEFAULT_DROP_ROOT]

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue

    fallback = Path.home() / ".nt132" / "data" / "drop"
    fallback.mkdir(parents=True, exist_ok=True)
    print(
        f"[file_factory] warning: project data directory is not writable; using {fallback}",
        file=sys.stderr,
    )
    return fallback


DROP_ROOT = resolve_drop_root()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def make_csv(path: str | Path, device_id: str) -> str:
    """Legacy nightly export: 20 rows of readings, header + ISO timestamps."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["device_id", "metric", "value", "event_time"])
        for i in range(20):
            metric = random.choice(["temperature_c", "humidity_pct", "noise_db"])
            writer.writerow([
                device_id,
                metric,
                round(random.uniform(15, 85), 2),
                (now.timestamp() - (20 - i) * 60).__str__(),
            ])
    return str(path)


def make_log(path: str | Path, device_id: str) -> str:
    """Unstructured device log - the messiest data type in the pipeline."""
    path = Path(path)
    lines = []
    for _ in range(30):
        level = random.choices(["INFO", "WARN", "ERROR"], weights=[80, 15, 5])[0]
        msg = random.choice([
            "heartbeat ok, uptime %d s" % random.randint(100, 90000),
            "firmware check skipped (offline)",
            "buffer flush took %d ms" % random.randint(3, 900),
            "reconnect attempt %d to broker mqtt:1883" % random.randint(1, 9),
            "temperature reading outside calibrated range",
        ])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{ts} {level} [{device_id}] {msg}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return str(path)


def drop_all() -> None:
    s = stamp()
    files = [
        make_csv(DROP_ROOT / "legacy" / f"readings_{s}.csv", "temp-001"),
        make_log(DROP_ROOT / "logs" / f"gw-001_{s}.log", "gw-001"),
    ]
    for p in files:
        print(f"[file_factory] wrote {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop test files for GetFile")
    parser.add_argument("--loop", type=int, default=0,
                        help="drop every N seconds (0 = once)")
    args = parser.parse_args()

    if args.loop <= 0:
        drop_all()
        return
    try:
        while True:
            drop_all()
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print("[file_factory] stopped")


if __name__ == "__main__":
    main()
