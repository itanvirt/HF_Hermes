---
title: Hermes Agent
emoji: 🤖
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
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
- a Cloudflare Worker keep-awake cron so the free Space doesn't go to sleep

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
5. (Optional) Deploy the Cloudflare Worker in `cloudflare/` to keep the free
   Space awake — see `cloudflare/README.md`. Until it's deployed, the
   "Keep Awake" card on the dashboard correctly shows "NOT CONFIGURED".

## Required secrets

Set these under **Settings → Variables and secrets** before (or right
after) duplicating:

| Secret | Description |
| --- | --- |
| `HF_TOKEN` | Hugging Face token (write access) — used for the automatic backup dataset. |
| `CLOUDFLARE_WORKERS_TOKEN` | Cloudflare API token used to deploy the keep-awake Worker. |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs allowed to message the agent. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from `@BotFather`. |
| `GATEWAY_TOKEN` | Shared secret protecting the terminal and ENV Builder. Use a long random string. |
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
