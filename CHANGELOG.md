# Changelog

Notable fixes and changes, in case you hit the same symptom on a duplicated
Space.

## Unreleased

- **Backup no longer builds a tarball.** `app/backup.py` now mirrors
  `~/.hermes` into the backup dataset file-by-file via
  `huggingface_hub.upload_folder`/`snapshot_download` instead of building a
  `.tar.gz` and uploading a new one every cycle. Only changed files are
  transferred, and `delete_patterns=["*"]` keeps the dataset an exact mirror
  (including cleaning up old `backups/*.tar.gz` / `priority/*.md` artifacts
  from the previous scheme on the first sync after upgrading). Change
  detection is now two-tier: a cheap `(file_count, total_size, newest_mtime)`
  marker first, then a full SHA-256 content hash to confirm before paying
  for an upload — avoids a real sync on a no-op `touch`.
- **Backup dataset grew to 83.9GB.** Root cause: every 10-minute backup
  cycle uploaded a brand-new timestamped tarball with no retention, so the
  dataset grew unbounded. First fix added retention + history squashing;
  that fix didn't actually prune because it deleted stale files one at a
  time (one commit per file) instead of in a single batched commit. Both
  problems are now moot under the no-tarball design above — there is only
  ever one "live" copy of each file, so unbounded growth from repeated
  cycles isn't possible by construction.
- **Auth token comparison wasn't timing-safe.** `app/auth.py`'s
  `verify_token()` used a plain `==` comparison against `GATEWAY_TOKEN`,
  which leaks timing information. Switched to `hmac.compare_digest`.
- **Terminal installs didn't survive a restart.** Packages installed
  interactively from `/terminal` (`apt install`, `pip install`, etc.) were
  lost on the next container rebuild unless you remembered to also add them
  to `STARTUP_APT_PACKAGES`/`STARTUP_PIP_PACKAGES` ahead of time. Added
  shell-capture wrapper functions (installed into `~/.bashrc` by
  `scripts/configure_startup.sh`) that auto-append successful installs to
  `data/startup.sh`, which is already replayed on every boot — so the
  Terminal now "remembers" what you installed without any pre-declaration.
- **SOUL.md (agent persona) was being written to the wrong path** by the
  agent and getting wiped on every container rebuild. Backup/restore/configure
  scripts now check and mirror all observed candidate paths
  (`~/.hermes/SOUL.md`, `~/.hermes/workspace/SOUL.md`, `~/SOUL.md`) so the
  persona survives regardless of which one the agent writes to.
- **A redeploy/restart could lose up to `SYNC_INTERVAL` of state.** Backups
  only ran on the periodic timer, so a `docker stop` (e.g. pushing a new
  image, restarting the Space) skipped straight to killing the container
  with no final sync. `scripts/entrypoint.sh` now traps `SIGTERM`/`SIGINT`
  and runs one last backup before letting supervisord stop its children —
  this requires *not* `exec`-ing supervisord (that would replace the trapping
  shell), so it now runs as a background child that the script `wait`s on
  instead. `scripts/hermes_gateway.sh` also syncs immediately whenever the
  gateway process exits/restarts, instead of waiting for the next tick.
- **No `.dockerignore`.** Every build/push sent the whole repo, including
  `.git/` history, into the Docker build context. Added one.
- **Backup interval had no jitter.** If you duplicate this Space many times
  around the same moment, every copy's sync timer would tick in lockstep.
  Added +/-10% jitter via APScheduler's native `jitter` parameter.
- **Login could silently fail when the dashboard is viewed inside the
  huggingface.co embed iframe.** Browsers' third-party cookie restrictions
  drop the session cookie `/login` sets when the page is embedded, with no
  obvious symptom beyond "login doesn't stick." `login.html` now detects
  `window.top !== window.self` and auto-redirects the top-level browsing
  context to the Space's own origin before submitting; the existing manual
  "Open in new tab" link stays as a fallback if that's blocked (e.g. a
  sandboxed embed).
- **Backup errors just showed the raw SDK exception** (e.g. `error: 401
  Client Error...`) on the dashboard, which didn't tell a duplicator what to
  actually do. `app/backup.py` now recognizes `HfHubHTTPError` 401/403
  responses and surfaces an actionable message (token invalid/expired vs.
  missing write scope) with a direct link to mint a new one.
- **The footer's "@owner" credit link silently never rendered.** It read a
  `SPACE_OWNER` env var that isn't a real thing — Hugging Face Spaces
  auto-injects `SPACE_AUTHOR_NAME` instead, and nothing told duplicators to
  set `SPACE_OWNER` themselves. `app/main.py` now reads `SPACE_AUTHOR_NAME`
  (falling back to `SPACE_OWNER` for anyone who'd set it manually), so the
  link works out of the box with zero configuration.
- **`hermes config set` had no retry and a swallowed-failure bug.**
  `scripts/configure_hermes.sh` chained the `model.default` and
  `model.provider` calls with `;` inside a `{ }` group, so the group's exit
  code reflected only the second call — a failed first call went unnoticed
  and unlogged. Also added 3x retry with backoff, since hermes may still be
  settling right after the fallback install a few lines above; reduces how
  often first boot needs a manual "finish via Terminal" fix.
