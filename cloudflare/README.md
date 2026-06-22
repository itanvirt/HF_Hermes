# Cloudflare Worker (manual / advanced)

**You probably don't need this.** If you set the `CLOUDFLARE_WORKERS_TOKEN`
Space secret, the container automatically deploys an equivalent Worker on
every boot (see `scripts/configure_cloudflare.sh` and the **Keep Awake** /
**Telegram** cards on the dashboard) — zero manual steps. This standalone
copy is useful if that auto-deploy fails, or if you want the optional
Telegram webhook proxy:

1. **Keep-awake**: pings `/health` on a cron schedule so a free-tier Space
   stays awake.
2. **Telegram Bot API proxy**: forwards `/bot*` and `/file/bot*` to
   `api.telegram.org`, so Hermes's Telegram client (long-polling by default)
   can reach Telegram even on networks that block it directly. The
   auto-deployed Worker configures this for you; with this standalone copy
   you'd point Hermes at it yourself (`hermes config set
   platforms.telegram.extra.base_url`, see below).
3. **Telegram webhook proxy (optional/advanced)**: if you've manually
   switched Hermes to webhook mode (`TELEGRAM_WEBHOOK_URL` /
   `TELEGRAM_WEBHOOK_PORT`, see the Hermes Agent docs) instead of the
   default long-polling, this proxies Telegram's webhook updates to the
   Space, attaching the `GATEWAY_TOKEN` bearer header that Telegram itself
   can't send. Not needed for the default setup.

## Prerequisites

- [Node.js](https://nodejs.org/) and `npx` available locally.
- A Cloudflare account and an API token with **Edit Cloudflare Workers**
  permission (this is the value you put in the `CLOUDFLARE_WORKERS_TOKEN`
  Space secret).

## Deploy

```bash
cd cloudflare
export CLOUDFLARE_API_TOKEN=<your CLOUDFLARE_WORKERS_TOKEN value>
npx wrangler deploy
```

This publishes the worker to
`https://hermes-agent-proxy.<your-subdomain>.workers.dev`.

## Configure secrets

```bash
npx wrangler secret put SPACE_URL
# -> https://<owner>-<space>.hf.space   (no trailing slash)
```

The `GATEWAY_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` secrets are only needed if
you're using the optional Telegram webhook proxy below.

```bash
npx wrangler secret put GATEWAY_TOKEN
# -> same value as the Space's GATEWAY_TOKEN secret

npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
# -> any random string, e.g. `openssl rand -hex 20`
```

## (Optional) Point Hermes's Telegram client at the worker's API proxy

```bash
hermes config set platforms.telegram.extra.base_url "https://hermes-agent-proxy.<your-subdomain>.workers.dev/bot"
hermes config set platforms.telegram.extra.base_file_url "https://hermes-agent-proxy.<your-subdomain>.workers.dev/file/bot"
```

Run from **Open Terminal** on the Space, then restart the gateway. The
auto-deployed Worker does this for you automatically.

## (Optional) Point Telegram at the worker for webhook mode

Only needed if you've configured Hermes for webhook mode instead of the
default long-polling. Register the webhook with Telegram, using the same
`TELEGRAM_WEBHOOK_SECRET` value as the `secret_token`:

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://hermes-agent-proxy.<your-subdomain>.workers.dev/telegram" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

## Verify keep-awake

The cron trigger runs every 12 hours (edit `wrangler.toml` to change the
schedule) and calls `${SPACE_URL}/health`. You can trigger it manually for
testing:

```bash
npx wrangler tail        # in one terminal, to watch logs
curl https://hermes-agent-proxy.<your-subdomain>.workers.dev/health
```
