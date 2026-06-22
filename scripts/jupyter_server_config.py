# Token/password auth is disabled because this server only binds to
# 127.0.0.1; the only path in is app/main.py's authenticated /jupyter
# reverse proxy, which gates every request with the Hermes session cookie.
c = get_config()  # noqa: F821

c.ServerApp.ip = "127.0.0.1"
c.ServerApp.port = 8888
c.ServerApp.open_browser = False
c.ServerApp.base_url = "/jupyter/"
c.ServerApp.token = ""
c.ServerApp.password = ""
c.ServerApp.disable_check_xsrf = True
c.ServerApp.allow_origin = "*"
c.ServerApp.allow_remote_access = True
c.ServerApp.root_dir = "/home/user"
c.ServerApp.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"},
}
