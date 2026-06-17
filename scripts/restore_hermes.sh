#!/usr/bin/env bash
# Restores ~/.hermes from the HF Dataset backup on every boot.
# The container is ephemeral (HF Spaces rebuilds wipe local state), so the
# dataset is the durable source of truth and always wins over whatever (if
# anything) happens to exist locally already.
set -uo pipefail

LOG="/home/user/app/data/hermes-restore.log"
mkdir -p "$(dirname "$LOG")"
: > "$LOG"

_log() { echo "[restore_hermes] $*" | tee -a "$LOG"; }

HF_TOKEN="${HF_TOKEN:-}"
if [ -z "$HF_TOKEN" ]; then
    _log "No HF_TOKEN — skipping restore."
    exit 0
fi

python3 - <<'PYEOF' 2>&1 | tee -a "$LOG"
import os, shutil, sys, tempfile
from pathlib import Path

try:
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError
except ImportError:
    print("huggingface_hub not available — skipping restore")
    sys.exit(0)

token = os.environ.get("HF_TOKEN", "")
hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

api = HfApi(token=token)
try:
    who = api.whoami(token=token)
except Exception as e:
    print(f"HF auth failed: {e}")
    sys.exit(0)

name = os.environ.get("BACKUP_DATASET_NAME", "hermes-backup")
repo_id = os.environ.get("BACKUP_DATASET_REPO", f"{who['name']}/{name}")

# Files that never leave the container, plus artifacts from the previous
# tarball-based backup scheme (a dataset that predates this change may still
# have a top-level "backups/" or "priority/" dir from that era). "hermes-agent"
# is skipped too: it's the installed agent + venv, excluded from backup as
# reproducible install state -- a dataset created before that exclusion may
# still have a partial copy (missing venv/) that would otherwise clobber a
# working local install with a broken one.
SKIP_NAMES = {".env", "credentials.json", "secrets.json", ".gitattributes", "backups", "priority", "hermes-agent"}

try:
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_download(
            repo_id=repo_id, repo_type="dataset", token=token,
            local_dir=tmpdir, local_dir_use_symlinks=False,
        )
        tmp_path = Path(tmpdir)
        if not any(tmp_path.iterdir()):
            print("Backup dataset is empty — fresh start.")
            sys.exit(0)

        hermes_home.mkdir(parents=True, exist_ok=True)
        for child in tmp_path.iterdir():
            if child.name in SKIP_NAMES:
                continue
            target = hermes_home / child.name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

    # Mirror SOUL.md to the paths the agent commonly writes to / looks for,
    # so it finds the persona regardless of where it searches next time.
    soul = hermes_home / "SOUL.md"
    if soul.exists() and soul.stat().st_size > 0:
        data = soul.read_bytes()
        for mirror in [hermes_home / "workspace" / "SOUL.md", Path.home() / "SOUL.md"]:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_bytes(data)

    print(f"Restored Hermes state from {repo_id}.")
except RepositoryNotFoundError:
    print(f"Backup dataset {repo_id} does not exist yet — fresh start.")
except HfHubHTTPError as e:
    if e.response is not None and e.response.status_code == 404:
        print(f"Backup dataset {repo_id} does not exist yet — fresh start.")
    else:
        print(f"Restore failed: {e}")
except Exception as e:
    print(f"Restore failed: {e}")
PYEOF
