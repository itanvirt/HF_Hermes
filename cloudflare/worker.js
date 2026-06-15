/**
 * Hermes Agent companion Cloudflare Worker.
 *
 * Jobs:
 *  1. Telegram Bot API proxy - forwards /bot* and /file/bot* requests to
 *     api.telegram.org, so Hermes can reach Telegram even on networks that
 *     block it directly. Point Hermes at this with `hermes config set
 *     platforms.telegram.extra.base_url https://<worker>/bot` (and
 *     base_file_url with /file/bot).
 *  2. Telegram webhook proxy - Telegram posts updates here; the worker
 *     checks the secret token Telegram sends, then forwards the update to
 *     the Hugging Face Space with the gateway's bearer token attached
 *     (Telegram itself cannot send custom Authorization headers).
 *  3. Keep-awake cron - on a schedule, pings the Space's /health endpoint
 *     so free-tier Spaces don't go to sleep from inactivity.
 *
 * Required secrets (set with `wrangler secret put <NAME>`):
 *   SPACE_URL                e.g. https://itanvirt-hf-hermes.hf.space
 *   GATEWAY_TOKEN            same value as the Space's GATEWAY_TOKEN secret
 *   TELEGRAM_WEBHOOK_SECRET  random string, also passed to Telegram's
 *                            setWebhook as `secret_token`
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("ok", { status: 200 });
    }

    if (url.pathname.startsWith("/bot") || url.pathname.startsWith("/file/bot")) {
      url.protocol = "https:";
      url.hostname = "api.telegram.org";
      url.port = "";
      return fetch(url.toString(), request);
    }

    if (url.pathname === "/telegram" && request.method === "POST") {
      const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (!env.TELEGRAM_WEBHOOK_SECRET || secret !== env.TELEGRAM_WEBHOOK_SECRET) {
        return new Response("unauthorized", { status: 401 });
      }

      const body = await request.text();
      const upstream = await fetch(`${env.SPACE_URL}/telegram-webhook`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${env.GATEWAY_TOKEN}`,
        },
        body,
      });

      return new Response(await upstream.text(), { status: upstream.status });
    }

    return new Response("not found", { status: 404 });
  },

  async scheduled(event, env, ctx) {
    if (!env.SPACE_URL) return;
    ctx.waitUntil(fetch(`${env.SPACE_URL}/health`).catch(() => {}));
  },
};
