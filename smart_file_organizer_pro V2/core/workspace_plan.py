"""
Workspace Mode's data model.

Nothing here touches the filesystem except:
  * load_folder()  - read-only listing of files/subfolders
  * apply()        - the one place that actually moves files

Everything else (assigning a file to a proposed folder, renaming a
proposed folder, merging proposed folders, deleting a proposed folder)
only mutates in-memory state, so Cancel always leaves disk untouched.
"""

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .file_operations import unique_dest, ensure_dirs, safe_move, ConflictAction
from .history import HistoryManager, CancelToken


@dataclass
class WorkspaceFile:
    id: str
    path: Path                 # current real location on disk
    name: str
    ext: str
    size: int
    folder_id: Optional[str] = None   # proposed destination folder, or None = unassigned


@dataclass
class WorkspaceFolder:
    id: str
    name: str
    existing_path: Optional[Path] = None   # set if this represents a real existing folder
    opened: bool = False                    # whether it has been 'shattered' already


class WorkspacePlan:
    """Proposed (not-yet-applied) reorganization of one root folder."""

    def __init__(self, root: Path, log: logging.Logger) -> None:
        self.root = root
        self.log = log
        self.files: dict[str, WorkspaceFile] = {}
        self.folders: dict[str, WorkspaceFolder] = {}

    # ------------------------------------------------------------------
    # Read-only loading
    # ------------------------------------------------------------------
    def load_folder(self, scan_subfolders: bool = False) -> None:
        """Populate unassigned files and existing-folder objects from disk."""
        self.files.clear()
        self.folders.clear()
        try:
            entries = sorted(self.root.iterdir())
        except OSError:
            return

        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                fid = str(uuid.uuid4())
                self.folders[fid] = WorkspaceFolder(id=fid, name=entry.name, existing_path=entry)
            elif entry.is_file():
                self._add_file(entry, folder_id=None)

    def _add_file(self, path: Path, folder_id: Optional[str]) -> str:
        fid = str(uuid.uuid4())
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.files[fid] = WorkspaceFile(
            id=fid, path=path, name=path.name,
            ext=path.suffix.lower(), size=size, folder_id=folder_id,
        )
        return fid

    def open_existing_folder(self, folder_id: str) -> list[str]:
        """
        'Shatter' an existing-folder object: load its real, on-disk
        contents into the workspace — files as movable file cards, and
        any nested subfolders as their own (still-closed) folder
        portals that can be shattered again the same way. This is what
        lets deeply-nested folder trees be explored a level at a time
        instead of needing everything scanned up front. Returns the
        combined list of newly created file/folder IDs.
        """
        folder = self.folders.get(folder_id)
        if not folder or not folder.existing_path or not folder.existing_path.exists():
            return []
        if folder.opened:
            return []   # already shattered — avoid adding duplicate cards
        new_ids: list[str] = []
        try:
            children = sorted(folder.existing_path.iterdir())
        except OSError:
            return []
        for child in children:
            if child.is_symlink():
                continue
            if child.is_file():
                new_ids.append(self._add_file(child, folder_id=None))
            elif child.is_dir():
                sub_id = str(uuid.uuid4())
                self.folders[sub_id] = WorkspaceFolder(
                    id=sub_id, name=child.name, existing_path=child)
                new_ids.append(sub_id)
        folder.opened = True
        return new_ids

    # ------------------------------------------------------------------
    # In-memory mutations (no disk changes)
    # ------------------------------------------------------------------
    def create_folder(self, name: str) -> str:
        fid = str(uuid.uuid4())
        self.folders[fid] = WorkspaceFolder(id=fid, name=name, existing_path=None)
        return fid

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        if folder_id in self.folders:
            self.folders[folder_id].name = new_name

    def delete_folder(self, folder_id: str) -> None:
        """Remove a proposed folder; its files become unassigned again (never deleted)."""
        if folder_id not in self.folders:
            return
        for f in self.files.values():
            if f.folder_id == folder_id:
                f.folder_id = None
        del self.folders[folder_id]

    def merge_folders(self, src_folder_id: str, dest_folder_id: str) -> None:
        """Move every file proposed for src_folder into dest_folder, then drop src_folder."""
        if src_folder_id == dest_folder_id:
            return
        if src_folder_id not in self.folders or dest_folder_id not in self.folders:
            return
        for f in self.files.values():
            if f.folder_id == src_folder_id:
                f.folder_id = dest_folder_id
        del self.folders[src_folder_id]

    def assign_file(self, file_id: str, folder_id: Optional[str]) -> None:
        if file_id in self.files:
            self.files[file_id].folder_id = folder_id

    def assign_files(self, file_ids: list[str], folder_id: Optional[str]) -> None:
        for fid in file_ids:
            self.assign_file(fid, folder_id)

    # ------------------------------------------------------------------
    # Preview summary
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        moves = [f for f in self.files.values() if f.folder_id is not None]
        new_folders = [
            fo for fo in self.folders.values()
            if fo.existing_path is None and any(f.folder_id == fo.id for f in self.files.values())
        ]
        # duplicate-name collisions within the same destination folder
        seen: dict[tuple, int] = {}
        dup_count = 0
        for f in moves:
            key = (f.folder_id, f.name.lower())
            seen[key] = seen.get(key, 0) + 1
        dup_count = sum(c - 1 for c in seen.values() if c > 1)

        return {
            "files_to_move": len(moves),
            "folders_to_create": len(new_folders),
            "duplicates": dup_count,
        }

    # ------------------------------------------------------------------
    # Apply — the only place real files move
    # ------------------------------------------------------------------
    def apply(
        self,
        history: HistoryManager,
        conflict_action: str = ConflictAction.RENAME,
        cancel: Optional[CancelToken] = None,
        progress_cb=None,
    ) -> dict:
        stats = {"moved": 0, "renamed": 0, "errors": 0, "skipped": 0}
        moves = [f for f in self.files.values() if f.folder_id is not None]
        total = len(moves)

        # Resolve each folder_id to a real destination directory path,
        # creating new proposed folders under root using their given name.
        dest_dirs: dict[str, Path] = {}
        for fo in self.folders.values():
            dest_dirs[fo.id] = fo.existing_path if fo.existing_path else (self.root / fo.name)

        needed = {dest_dirs[f.folder_id] for f in moves if f.folder_id in dest_dirs}
        failed_dirs = ensure_dirs(needed, log=self.log)

        history.begin_session()

        for idx, f in enumerate(moves, 1):
            if cancel and cancel.is_cancelled:
                break
            if progress_cb:
                progress_cb(idx, total)

            if not f.path.exists():
                stats["skipped"] += 1
                continue

            dest_dir = dest_dirs.get(f.folder_id)
            if dest_dir is None or dest_dir in failed_dirs:
                stats["errors"] += 1
                continue

            raw_dest = dest_dir / f.name
            if raw_dest.exists() and raw_dest != f.path:
                if conflict_action == ConflictAction.SKIP:
                    stats["skipped"] += 1
                    continue
                elif conflict_action == ConflictAction.REPLACE:
                    dest = raw_dest
                else:
                    dest = unique_dest(raw_dest)
            else:
                dest = raw_dest

            renamed = dest.name != f.path.name
            try:
                if conflict_action == ConflictAction.REPLACE and dest.exists() and dest != f.path:
                    dest.unlink()
                safe_move(f.path, dest, log=self.log)
                history.record(str(f.path), str(dest))
                stats["moved"] += 1
                if renamed:
                    stats["renamed"] += 1
                f.path = dest
            except OSError as exc:
                stats["errors"] += 1
                self.log.error("WORKSPACE MOVE ERROR %s -> %s: %s", f.path, dest, exc)

        history.end_session()
        return stats
