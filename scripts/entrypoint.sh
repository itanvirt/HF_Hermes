#!/usr/bin/env bash
set -uo pipefail

echo "=== Hermes Agent (HF Space) starting ==="

# Deploys the Cloudflare Worker (keep-awake ping + Telegram Bot API proxy)
# before configure_hermes.sh, which reads its output (cloudflare_proxy.env)
# to point Hermes at the proxy when Telegram is configured. Synchronous
# (with short curl timeouts) so config.yaml is written correctly on first
# boot; best-effort and non-fatal.
bash /home/user/app/scripts/configure_cloudflare.sh || true

bash /home/user/app/scripts/restore_hermes.sh || true

bash /home/user/app/scripts/configure_hermes.sh

bash /home/user/app/scripts/configure_startup.sh || true

# Trap shutdown signals so a Space restart/redeploy doesn't lose up to
# SYNC_INTERVAL of state: run one last backup sync before supervisord's
# children are stopped. Requires NOT exec'ing supervisord (exec would
# replace this shell, and the trap with it) - so supervisord runs as a
# background child instead, and this script blocks on it via `wait`.
SUPERVISOR_PID=""
graceful_shutdown() {
    echo "[entrypoint] caught shutdown signal; syncing state before exit..."
    python3 -c "from app.backup import run_backup; print('[entrypoint] shutdown sync result:', run_backup())" 2>&1 || true
    if [ -n "$SUPERVISOR_PID" ] && kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
        kill -TERM "$SUPERVISOR_PID" 2>/dev/null || true
        wait "$SUPERVISOR_PID" 2>/dev/null || true
    fi
    exit 0
}
trap graceful_shutdown SIGTERM SIGINT

supervisord -c /home/user/app/supervisord.conf &
SUPERVISOR_PID=$!
wait "$SUPERVISOR_PID"
