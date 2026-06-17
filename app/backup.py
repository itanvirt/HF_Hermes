"""Periodically archives Hermes Agent state and uploads it to a private
Hugging Face dataset repo (<your-username>/hermes-backup).
"""
import json
import logging
import os
import shutil
import tarfile
import tempfile
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

# Directories that are either reproducible (caches, venvs) or not worth
# the storage (logs, vcs metadata) -- skip them at any depth.
EXCLUDE_DIR_NAMES = {".cache", ".git", ".npm", ".venv", "__pycache__", "node_modules", "venv", "logs"}

# SQLite working files; only the *.db itself is needed for a consistent restore.
EXCLUDE_FILE_SUFFIXES = (".db-shm", ".db-wal", ".db-journal")

# Skip any single file larger than this (default 50MB) so one oversized
# cache/model file can't dominate every backup.
SYNC_MAX_FILE_BYTES = int(os.environ.get("SYNC_MAX_FILE_BYTES", str(50 * 1024 * 1024)))

# How many tarball backups to keep; older ones are deleted (and history
# squashed) so the dataset doesn't grow unbounded across restarts.
RETENTION_COUNT = int(os.environ.get("BACKUP_RETENTION_COUNT", "5"))

# Tracks (file_count, total_size, newest_mtime) of HERMES_HOME between runs
# so a full tarball is only built and uploaded when something actually
# changed, instead of re-uploading an identical snapshot every cycle.
FINGERPRINT_FILE = Path(
    os.environ.get("BACKUP_FINGERPRINT_FILE", str(BACKUP_STATE_FILE.parent / "backup_fingerprint.json"))
)

# Priority files saved as plain files in the dataset (not just in the tarball)
# so they can be restored immediately on cold start without waiting for a tarball.
PRIORITY_FILES = [
    ("memories/USER.md",  "priority/USER.md"),
    ("SOUL.md",           "priority/SOUL.md"),
]

# Other places the agent has been observed writing SOUL.md instead of the
# canonical HERMES_HOME/SOUL.md path.
SOUL_FALLBACK_PATHS = [
    HERMES_HOME / "workspace" / "SOUL.md",
    Path.home() / "SOUL.md",
    Path.home() / ".hermes" / "workspace" / "SOUL.md",
]


def _write_state(data: dict) -> None:
    BACKUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_STATE_FILE.write_text(json.dumps(data))


def _read_state() -> dict:
    if BACKUP_STATE_FILE.exists():
        try:
            return json.loads(BACKUP_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _read_fingerprint() -> dict | None:
    if FINGERPRINT_FILE.exists():
        try:
            return json.loads(FINGERPRINT_FILE.read_text())
        except Exception:
            return None
    return None


def _write_fingerprint(marker: dict) -> None:
    FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(json.dumps(marker))


def _dataset_repo_id(api: HfApi, token: str) -> str:
    custom = os.environ.get("BACKUP_DATASET_REPO")
    if custom:
        return custom
    who = api.whoami(token=token)
    name = os.environ.get("BACKUP_DATASET_NAME", "hermes-backup")
    return f"{who['name']}/{name}"


def _is_excluded(parts: tuple) -> bool:
    if not parts:
        return False
    name = parts[-1]
    if name in EXCLUDE_NAMES:
        return True
    if name.endswith(EXCLUDE_FILE_SUFFIXES):
        return True
    if any(part in EXCLUDE_DIR_NAMES for part in parts[:-1]):
        return True
    return False


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(tarinfo.name).parts[1:]  # strip the "hermes-state" arcname prefix
    if _is_excluded(parts):
        return None
    # Exclude the directory itself (not just its contents) so tarfile
    # doesn't recurse into large trees like node_modules/.venv at all.
    if tarinfo.isdir() and parts and parts[-1] in EXCLUDE_DIR_NAMES:
        return None
    if tarinfo.isfile() and tarinfo.size > SYNC_MAX_FILE_BYTES:
        return None
    return tarinfo


def _fingerprint(root: Path) -> dict:
    """Cheap metadata fingerprint (no content hashing): catches additions,
    deletions, and edits without having to read every file's bytes."""
    file_count = 0
    total_size = 0
    newest_mtime = 0.0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if _is_excluded(rel_parts):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > SYNC_MAX_FILE_BYTES:
            continue
        file_count += 1
        total_size += st.st_size
        newest_mtime = max(newest_mtime, st.st_mtime)
    # Also fold in the SOUL.md fallback paths (outside HERMES_HOME) so a
    # write there still triggers the priority-file promotion check below.
    for fallback in SOUL_FALLBACK_PATHS:
        try:
            st = fallback.stat()
        except OSError:
            continue
        file_count += 1
        total_size += st.st_size
        newest_mtime = max(newest_mtime, st.st_mtime)
    return {"file_count": file_count, "total_size": total_size, "newest_mtime": newest_mtime}


def _sync_priority_files(api: HfApi, repo_id: str, token: str) -> None:
    for local_rel, remote_rel in PRIORITY_FILES:
        local = HERMES_HOME / local_rel
        # Agent writes SOUL.md to unpredictable locations; check all known
        # wrong paths and promote to the correct one before uploading.
        if local_rel == "SOUL.md" and (not local.exists() or local.stat().st_size == 0):
            for candidate in SOUL_FALLBACK_PATHS:
                if candidate.exists() and candidate.stat().st_size > 0:
                    local.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, local)
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


def _prune_old_backups(api: HfApi, repo_id: str, token: str) -> dict:
    try:
        all_files = list(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    except Exception:
        logger.warning("could not list repo files for pruning", exc_info=True)
        return {"pruned": 0, "error": "list failed"}
    backups = sorted(f for f in all_files if f.startswith("backups/") and f.endswith(".tar.gz"))
    stale = backups[:-RETENTION_COUNT] if len(backups) > RETENTION_COUNT else []
    if not stale:
        return {"pruned": 0}
    # Delete all stale files in a single commit -- doing this one file at a
    # time (one commit per file) is far too slow / rate-limit-prone once
    # hundreds or thousands of backups have accumulated.
    try:
        api.delete_files(
            repo_id=repo_id,
            repo_type="dataset",
            delete_patterns=stale,
            token=token,
            commit_message=f"Prune {len(stale)} old backup(s)",
        )
    except Exception:
        logger.warning("could not delete stale backups", exc_info=True)
        return {"pruned": 0, "error": "delete failed"}
    # Deleting files only removes them from the latest commit tree -- the old
    # blobs stay in git history (and count toward dataset storage) until the
    # history is squashed.
    try:
        api.super_squash_history(repo_id=repo_id, repo_type="dataset", token=token)
    except Exception:
        logger.warning("history squash failed", exc_info=True)
        return {"pruned": len(stale), "error": "squash failed"}
    return {"pruned": len(stale)}


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

        # Priority files are tiny, so save them every cycle regardless of
        # whether the full tree changed -- SOUL.md/USER.md should survive
        # even between full snapshots.
        _sync_priority_files(api, repo_id, token)

        marker = _fingerprint(HERMES_HOME)
        if marker == _read_fingerprint():
            result = _read_state()
            result["status"] = "no changes"
            result["repo"] = repo_id
            result["checked_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
            _write_state(result)
            return result

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

        prune_result = _prune_old_backups(api, repo_id, token)
        _write_fingerprint(marker)

        result = {
            "status": "success",
            "repo": repo_id,
            "path": remote_path,
            "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "pruned": prune_result.get("pruned", 0),
        }
        if prune_result.get("error"):
            result["prune_error"] = prune_result["error"]
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
