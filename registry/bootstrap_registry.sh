#!/usr/bin/env bash
# =============================================================================
# bootstrap_registry.sh - creates the "iot-datahub" bucket inside NiFi
# Registry so that versioned flows have somewhere to live.
#
# Prereq: docker compose up -d  (nifi-registry listens on localhost:18080,
# HTTP without auth - fine for a local learning stack, never for production).
#
# Usage:  bash registry/bootstrap_registry.sh
# =============================================================================
set -euo pipefail

REGISTRY_URL="${REGISTRY_URL:-http://localhost:18080}"
BUCKET_NAME="${BUCKET_NAME:-iot-datahub}"
BUCKET_DESC="Versioned flows of the NiFi IoT DataHub project (university project)"

echo "[i] Checking NiFi Registry at ${REGISTRY_URL} ..."
curl -fsS "${REGISTRY_URL}/nifi-registry-api/flower" > /dev/null \
  || { echo "[x] Registry not reachable - is the stack up?"; exit 1; }

echo "[i] Creating bucket '${BUCKET_NAME}' (skipped if it already exists) ..."
HTTP_CODE=$(curl -s -o /tmp/bucket_resp.json -w "%{http_code}" \
  -X POST "${REGISTRY_URL}/nifi-registry-api/buckets" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${BUCKET_NAME}\", \"description\": \"${BUCKET_DESC}\"}") || true

case "${HTTP_CODE}" in
  200|201) echo "[+] Bucket created: $(cat /tmp/bucket_resp.json)" ;;
  409)     echo "[=] Bucket already exists - nothing to do" ;;
  *)       echo "[x] Unexpected HTTP ${HTTP_CODE}: $(cat /tmp/bucket_resp.json)"
           exit 1 ;;
esac

echo
echo "Next steps (in the NiFi UI at https://localhost:8443/nifi):"
echo "  1. Global menu > Registry Clients > + ADD: name=local-registry,"
echo "     URL=http://nifi-registry:18080   (hostname INSIDE the docker net)"
echo "  2. Right-click a process group > Versioning > Start version control"
echo "     > pick 'local-registry' + bucket 'iot-datahub' > choose a name"
echo "  3. After edits: right-click > Versioning > Save flow versions"
echo "  4. On another environment: drag the versioned flow onto the canvas"
echo "     and 'Import' - that is the dev -> test -> prod promotion path."
