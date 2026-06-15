# Setup guide

## 1. Create the Hugging Face Space

1. On Hugging Face, create a new Space: **Docker** SDK, free CPU hardware.
2. Note its owner/name, e.g. `itanvirt/hf_hermes` — you'll need this for
   the sync workflow and the Cloudflare Worker config.

## 2. Add Space secrets

Settings → Variables and secrets → **New secret** for each of:

- `HF_TOKEN` — create one at https://huggingface.co/settings/tokens with
  **write** access (needed to create/update the `hermes-backup` dataset).
- `CLOUDFLARE_WORKERS_TOKEN` — Cloudflare API token with "Edit Cloudflare
  Workers" permission. On first boot, the container uses this to
  automatically deploy a tiny Worker that pings this Space's `/health`
  endpoint every 10 minutes, so the free tier doesn't go to sleep — no
  further setup (see step 5).
- `TELEGRAM_ALLOWED_USERS` — your Telegram numeric user ID(s),
  comma-separated. Get yours from `@userinfobot` on Telegram.
- `TELEGRAM_BOT_TOKEN` — from `@BotFather` (`/newbot`).
- `GATEWAY_TOKEN` — generate with `openssl rand -hex 24`.
- `LLM_MODEL` — e.g. `gemini-2.5-flash` (Gemini has a free tier).
- `LLM_API_KEY` — API key matching `LLM_MODEL`'s provider.

Anyone who later duplicates this Space will be prompted for the same list
of secret names (without values).

## 3. Sync this GitHub repo to the Space

The workflow in `.github/workflows/sync-to-hf.yml` pushes this repo to
`huggingface.co/spaces/itanvirt/hf_hermes` on every push to `main`.

1. Create a Hugging Face token with **write** access (can be the same
   token as `HF_TOKEN` above, or a separate one).
2. In the GitHub repo: Settings → Secrets and variables → Actions →
   **New repository secret** → name it `HF_TOKEN`, paste the token.
3. If your target Space has a different owner/name, edit `HF_SPACE` in
   `.github/workflows/sync-to-hf.yml`.
4. Push to `main` (or run the workflow manually from the Actions tab).

## 4. First boot

- Open the Space. The dashboard shows live status for the gateway, model,
  runtime, Telegram, backup and keep-awake.
- Click **Open Terminal** or **ENV Builder**, and unlock with the
  `GATEWAY_TOKEN` value you set in step 2.
- Before configuring Hermes, the container deploys the Cloudflare Worker
  from step 5 (if `CLOUDFLARE_WORKERS_TOKEN` is set) and, when a
  `TELEGRAM_BOT_TOKEN` is configured, points Hermes's Telegram client at
  that Worker's `/bot` proxy instead of `api.telegram.org` directly.
- The container then writes your `LLM_MODEL` / `LLM_API_KEY` and Telegram
  secrets into `~/.hermes/.env` and runs `hermes config set` to select the
  model, provider, and (if proxied) the Telegram API base URL. The gateway
  then starts with `hermes gateway run` (long-polling) — your bot should
  come online within seconds of the Space starting. If anything looks off,
  check `data/hermes-setup.log` or finish configuration from **Open Hermes
  Agent** or **Open Terminal** (`hermes config`, `hermes model`), then click
  **Restart agent** in ENV Builder.

### Troubleshooting: Telegram bot not connecting

Some networks (including some Hugging Face Spaces) block outbound
connections to Telegram's API, so long-polling never establishes even
though everything is configured correctly — the gateway logs (**Open
Terminal** → `tail -n 60 /var/log/supervisor/gateway.log`) would show
`connect timed out` errors to `api.telegram.org`.

Setting `CLOUDFLARE_WORKERS_TOKEN` (step 5) fixes this automatically: the
container reverse-proxies Telegram's API through your Cloudflare Worker,
which isn't subject to the same restriction. The **Telegram** card on the
dashboard shows "Long-polling via Cloudflare Worker proxy" once this is
active.

If the Telegram card instead shows a proxy error, check
`data/cloudflare-setup.log` — the most common cause is that your
Cloudflare account doesn't have a `workers.dev` subdomain yet. Claim one
once at Cloudflare dashboard → Workers & Pages → "Set up a subdomain", then
restart the Space.

As a last resort, `TELEGRAM_MODE=webhook` switches the gateway to inbound
delivery via `https://<this-space>.hf.space/telegram-webhook` instead of
polling — but registering the webhook and sending replies are still
outbound calls to Telegram's API, so this only helps if the Cloudflare
proxy above isn't an option.

## 5. Keep-awake & Telegram proxy (automatic)

If you set `CLOUDFLARE_WORKERS_TOKEN` in step 2, the container deploys a
Cloudflare Worker on every boot that:

- pings this Space's `/health` endpoint every 10 minutes, so the free tier
  doesn't go to sleep, and
- reverse-proxies Telegram's Bot API (`api.telegram.org`), which Hermes
  uses automatically if `TELEGRAM_BOT_TOKEN` is set (see step 4).

Nothing more to do — check the **Keep Awake** and **Telegram** cards on the
dashboard to confirm it deployed (or `data/cloudflare-setup.log` if either
shows an error).

The Worker is created under the first account your token can see. If your
token has access to multiple Cloudflare accounts, set the
`CLOUDFLARE_ACCOUNT_ID` secret too (Cloudflare dashboard → Workers & Pages →
Account ID, right sidebar).

`cloudflare/` also has a standalone copy of this Worker for manual
deployment (`npx wrangler deploy`), plus an optional Telegram webhook proxy
mode — see `cloudflare/README.md`. You generally don't need it.

## 6. Backups

Every `BACKUP_INTERVAL_HOURS` (default 6), the Space tars `~/.hermes`
(excluding secret files) and uploads it to a private dataset
`<your-hf-username>/hermes-backup`. Override the target with the
`BACKUP_DATASET_REPO` env var if you want a different repo name.
