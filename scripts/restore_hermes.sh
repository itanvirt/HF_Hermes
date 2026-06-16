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
except Exception as e:
    print(f"Cannot list backup repo ({repo_id}): {e}")
    sys.exit(0)

# --- Step 1: Restore priority plain files (SOUL.md, USER.md) immediately ---
# These are saved as plain files on every backup cycle so they survive even
# when the full tarball backup hasn't run yet since the last write.
PRIORITY = [
    ("priority/SOUL.md",  hermes_home / "SOUL.md"),
    ("priority/USER.md",  hermes_home / "memories" / "USER.md"),
]
for remote, local in PRIORITY:
    if remote in all_files:
        try:
            src = hf_hub_download(repo_id=repo_id, filename=remote,
                                  repo_type="dataset", token=token)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(Path(src).read_bytes())
            print(f"Restored priority file: {local.name}")
            # Mirror SOUL.md into workspace/ so the agent finds it at
            # the path it sometimes writes to (/workspace/SOUL.md).
            if local.name == "SOUL.md":
                workspace_copy = hermes_home / "workspace" / "SOUL.md"
                workspace_copy.parent.mkdir(parents=True, exist_ok=True)
                workspace_copy.write_bytes(local.read_bytes())
        except Exception as ex:
            print(f"Could not restore {remote}: {ex}")

# --- Step 2: Restore full state from latest tarball (if no DB yet) ----------
existing_dbs = (
    list(hermes_home.glob("**/*.db")) +
    list(hermes_home.glob("**/*.sqlite")) +
    list(hermes_home.glob("**/*.sqlite3"))
)
if existing_dbs:
    print(f"~/.hermes already has state ({existing_dbs[0].name}) — skipping tarball restore.")
    sys.exit(0)

backups = sorted(f for f in all_files if f.startswith("backups/") and f.endswith(".tar.gz"))
if not backups:
    print("No tarball backups found — fresh start.")
    sys.exit(0)

latest = backups[-1]
print(f"Restoring full state from {latest} ...")

SKIP_NAMES = {".env", "credentials.json", "secrets.json"}

try:
    local_path = hf_hub_download(
        repo_id=repo_id, filename=latest,
        repo_type="dataset", token=token,
    )
    hermes_home.mkdir(parents=True, exist_ok=True)
    hermes_root = hermes_home.resolve()

    with tarfile.open(local_path) as tar:
        for member in tar.getmembers():
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            tail = parts[1]
            if Path(tail).name in SKIP_NAMES:
                continue
            dest = (hermes_home / tail).resolve()
            if not str(dest).startswith(str(hermes_root)):
                continue
            member.name = tail
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                tar.extract(member, path=str(hermes_home), filter="data")
            except TypeError:
                tar.extract(member, path=str(hermes_home))

    print("Full restore complete.")
except Exception as e:
    print(f"Tarball restore failed: {e}")
    sys.exit(1)
PYEOF
