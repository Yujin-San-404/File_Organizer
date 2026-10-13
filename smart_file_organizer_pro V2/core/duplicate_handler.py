"""Two-stage (size -> hash) duplicate file detection."""

from pathlib import Path
from typing import Optional, Callable

from .file_operations import sha256_of_file


def find_duplicates(
    files: list[Path],
    cancel: Optional[object] = None,
) -> list[tuple[Path, Path]]:
    """
    Return a list of (duplicate_path, original_path) pairs.

    Stage 1 groups files by size (cheap). Stage 2 hashes only files that
    share a size with at least one other file, avoiding hashing everything.
    """
    size_groups: dict[int, list[Path]] = {}
    for p in files:
        try:
            sz = p.stat().st_size
        except OSError:
            sz = -1
        size_groups.setdefault(sz, []).append(p)

    hash_map: dict[str, Path] = {}
    duplicates: list[tuple[Path, Path]] = []

    for sz, group in size_groups.items():
        if sz <= 0 or len(group) < 2:
            continue
        for p in group:
            if cancel is not None and getattr(cancel, "is_cancelled", False):
                return duplicates
            try:
                digest = sha256_of_file(p)
            except OSError:
                continue
            if digest in hash_map:
                duplicates.append((p, hash_map[digest]))
            else:
                hash_map[digest] = p

    return duplicates
