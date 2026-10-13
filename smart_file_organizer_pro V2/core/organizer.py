"""FileOrganizer: scans a folder, previews planned moves, executes them."""

import datetime
import logging
import time
from pathlib import Path
from typing import Optional, Callable

from .categories import ConfigManager, SYSTEM_SKIP_DIRS, ARCHIVE_EXTENSIONS
from .history import HistoryManager, CancelToken
from .file_operations import (
    unique_dest, safe_move, ensure_dirs, ConflictAction,
    resolve_category_destination,
)
from .duplicate_handler import find_duplicates


class FileOrganizer:
    """
    Scans a directory, previews planned moves, executes them, detects
    duplicates, and supports session-based undo.
    """

    def __init__(self, config: ConfigManager, history: HistoryManager,
                 log: logging.Logger) -> None:
        self.config = config
        self.history = history
        self.log = log

        self.scan_results: list[dict] = []
        self.duplicates: list[tuple[Path, Path]] = []

        self.stats: dict[str, int] = {
            "scanned": 0, "moved": 0, "renamed": 0,
            "duplicates": 0, "skipped": 0, "errors": 0,
            "folder_errors": 0,
        }

    # ------------------------------------------------------------------
    def _should_skip_dir(self, d: Path, root: Path, category_names: set[str],
                          skip_organised: bool) -> bool:
        name_lower = d.name.lower()
        if name_lower.startswith(".") or name_lower in SYSTEM_SKIP_DIRS:
            return True
        if d.name in category_names:
            return True
        for ext in ARCHIVE_EXTENSIONS:
            if (d.parent / (d.name + ext)).exists():
                return True
        if skip_organised:
            try:
                rel = d.relative_to(root)
                if len(rel.parts) == 1 and d.name in category_names:
                    return True
            except ValueError:
                pass
        return False

    # ------------------------------------------------------------------
    def scan(
        self,
        folder: Path,
        date_mode: str = "none",
        skip_nested: bool = False,
        scan_subfolders: bool = True,
        active_categories: Optional[set[str]] = None,
        reuse_existing_folders: bool = True,
        cancel: Optional[CancelToken] = None,
        progress_cb: Optional[Callable] = None,
    ) -> list[dict]:
        """Walk *folder* and build a preview list without moving anything."""
        ext_map = self.config.extension_to_category()
        category_names = self.config.category_folder_names()

        self.scan_results = []
        self.duplicates = []

        all_files: list[Path] = []

        if scan_subfolders:
            def _walk(directory: Path) -> None:
                if cancel and cancel.is_cancelled:
                    return
                try:
                    entries = sorted(directory.iterdir())
                except PermissionError:
                    return
                for entry in entries:
                    if cancel and cancel.is_cancelled:
                        return
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        if not self._should_skip_dir(entry, folder, category_names, skip_nested):
                            _walk(entry)
                    elif entry.is_file():
                        all_files.append(entry)

            _walk(folder)
        else:
            try:
                all_files = [p for p in folder.iterdir()
                             if p.is_file() and not p.is_symlink()]
            except PermissionError:
                pass

        if cancel and cancel.is_cancelled:
            return []

        total = len(all_files)
        dup_pairs = find_duplicates(all_files, cancel=cancel)
        self.duplicates = dup_pairs
        dup_set = {p for p, _orig in dup_pairs}

        start_time = time.monotonic()
        results: list[dict] = []

        for idx, path in enumerate(all_files, 1):
            if cancel and cancel.is_cancelled:
                return []

            if progress_cb:
                elapsed = time.monotonic() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                from .file_operations import format_eta
                eta = format_eta((total - idx) / rate) if rate > 0 else "…"
                progress_cb(idx, total, path.name, eta)

            ext = path.suffix.lower()
            cat = ext_map.get(ext, "Others")

            if active_categories is not None and cat not in active_categories:
                continue

            if reuse_existing_folders:
                dest_folder = resolve_category_destination(folder, cat)
            else:
                dest_folder = folder / cat

            if date_mode != "none":
                try:
                    mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
                    dest_folder = dest_folder / str(mtime.year)
                    if date_mode == "year_month":
                        dest_folder = dest_folder / f"{mtime.month:02d}-{mtime.strftime('%b')}"
                except OSError:
                    pass

            dest_path = dest_folder / path.name
            is_dup = path in dup_set

            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            results.append({
                "file": path.name,
                "src": str(path),
                "dest": str(dest_path),
                "category": cat,
                "size": size,
                "is_dup": is_dup,
            })

        self.scan_results = results
        self.stats["scanned"] = len(results)
        self.stats["duplicates"] = len(self.duplicates)
        return results

    # ------------------------------------------------------------------
    def organize(
        self,
        conflict_action: str = ConflictAction.RENAME,
        cancel: Optional[CancelToken] = None,
        progress_cb: Optional[Callable] = None,
        status_cb: Optional[Callable] = None,
    ) -> dict:
        """Execute the file moves planned during scan(). Session-aware."""
        self.stats["moved"] = 0
        self.stats["renamed"] = 0
        self.stats["skipped"] = 0
        self.stats["errors"] = 0
        self.stats["folder_errors"] = 0

        self.history.begin_session()
        total = len(self.scan_results)
        start_t = time.monotonic()

        needed_dirs = {Path(item["dest"]).parent for item in self.scan_results}
        failed_dirs = ensure_dirs(needed_dirs, log=self.log)

        from .file_operations import format_eta

        for idx, item in enumerate(self.scan_results, 1):
            if cancel and cancel.is_cancelled:
                break

            if progress_cb:
                elapsed = time.monotonic() - start_t
                rate = idx / elapsed if elapsed > 0 else 0
                eta = format_eta((total - idx) / rate) if rate > 0 else "…"
                progress_cb(idx, total, eta)

            src = Path(item["src"])
            raw_dest = Path(item["dest"])

            if not src.exists():
                self.stats["skipped"] += 1
                continue

            if raw_dest.parent in failed_dirs:
                self.stats["errors"] += 1
                self.stats["folder_errors"] += 1
                self.log.error("ERROR moving %s: destination folder %s could not be created",
                                src, raw_dest.parent)
                continue

            if raw_dest.exists():
                if conflict_action == ConflictAction.SKIP:
                    self.stats["skipped"] += 1
                    continue
                elif conflict_action == ConflictAction.REPLACE:
                    dest = raw_dest
                else:
                    dest = unique_dest(raw_dest)
            else:
                dest = raw_dest

            renamed = dest.name != src.name

            try:
                if conflict_action == ConflictAction.REPLACE and dest.exists() and dest != src:
                    dest.unlink()
                safe_move(src, dest, log=self.log)
                self.history.record(str(src), str(dest))
                self.stats["moved"] += 1
                if renamed:
                    self.stats["renamed"] += 1
                self.log.info("MOVE %s -> %s", src, dest)
                if status_cb:
                    status_cb(f"Moved: {src.name}")
            except OSError as exc:
                self.stats["errors"] += 1
                self.log.error("ERROR moving %s: %s", src, exc)

        self.history.end_session()
        return dict(self.stats)

    # ------------------------------------------------------------------
    def undo_last_session(
        self,
        cancel: Optional[CancelToken] = None,
        progress_cb: Optional[Callable] = None,
        status_cb: Optional[Callable] = None,
        conflict_cb: Optional[Callable[[Path], str]] = None,
    ) -> int:
        records = list(reversed(self.history.pop_last_session()))
        restored = 0
        total = len(records)

        needed_dirs = {Path(rec["src"]).parent for rec in records}
        failed_dirs = ensure_dirs(needed_dirs, log=self.log)

        for idx, rec in enumerate(records, 1):
            if cancel and cancel.is_cancelled:
                break
            if progress_cb:
                progress_cb(idx, total)

            src = Path(rec["dst"])
            original_dest = Path(rec["src"])

            if not src.exists():
                self.log.warning("UNDO skip (missing): %s", src)
                continue

            if original_dest.parent in failed_dirs:
                self.log.error("UNDO ERROR %s: destination folder %s could not be created",
                                src, original_dest.parent)
                continue

            dest = original_dest
            if original_dest.exists():
                action = conflict_cb(original_dest) if conflict_cb else ConflictAction.RENAME
                if action == ConflictAction.SKIP:
                    continue
                elif action == ConflictAction.REPLACE:
                    dest = original_dest
                else:
                    dest = unique_dest(original_dest)

            try:
                if dest == original_dest and original_dest.exists():
                    original_dest.unlink()
                safe_move(src, dest, log=self.log)
                restored += 1
                self.log.info("UNDO %s -> %s", src, dest)
                if status_cb:
                    status_cb(f"Restored: {src.name}")
            except OSError as exc:
                self.log.error("UNDO ERROR %s: %s", src, exc)

        return restored

    # ------------------------------------------------------------------
    def move_duplicates(
        self,
        folder: Path,
        cancel: Optional[CancelToken] = None,
        progress_cb: Optional[Callable] = None,
    ) -> int:
        dup_dir = resolve_category_destination(folder, "Duplicates")
        moved = 0
        total = len(self.duplicates)

        self.history.begin_session()
        failed_dirs = ensure_dirs({dup_dir}, log=self.log)

        for idx, (dup_path, _original) in enumerate(self.duplicates, 1):
            if cancel and cancel.is_cancelled:
                break
            if progress_cb:
                progress_cb(idx, total)
            if not dup_path.exists():
                continue
            if dup_dir in failed_dirs:
                continue

            dest = unique_dest(dup_dir / dup_path.name)
            try:
                safe_move(dup_path, dest, log=self.log)
                self.history.record(str(dup_path), str(dest))
                moved += 1
                self.log.info("DUP_MOVE %s -> %s", dup_path, dest)
            except OSError as exc:
                self.log.error("DUP_MOVE ERROR %s: %s", dup_path, exc)

        self.history.end_session()
        return moved
