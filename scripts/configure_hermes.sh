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
    gemini*|*gemini*|google/*)
        HERMES_PROVIDER="google"
        export GOOGLE_API_KEY="${GOOGLE_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    gpt-*|o1*|o3*|o4*|*openai*|openai/*)
        HERMES_PROVIDER="openai"
        export OPENAI_API_KEY="${OPENAI_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    claude*|*anthropic*|anthropic/*)
        HERMES_PROVIDER="anthropic"
        export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    openrouter/*|*openrouter*)
        HERMES_PROVIDER="openrouter"
        export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    deepseek/*|*deepseek*)
        HERMES_PROVIDER="deepseek"
        export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    xai/*|grok/*)
        HERMES_PROVIDER="xai"
        export XAI_API_KEY="${XAI_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    nvidia/*)
        HERMES_PROVIDER="nvidia"
        export NVIDIA_API_KEY="${NVIDIA_API_KEY:-${LLM_API_KEY:-}}"
        ;;
    huggingface/*|hf/*)
        HERMES_PROVIDER="huggingface"
        export HF_INFERENCE_TOKEN="${HF_INFERENCE_TOKEN:-${LLM_API_KEY:-${HF_TOKEN:-}}}"
        ;;
    *)
        # Unknown/vendor prefix (e.g. "mistral/", "kimi/") — route through
        # OpenRouter which supports virtually every model via its prefix format.
        HERMES_PROVIDER="openrouter"
        export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-${LLM_API_KEY:-}}"
        ;;
esac

# --- API key pool rotation ------------------------------------------------
# If a *_KEYS pool var is set (comma-separated values), promote the first
# key to the singular var Hermes reads. Lets you supply multiple keys for
# load-sharing or rate-limit avoidance without changing the rest of the config.
for _pair in \
    "OPENROUTER_API_KEYS:OPENROUTER_API_KEY" \
    "ANTHROPIC_API_KEYS:ANTHROPIC_API_KEY" \
    "OPENAI_API_KEYS:OPENAI_API_KEY" \
    "GOOGLE_API_KEYS:GOOGLE_API_KEY" \
    "DEEPSEEK_API_KEYS:DEEPSEEK_API_KEY" \
    "XAI_API_KEYS:XAI_API_KEY" \
    "NVIDIA_API_KEYS:NVIDIA_API_KEY"; do
    _pool_var="${_pair%%:*}"
    _single_var="${_pair##*:}"
    _pool="${!_pool_var:-}"
    if [ -n "$_pool" ]; then
        export "${_single_var}=${_pool%%,*}"
    fi
done
unset _pair _pool_var _single_var _pool

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
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
XAI_API_KEY=${XAI_API_KEY:-}
NVIDIA_API_KEY=${NVIDIA_API_KEY:-}
HF_INFERENCE_TOKEN=${HF_INFERENCE_TOKEN:-}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS:-}
TELEGRAM_WEBHOOK_URL=${TELEGRAM_WEBHOOK_URL:-}
TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET:-}
TELEGRAM_WEBHOOK_PORT=${TELEGRAM_WEBHOOK_PORT:-}
HERMES_PROVIDER=${HERMES_PROVIDER}
EOF
chmod 600 "$HERMES_HOME/.env"

# --- non-interactive model + provider selection ---------------------------
# `hermes config set` writes non-secret settings to ~/.hermes/config.yaml.
# Best-effort: logs failures so the operator can finish configuration from
# the in-browser terminal.
#
# Retries a few times since hermes may still be settling right after the
# fallback install above; also makes failure detection correct - chaining
# the two `config set` calls with `;` (as before) reported success based on
# the second call's exit code alone, silently swallowing a failure of the
# first.
_hermes_config_set() {
    local attempt
    for attempt in 1 2 3; do
        if hermes config set "$@" >>/home/user/app/data/hermes-setup.log 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

if command -v hermes >/dev/null 2>&1 && [ -n "${LLM_MODEL:-}" ]; then
    _hermes_config_set model.default "${LLM_MODEL}" && _hermes_config_set model.provider "${HERMES_PROVIDER}" || \
        echo "[configure_hermes] 'hermes config set' did not complete after retries; configure manually via the in-browser terminal." \
            >>/home/user/app/data/hermes-setup.log
fi

if command -v hermes >/dev/null 2>&1 && [ -n "${TELEGRAM_API_BASE_URL:-}" ]; then
    _hermes_config_set platforms.telegram.extra.base_url "${TELEGRAM_API_BASE_URL}" && \
        _hermes_config_set platforms.telegram.extra.base_file_url "${TELEGRAM_API_FILE_BASE_URL}" || \
        echo "[configure_hermes] 'hermes config set' for the Telegram proxy did not complete after retries; configure manually via the in-browser terminal." \
            >>/home/user/app/data/hermes-setup.log
fi

# --- preserve SOUL.md across restarts ------------------------------------
# If SOUL.md is missing or contains only template comments (no real content),
# restore it from the bundled default so the persona survives cold starts
# before the first backup/restore cycle runs.
SOUL_FILE="$HERMES_HOME/SOUL.md"
SOUL_DEFAULT="/home/user/app/scripts/default_soul.md"
if [ -f "$SOUL_DEFAULT" ]; then
    # Check if soul file has real content (not just template comments)
    SOUL_ACTIVE=$(sed 's/<!--.*-->//g' "$SOUL_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$SOUL_ACTIVE" ]; then
        cp "$SOUL_DEFAULT" "$SOUL_FILE"
        # Mirror to paths the agent commonly writes to so it finds the
        # persona regardless of where it searches or writes next time.
        mkdir -p "$HERMES_HOME/workspace"
        cp "$SOUL_DEFAULT" "$HERMES_HOME/workspace/SOUL.md"
        cp "$SOUL_DEFAULT" "$HOME/SOUL.md"
        echo "[configure_hermes] seeded SOUL.md from default." >>/home/user/app/data/hermes-setup.log
    fi
fi

echo "[configure_hermes] done."
