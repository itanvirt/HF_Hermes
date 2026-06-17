---
title: Hermes Agent
emoji: 🤖
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Free, self-hosted AI agent with a Telegram bot, dashboard, and auto backups — no coding required.
tags:
  - agent
  - ai-agent
  - llm
  - telegram-bot
  - chatbot
  - automation
  - self-hosted
  - docker
  - free-tier
  - no-code
variables:
  CLOUDFLARE_KEEPALIVE_ENABLED: "true"
  CLOUDFLARE_ACCOUNT_ID: ""
  SYNC_INTERVAL: "600"
  BACKUP_DATASET_NAME: "hermes-backup"
  GATEWAY_RESTART_DELAY: "5"
  GATEWAY_MAX_RESTARTS: "0"
  GATEWAY_PORT: "8642"
---

# Hermes Agent: run a free, self-hosted AI agent + Telegram bot on Hugging Face Spaces

[![Duplicate this Space](https://huggingface.co/datasets/huggingface/badges/resolve/main/duplicate-this-space-md.svg)](https://huggingface.co/spaces/itanvirt/hf_hermes?duplicate=true)

**No coding required.** This is a ready-to-duplicate [Hugging Face Space](https://huggingface.co/spaces)
that runs [Hermes Agent](https://github.com/NousResearch/hermes-agent) — a
general-purpose AI agent — on Hugging Face's **free CPU tier**, fully
configured through a web dashboard. Click **Duplicate this Space**, paste in
a handful of secrets, and within a few minutes you have:

- your own **AI agent you can talk to from Telegram**, running 24/7 on a free server
- a **web dashboard** showing live status for the bot, model, backups, and uptime
- an in-browser **terminal** and **agent CLI** — no SSH, no local install
- automatic **backups** of your agent's memory/state to a private Hugging Face dataset
- automatic **keep-awake** so the free Space doesn't fall asleep, and a
  built-in fix for networks that block Telegram's API
- support for **any LLM provider** — Gemini, OpenAI, Claude, OpenRouter,
  DeepSeek, Grok, NVIDIA NIM, or any Hugging Face-hosted model

If you've ever wanted your own free, private, self-hosted ChatGPT-style
assistant that lives in Telegram, this is built for someone setting that up
for the very first time.

## Table of contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Step-by-step setup](#step-by-step-setup)
  - [Step 1: Create the Hugging Face Space](#step-1-create-the-hugging-face-space)
  - [Step 2: Collect your secrets](#step-2-collect-your-secrets)
  - [Step 3: Add the secrets to your Space](#step-3-add-the-secrets-to-your-space)
  - [Step 4: First boot](#step-4-first-boot)
  - [Step 5: Talk to your agent](#step-5-talk-to-your-agent)
- [Required secrets reference](#required-secrets-reference)
- [Choosing an LLM provider](#choosing-an-llm-provider)
- [Optional settings](#optional-settings)
- [Frequently asked questions](#frequently-asked-questions)
- [Troubleshooting](#troubleshooting)
- [How backups work](#how-backups-work)
- [Repository layout](#repository-layout)
- [For maintainers: keeping your own fork in sync](#for-maintainers-keeping-your-own-fork-in-sync)

## What you get

| Feature | Description |
| --- | --- |
| Dashboard | A landing page with live status cards for the gateway, model, runtime, Telegram, backups, and keep-awake. |
| **Open Hermes Agent** | The Hermes CLI, running in your browser — chat with your agent without leaving the dashboard. |
| **Open Terminal** | Full shell access inside the container — install packages, inspect logs, run commands. |
| **ENV Builder** | View and edit your configuration without redeploying the Space. |
| Telegram bot | Hermes's messaging gateway, talking to your bot via long-polling (no public webhook needed). |
| Automatic backups | Agent state mirrored file-by-file into a private Hugging Face dataset — no tarballs, no unbounded growth. |
| Automatic keep-awake | A tiny Cloudflare Worker pings the Space every 10 minutes so the free tier doesn't sleep. |

## Before you start

You'll need free accounts on:

- **[Hugging Face](https://huggingface.co/join)** — hosts the Space (the server your agent runs on) and the private backup dataset.
- **[Telegram](https://telegram.org/)** — to talk to your agent through a bot.
- An account with **one LLM provider** of your choice (see [Choosing an LLM provider](#choosing-an-llm-provider)) — several offer a free tier, e.g. Google Gemini.
- *(Optional but recommended)* **[Cloudflare](https://dash.cloudflare.com/sign-up)** — free, used only to keep the Space awake and to work around networks that block Telegram's API.

No credit card and no programming experience is required for any of the above.

## Step-by-step setup

### Step 1: Create the Hugging Face Space

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space).
2. Pick a name for your Space.
3. Under **Select the Space SDK**, choose **Docker**.
4. Under **Space hardware**, choose the free **CPU basic** tier.
5. Click **Create Space**.

> Easier option: instead of creating a blank Space, click the green
> **Duplicate this Space** button at the top of this page — it copies
> everything for you and skips straight to Step 2.

### Step 2: Collect your secrets

"Secrets" are just passwords/keys the Space needs — you paste them in once
and never see them again. Gather these before continuing (links open in a
new tab):

1. **`HF_TOKEN`** — a Hugging Face token with **write** access, used to
   create your private backup dataset. Create one at
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   → **New token** → role **Write**.
2. **`TELEGRAM_BOT_TOKEN`** — open Telegram, message
   [`@BotFather`](https://t.me/BotFather), send `/newbot`, and follow the
   prompts. BotFather replies with a token like `123456:ABC-DEF...`.
3. **`TELEGRAM_ALLOWED_USERS`** — your own numeric Telegram user ID, so
   strangers can't message your bot. Message
   [`@userinfobot`](https://t.me/userinfobot) on Telegram and it replies
   with your ID. (Comma-separate multiple IDs if you want more than one
   person to have access.)
4. **`GATEWAY_TOKEN`** — a password you make up to protect your dashboard's
   Terminal and ENV Builder. Generate a strong random one with:
   ```bash
   openssl rand -hex 24
   ```
   No terminal handy? Any long random string works — for example, mash the
   keyboard for 20+ characters.
5. **`LLM_MODEL`** and **`LLM_API_KEY`** — which AI model your agent uses,
   and the API key for that provider. See
   [Choosing an LLM provider](#choosing-an-llm-provider) below — Google
   Gemini has a generous free tier and is the easiest first choice
   (`gemini-2.5-flash`).
6. *(Recommended)* **`CLOUDFLARE_WORKERS_TOKEN`** — keeps the free Space
   awake and fixes Telegram connectivity on restrictive networks. Create one
   at [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
   → **Create Token** → template **Edit Cloudflare Workers**.

### Step 3: Add the secrets to your Space

1. On your Space's page, click **Settings**.
2. Scroll to **Variables and secrets**.
3. Click **New secret** for each value collected in Step 2, using the exact
   names above (e.g. `HF_TOKEN`, `TELEGRAM_BOT_TOKEN`, ...).
4. Save each one — the Space restarts automatically after secrets change.

### Step 4: First boot

1. Open your Space and wait for the build to finish (a progress log streams
   on the page — this takes a couple of minutes the first time).
2. **Open it in its own browser tab** at
   `https://<your-username>-<space-name>.hf.space`, not the embedded preview
   on huggingface.co — some browsers block login cookies inside embedded
   pages. (The dashboard does this for you automatically if it detects it's
   embedded.)
3. The dashboard's status cards should turn green within a few seconds:
   **Gateway** (online), **Language Model** (ready), **Telegram**
   (configured), **State Backup** (synced), **Keep Awake** (active).
4. If any card shows a warning, click **Open Terminal**, unlock with your
   `GATEWAY_TOKEN`, and run `hermes config` or `hermes model` to finish
   configuration by hand — or check `data/hermes-setup.log`.

### Step 5: Talk to your agent

Open Telegram, find the bot you created with BotFather, and send it a
message. That's it — you now have your own free, self-hosted AI agent.

You can also click **Open Hermes Agent** on the dashboard to chat with it
directly in your browser, no Telegram required.

## Required secrets reference

| Secret | Description |
| --- | --- |
| `HF_TOKEN` | Hugging Face token (write access) — used for the automatic backup dataset. |
| `CLOUDFLARE_WORKERS_TOKEN` | Cloudflare API token with "Edit Cloudflare Workers" permission. The container uses this to auto-deploy a Worker on first boot that pings `/health` (keep-awake) and proxies Telegram's API. Also set `CLOUDFLARE_ACCOUNT_ID` (see optional variables below) for reliable deployment. |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs allowed to message the agent. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from `@BotFather`. |
| `GATEWAY_TOKEN` | Shared secret protecting the terminal, ENV Builder, and the `/v1/*` LLM relay. Use a long random string. |
| `LLM_MODEL` | Model identifier. See provider table below. |
| `LLM_API_KEY` | API key for the provider implied by `LLM_MODEL`. |

Anyone who later duplicates this Space will be prompted for the same list
of secret names (without values).

## Choosing an LLM provider

`LLM_MODEL` tells Hermes which model and provider to use; the prefix decides
which env var your `LLM_API_KEY` gets mapped to internally:

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

New to all this and just want something free and easy? Use
`LLM_MODEL=gemini-2.5-flash` and get an API key from
[Google AI Studio](https://aistudio.google.com/apikey) — no credit card
needed for the free tier.

For API key rotation, set `OPENROUTER_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`,
`GOOGLE_API_KEYS`, `DEEPSEEK_API_KEYS`, `XAI_API_KEYS`, or `NVIDIA_API_KEYS` to a
comma-separated list — the first key is promoted to the active singular var automatically.

## Optional settings

| Variable | Default | Description |
| --- | --- | --- |
| `STARTUP_APT_PACKAGES` | — | Space-separated apt packages to install on every boot. |
| `STARTUP_PIP_PACKAGES` | — | Space-separated pip packages to install on every boot. |
| `STARTUP_NPM_PACKAGES` | — | Space-separated npm packages to install on every boot. |
| `STARTUP_RUN` | — | Bash commands to run on every boot (use `STARTUP_RUN_BASE64` for multi-line). |
| `STARTUP_CAPTURE_DISABLE` | — | Set to `1` to disable the Terminal's auto-capture wrappers (apt/pip/npm/hermes installs are normally auto-appended to `data/startup.sh` for replay on next boot). |
| `SYNC_INTERVAL` | `600` | Backup check frequency in seconds. Files are only uploaded when something actually changed since the last check (cheap metadata check first, full content hash to confirm). |
| `BACKUP_DATASET_NAME` | `hermes-backup` | Dataset name for backups (owner is auto-detected from `HF_TOKEN`). |
| `SYNC_MAX_FILE_BYTES` | `52428800` (50MB) | Skip any single file larger than this when backing up, so one oversized cache/log file can't bloat every backup. |
| `CLOUDFLARE_ACCOUNT_ID` | — | Your Cloudflare account ID (Cloudflare dashboard → Workers & Pages → right sidebar). The container will try to auto-detect it from your token, but setting it explicitly is more reliable if your token can see multiple accounts. |
| `CLOUDFLARE_KEEPALIVE_ENABLED` | `true` | Set to `false` to deploy the Worker (for Telegram proxy) without the keep-awake cron. |
| `GATEWAY_RESTART_DELAY` | `5` | Seconds to wait between gateway restarts. |
| `GATEWAY_MAX_RESTARTS` | `0` | Max gateway restart attempts (0 = unlimited). |
| `WEBHOOK_URL` | — | URL to POST to on each gateway restart (JSON body with `event` and `space`). |
| `TELEGRAM_MODE` | — | Set to `webhook` to use inbound webhook delivery instead of long-polling. |

## Frequently asked questions

**Is this really free?**
Yes — Hugging Face's CPU basic tier, Telegram, and Cloudflare Workers'
free tier all have no-cost plans that comfortably cover one personal agent.
The only variable cost is your chosen LLM provider, and several
(Google Gemini, OpenRouter's free models, Hugging Face Inference) have free
tiers too.

**Do I need to know how to code?**
No. Every step is done by pasting values into Hugging Face's secrets form
and clicking buttons on the dashboard. The in-browser Terminal is there if
you ever want to go further, but it's optional.

**Will my free Space go to sleep?**
Free Hugging Face Spaces normally sleep after inactivity. Setting
`CLOUDFLARE_WORKERS_TOKEN` (Step 2.6 above) deploys a Worker that pings the
Space every 10 minutes so it never goes idle — automatic, no extra setup
once the secret is set.

**Is my data private?**
Your agent's state backs up to a **private** Hugging Face dataset under
your own account, readable only by you. Secret files (`.env`, credentials)
are explicitly excluded from every backup.

**Can I use a different LLM later?**
Yes — change `LLM_MODEL`/`LLM_API_KEY` in Settings → Variables and secrets
and restart the Space, or use the in-dashboard **ENV Builder**. No
redeploy needed.

**Can more than one person use the bot?**
Yes — add more comma-separated IDs to `TELEGRAM_ALLOWED_USERS`.

## Troubleshooting

**Telegram bot not connecting / dashboard shows "Offline"**

Some networks (including some Hugging Face Spaces) block outbound
connections to Telegram's API, so long-polling never establishes even
though everything is configured correctly. **Open Terminal** →
`tail -n 60 /var/log/supervisor/gateway.log` would show `connect timed out`
errors to `api.telegram.org` in that case.

Setting `CLOUDFLARE_WORKERS_TOKEN` fixes this automatically: the container
reverse-proxies Telegram's API through your Cloudflare Worker, which isn't
subject to the same restriction. The **Telegram** card on the dashboard
shows "Long-polling via Cloudflare Worker proxy" once this is active.

If the Telegram card instead shows a proxy error, check
`data/cloudflare-setup.log` — the most common cause is that your Cloudflare
account doesn't have a `workers.dev` subdomain yet. Claim one once at
Cloudflare dashboard → Workers & Pages → "Set up a subdomain", then restart
the Space.

As a last resort, `TELEGRAM_MODE=webhook` switches the gateway to inbound
delivery via `https://<this-space>.hf.space/telegram-webhook` instead of
polling — but registering the webhook and sending replies are still
outbound calls to Telegram's API, so this only helps if the Cloudflare
proxy above isn't an option.

**Login doesn't stick on the Terminal / ENV Builder**

Open the Space in its own browser tab
(`https://<owner>-<space>.hf.space`), not the embedded view on
huggingface.co — some browsers block cookies in embedded iframes. The login
page detects this and redirects you automatically; if it can't, use the
"Open in new tab" link it shows.

**A status card shows a warning after first boot**

Click **Open Terminal**, unlock with your `GATEWAY_TOKEN`, and run
`hermes config` or `hermes model` to finish configuration interactively, or
check `data/hermes-setup.log` for what failed.

## How backups work

Every `SYNC_INTERVAL` seconds (default 600 = 10 minutes), the Space checks
whether anything in `~/.hermes` changed since the last check (a cheap
metadata check first, a full content hash to confirm) and, only if so,
mirrors the changed files into a private dataset
`<your-hf-username>/hermes-backup` — one file per file, no tarball, so the
dataset's size stays bounded to the size of `~/.hermes` itself instead of
growing with every sync. Secret files (`.env`, credentials) are always
excluded. Override the dataset name with `BACKUP_DATASET_NAME`.

## Repository layout

```
Dockerfile                 Container image (Hermes Agent + dashboard app)
supervisord.conf           Runs the web app and the Hermes gateway
app/                        FastAPI dashboard, gateway proxy, terminal, ENV Builder, backups
scripts/                    Install + runtime configuration scripts
cloudflare/                 Manual/advanced Cloudflare Worker (Telegram webhook proxy, keep-awake fallback)
.github/workflows/          Sync to Hugging Face
```

## For maintainers: keeping your own fork in sync

This section is only relevant if you're maintaining your **own GitHub
fork** of this project that auto-deploys to your own Space on every push —
not needed if you just duplicated the Space directly on Hugging Face.

The workflow in `.github/workflows/sync-to-hf.yml` pushes this repo to
your Space on every push to `main`:

1. Create a Hugging Face token with **write** access (can be the same
   token as `HF_TOKEN` above, or a separate one).
2. In your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret** → name it `HF_TOKEN`, paste the token.
3. If your target Space has a different owner/name, edit `HF_SPACE` in
   `.github/workflows/sync-to-hf.yml`.
4. Push to `main` (or run the workflow manually from the **Actions** tab).

---

Built on [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
