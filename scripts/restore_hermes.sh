#!/usr/bin/env bash
# Restores ~/.hermes from the most recent HF Dataset backup on cold start.
# Safe to run on every boot: no-ops if state already exists.
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
import os, sys, tarfile
from pathlib import Path

try:
    from huggingface_hub import HfApi, hf_hub_download
except ImportError:
    print("huggingface_hub not available — skipping restore")
    sys.exit(0)

token = os.environ.get("HF_TOKEN", "")
hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

# Skip if there is already a database — avoids overwriting a mid-session restart
existing_dbs = (
    list(hermes_home.glob("**/*.db")) +
    list(hermes_home.glob("**/*.sqlite")) +
    list(hermes_home.glob("**/*.sqlite3"))
)
if existing_dbs:
    print(f"~/.hermes already has state ({existing_dbs[0].name}) — skipping restore.")
    sys.exit(0)

api = HfApi(token=token)
try:
    who = api.whoami(token=token)
except Exception as e:
    print(f"HF auth failed: {e}")
    sys.exit(0)

name = os.environ.get("BACKUP_DATASET_NAME", "hermes-backup")
repo_id = os.environ.get("BACKUP_DATASET_REPO", f"{who['name']}/{name}")

try:
    all_files = list(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    backups = sorted(f for f in all_files if f.startswith("backups/") and f.endswith(".tar.gz"))
except Exception as e:
    print(f"Cannot list backup repo ({repo_id}): {e}")
    sys.exit(0)

if not backups:
    print("No backups found — fresh start.")
    sys.exit(0)

latest = backups[-1]
print(f"Restoring from {latest} ...")

SKIP_NAMES = {".env", "credentials.json", "secrets.json"}

try:
    local_path = hf_hub_download(
        repo_id=repo_id,
        filename=latest,
        repo_type="dataset",
        token=token,
    )
    hermes_home.mkdir(parents=True, exist_ok=True)
    hermes_root = hermes_home.resolve()

    with tarfile.open(local_path) as tar:
        for member in tar.getmembers():
            # Archive was created with arcname="hermes-state"; strip that prefix
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            tail = parts[1]
            if Path(tail).name in SKIP_NAMES:
                continue
            # Path traversal guard
            dest = (hermes_home / tail).resolve()
            if not str(dest).startswith(str(hermes_root)):
                continue
            member.name = tail
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                tar.extract(member, path=str(hermes_home), filter="data")
            except TypeError:
                tar.extract(member, path=str(hermes_home))  # Python < 3.12

    print(f"Restore complete.")
except Exception as e:
    print(f"Restore failed: {e}")
    sys.exit(1)
PYEOF
