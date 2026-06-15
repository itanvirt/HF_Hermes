---
title: Hermes Agent
emoji: 🜂
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Hermes Agent — self-hosted, free-tier build

[![Duplicate this Space](https://huggingface.co/datasets/huggingface/badges/resolve/main/duplicate-this-space-md.svg)](https://huggingface.co/spaces/itanvirt/hf-hermes?duplicate=true)

A ready-to-duplicate Hugging Face Space that runs [Hermes Agent](https://github.com/NousResearch/hermes-agent)
on the free CPU tier, with:

- a dashboard landing page showing live status (gateway, model, runtime,
  Telegram, backups, keep-awake)
- **Open Hermes Agent** — the Hermes CLI in your browser
- **Open Terminal** — full shell access to the container
- **ENV Builder** — view/edit runtime configuration without redeploying
- a protected gateway API for Telegram (via a Cloudflare Worker proxy)
- automatic backups of agent state to a private Hugging Face dataset
- a keep-awake cron so the free Space doesn't go to sleep

## Quickstart: duplicate this Space

1. Click **Duplicate this Space** (top right).
2. Fill in the required secrets (see below).
3. Wait for the build to finish, then open the Space.
4. Visit `/env-builder` (unlock with your `GATEWAY_TOKEN`) to confirm
   everything is configured, or `/terminal` to run `hermes setup`
   interactively if anything needs adjusting.
5. (Optional) Deploy the Cloudflare Worker in `cloudflare/` for the
   Telegram webhook proxy and keep-awake cron — see `cloudflare/README.md`.

## Required secrets

Set these under **Settings → Variables and secrets** before (or right
after) duplicating:

| Secret | Description |
| --- | --- |
| `HF_TOKEN` | Hugging Face token (write access) — used for the automatic backup dataset. |
| `CLOUDFLARE_WORKERS_TOKEN` | Cloudflare API token used to deploy the Telegram/keep-awake Worker. |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs allowed to message the agent. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from `@BotFather`. |
| `GATEWAY_TOKEN` | Shared secret protecting the gateway API, terminal and ENV Builder. Use a long random string. |
| `LLM_MODEL` | Model identifier, e.g. `gemini-2.5-flash` (good free-tier default). |
| `LLM_API_KEY` | API key for the provider implied by `LLM_MODEL`. |

See `SETUP.md` for a full walkthrough, including the Cloudflare Worker and
the GitHub → Hugging Face sync workflow.

## Repository layout

```
Dockerfile                 Container image (Hermes Agent + dashboard app)
supervisord.conf           Runs the web app and the Hermes gateway
app/                        FastAPI dashboard, gateway proxy, terminal, ENV Builder, backups
scripts/                    Install + runtime configuration scripts
cloudflare/                 Telegram webhook proxy + keep-awake Worker
.github/workflows/          Sync this repo to a Hugging Face Space
```
