#!/usr/bin/env python3
"""
sensor_sim.py - MQTT telemetry publisher (simulated IoT devices).

Publishes JSON telemetry to  iot/telemetry/<device_id>  on the Mosquitto
broker. NiFi's ConsumeMQTT processor subscribes to  iot/telemetry/#  and
routes each message through validation, enrichment and JDBC persistence.

Every message is intentionally schema-consistent:

    {"device_id": "temp-001",
     "metric": "temperature_c",
     "value": 24.83,
     "event_time": "2026-10-27T09:15:02.123Z"}

Roughly 1 in 12 messages is deliberately malformed (missing fields, string
values) so learners can watch ValidateJson / RouteOnContent route failures
instead of silently succeeding.

Usage:
    python generators/sensor_sim.py                    # runs forever
    python generators/sensor_sim.py --count 50         # 50 messages then exit
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'paho-mqtt'. Install it with: python3 -m pip install -r generators/requirements.txt"
    ) from exc

BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
BASE_TOPIC = os.environ.get("MQTT_BASE_TOPIC", "iot/telemetry")

DEVICES = [
    # device_id, metric, unit-range (low, high)
    ("temp-001", "temperature_c", (18.0, 34.0)),
    ("temp-002", "temperature_c", (17.0, 31.0)),
    ("temp-001", "humidity_pct", (35.0, 80.0)),
    ("temp-002", "humidity_pct", (30.0, 75.0)),
    ("gw-001", "battery_pct", (40.0, 100.0)),
    ("mic-001", "noise_db", (30.0, 95.0)),
]


def build_message(device_id: str, metric: str, low: float, high: float) -> str:
    """One telemetry record. 1-in-12 chance of being malformed on purpose."""
    if random.random() < 0.083:
        corrupt = random.choice([
            json.dumps({"device_id": device_id}),                      # missing fields
            json.dumps({"device_id": device_id, "metric": metric,
                        "value": "not-a-number", "event_time": None}), # bad type
            '{"device_id": truncated json',                            # broken JSON
        ])
        return corrupt

    payload = {
        "device_id": device_id,
        "metric": metric,
        "value": round(random.uniform(low, high), 3),
        "event_time": datetime.now(timezone.utc)
                      .isoformat(timespec="milliseconds")
                      .replace("+00:00", "Z"),
    }
    return json.dumps(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT telemetry simulator")
    parser.add_argument("--count", type=int, default=0,
                        help="stop after N messages (0 = run forever)")
    parser.add_argument("--interval", type=float, default=1.5,
                        help="seconds between messages")
    args = parser.parse_args()

    try:
        if hasattr(mqtt, "CallbackAPIVersion"):
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
            client = mqtt.Client()
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except Exception as exc:
        print(
            f"[sensor_sim] unable to connect to MQTT broker at {BROKER_HOST}:{BROKER_PORT}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    client.loop_start()

    sent = 0
    print(f"[sensor_sim] publishing to {BROKER_HOST}:{BROKER_PORT}/{BASE_TOPIC}/# "
          f"(ctrl-c to stop)")
    try:
        while args.count == 0 or sent < args.count:
            device_id, metric, (low, high) = random.choice(DEVICES)
            topic = f"{BASE_TOPIC}/{device_id}"
            body = build_message(device_id, metric, low, high)
            client.publish(topic, body, qos=1)
            sent += 1
            if sent % 10 == 0:
                print(f"[sensor_sim] sent {sent} messages")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"[sensor_sim] stopped after {sent} messages")


if __name__ == "__main__":
    main()
