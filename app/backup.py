"""Mirrors Hermes Agent state into a private Hugging Face dataset repo
(<your-username>/hermes-backup) — one file per file, no tarball.

Ported from HuggingMes's hermes-sync.py: `upload_folder`/`snapshot_download`
let huggingface_hub diff against the repo and only transfer files that
actually changed, so the dataset's working tree stays bounded to the size of
~/.hermes itself instead of accumulating a brand-new full archive every
cycle (which is what grew our previous tarball-based backup to 83.9GB).
"""
import hashlib
import json
import logging
import os
import shutil
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, upload_folder

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

# Cheap (file_count, total_size, newest_mtime) marker is checked first on
# every cycle; only when it changes do we pay for a full SHA-256 content
# hash, and only when *that* also differs do we actually snapshot + upload.
# Catches "marker changed but content didn't" (e.g. a touch) without paying
# for an upload. Mirrors HuggingMes's metadata_marker()/fingerprint_dir().
FINGERPRINT_FILE = Path(
    os.environ.get("BACKUP_FINGERPRINT_FILE", str(BACKUP_STATE_FILE.parent / "backup_fingerprint.json"))
)

# Other places the agent has been observed writing SOUL.md instead of the
# canonical HERMES_HOME/SOUL.md path.
SOUL_FALLBACK_PATHS = [
    HERMES_HOME / "workspace" / "SOUL.md",
    Path.home() / "SOUL.md",
    Path.home() / ".hermes" / "workspace" / "SOUL.md",
]

_REPO_ID_CACHE: str | None = None


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


def _read_fingerprint() -> dict:
    if FINGERPRINT_FILE.exists():
        try:
            return json.loads(FINGERPRINT_FILE.read_text())
        except Exception:
            pass
    return {}


def _write_fingerprint(data: dict) -> None:
    FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(json.dumps(data))


def _dataset_repo_id(api: HfApi, token: str) -> str:
    global _REPO_ID_CACHE
    if _REPO_ID_CACHE:
        return _REPO_ID_CACHE
    custom = os.environ.get("BACKUP_DATASET_REPO")
    if custom:
        _REPO_ID_CACHE = custom
        return custom
    who = api.whoami(token=token)
    name = os.environ.get("BACKUP_DATASET_NAME", "hermes-backup")
    _REPO_ID_CACHE = f"{who['name']}/{name}"
    return _REPO_ID_CACHE


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


def _should_exclude(rel: Path, full_path: Path) -> bool:
    if _is_excluded(rel.parts):
        return True
    if full_path.is_file():
        try:
            return full_path.stat().st_size > SYNC_MAX_FILE_BYTES
        except OSError:
            return True
    return False


def _promote_soul_md() -> None:
    """Agent writes SOUL.md to unpredictable locations; promote the first
    non-empty copy found to the canonical path before syncing."""
    local = HERMES_HOME / "SOUL.md"
    if local.exists() and local.stat().st_size > 0:
        return
    for candidate in SOUL_FALLBACK_PATHS:
        if candidate.exists() and candidate.stat().st_size > 0:
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, local)
            logger.info("Promoted %s → SOUL.md for backup", candidate)
            return


def _metadata_marker(root: Path) -> dict:
    file_count = 0
    total_size = 0
    newest_mtime = 0.0
    if root.exists():
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if _should_exclude(rel, p):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            file_count += 1
            total_size += st.st_size
            newest_mtime = max(newest_mtime, st.st_mtime)
    return {"file_count": file_count, "total_size": total_size, "newest_mtime": newest_mtime}


def _content_fingerprint(root: Path) -> str:
    """Full SHA-256 over relative paths + file contents. Only computed when
    the cheap marker indicates something may have changed."""
    hasher = hashlib.sha256()
    if not root.exists():
        return hasher.hexdigest()
    for p in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if _should_exclude(rel, p):
            continue
        hasher.update(rel.as_posix().encode("utf-8"))
        try:
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError:
            continue
    return hasher.hexdigest()


def _create_snapshot_dir(source_root: Path) -> Path:
    """Copy the (filtered) tree into a temp staging dir so the upload sees a
    consistent snapshot instead of a tree the agent might mutate mid-upload."""
    staging = Path(tempfile.mkdtemp(prefix="hermes-sync-"))
    for p in sorted(source_root.rglob("*")):
        rel = p.relative_to(source_root)
        if _should_exclude(rel, p):
            continue
        target = staging / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, target)
        except OSError:
            continue  # file removed mid-snapshot by the agent
    return staging


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

        _promote_soul_md()

        prev = _read_fingerprint()
        marker = _metadata_marker(HERMES_HOME)
        if marker == prev.get("marker"):
            result = _read_state()
            result["status"] = "no changes"
            result["repo"] = repo_id
            result["checked_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
            _write_state(result)
            return result

        content_hash = _content_fingerprint(HERMES_HOME)
        if content_hash == prev.get("hash"):
            # Marker drifted (e.g. a touch) but content is identical --
            # confirmed via full hash, so skip the upload.
            _write_fingerprint({"marker": marker, "hash": content_hash})
            result = _read_state()
            result["status"] = "no changes"
            result["repo"] = repo_id
            result["checked_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
            _write_state(result)
            return result

        hostname = socket.gethostname()
        snapshot_dir = _create_snapshot_dir(HERMES_HOME)
        try:
            upload_folder(
                folder_path=str(snapshot_dir),
                repo_id=repo_id,
                repo_type="dataset",
                token=token,
                commit_message=f"Hermes sync [{hostname}] {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                # Mirror the live tree exactly: anything no longer present
                # locally (deleted files, or legacy backups/priority dirs
                # from the old tarball scheme) is removed from the repo too,
                # instead of accumulating forever.
                delete_patterns=["*"],
            )
        finally:
            shutil.rmtree(snapshot_dir, ignore_errors=True)

        _write_fingerprint({"marker": marker, "hash": content_hash})

        result = {
            "status": "success",
            "repo": repo_id,
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
        # +/-10% jitter so a duplicated Space doesn't line up its sync tick
        # with everyone else who duplicated at the same moment.
        jitter=SYNC_INTERVAL_SECS * 0.1,
        next_run_time=datetime.now(timezone.utc),
        id="hermes-backup",
        replace_existing=True,
    )
