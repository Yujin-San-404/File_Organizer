"""Category <-> extension configuration, persisted as JSON."""

import json
import logging
from pathlib import Path

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Images":    [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
                  ".webp", ".svg", ".ico", ".heic", ".raw", ".cr2", ".nef"],
    "Papers": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".txt", ".odt", ".ods", ".odp", ".rtf", ".csv", ".md",
                  ".pages", ".numbers", ".key"],
    "Videos":    [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
                  ".m4v", ".mpeg", ".mpg", ".3gp", ".ts", ".vob"],
    "Audio":     [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a",
                  ".opus", ".aiff", ".alac", ".mid", ".midi"],
    "Code":      [".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
                  ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs",
                  ".rb", ".php", ".swift", ".kt", ".kts", ".sh", ".bash",
                  ".ps1", ".sql", ".json", ".yaml", ".yml", ".xml", ".toml",
                  ".lua", ".dart", ".scala", ".r", ".m", ".vue", ".svelte",
                  ".graphql", ".proto"],
    "Scripts":   [".bat", ".cmd", ".vbs"],
    "Configuration": [".ini", ".cfg", ".env", ".conf", ".properties"],
    "Logs":      [".log"],
    "Archives":  [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
                  ".iso", ".dmg", ".pkg"],
    "Disk Images": [".vhd", ".vhdx", ".vmdk", ".qcow2"],
    "Executables": [".exe", ".msi", ".apk", ".app", ".deb", ".rpm"],
    "Fonts":     [".ttf", ".otf", ".woff", ".woff2"],
    "Design Files": [".psd", ".ai", ".fig", ".sketch", ".xd"],
    "3D Models": [".blend", ".fbx", ".obj", ".stl", ".glb"],
    "CAD":       [".dwg", ".dxf", ".step", ".iges"],
    "Databases": [".db", ".sqlite", ".sqlite3", ".mdb", ".accdb"],
    "Certificates": [".pem", ".crt", ".cer", ".pfx", ".p12"],
    "E-books":   [".epub", ".mobi", ".azw3"],
}

SYSTEM_SKIP_DIRS: set[str] = {
    "$recycle.bin", "system volume information", "appdata", "programdata",
    ".cache", ".config", ".local", ".ds_store", ".trashes",
}

ARCHIVE_EXTENSIONS: set[str] = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}

CONFIG_FILENAME = "sfo_categories.json"


class ConfigManager:
    """Loads and persists category -> extension mappings as JSON."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.categories: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as fh:
                    self.categories = json.load(fh)
                self._merge_missing_defaults()
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.categories = {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}
        self._save()

    def _merge_missing_defaults(self) -> None:
        added = False
        for cat, exts in DEFAULT_CATEGORIES.items():
            if cat not in self.categories:
                self.categories[cat] = list(exts)
                added = True
        if added:
            self._save()

    def restore_defaults(self) -> None:
        self.categories = {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}
        self._save()

    def _save(self) -> None:
        try:
            with self.config_path.open("w", encoding="utf-8") as fh:
                json.dump(self.categories, fh, indent=2)
        except OSError as exc:
            logging.warning("Could not save config: %s", exc)

    def extension_to_category(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for cat, exts in self.categories.items():
            for ext in exts:
                mapping[ext.lower()] = cat
        return mapping

    def add_category(self, name: str, extensions: list[str]) -> None:
        self.categories[name] = [e.lower() for e in extensions]
        self._save()

    def remove_category(self, name: str) -> None:
        self.categories.pop(name, None)
        self._save()

    def category_folder_names(self) -> set[str]:
        return set(self.categories.keys()) | {"Others", "Duplicates"}
