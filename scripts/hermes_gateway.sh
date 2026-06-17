#!/usr/bin/env bash
# Runs the Hermes Agent messaging gateway (Telegram long-polling, or
# webhook mode if TELEGRAM_MODE=webhook - see configure_hermes.sh).
# Restarts automatically on exit; GATEWAY_RESTART_DELAY controls the
# wait between attempts (default 5s), GATEWAY_MAX_RESTARTS caps total
# attempts (default 0 = unlimited). WEBHOOK_URL receives a POST on each
# restart. If no Telegram token is configured, idles instead of looping.
set -uo pipefail

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    echo "[hermes-gateway] TELEGRAM_BOT_TOKEN not set; gateway idle. Configure secrets and restart."
    exec sleep infinity
fi

if ! command -v hermes >/dev/null 2>&1; then
    echo "[hermes-gateway] hermes binary not found; gateway idle."
    exec sleep infinity
fi

RESTART_DELAY="${GATEWAY_RESTART_DELAY:-5}"
MAX_RESTARTS="${GATEWAY_MAX_RESTARTS:-0}"
WEBHOOK_URL="${WEBHOOK_URL:-}"

if [ "${TELEGRAM_MODE:-}" = "webhook" ]; then
    echo "[hermes-gateway] starting (Telegram webhook mode, port ${GATEWAY_PORT:-8642})"
else
    echo "[hermes-gateway] starting (Telegram long-polling)"
fi

_notify() {
    [ -n "$WEBHOOK_URL" ] || return 0
    curl -sS --max-time 5 -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"$1\",\"space\":\"${SPACE_HOST:-unknown}\"}" \
        >/dev/null 2>&1 || true
}

restarts=0
while true; do
    hermes gateway run
    code=$?
    restarts=$((restarts + 1))
    echo "[hermes-gateway] exited (code $code, restart #${restarts})"
    python3 -c "from app.backup import run_backup; print('[hermes-gateway] sync result:', run_backup())" 2>&1 || true
    _notify "restart"
    if [ "$MAX_RESTARTS" -gt 0 ] && [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        echo "[hermes-gateway] max restarts ($MAX_RESTARTS) reached; exiting."
        _notify "max_restarts"
        exit "$code"
    fi
    sleep "$RESTART_DELAY"
done
