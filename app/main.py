import json
import mimetypes
import os
import platform
import re
import subprocess
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, backup, status, terminal

APP_DIR = Path(__file__).resolve().parent
GATEWAY_PORT    = int(os.environ.get("GATEWAY_PORT", "8642"))
DASHBOARD_PORT  = int(os.environ.get("DASHBOARD_PORT", "9119"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_ENV_FILE = HERMES_HOME / ".env"
TELEGRAM_WEBHOOK_PATH = os.environ.get("HERMES_TELEGRAM_WEBHOOK_PATH", "/telegram-webhook")
SPACE_HOST = os.environ.get("SPACE_HOST", "")


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

# Provider API bases for the /v1/* relay. The active provider and its key are
# read from ~/.hermes/.env (written by configure_hermes.sh on every boot).
_PROVIDER_API_BASE = {
    "google": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "openrouter": "https://openrouter.ai/api",
    "deepseek": "https://api.deepseek.com",
    "xai": "https://api.x.ai",
    "nvidia": "https://integrate.api.nvidia.com",
    "huggingface": "https://router.huggingface.co",
}
_PROVIDER_KEY_VAR = {
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "huggingface": "HF_INFERENCE_TOKEN",
}

# --------------------------------------------------------------------------
# Files browser — root and path guard
# --------------------------------------------------------------------------
FILES_ROOT = Path("/home/user").resolve()

LOG_FILES = {
    "gateway":     "/var/log/supervisor/gateway.log",
    "web":         "/var/log/supervisor/web.log",
    "supervisor":  "/var/log/supervisor/supervisord.log",
    "dashboard":   "/var/log/supervisor/dashboard.log",
    "startup":     "/home/user/app/data/startup.log",
    "hermes-setup":"/home/user/app/data/hermes-setup.log",
    "cloudflare":  "/home/user/app/data/cloudflare-setup.log",
    "restore":     "/home/user/app/data/hermes-restore.log",
}


def _safe_path(requested: str) -> Path | None:
    """Return path only if it resolves inside FILES_ROOT (prevents traversal)."""
    try:
        p = FILES_ROOT.joinpath(requested.lstrip("/")).resolve()
        return p if str(p).startswith(str(FILES_ROOT)) else None
    except Exception:
        return None


def _proc_mem() -> dict:
    mem: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
    except Exception:
        pass
    total = mem.get("MemTotal", 0) * 1024
    avail = mem.get("MemAvailable", 0) * 1024
    used  = total - avail
    return {"total": total, "used": used, "available": avail,
            "pct": round(used / total * 100, 1) if total else 0}


def _proc_load() -> dict:
    try:
        parts = Path("/proc/loadavg").read_text().split()
        return {"1m": parts[0], "5m": parts[1], "15m": parts[2]}
    except Exception:
        return {"1m": "?", "5m": "?", "15m": "?"}


def _proc_uptime() -> str:
    try:
        secs = float(Path("/proc/uptime").read_text().split()[0])
        h, rem = divmod(int(secs), 3600)
        m, s   = divmod(rem, 60)
        return f"{h}h {m}m {s}s"
    except Exception:
        return "?"


def _active_llm_upstream() -> tuple[str, str]:
    provider = _read_hermes_env_var("HERMES_PROVIDER") or "openrouter"
    key_var = _PROVIDER_KEY_VAR.get(provider, "OPENROUTER_API_KEY")
    key = os.environ.get(key_var) or _read_hermes_env_var(key_var)
    base = _PROVIDER_API_BASE.get(provider, "https://openrouter.ai/api")
    return base, key


app = FastAPI(title="Hermes Agent")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

_NO_CACHE = "no-cache, no-store, must-revalidate"


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "text/html" in ct:
        response.headers["cache-control"] = _NO_CACHE
        response.headers["pragma"] = "no-cache"
    return response

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
        {
            "request": request,
            "next": next,
            "configured": auth.gateway_token_configured(),
            "error": None,
            "space_host": SPACE_HOST,
        },
    )


@app.post("/login")
async def login(request: Request, token: str = Form(...), next: str = Form("/")):
    if not auth.verify_token(token):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "next": next,
                "configured": auth.gateway_token_configured(),
                "error": "Invalid token",
                "space_host": SPACE_HOST,
            },
            status_code=401,
        )
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_session_cookie(),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="none",
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
# Agent chat UI (public — auth via Bearer token stored in localStorage)
# --------------------------------------------------------------------------
@app.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request):
    data = await status.full_status()
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "model": data["model"]["model"],
            "space_host": SPACE_HOST,
        },
    )


# --------------------------------------------------------------------------
# Terminal (session cookie required)
# --------------------------------------------------------------------------
@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "terminal.html", {"request": request, "ws_path": "/ws/terminal", "page_title": "Terminal"}
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
# OpenAI-compatible LLM relay (Bearer GATEWAY_TOKEN required)
#
# Forwards /v1/* to the configured LLM provider's API, substituting your
# real API key. Supports streaming (text/event-stream) when the request
# body contains "stream": true.
# --------------------------------------------------------------------------
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def v1_relay(path: str, request: Request):
    if not auth.verify_bearer(request.headers.get("authorization")):
        return PlainTextResponse("unauthorized", status_code=401)
    base_url, api_key = _active_llm_upstream()
    upstream_url = f"{base_url}/v1/{path}"
    body = await request.body()
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "authorization", "content-length"}
    }
    if api_key:
        forward_headers["authorization"] = f"Bearer {api_key}"

    # Detect streaming request
    streaming = False
    if body:
        try:
            streaming = bool(json.loads(body).get("stream", False))
        except Exception:
            pass

    if streaming:
        async def _stream():
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        request.method,
                        upstream_url,
                        params=dict(request.query_params),
                        content=body,
                        headers=forward_headers,
                    ) as upstream:
                        async for chunk in upstream.aiter_bytes():
                            yield chunk
            except httpx.ConnectError:
                yield b"data: {\"error\":{\"message\":\"upstream LLM API unavailable\"}}\n\ndata: [DONE]\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                params=dict(request.query_params),
                content=body,
                headers=forward_headers,
            )
    except httpx.ConnectError:
        return PlainTextResponse("upstream LLM API unavailable", status_code=503)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


# --------------------------------------------------------------------------
# Gateway reverse proxy (Bearer GATEWAY_TOKEN required)
# --------------------------------------------------------------------------
@app.api_route("/gateway/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def gateway_proxy(path: str, request: Request):
    if not auth.verify_bearer(request.headers.get("authorization")):
        return PlainTextResponse("unauthorized", status_code=401)
    return await _proxy_to_gateway(f"/{path}", request)


# --------------------------------------------------------------------------
# Telegram webhook (TELEGRAM_MODE=webhook)
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


# --------------------------------------------------------------------------
# Logs viewer
# --------------------------------------------------------------------------
@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("logs.html", {"request": request})


@app.get("/api/logs")
async def api_logs(request: Request, file: str = "gateway", lines: int = 100):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    path = LOG_FILES.get(file)
    if not path:
        return JSONResponse({"error": "unknown log file", "content": ""})
    p = Path(path)
    if not p.exists():
        return JSONResponse({"content": f"[{path} not found — file may not exist yet]",
                             "file": file, "total_lines": 0})
    try:
        text = p.read_text(errors="replace")
        all_lines = text.splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return JSONResponse({"content": "\n".join(tail), "file": file,
                             "total_lines": len(all_lines)})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "content": ""})


# --------------------------------------------------------------------------
# System info + gateway controls + model switcher
# --------------------------------------------------------------------------
@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, message: str = ""):
    redirect = _require_session(request)
    if redirect:
        return redirect
    current_model    = _read_hermes_env_var("LLM_MODEL") or os.environ.get("LLM_MODEL", "")
    current_provider = _read_hermes_env_var("HERMES_PROVIDER") or "openrouter"
    return templates.TemplateResponse("system.html", {
        "request": request,
        "model":    current_model,
        "provider": current_provider,
        "message":  message,
    })


@app.get("/api/system")
async def api_system(request: Request):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import shutil as _shutil
    disk     = _shutil.disk_usage("/home/user")
    mem      = _proc_mem()
    load     = _proc_load()
    uptime   = _proc_uptime()
    try:
        r = subprocess.run(["pgrep", "-f", "hermes gateway"], capture_output=True, text=True)
        gw_pid = r.stdout.strip().split("\n")[0] if r.stdout.strip() else None
    except Exception:
        gw_pid = None
    try:
        r = subprocess.run(["hermes", "--version"], capture_output=True, text=True, timeout=3)
        hv = (r.stdout.strip() or r.stderr.strip()).split("\n")[0][:40]
    except Exception:
        hv = "unknown"
    return JSONResponse({
        "os":       platform.platform()[:60],
        "arch":     platform.machine(),
        "python":   platform.python_version(),
        "hostname": platform.node(),
        "cpu_count":os.cpu_count(),
        "hermes_version": hv,
        "memory":   mem,
        "disk":     {"total": disk.total, "used": disk.used, "free": disk.free,
                     "pct": round(disk.used / disk.total * 100, 1) if disk.total else 0},
        "load":     load,
        "uptime":   uptime,
        "gateway_pid":     gw_pid,
        "gateway_running": bool(gw_pid),
    })


@app.post("/api/gateway/start")
async def gateway_start(request: Request):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    subprocess.run(["supervisorctl", "start", "hermes-gateway"], check=False)
    return JSONResponse({"ok": True})


@app.post("/api/gateway/stop")
async def gateway_stop(request: Request):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    subprocess.run(["supervisorctl", "stop", "hermes-gateway"], check=False)
    return JSONResponse({"ok": True})


@app.post("/api/models/switch")
async def models_switch(
    request: Request,
    model:   str = Form(...),
    api_key: str = Form(""),
    provider: str = Form(""),
):
    redirect = _require_session(request)
    if redirect:
        return redirect
    env_dict: dict[str, str] = {}
    if HERMES_ENV_FILE.exists():
        for line in HERMES_ENV_FILE.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env_dict[k.strip()] = v.strip()
    if model:
        env_dict["LLM_MODEL"] = model
        # Auto-detect provider from model name if not supplied
        if not provider:
            if model.startswith(("gemini", "google/")):
                provider = "google"
            elif model.startswith(("gpt-", "openai/")):
                provider = "openai"
            elif model.startswith(("claude", "anthropic/")):
                provider = "anthropic"
            elif model.startswith("deepseek/"):
                provider = "deepseek"
            elif model.startswith(("xai/", "grok")):
                provider = "xai"
            elif model.startswith("nvidia/"):
                provider = "nvidia"
            elif model.startswith(("hf/", "huggingface/")):
                provider = "huggingface"
            else:
                provider = "openrouter"
        env_dict["HERMES_PROVIDER"] = provider
    if api_key:
        key_var = _PROVIDER_KEY_VAR.get(provider or "openrouter", "OPENROUTER_API_KEY")
        env_dict[key_var] = api_key
        env_dict["LLM_API_KEY"] = api_key
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    HERMES_ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in env_dict.items()) + "\n")
    HERMES_ENV_FILE.chmod(0o600)
    subprocess.run(["supervisorctl", "restart", "hermes-gateway"], check=False)
    return RedirectResponse(url="/system?message=Model+updated+%E2%80%94+gateway+restarted", status_code=302)


# --------------------------------------------------------------------------
# Files browser
# --------------------------------------------------------------------------
@app.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("files.html", {"request": request})


@app.get("/api/files/list")
async def api_files_list(request: Request, path: str = ""):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    target = _safe_path(path) if path else FILES_ROOT
    if not target or not target.exists() or not target.is_dir():
        return JSONResponse({"error": "not a directory", "items": []})
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
                items.append({
                    "name":   entry.name,
                    "path":   str(entry.relative_to(FILES_ROOT)),
                    "is_dir": entry.is_dir(),
                    "size":   st.st_size if entry.is_file() else None,
                    "mtime":  st.st_mtime,
                })
            except OSError:
                pass
    except PermissionError as exc:
        return JSONResponse({"error": str(exc), "items": []})
    rel = str(target.relative_to(FILES_ROOT)) if target != FILES_ROOT else ""
    return JSONResponse({"path": rel, "items": items})


@app.post("/api/files/upload")
async def api_files_upload(
    request: Request,
    path:    str        = Form(""),
    file:    UploadFile = File(...),
):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    target_dir = (_safe_path(path) if path else FILES_ROOT) or FILES_ROOT
    if not target_dir.is_dir():
        return JSONResponse({"error": "invalid directory"})
    dest    = target_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return JSONResponse({"ok": True, "path": str(dest.relative_to(FILES_ROOT))})


@app.post("/api/files/mkdir")
async def api_files_mkdir(request: Request, path: str = Form(...)):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    target = _safe_path(path)
    if not target:
        return JSONResponse({"error": "invalid path"})
    target.mkdir(parents=True, exist_ok=True)
    return JSONResponse({"ok": True})


@app.get("/api/files/download")
async def api_files_download(request: Request, path: str):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return PlainTextResponse("unauthorized", status_code=401)
    target = _safe_path(path)
    if not target or not target.is_file():
        return PlainTextResponse("not found", status_code=404)
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(
        content=target.read_bytes(),
        media_type=ctype,
        headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
    )


# --------------------------------------------------------------------------
# Hermes built-in dashboard proxy  (/hermes/*)
#
# Proxies to the hermes-dashboard supervisor process on DASHBOARD_PORT (9119).
# Requires session cookie so the dashboard isn't publicly accessible.
# Injects window.__HERMES_BASE_PATH__ into every HTML response so the SPA
# prefixes all its internal routes and API calls with /hermes.
# --------------------------------------------------------------------------
_DASH_STRIP_HEADERS = {"host", "content-length", "transfer-encoding", "content-encoding"}


@app.get("/hermes", include_in_schema=False)
async def hermes_root_redirect():
    return RedirectResponse(url="/hermes/")


@app.api_route("/hermes/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def hermes_proxy(path: str, request: Request):
    if not auth.verify_session_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return RedirectResponse(url=f"/login?next=/hermes/")

    upstream_url = f"http://127.0.0.1:{DASHBOARD_PORT}/{path}"
    body = await request.body()
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length"}
    }

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            upstream = await client.request(
                request.method,
                upstream_url,
                params=dict(request.query_params),
                content=body,
                headers=fwd_headers,
            )
    except httpx.ConnectError:
        return HTMLResponse(
            "<html><body style='font-family:monospace;background:#08090e;color:#dde5f8;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
            "<div style='text-align:center'>"
            "<h2 style='color:#f06b6b'>Hermes Dashboard Not Running</h2>"
            "<p>The hermes-dashboard process hasn't started yet.<br>"
            "Check <a href='/logs' style='color:#818cf8'>Logs → dashboard</a> for details.<br>"
            "It may take 30–60 s after first boot.</p>"
            "<p><a href='/system' style='color:#818cf8'>System page</a> · "
            "<a href='/agent' style='color:#818cf8'>Back to Chat</a></p>"
            "</div></body></html>",
            status_code=503,
        )

    ctype = upstream.headers.get("content-type", "")
    content = upstream.content

    # Rewrite absolute asset paths and inject base-path variable
    if "text/html" in ctype:
        html = content.decode("utf-8", errors="replace")
        # Vite builds absolute paths like src="/assets/..." — rewrite to /hermes/assets/...
        html = re.sub(r'((?:src|href|action)=")/', r'\1/hermes/', html)
        inject = '<script>window.__HERMES_BASE_PATH__="/hermes";</script>'
        if "</head>" in html:
            html = html.replace("</head>", inject + "</head>", 1)
        else:
            html = inject + html
        content = html.encode("utf-8")

    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _DASH_STRIP_HEADERS
    }
    return Response(
        content=content,
        status_code=upstream.status_code,
        media_type=ctype,
        headers=resp_headers,
    )


@app.get("/assets/{path:path}", include_in_schema=False)
async def hermes_assets_proxy(path: str, request: Request):
    """Proxy Vite-built static assets from the Hermes dashboard."""
    upstream_url = f"http://127.0.0.1:{DASHBOARD_PORT}/assets/{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.get(upstream_url, params=dict(request.query_params))
    except httpx.ConnectError:
        return Response(status_code=503)
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _DASH_STRIP_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        headers=resp_headers,
    )
