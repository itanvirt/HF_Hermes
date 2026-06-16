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

exec supervisord -c /home/user/app/supervisord.conf
