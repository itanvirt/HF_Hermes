import os
import subprocess
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, backup, status, terminal

APP_DIR = Path(__file__).resolve().parent
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8642"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_ENV_FILE = HERMES_HOME / ".env"
TELEGRAM_WEBHOOK_PATH = os.environ.get("HERMES_TELEGRAM_WEBHOOK_PATH", "/telegram-webhook")


def _read_hermes_env_var(name: str) -> str:
    # configure_hermes.sh may generate TELEGRAM_WEBHOOK_SECRET itself (when
    # not provided as a Space secret) and only write it to ~/.hermes/.env,
    # not the process environment - so check both.
    if not HERMES_ENV_FILE.exists():
        return ""
    for line in HERMES_ENV_FILE.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or _read_hermes_env_var("TELEGRAM_WEBHOOK_SECRET")

app = FastAPI(title="Hermes Agent")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def on_startup() -> None:
    backup.start_scheduler(scheduler)
    scheduler.start()


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    data = await status.full_status()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": os.environ.get("SPACE_TITLE", "Hermes Agent"),
            "subtitle": "SELF-HOSTED · HERMES AGENT",
            "status": data,
            "authenticated": auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)),
            "owner": os.environ.get("SPACE_OWNER", ""),
        },
    )


@app.get("/api/status")
async def api_status():
    return await status.full_status()


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": next, "configured": auth.gateway_token_configured(), "error": None},
    )


@app.post("/login")
async def login(request: Request, token: str = Form(...), next: str = Form("/")):
    if not auth.verify_token(token):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": next, "configured": auth.gateway_token_configured(), "error": "Invalid token"},
            status_code=401,
        )
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_session_cookie(),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie(auth.COOKIE_NAME)
    return response


def _require_session(request: Request) -> RedirectResponse | None:
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return RedirectResponse(url=f"/login?next={request.url.path}")
    return None


# --------------------------------------------------------------------------
# Terminal / Hermes Agent TUI
# --------------------------------------------------------------------------
@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "terminal.html", {"request": request, "ws_path": "/ws/terminal", "page_title": "Terminal"}
    )


@app.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "terminal.html", {"request": request, "ws_path": "/ws/agent", "page_title": "Hermes Agent"}
    )


@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    if not auth.verify_session_cookie(websocket.cookies.get(auth.COOKIE_NAME)):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    shell = os.environ.get("SHELL", "/bin/bash")
    await terminal.run_pty(websocket, [shell], cwd=str(Path.home()))


@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    if not auth.verify_session_cookie(websocket.cookies.get(auth.COOKIE_NAME)):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    if shutil_which("hermes"):
        argv = ["hermes"]
    else:
        argv = [os.environ.get("SHELL", "/bin/bash"), "-c", "echo 'hermes CLI not found on PATH'; exec bash"]
    await terminal.run_pty(websocket, argv, cwd=str(Path.home()))


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


# --------------------------------------------------------------------------
# ENV Builder
# --------------------------------------------------------------------------
REQUIRED_SECRETS = [
    "HF_TOKEN",
    "CLOUDFLARE_WORKERS_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_BOT_TOKEN",
    "GATEWAY_TOKEN",
    "LLM_MODEL",
    "LLM_API_KEY",
]


@app.get("/env-builder", response_class=HTMLResponse)
async def env_builder_page(request: Request, message: str = ""):
    redirect = _require_session(request)
    if redirect:
        return redirect
    secrets_state = [{"name": name, "set": bool(os.environ.get(name))} for name in REQUIRED_SECRETS]
    env_contents = HERMES_ENV_FILE.read_text() if HERMES_ENV_FILE.exists() else ""
    return templates.TemplateResponse(
        "env_builder.html",
        {
            "request": request,
            "secrets_state": secrets_state,
            "env_contents": env_contents,
            "env_path": str(HERMES_ENV_FILE),
            "message": message,
        },
    )


@app.post("/env-builder/save")
async def env_builder_save(request: Request, env_contents: str = Form(...)):
    redirect = _require_session(request)
    if redirect:
        return redirect
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    HERMES_ENV_FILE.write_text(env_contents)
    HERMES_ENV_FILE.chmod(0o600)
    return RedirectResponse(url="/env-builder?message=Saved", status_code=302)


@app.post("/env-builder/reconfigure")
async def env_builder_reconfigure(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    subprocess.run(["bash", "/home/user/app/scripts/configure_hermes.sh"], check=False)
    return RedirectResponse(url="/env-builder?message=Reconfigured", status_code=302)


@app.post("/env-builder/restart")
async def env_builder_restart(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    subprocess.run(["supervisorctl", "restart", "hermes-gateway"], check=False)
    return RedirectResponse(url="/env-builder?message=Restarted", status_code=302)


# --------------------------------------------------------------------------
# Gateway reverse proxy (Bearer GATEWAY_TOKEN required)
#
# By default `hermes gateway run` talks to Telegram via long-polling and
# opens no port, so these routes have nothing to proxy to. They become
# useful in webhook mode (TELEGRAM_MODE=webhook, see configure_hermes.sh),
# where hermes listens on GATEWAY_PORT for Telegram updates.
# --------------------------------------------------------------------------
@app.api_route("/gateway/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def gateway_proxy(path: str, request: Request):
    if not auth.verify_bearer(request.headers.get("authorization")):
        return PlainTextResponse("unauthorized", status_code=401)
    return await _proxy_to_gateway(f"/{path}", request)


# --------------------------------------------------------------------------
# Telegram webhook (TELEGRAM_MODE=webhook)
#
# Telegram itself authenticates with the X-Telegram-Bot-Api-Secret-Token
# header (TELEGRAM_WEBHOOK_SECRET). The Bearer GATEWAY_TOKEN path is for the
# optional Cloudflare Worker proxy, which can't forward Telegram's header.
# --------------------------------------------------------------------------
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    telegram_secret = request.headers.get("x-telegram-bot-api-secret-token")
    authorized = (
        bool(TELEGRAM_WEBHOOK_SECRET) and telegram_secret == TELEGRAM_WEBHOOK_SECRET
    ) or auth.verify_bearer(request.headers.get("authorization"))
    if not authorized:
        return PlainTextResponse("unauthorized", status_code=401)
    return await _proxy_to_gateway(TELEGRAM_WEBHOOK_PATH, request, body_override=await request.body())


async def _proxy_to_gateway(path: str, request: Request, body_override: bytes | None = None) -> Response:
    body = body_override if body_override is not None else await request.body()
    url = f"http://127.0.0.1:{GATEWAY_PORT}{path}"
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    telegram_secret = request.headers.get("x-telegram-bot-api-secret-token")
    if telegram_secret:
        headers["x-telegram-bot-api-secret-token"] = telegram_secret
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.request(
                request.method,
                url,
                params=dict(request.query_params),
                content=body,
                headers=headers,
            )
    except httpx.ConnectError:
        return PlainTextResponse("gateway unavailable", status_code=503)
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))
