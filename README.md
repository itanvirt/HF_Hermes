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
| `GATEWAY_TOKEN` | Shared secret protecting the terminal and ENV Builder. Use a long random string. |
| `LLM_MODEL` | Model identifier, e.g. `gemini-2.5-flash` (good free-tier default). |
| `LLM_API_KEY` | API key for the provider implied by `LLM_MODEL`. |

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
