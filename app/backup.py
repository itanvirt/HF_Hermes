"""Periodically archives Hermes Agent state and uploads it to a private
Hugging Face dataset repo (<your-username>/hermes-backup).
"""
import json
import logging
import os
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi

from app.status import BACKUP_STATE_FILE

logger = logging.getLogger("hermes.backup")

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

# SYNC_INTERVAL (seconds, default 600 = 10 min) is checked first;
# BACKUP_INTERVAL_HOURS is kept for backward compatibility.
_hours_override = os.environ.get("BACKUP_INTERVAL_HOURS")
SYNC_INTERVAL_SECS = (
    float(_hours_override) * 3600 if _hours_override
    else float(os.environ.get("SYNC_INTERVAL", "600"))
)

# Files that must never leave the container.
EXCLUDE_NAMES = {".env", "credentials.json", "secrets.json"}

# How many tarball backups to keep; older ones are deleted (and history
# squashed) so the dataset doesn't grow unbounded across restarts.
RETENTION_COUNT = int(os.environ.get("BACKUP_RETENTION_COUNT", "5"))

# Priority files saved as plain files in the dataset (not just in the tarball)
# so they can be restored immediately on cold start without waiting for a tarball.
PRIORITY_FILES = [
    ("memories/USER.md",  "priority/USER.md"),
    ("SOUL.md",           "priority/SOUL.md"),
]


def _write_state(data: dict) -> None:
    BACKUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_STATE_FILE.write_text(json.dumps(data))


def _dataset_repo_id(api: HfApi, token: str) -> str:
    custom = os.environ.get("BACKUP_DATASET_REPO")
    if custom:
        return custom
    who = api.whoami(token=token)
    name = os.environ.get("BACKUP_DATASET_NAME", "hermes-backup")
    return f"{who['name']}/{name}"


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if Path(tarinfo.name).name in EXCLUDE_NAMES:
        return None
    return tarinfo


def _prune_old_backups(api: HfApi, repo_id: str, token: str) -> None:
    try:
        all_files = list(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    except Exception:
        return
    backups = sorted(f for f in all_files if f.startswith("backups/") and f.endswith(".tar.gz"))
    stale = backups[:-RETENTION_COUNT] if len(backups) > RETENTION_COUNT else []
    if not stale:
        return
    for old in stale:
        try:
            api.delete_file(path_in_repo=old, repo_id=repo_id, repo_type="dataset", token=token)
        except Exception:
            logger.warning("could not delete stale backup %s", old, exc_info=True)
    # Deleting a file only removes it from the latest commit tree -- the old
    # blob stays in git history (and counts toward dataset storage) until the
    # history is squashed.
    try:
        api.super_squash_history(repo_id=repo_id, repo_type="dataset", token=token)
    except Exception:
        logger.warning("history squash failed", exc_info=True)


def run_backup() -> dict:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        result = {"status": "not configured", "repo": None, "at": None}
        _write_state(result)
        return result

    if not HERMES_HOME.exists():
        result = {"status": "skipped (no state yet)", "repo": None, "at": None}
        _write_state(result)
        return result

    api = HfApi(token=token)
    try:
        repo_id = _dataset_repo_id(api, token)
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True, token=token)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            archive_path = tmp.name
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(HERMES_HOME, arcname="hermes-state", filter=_tar_filter)

            remote_path = f"backups/hermes-state-{timestamp}.tar.gz"
            api.upload_file(
                path_or_fileobj=archive_path,
                path_in_repo=remote_path,
                repo_id=repo_id,
                repo_type="dataset",
                token=token,
            )
        finally:
            os.unlink(archive_path)

        # Save priority files as plain files for fast cold-start restore
        import shutil as _shutil
        for local_rel, remote_rel in PRIORITY_FILES:
            local = HERMES_HOME / local_rel
            # Agent writes SOUL.md to unpredictable locations; check all known
            # wrong paths and promote to the correct one before uploading.
            if local_rel == "SOUL.md" and (not local.exists() or local.stat().st_size == 0):
                for candidate in [
                    HERMES_HOME / "workspace" / "SOUL.md",
                    Path.home() / "SOUL.md",
                    Path.home() / ".hermes" / "workspace" / "SOUL.md",
                ]:
                    if candidate.exists() and candidate.stat().st_size > 0:
                        local.parent.mkdir(parents=True, exist_ok=True)
                        _shutil.copy2(candidate, local)
                        logger.info("Promoted %s → SOUL.md for backup", candidate)
                        break
            if local.exists() and local.stat().st_size > 0:
                try:
                    api.upload_file(
                        path_or_fileobj=str(local),
                        path_in_repo=remote_rel,
                        repo_id=repo_id,
                        repo_type="dataset",
                        token=token,
                    )
                except Exception:
                    pass  # non-fatal

        _prune_old_backups(api, repo_id, token)

        result = {
            "status": "success",
            "repo": repo_id,
            "path": remote_path,
            "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        }
    except Exception as exc:  # noqa: BLE001 - surface any failure on the dashboard
        logger.exception("backup failed")
        result = {"status": f"error: {exc}", "repo": None, "at": None}

    _write_state(result)
    return result


def start_scheduler(scheduler) -> None:
    scheduler.add_job(
        run_backup,
        "interval",
        seconds=SYNC_INTERVAL_SECS,
        next_run_time=datetime.now(timezone.utc),
        id="hermes-backup",
        replace_existing=True,
    )
