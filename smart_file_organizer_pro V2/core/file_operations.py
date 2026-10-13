"""Low-level, safe filesystem helpers shared by Main Organizer and Workspace."""

import hashlib
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional


def sha256_of_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def unique_dest(dest: Path) -> Path:
    """report.pdf -> report (1).pdf -> report (2).pdf ..."""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class ConflictAction:
    RENAME = "rename"
    REPLACE = "replace"
    SKIP = "skip"


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s"
    h, remainder = divmod(int(seconds), 3600)
    m = remainder // 60
    return f"{h}h {m:02d}m"


def check_folder_writable(folder: Path, log: Optional[logging.Logger] = None) -> Optional[str]:
    """Return None if writable, else a human-readable explanation."""
    probe = folder / f".sfo_write_test_{uuid.uuid4().hex[:8]}"
    try:
        probe.mkdir()
        probe.rmdir()
        return None
    except OSError as exc:
        if log:
            log.warning("Write-test failed for %s: %s", folder, exc)
        return (
            f"Could not create a folder inside:\n{folder}\n\n"
            f"This usually means the folder is managed by a cloud-sync "
            f"service that's paused/signed out, or a permission setting is "
            f"blocking new folders there.\n\nDetails: {exc}"
        )


def ensure_dirs(dirs: set, log: Optional[logging.Logger] = None,
                 retries: int = 5, base_delay: float = 0.4) -> dict:
    """Create every directory in *dirs* with retry/back-off. Returns failures."""
    failed: dict = {}
    for d in sorted(dirs, key=lambda p: len(p.parts)):
        last_exc: Optional[OSError] = None
        for attempt in range(retries):
            try:
                d.mkdir(parents=True, exist_ok=True)
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
        if last_exc is not None:
            failed[d] = last_exc
            if log:
                log.error("ERROR creating folder %s: %s", d, last_exc)
    return failed


def safe_move(src: Path, dest: Path, log: Optional[logging.Logger] = None,
              retries: int = 3, delay: float = 0.3) -> None:
    """Move src -> dest, retrying and falling back to copy+delete on failure."""
    last_exc: Optional[OSError] = None
    for attempt in range(retries):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            return
        except OSError as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(delay)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        os.remove(str(src))
        return
    except OSError as exc:
        last_exc = exc

    assert last_exc is not None
    if log:
        log.error("MOVE FAILED %s -> %s: %s", src, dest, last_exc)
    raise last_exc


def find_existing_category_folder(root: Path, category_name: str) -> Optional[Path]:
    """
    Look for a folder directly under *root* that already represents
    *category_name* (case-insensitive exact match), so we reuse it
    instead of creating a duplicate ("Images" vs "images" vs "Images 2").
    """
    if not root.exists():
        return None
    target = category_name.strip().lower()
    try:
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.strip().lower() == target:
                return entry
    except OSError:
        return None
    return None


def resolve_category_destination(root: Path, category_name: str) -> Path:
    """Reuse an existing matching folder, or plan a new one with the exact name."""
    existing = find_existing_category_folder(root, category_name)
    return existing if existing is not None else root / category_name
