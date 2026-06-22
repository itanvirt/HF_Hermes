#!/usr/bin/env bash
# Auto-deploys a Cloudflare Worker that:
#  1. pings this Space's /health endpoint once a day (well under the 48h
#     free-tier sleep threshold, with margin for a missed ping) so the
#     Space doesn't go to sleep. Deliberately low-frequency: a Worker
#     hitting /health every few minutes has gotten real Spaces auto-flagged
#     as abusive by HF's abuse-handler (see discuss.huggingface.co thread
#     "Keepalive ping (GET /health/ready every 2 minutes)"), and
#  2. reverse-proxies Telegram's Bot API (api.telegram.org), so the gateway
#     can reach Telegram even when this network blocks direct outbound
#     connections to it.
# Runs synchronously, early in entrypoint.sh, BEFORE configure_hermes.sh -
# which reads CLOUDFLARE_PROXY_ENV_FILE (written below) to point Hermes at
# the proxy. Best-effort and non-fatal; skipped if CLOUDFLARE_WORKERS_TOKEN
# or SPACE_HOST aren't set (e.g. local dev).
set -uo pipefail

STATE_FILE="${CLOUDFLARE_STATE_FILE:-/home/user/app/data/cloudflare_state.json}"
PROXY_ENV_FILE="${CLOUDFLARE_PROXY_ENV_FILE:-/home/user/app/data/cloudflare_proxy.env}"
LOG=/home/user/app/data/cloudflare-setup.log
mkdir -p "$(dirname "$STATE_FILE")"
: > "$LOG"
rm -f "$PROXY_ENV_FILE"

# Merges a status update for one section ("keepawake" or "telegram_proxy")
# into the shared state JSON read by app/status.py.
write_state() {
    python3 - "$STATE_FILE" "$1" "$2" "$3" "$4" "$5" <<'PYEOF'
import json, sys, datetime
state_file, section, status, worker, target, detail = sys.argv[1:7]
try:
    data = json.load(open(state_file))
except Exception:
    data = {}
data[section] = {
    "status": status,
    "worker": worker or None,
    "target": target or None,
    "detail": detail or None,
    "at": datetime.datetime.utcnow().strftime("%H:%M:%S"),
}
json.dump(data, open(state_file, "w"))
PYEOF
}

# Extracts a human-readable error message from a Cloudflare API JSON
# response (its "errors" array), falling back to the HTTP status code.
api_error() {
    python3 - "$1" "$2" <<'PYEOF'
import json, sys
path, code = sys.argv[1], sys.argv[2]
msg = ""
try:
    data = json.load(open(path))
    errors = data.get("errors") or []
    msg = "; ".join(f"{e.get('code', '')}: {e.get('message', '')}".strip(": ") for e in errors)
except Exception:
    pass
print(msg or f"HTTP {code}")
PYEOF
}

if [ -z "${CLOUDFLARE_WORKERS_TOKEN:-}" ]; then
    echo "[cloudflare] CLOUDFLARE_WORKERS_TOKEN not set; skipping." >>"$LOG"
    write_state "keepawake" "not configured" "" "" ""
    write_state "telegram_proxy" "not configured" "" "" ""
    exit 0
fi

if [ -z "${SPACE_HOST:-}" ]; then
    echo "[cloudflare] SPACE_HOST not set (not running on Hugging Face?); skipping." >>"$LOG"
    write_state "keepawake" "not configured" "" "" ""
    write_state "telegram_proxy" "not configured" "" "" ""
    exit 0
fi

API="https://api.cloudflare.com/client/v4"
TARGET="https://${SPACE_HOST}/health"

# Resolve the Cloudflare account id: prefer an explicit override, else ask
# the API for the accounts this token can see.
ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
if [ -z "$ACCOUNT_ID" ]; then
    ACCOUNTS_CODE=$(curl -sS -o /tmp/cloudflare-accounts.json -w '%{http_code}' --max-time 10 \
        -H "Authorization: Bearer ${CLOUDFLARE_WORKERS_TOKEN}" "$API/accounts")
    cat /tmp/cloudflare-accounts.json >>"$LOG"
    echo >>"$LOG"
    if [ "$ACCOUNTS_CODE" = "200" ]; then
        ACCOUNT_ID=$(python3 -c 'import json; d=json.load(open("/tmp/cloudflare-accounts.json")); r=d.get("result") or []; print(r[0]["id"] if r else "")' 2>>"$LOG" || true)
    fi
fi

if [ -z "$ACCOUNT_ID" ]; then
    DETAIL=$(api_error /tmp/cloudflare-accounts.json "${ACCOUNTS_CODE:-unknown}")
    echo "[cloudflare] could not determine Cloudflare account id ($DETAIL). Set the CLOUDFLARE_ACCOUNT_ID secret (Cloudflare dashboard -> Workers & Pages -> Account ID, right sidebar) and restart." >>"$LOG"
    write_state "keepawake" "error" "" "$TARGET" "account lookup: $DETAIL"
    write_state "telegram_proxy" "error" "" "" "account lookup: $DETAIL"
    exit 0
fi

# Worker script name derived from the Space host (must be a valid Cloudflare
# script name: lowercase letters, digits, hyphens).
WORKER_NAME="keepawake-$(echo "$SPACE_HOST" | sed -E 's/\.hf\.space$//; s/[^a-zA-Z0-9-]/-/g' | tr '[:upper:]' '[:lower:]' | cut -c1-50)"

cat > /tmp/cloudflare-worker.js <<EOF
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch("${TARGET}").catch(() => {}));
  },
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/bot") || url.pathname.startsWith("/file/bot")) {
      url.protocol = "https:";
      url.hostname = "api.telegram.org";
      url.port = "";
      return fetch(url.toString(), request);
    }
    return new Response("ok");
  },
};
EOF

DEPLOY_CODE=$(curl -sS -o /tmp/cloudflare-deploy.json -w '%{http_code}' --max-time 20 -X PUT \
    -H "Authorization: Bearer ${CLOUDFLARE_WORKERS_TOKEN}" \
    "$API/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME" \
    -F 'metadata={"main_module":"worker.js","compatibility_date":"2024-09-01"};type=application/json' \
    -F "worker.js=@/tmp/cloudflare-worker.js;filename=worker.js;type=application/javascript+module")
cat /tmp/cloudflare-deploy.json >>"$LOG"
echo >>"$LOG"

if [ "$DEPLOY_CODE" != "200" ]; then
    DETAIL=$(api_error /tmp/cloudflare-deploy.json "$DEPLOY_CODE")
    echo "[cloudflare] Worker deploy failed: $DETAIL" >>"$LOG"
    write_state "keepawake" "error" "$WORKER_NAME" "$TARGET" "deploy: $DETAIL"
    write_state "telegram_proxy" "error" "$WORKER_NAME" "" "deploy: $DETAIL"
    exit 0
fi

if [ "${CLOUDFLARE_KEEPALIVE_ENABLED:-true}" = "false" ]; then
    echo "[cloudflare] keep-awake cron disabled (CLOUDFLARE_KEEPALIVE_ENABLED=false)." >>"$LOG"
    write_state "keepawake" "disabled" "$WORKER_NAME" "$TARGET" ""
else
    SCHEDULE_CODE=$(curl -sS -o /tmp/cloudflare-schedule.json -w '%{http_code}' --max-time 20 -X PUT \
        -H "Authorization: Bearer ${CLOUDFLARE_WORKERS_TOKEN}" \
        -H "Content-Type: application/json" \
        "$API/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME/schedules" \
        -d '[{"cron":"0 0 * * *"}]')
    cat /tmp/cloudflare-schedule.json >>"$LOG"
    echo >>"$LOG"
    if [ "$SCHEDULE_CODE" != "200" ]; then
        DETAIL=$(api_error /tmp/cloudflare-schedule.json "$SCHEDULE_CODE")
        echo "[cloudflare] Worker schedule failed: $DETAIL" >>"$LOG"
        write_state "keepawake" "error" "$WORKER_NAME" "$TARGET" "schedule: $DETAIL"
    else
        echo "[cloudflare] deployed Worker '$WORKER_NAME' pinging $TARGET every 24h." >>"$LOG"
        write_state "keepawake" "configured" "$WORKER_NAME" "$TARGET" ""
    fi
fi

# --- Telegram Bot API proxy (only if a bot is configured) -----------------
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    echo "[cloudflare] TELEGRAM_BOT_TOKEN not set; skipping Telegram proxy." >>"$LOG"
    write_state "telegram_proxy" "not configured" "$WORKER_NAME" "" ""
    exit 0
fi

# The proxy needs a public URL for the Worker, which requires a workers.dev
# subdomain on the account (most accounts have one; if not, it's a one-time
# claim in the Cloudflare dashboard: Workers & Pages -> "Set up a subdomain").
SUBDOMAIN_CODE=$(curl -sS -o /tmp/cloudflare-subdomain.json -w '%{http_code}' --max-time 10 \
    -H "Authorization: Bearer ${CLOUDFLARE_WORKERS_TOKEN}" \
    "$API/accounts/$ACCOUNT_ID/workers/subdomain")
cat /tmp/cloudflare-subdomain.json >>"$LOG"
echo >>"$LOG"

SUBDOMAIN=""
if [ "$SUBDOMAIN_CODE" = "200" ]; then
    SUBDOMAIN=$(python3 -c 'import json; d=json.load(open("/tmp/cloudflare-subdomain.json")); print((d.get("result") or {}).get("subdomain") or "")' 2>>"$LOG" || true)
fi

if [ -z "$SUBDOMAIN" ]; then
    DETAIL=$(api_error /tmp/cloudflare-subdomain.json "$SUBDOMAIN_CODE")
    echo "[cloudflare] no workers.dev subdomain on this account ($DETAIL). Claim one once at Cloudflare dashboard -> Workers & Pages -> 'Set up a subdomain', then restart this Space." >>"$LOG"
    write_state "telegram_proxy" "error" "$WORKER_NAME" "" "no workers.dev subdomain: $DETAIL"
    exit 0
fi

ENABLE_CODE=$(curl -sS -o /tmp/cloudflare-enable.json -w '%{http_code}' --max-time 10 -X POST \
    -H "Authorization: Bearer ${CLOUDFLARE_WORKERS_TOKEN}" \
    -H "Content-Type: application/json" \
    "$API/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME/subdomain" \
    -d '{"enabled":true,"previews_enabled":false}')
cat /tmp/cloudflare-enable.json >>"$LOG"
echo >>"$LOG"

if [ "$ENABLE_CODE" != "200" ]; then
    DETAIL=$(api_error /tmp/cloudflare-enable.json "$ENABLE_CODE")
    echo "[cloudflare] enabling workers.dev route failed: $DETAIL" >>"$LOG"
    write_state "telegram_proxy" "error" "$WORKER_NAME" "" "subdomain route: $DETAIL"
    exit 0
fi

PROXY_URL="https://${WORKER_NAME}.${SUBDOMAIN}.workers.dev"
{
    echo "TELEGRAM_API_BASE_URL=${PROXY_URL}/bot"
    echo "TELEGRAM_API_FILE_BASE_URL=${PROXY_URL}/file/bot"
} > "$PROXY_ENV_FILE"

echo "[cloudflare] Telegram Bot API proxy ready at $PROXY_URL" >>"$LOG"
write_state "telegram_proxy" "configured" "$WORKER_NAME" "$PROXY_URL" ""
