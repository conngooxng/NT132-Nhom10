#!/usr/bin/env python3
"""
import_flows.py - imports every flow definition in this folder into a RUNNING
NiFi 2.x instance via the REST API, then wires up the secrets.

What it does, step by step:
  1. Authenticate (single-user credentials, same as docker-compose.yml).
  2. Find the root Process Group id.
  3. POST each 01..04*.json to  /process-groups/{root}/process-groups/upload
     (this endpoint parses the FlowDefinition JSON and builds the real flow).
  4. Fill the sensitive properties that cannot be exported in flow JSON:
       - DBCPConnectionPool "Password"  <- MARIADB_PASSWORD (default iotpass2026)
       - PutSFTP           "Password"   <- SFTP_PASSWORD   (default iotpass2026)
  5. Try to ENABLE every controller service of the imported groups.
  6. Print a manual checklist for anything it could not do automatically.

Usage:
    pip install requests
    python flows/import_flows.py                 # defaults below
    NIFI_URL=https://nifi.example.com python flows/import_flows.py

NOTE: --insecure is implicit (the NiFi docker image ships a self-signed
certificate). The script only talks to your local docker stack.
"""

import glob
import json
import os
import ssl
import sys
import urllib3

try:
    import requests
except ImportError:
    sys.exit("[!] Missing dependency: pip install requests")

# --------------------------------------------------------------------------
# Connection settings (override via environment variables)
# --------------------------------------------------------------------------
NIFI_URL = os.environ.get("NIFI_URL", "https://localhost:8443").rstrip("/")
NIFI_USER = os.environ.get("NIFI_USER", "admin")
NIFI_PASSWORD = os.environ.get("NIFI_PASSWORD", "changemeNifi2026")
MARIADB_PASSWORD = os.environ.get("MARIADB_PASSWORD", "iotpass2026")
SFTP_PASSWORD = os.environ.get("SFTP_PASSWORD", "iotpass2026")

# Silence the "unverified HTTPS" warning (self-signed cert by design).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
CLIENT = requests.Session()
CLIENT.verify = False
CLIENT_ID = "nifi-flow-importer-script"

FLOWS_DIR = os.path.dirname(os.path.abspath(__file__))
FLOW_FILES = sorted(glob.glob(os.path.join(FLOWS_DIR, "0*_*.json")))


def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)


def api(method: str, path: str, ok_codes=(200,), **kwargs):
    """Small REST helper - returns parsed JSON or raises with a clear message."""
    url = f"{NIFI_URL}/nifi-api{path}"
    resp = CLIENT.request(method, url, timeout=30, **kwargs)
    if resp.status_code not in ok_codes:
        raise RuntimeError(f"{method} {path} -> HTTP {resp.status_code}: "
                           f"{resp.text[:300]}")
    return resp.json() if resp.text else {}


def authenticate() -> None:
    """Exchange single-user credentials for a NiFi API bearer token."""
    resp = CLIENT.post(
        f"{NIFI_URL}/nifi-api/access/token",
        data={"username": NIFI_USER, "password": NIFI_PASSWORD},
        timeout=30,
    )
    if resp.status_code not in (200, 201) or not resp.text:
        raise RuntimeError(f"POST /access/token -> HTTP {resp.status_code}: "
                           f"{resp.text[:300]}")
    CLIENT.headers["Authorization"] = f"Bearer {resp.text.strip()}"


# --------------------------------------------------------------------------
def get_root_process_group() -> str:
    data = api("GET", "/flow/process-groups/root")
    pg_id = data["processGroupFlow"]["id"]
    print(f"[i] Root process group id = {pg_id}")
    return pg_id


def upload_flow(root_id: str, path: str, group_name: str,
                position_x: int, position_y: int) -> str:
    """POST one FlowDefinition JSON; returns the new child PG id."""
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f,
                          "application/json")}
        data = {
            "groupName": group_name,
            "positionX": str(position_x),
            "positionY": str(position_y),
            "clientId": CLIENT_ID,
        }
        resp = CLIENT.post(
            f"{NIFI_URL}/nifi-api/process-groups/{root_id}/process-groups/upload",
            files=files, data=data, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"upload {os.path.basename(path)} -> "
                           f"HTTP {resp.status_code}: {resp.text[:400]}")
    entity = resp.json()
    pg_id = entity["id"]
    pg_name = entity["component"]["name"]
    print(f"[+] Imported '{pg_name}' (id={pg_id})")
    return pg_id


# --------------------------------------------------------------------------
def update_controller_service(cs_id: str, revision: int, props: dict) -> int:
    body = {
        "revision": {"version": revision, "clientId": CLIENT_ID},
        "disconnectedNodeAcknowledged": False,
        "component": {"id": cs_id, "properties": props},
    }
    entity = api("PUT", f"/controller-services/{cs_id}", json=body)
    return entity["revision"]["version"]


def enable_controller_service(cs_id: str, revision: int) -> None:
    body = {
        "revision": {"version": revision, "clientId": CLIENT_ID},
        "disconnectedNodeAcknowledged": False,
        "state": "ENABLED",
    }
    api("PUT", f"/controller-services/{cs_id}/run-status",
        json=body)


def service_properties(flow_pg: dict) -> list:
    """Extract (id, revision, name, type, properties) for each service."""
    out = []
    for cs in flow_pg.get("controllerServices", []):
        comp = cs["component"]
        out.append((comp["id"], cs["revision"]["version"],
                    comp["name"], comp["type"], comp.get("properties", {})))
    return out


def processor_entities(flow_pg: dict) -> list:
    out = []
    for p in flow_pg.get("processors", []):
        entity = api("GET", f"/processors/{p['component']['id']}")
        comp = entity["component"]
        props = (comp.get("config") or {}).get("properties") or {}
        out.append((entity["id"], entity["revision"]["version"],
                    comp["name"], comp["type"], props))
    return out


def configure_group(pg_id: str) -> None:
    """Fill sensitive properties + enable services for one imported group."""
    flow = api("GET", f"/flow/process-groups/{pg_id}")["processGroupFlow"]["flow"]
    services = api(
        "GET", f"/flow/process-groups/{pg_id}/controller-services",
        params={"includeAncestorGroups": "false",
                "includeDescendantGroups": "false"},
    ).get("controllerServices", [])
    todo_passwords = []

    # 4a. DBCPConnectionPool password (any service whose type matches)
    for cs_id, rev, name, ctype, props in service_properties(
            {"controllerServices": services}):
        service_revision = rev
        if "DBCPConnectionPool" in ctype and "Password" in props:
            service_revision = update_controller_service(
                cs_id, rev, {"Password": MARIADB_PASSWORD})
            print(f"[+] Set DB password on service '{name}'")
        # 4b. enable every service
        try:
            enable_controller_service(cs_id, service_revision)
            print(f"[+] Enabled controller service '{name}'")
        except Exception as exc:  # noqa: BLE001 - best effort
            print(f"[!] Could not enable '{name}' automatically: {exc}")
            todo_passwords.append(f"Enable controller service: {name}")

    # 4c. PutSFTP password
    for p_id, rev, name, ptype, props in processor_entities(flow):
        if "PutSFTP" in ptype and "Password" in props:
            body = {
                "revision": {"version": rev, "clientId": CLIENT_ID},
                "disconnectedNodeAcknowledged": False,
                "component": {
                    "id": p_id,
                    "config": {"properties": {"Password": SFTP_PASSWORD}},
                },
            }
            api("PUT", f"/processors/{p_id}", json=body)
            print(f"[+] Set SFTP password on processor '{name}'")


# --------------------------------------------------------------------------
def main() -> None:
    if not FLOW_FILES:
        die(f"No 0*_*.json flow definitions found in {FLOWS_DIR}")

    # A single-token login check (GET /flow/current-user) verifies creds early.
    try:
        authenticate()
        who = api("GET", "/flow/current-user")
        print(f"[i] Authenticated as '{who.get('identity', NIFI_USER)}'")
    except Exception as exc:  # noqa: BLE001
        die(f"Cannot authenticate against {NIFI_URL} - is the stack up "
            f"(docker compose up -d) and the password correct? ({exc})")

    root_id = get_root_process_group()

    # avoid name clashes if the script is run twice
    existing = {g["component"]["name"]
                for g in api("GET", f"/flow/process-groups/{root_id}")
                ["processGroupFlow"]["flow"]["processGroups"]}

    imported = []
    for index, path in enumerate(FLOW_FILES):
        with open(path, encoding="utf-8") as f:
            name = json.load(f)["flowContents"]["name"]
        if name in existing:
            print(f"[=] Process group '{name}' already imported - skipped "
                  f"(delete it in the UI first to re-import)")
            continue
        try:
            pg_id = upload_flow(root_id, path, name, index * 1200, 0)
            imported.append((pg_id, name))
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Import of '{name}' failed: {exc}")

    for pg_id, name in imported:
        try:
            configure_group(pg_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Post-configuration of '{name}' incomplete: {exc}")

    print(
        "\n=== MANUAL CHECKLIST (only needed if any step above printed [!]) ===\n"
        "1. Open https://localhost:8443/nifi  (admin / changemeNifi2026)\n"
        "2. To start a flow: select the group, then click the play button in\n"
        "   the Operate palette (left bottom corner).\n"
        "3. If a controller service shows a warning icon: open it, fill the\n"
        "   missing 'Password' property, then click Enable.\n"
        "4. If a processor is invalid (red exclamation): open it and fix the\n"
        "   highlighted property (usually a relationship without a target).\n"
        "5. Then run the generators (see README section 5)."
    )


if __name__ == "__main__":
    main()
