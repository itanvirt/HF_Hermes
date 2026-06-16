---
title: Hermes Agent
emoji: 🤖
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
variables:
  CLOUDFLARE_KEEPALIVE_ENABLED: "true"
  SYNC_INTERVAL: "600"
  BACKUP_DATASET_NAME: "hermes-backup"
  GATEWAY_RESTART_DELAY: "5"
  GATEWAY_MAX_RESTARTS: "0"
  GATEWAY_PORT: "8642"
---

# Hermes Agent — self-hosted, free-tier build

[![Duplicate this Space](https://huggingface.co/datasets/huggingface/badges/resolve/main/duplicate-this-space-md.svg)](https://huggingface.co/spaces/itanvirt/hf_hermes?duplicate=true)

A ready-to-duplicate Hugging Face Space that runs [Hermes Agent](https://github.com/NousResearch/hermes-agent)
on the free CPU tier, with:

- a dashboard landing page showing live status (gateway, model, runtime,
  Telegram, backups, keep-awake)
- **Open Hermes Agent** — the Hermes CLI in your browser
- **Open Terminal** — full shell access to the container
- **ENV Builder** — view/edit runtime configuration without redeploying
- a Telegram bot via the Hermes messaging gateway (long-polling, no inbound
  webhook required)
- automatic backups of agent state to a private Hugging Face dataset
- automatic keep-awake + Telegram proxy: on first boot, the container
  deploys a tiny Cloudflare Worker (using your `CLOUDFLARE_WORKERS_TOKEN`
  secret) that pings `/health` every 10 minutes so the free Space doesn't
  sleep, and reverse-proxies Telegram's API so the bot still connects on
  networks that block direct outbound connections to `api.telegram.org` —
  no manual steps, works for any duplicated Space

## Quickstart: duplicate this Space

1. Click **Duplicate this Space** (top right). The duplicate dialog suggests
   a new Space name (Hugging Face defaults this to a hyphenated slug,
   independent of the source repo's name) — pick whatever you like.
2. Fill in the required secrets (see below).
3. Wait for the build to finish, then open the Space **in its own tab**
   (`https://<owner>-<space>.hf.space`, not the embedded view on
   huggingface.co — some browsers block cookies in embedded iframes, which
   breaks the Terminal/ENV Builder login).
4. Visit `/env-builder` (unlock with your `GATEWAY_TOKEN`) to confirm
   everything is configured, or `/terminal` to run `hermes setup`
   interactively if anything needs adjusting.
5. That's it — on first boot, the container automatically deploys a
   Cloudflare Worker (using your `CLOUDFLARE_WORKERS_TOKEN` secret) that
   pings `/health` every 10 minutes, so the free Space doesn't go to sleep.
   Check the **Keep Awake** card on the dashboard to confirm it deployed.

## Required secrets

Set these under **Settings → Variables and secrets** before (or right
after) duplicating:

| Secret | Description |
| --- | --- |
| `HF_TOKEN` | Hugging Face token (write access) — used for the automatic backup dataset. |
| `CLOUDFLARE_WORKERS_TOKEN` | Cloudflare API token with "Edit Cloudflare Workers" permission. The container uses this to auto-deploy a Worker on first boot that pings `/health` (keep-awake) and proxies Telegram's API (so the bot connects even if this network blocks `api.telegram.org` directly) — no manual steps. |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs allowed to message the agent. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from `@BotFather`. |
| `GATEWAY_TOKEN` | Shared secret protecting the terminal, ENV Builder, and the `/v1/*` LLM relay. Use a long random string. |
| `LLM_MODEL` | Model identifier. See provider table below. |
| `LLM_API_KEY` | API key for the provider implied by `LLM_MODEL`. |

### LLM providers

| Prefix | Example | Key secret |
| --- | --- | --- |
| `gemini-*` / `google/` | `gemini-2.5-flash` | `LLM_API_KEY` (→ `GOOGLE_API_KEY`) |
| `gpt-*` / `openai/` | `gpt-4o` | `LLM_API_KEY` (→ `OPENAI_API_KEY`) |
| `claude*` / `anthropic/` | `claude-sonnet-4-6` | `LLM_API_KEY` (→ `ANTHROPIC_API_KEY`) |
| `openrouter/*` | `openrouter/google/gemini-2.5-flash` | `LLM_API_KEY` (→ `OPENROUTER_API_KEY`) |
| `deepseek/*` | `deepseek/deepseek-chat` | `LLM_API_KEY` (→ `DEEPSEEK_API_KEY`) |
| `xai/*` / `grok/` | `xai/grok-4` | `LLM_API_KEY` (→ `XAI_API_KEY`) |
| `nvidia/*` | `nvidia/llama-3.1-nemotron-ultra-253b-v1` | `LLM_API_KEY` (→ `NVIDIA_API_KEY`) |
| `hf/*` / `huggingface/*` | `hf/Qwen/Qwen3-235B` | `LLM_API_KEY` (→ `HF_INFERENCE_TOKEN`) |
| anything else | `mistral/mistral-large` | `LLM_API_KEY` (→ `OPENROUTER_API_KEY`) |

For API key rotation, set `OPENROUTER_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`,
`GOOGLE_API_KEYS`, `DEEPSEEK_API_KEYS`, `XAI_API_KEYS`, or `NVIDIA_API_KEYS` to a
comma-separated list — the first key is promoted to the active singular var automatically.

### Optional variables

| Variable | Default | Description |
| --- | --- | --- |
| `STARTUP_APT_PACKAGES` | — | Space-separated apt packages to install on every boot. |
| `STARTUP_PIP_PACKAGES` | — | Space-separated pip packages to install on every boot. |
| `STARTUP_NPM_PACKAGES` | — | Space-separated npm packages to install on every boot. |
| `STARTUP_RUN` | — | Bash commands to run on every boot (use `STARTUP_RUN_BASE64` for multi-line). |
| `SYNC_INTERVAL` | `600` | Backup frequency in seconds. |
| `BACKUP_DATASET_NAME` | `hermes-backup` | Dataset name for backups (owner is auto-detected from `HF_TOKEN`). |
| `CLOUDFLARE_KEEPALIVE_ENABLED` | `true` | Set to `false` to deploy the Worker (for Telegram proxy) without the keep-awake cron. |
| `CLOUDFLARE_ACCOUNT_ID` | — | Override Cloudflare account ID if your token has access to multiple accounts. |
| `GATEWAY_RESTART_DELAY` | `5` | Seconds to wait between gateway restarts. |
| `GATEWAY_MAX_RESTARTS` | `0` | Max gateway restart attempts (0 = unlimited). |
| `WEBHOOK_URL` | — | URL to POST to on each gateway restart (JSON body with `event` and `space`). |
| `TELEGRAM_MODE` | — | Set to `webhook` to use inbound webhook delivery instead of long-polling. |

See `SETUP.md` for a full walkthrough, including the keep-awake Worker and
the GitHub → Hugging Face sync workflow.

## Repository layout

```
Dockerfile                 Container image (Hermes Agent + dashboard app)
supervisord.conf           Runs the web app and the Hermes gateway
app/                        FastAPI dashboard, gateway proxy, terminal, ENV Builder, backups
scripts/                    Install + runtime configuration scripts
cloudflare/                 Manual/advanced Cloudflare Worker (Telegram webhook proxy, keep-awake fallback)
.github/workflows/          Sync to Hugging Face
```
