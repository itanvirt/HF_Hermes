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
        for local_rel, remote_rel in PRIORITY_FILES:
            local = HERMES_HOME / local_rel
            # Fallback: Hermes agent sometimes writes SOUL.md into workspace/
            # instead of the root; capture it from there if the root copy is missing.
            if local_rel == "SOUL.md" and (not local.exists() or local.stat().st_size == 0):
                workspace_copy = HERMES_HOME / "workspace" / "SOUL.md"
                if workspace_copy.exists() and workspace_copy.stat().st_size > 0:
                    import shutil
                    shutil.copy2(workspace_copy, local)
                    logger.info("Promoted workspace/SOUL.md → SOUL.md for backup")
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
