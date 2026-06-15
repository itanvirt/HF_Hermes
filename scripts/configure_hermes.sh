#!/usr/bin/env bash
# Translates Space secrets / env vars into Hermes Agent configuration.
# Runs on every container start (entrypoint.sh), so it must be idempotent.
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_HOME"

# Re-install if the build-time install didn't complete (e.g. installer
# needed network access that wasn't available during image build).
if ! command -v hermes >/dev/null 2>&1; then
    echo "[configure_hermes] hermes binary not found, retrying install..."
    bash "$(dirname "$0")/install_hermes.sh" || true
fi

# --- map LLM_MODEL -> provider id + the API key env var Hermes expects ----
case "${LLM_MODEL:-}" in
    gemini*|*gemini*)
        HERMES_PROVIDER="google"
        export GOOGLE_API_KEY="${LLM_API_KEY:-}"
        ;;
    gpt-*|o1*|o3*|o4*|*openai*)
        HERMES_PROVIDER="openai"
        export OPENAI_API_KEY="${LLM_API_KEY:-}"
        ;;
    claude*|*anthropic*)
        HERMES_PROVIDER="anthropic"
        export ANTHROPIC_API_KEY="${LLM_API_KEY:-}"
        ;;
    openrouter/*|*openrouter*)
        HERMES_PROVIDER="openrouter"
        export OPENROUTER_API_KEY="${LLM_API_KEY:-}"
        ;;
    *)
        # Unknown prefix: assume an OpenRouter-style "vendor/model" id.
        HERMES_PROVIDER="openrouter"
        export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-${LLM_API_KEY:-}}"
        ;;
esac

# --- Telegram Bot API proxy (via Cloudflare Worker, see configure_cloudflare.sh) ---
# If configure_cloudflare.sh deployed a reverse proxy for api.telegram.org
# (works around this network blocking outbound connections to Telegram),
# point Hermes's Telegram client at it instead of the public API.
CLOUDFLARE_PROXY_ENV_FILE="${CLOUDFLARE_PROXY_ENV_FILE:-/home/user/app/data/cloudflare_proxy.env}"
if [ -f "$CLOUDFLARE_PROXY_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$CLOUDFLARE_PROXY_ENV_FILE"
fi

# --- optional Telegram webhook mode -----------------------------------
# Default is long-polling (outbound to Telegram, no extra config). Set
# TELEGRAM_MODE=webhook to switch to inbound delivery via this Space's own
# HTTPS endpoint instead - useful if outbound connections to Telegram's API
# are blocked from this network (the gateway log would show "connect timed
# out" for api.telegram.org).
GATEWAY_PORT="${GATEWAY_PORT:-8642}"
if [ "${TELEGRAM_MODE:-}" = "webhook" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${SPACE_HOST:-}" ]; then
    export TELEGRAM_WEBHOOK_URL="https://${SPACE_HOST}/telegram-webhook"
    export TELEGRAM_WEBHOOK_SECRET="${TELEGRAM_WEBHOOK_SECRET:-$(openssl rand -hex 32)}"
    export TELEGRAM_WEBHOOK_PORT="$GATEWAY_PORT"
fi

# Always write the provider keys + Telegram config to ~/.hermes/.env, which
# Hermes loads on startup (required for secrets per the Hermes config docs).
cat > "$HERMES_HOME/.env" <<EOF
GOOGLE_API_KEY=${GOOGLE_API_KEY:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS:-}
TELEGRAM_WEBHOOK_URL=${TELEGRAM_WEBHOOK_URL:-}
TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET:-}
TELEGRAM_WEBHOOK_PORT=${TELEGRAM_WEBHOOK_PORT:-}
EOF
chmod 600 "$HERMES_HOME/.env"

# --- non-interactive model selection ---------------------------------------
# `hermes config set` writes non-secret settings to ~/.hermes/config.yaml.
# Best-effort: logs failures instead of failing the container start, so the
# operator can finish configuration from the in-browser terminal
# ("Open Hermes Agent" / "Open Terminal" -> `hermes config` / `hermes model`).
if command -v hermes >/dev/null 2>&1 && [ -n "${LLM_MODEL:-}" ]; then
    {
        hermes config set model.default "${LLM_MODEL}"
        hermes config set model.provider "${HERMES_PROVIDER}"
    } >/home/user/app/data/hermes-setup.log 2>&1 || \
        echo "[configure_hermes] 'hermes config set' did not complete; configure manually via the in-browser terminal." \
            >>/home/user/app/data/hermes-setup.log
fi

if command -v hermes >/dev/null 2>&1 && [ -n "${TELEGRAM_API_BASE_URL:-}" ]; then
    {
        hermes config set platforms.telegram.extra.base_url "${TELEGRAM_API_BASE_URL}"
        hermes config set platforms.telegram.extra.base_file_url "${TELEGRAM_API_FILE_BASE_URL}"
    } >>/home/user/app/data/hermes-setup.log 2>&1 || \
        echo "[configure_hermes] 'hermes config set' for the Telegram proxy did not complete; configure manually via the in-browser terminal." \
            >>/home/user/app/data/hermes-setup.log
fi

echo "[configure_hermes] done."
