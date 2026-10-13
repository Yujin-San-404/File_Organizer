"""Main Organizer window — simple, fast, predictable."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QFrame, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QToolButton, QStackedWidget,
)

from core.categories import ConfigManager, CONFIG_FILENAME
from core.history import HistoryManager, CancelToken, HISTORY_FILENAME
from core.organizer import FileOrganizer
from core.file_operations import check_folder_writable, human_size, ConflictAction

from .workspace import WorkspacePage

LOG_FILENAME = "sfo_operations.log"

STYLE = """
QWidget {
    background:#0E1117; color:#F0F6FC; font-family:'Segoe UI'; font-size:13px;
}
QMainWindow, QDialog, QMessageBox, QFileDialog, QInputDialog { background:#0E1117; }

QPushButton {
    background:#21262D; color:#F0F6FC; border:1px solid #3D444D;
    border-radius:8px; padding:8px 14px; font-weight:500;
}
QPushButton:hover { background:#2D333B; border-color:#58A6FF; }
QPushButton:pressed { background:#1C2128; }
QPushButton:disabled { background:#161B22; color:#6E7681; border-color:#21262D; }

QPushButton#primary { background:#00D4FF; color:#0A0D12; font-weight:700; border:none; }
QPushButton#primary:hover { background:#3DDEFF; }
QPushButton#primary:disabled { background:#164A57; color:#4B6970; }

QPushButton#success { background:#3FB950; color:#0A0D12; font-weight:700; border:none; }
QPushButton#success:hover { background:#56C96A; }
QPushButton#success:disabled { background:#1F4D28; color:#4E7256; }

QPushButton#danger { background:#F85149; color:#0A0D12; font-weight:700; border:none; }
QPushButton#danger:hover { background:#FF6B62; }

QLabel { color:#F0F6FC; background:transparent; }
QLabel#heading { font-size:17px; font-weight:700; color:#00D4FF; }
QLabel#muted { color:#9AA4AF; }
QLabel#success { color:#3FB950; font-weight:600; }
QLabel#warning { color:#D29922; font-weight:600; }

QFrame#sourceCard {
    background:#161B22; border:1px solid #30363D; border-radius:10px;
}
QFrame#sourceCard[hasFolder="true"] { border:1.5px solid #3FB950; }

QCheckBox { spacing:8px; color:#F0F6FC; background:transparent; }
QCheckBox::indicator {
    width:16px; height:16px; border-radius:4px;
    border:1.5px solid #58636D; background:#161B22;
}
QCheckBox::indicator:hover { border-color:#00D4FF; }
QCheckBox::indicator:checked {
    background:#00D4FF; border-color:#00D4FF;
    image: none;
}

QComboBox {
    background:#161B22; color:#F0F6FC; border:1px solid #3D444D;
    border-radius:6px; padding:5px 10px; min-height:22px;
}
QComboBox:hover { border-color:#58A6FF; }
QComboBox::drop-down { border:none; width:22px; }
QComboBox QAbstractItemView {
    background:#161B22; color:#F0F6FC; border:1px solid #3D444D;
    selection-background-color:#1F6FEB; selection-color:#FFFFFF;
    outline:none;
}

QToolButton {
    background:transparent; color:#F0F6FC; border:1px solid #3D444D;
    border-radius:8px; padding:6px 10px;
}
QToolButton:hover { background:#21262D; }
QToolButton:checked { background:#1F6FEB; color:#FFFFFF; border-color:#1F6FEB; }

QTableWidget {
    background:#161B22; color:#F0F6FC; border:1px solid #30363D;
    border-radius:6px; gridline-color:#30363D;
    alternate-background-color:#1C2128;
}
QTableWidget::item { padding:4px; }
QTableWidget::item:selected { background:#1F6FEB; color:#FFFFFF; }
QHeaderView::section {
    background:#1C2128; color:#00D4FF; border:none; border-bottom:1px solid #30363D;
    padding:6px; font-weight:600;
}

QProgressBar {
    border:1px solid #30363D; border-radius:6px; background:#161B22;
    text-align:center; color:#F0F6FC; min-height:18px;
}
QProgressBar::chunk { background:#00D4FF; border-radius:6px; }

QScrollBar:vertical, QScrollBar:horizontal { background:#0E1117; }
QScrollBar::handle { background:#30363D; border-radius:4px; }
QScrollBar::handle:hover { background:#58636D; }

QMessageBox QLabel, QInputDialog QLabel { color:#F0F6FC; }
QMessageBox QPushButton, QInputDialog QPushButton, QFileDialog QPushButton {
    min-width:72px;
}
QLineEdit {
    background:#161B22; color:#F0F6FC; border:1px solid #3D444D;
    border-radius:6px; padding:5px 8px; selection-background-color:#1F6FEB;
}
QLineEdit:focus { border-color:#00D4FF; }
QToolTip {
    background:#21262D; color:#F0F6FC; border:1px solid #3D444D; padding:4px;
}
"""


class ScanWorker(QThread):
    progress = Signal(int, int, str, str)
    done = Signal(list)

    def __init__(self, organizer: FileOrganizer, folder: Path, active_categories,
                 reuse_existing: bool, cancel: CancelToken):
        super().__init__()
        self.organizer = organizer
        self.folder = folder
        self.active_categories = active_categories
        self.reuse_existing = reuse_existing
        self.cancel = cancel

    def run(self) -> None:
        results = self.organizer.scan(
            self.folder,
            active_categories=self.active_categories,
            reuse_existing_folders=self.reuse_existing,
            cancel=self.cancel,
            progress_cb=lambda d, t, f, e: self.progress.emit(d, t, f, e),
        )
        self.done.emit([] if self.cancel.is_cancelled else results)


class OrganizeWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(dict)

    def __init__(self, organizer: FileOrganizer, conflict_action: str, cancel: CancelToken):
        super().__init__()
        self.organizer = organizer
        self.conflict_action = conflict_action
        self.cancel = cancel

    def run(self) -> None:
        stats = self.organizer.organize(
            conflict_action=self.conflict_action,
            cancel=self.cancel,
            progress_cb=lambda d, t, e: self.progress.emit(d, t, e),
        )
        self.done.emit(stats)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Smart File Organizer Pro")
        self.resize(880, 620)
        # STYLE is applied globally on QApplication in main.py; no need
        # to re-set it here.

        self.base_dir = Path.home() / ".sfo_pro"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._setup_logger()
        self.config = ConfigManager(self.base_dir / CONFIG_FILENAME)
        self.history = HistoryManager(self.base_dir / HISTORY_FILENAME)
        self.organizer = FileOrganizer(self.config, self.history, self.logger)

        self.selected_folder: Optional[Path] = None
        self.cancel_token = CancelToken()
        self._workspace_page: Optional[WorkspacePage] = None

        self._build_ui()
        self._refresh_undo_state()

    # ------------------------------------------------------------------
    def _setup_logger(self) -> None:
        self.logger = logging.getLogger("SFO")
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler(str(self.base_dir / LOG_FILENAME), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
            self.logger.addHandler(fh)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        central = QWidget()
        self.stack.addWidget(central)   # index 0: organizer page
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QLabel("🗂  Smart File Organizer")
        header.setObjectName("heading")
        root.addWidget(header)

        # SOURCE
        src_frame = QFrame()
        src_frame.setObjectName("sourceCard")
        src_frame.setProperty("hasFolder", "false")
        src_l = QHBoxLayout(src_frame)
        src_l.setContentsMargins(14, 12, 14, 12)

        self.folder_status_icon = QLabel("○")
        self.folder_status_icon.setObjectName("warning")
        src_l.addWidget(self.folder_status_icon)

        self.folder_label = QLabel("No folder selected yet")
        self.folder_label.setObjectName("muted")
        src_l.addWidget(self.folder_label, stretch=1)

        self.select_btn = QPushButton("📂  Select Folder")
        self.select_btn.setObjectName("primary")
        self.select_btn.clicked.connect(self._select_folder)
        src_l.addWidget(self.select_btn)

        self._src_frame = src_frame
        root.addWidget(src_frame)

        # ORGANIZE OPTIONS
        opts_frame = QFrame()
        opts_l = QHBoxLayout(opts_frame)
        opts_l.setContentsMargins(0, 0, 0, 0)

        self.existing_folders_cb = QCheckBox("Reuse existing folders")
        self.existing_folders_cb.setChecked(True)
        self.existing_folders_cb.setToolTip(
            "Put files into a matching folder that already exists instead of "
            "creating a new one.")
        opts_l.addWidget(self.existing_folders_cb)

        opts_l.addStretch()
        opts_l.addWidget(QLabel("Duplicates:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["Rename", "Replace", "Skip"])
        self.conflict_combo.setToolTip("What to do when a file with the same name already exists")
        opts_l.addWidget(self.conflict_combo)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("▸ Advanced")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        opts_l.addWidget(self.advanced_toggle)

        root.addWidget(opts_frame)

        # Advanced (hidden by default)
        self.advanced_frame = QFrame()
        adv_l = QHBoxLayout(self.advanced_frame)
        adv_l.setContentsMargins(0, 0, 0, 0)
        self.subfolders_cb = QCheckBox("Scan subfolders")
        self.subfolders_cb.setChecked(True)
        adv_l.addWidget(self.subfolders_cb)
        self.skip_organised_cb = QCheckBox("Skip already-organised")
        adv_l.addWidget(self.skip_organised_cb)
        adv_l.addStretch()
        root.addWidget(self.advanced_frame)
        self.advanced_frame.setVisible(False)

        # Progress
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.status_label = QLabel("Ready — select a folder to begin.")
        self.status_label.setObjectName("muted")
        root.addWidget(self.status_label)

        self.progress.setVisible(False)

        # Preview table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Category", "Destination", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, stretch=1)

        # Actions
        actions = QHBoxLayout()
        self.preview_btn = QPushButton("👁  Preview")
        self.preview_btn.clicked.connect(self._start_scan)
        self.preview_btn.setEnabled(False)
        actions.addWidget(self.preview_btn)

        self.organize_btn = QPushButton("✨  Organize")
        self.organize_btn.setObjectName("success")
        self.organize_btn.clicked.connect(self._start_organize)
        self.organize_btn.setEnabled(False)
        actions.addWidget(self.organize_btn)

        self.undo_btn = QPushButton("↩  Undo")
        self.undo_btn.clicked.connect(self._undo)
        actions.addWidget(self.undo_btn)

        self.cancel_btn = QPushButton("✕  Cancel")
        self.cancel_btn.clicked.connect(self.cancel_token.cancel)
        self.cancel_btn.setVisible(False)
        actions.addWidget(self.cancel_btn)

        actions.addStretch()

        workspace_btn = QPushButton("🎨  Workspace")
        workspace_btn.setObjectName("primary")
        workspace_btn.clicked.connect(self._open_workspace)
        actions.addWidget(workspace_btn)

        root.addLayout(actions)

    def _set_status(self, text: str, color: str = "#9AA4AF") -> None:
        self.status_label.setStyleSheet(f"color:{color};")
        self.status_label.setText(text)

    def _toggle_advanced(self) -> None:
        show = self.advanced_toggle.isChecked()
        self.advanced_toggle.setText("▾ Advanced" if show else "▸ Advanced")
        self.advanced_frame.setVisible(show)

    # ------------------------------------------------------------------
    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder to organize")
        if not folder:
            return
        selected = Path(folder)
        problem = check_folder_writable(selected, self.logger)
        if problem:
            proceed = QMessageBox.question(
                self, "Folder May Not Be Writable",
                problem + "\n\nContinue with this folder anyway?",
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        self.selected_folder = selected
        self.folder_label.setText(folder)
        self.folder_label.setObjectName("")
        self.folder_label.setStyleSheet("color:#F0F6FC; font-weight:600;")
        self.folder_status_icon.setText("✓")
        self.folder_status_icon.setObjectName("success")
        self.folder_status_icon.setStyleSheet("color:#3FB950; font-weight:700;")
        self._src_frame.setProperty("hasFolder", "true")
        self._src_frame.style().unpolish(self._src_frame)
        self._src_frame.style().polish(self._src_frame)
        self.preview_btn.setEnabled(True)
        self.organize_btn.setEnabled(False)
        self.table.setRowCount(0)
        self._set_status("✓ Folder selected — click Preview to see planned changes.", "#3FB950")

    # ------------------------------------------------------------------
    def _start_scan(self) -> None:
        if not self.selected_folder:
            return
        self.cancel_token.reset()
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.preview_btn.setEnabled(False)
        self._set_status("Starting scan…")
        self._scan_worker = ScanWorker(
            self.organizer, self.selected_folder,
            active_categories=None,
            reuse_existing=self.existing_folders_cb.isChecked(),
            cancel=self.cancel_token,
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_progress(self, done: int, total: int, filename: str, eta: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self._set_status(f"Scanning… {done}/{total} • {filename} • ETA {eta}")

    def _on_scan_done(self, results: list) -> None:
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)
        self.preview_btn.setEnabled(True)
        self._populate_table(results)
        n_dup = len(self.organizer.duplicates)
        n_cat = len({r["category"] for r in results})
        color = "#3FB950" if results else "#9AA4AF"
        self._set_status(
            f"{len(results)} files  •  {n_cat} categories  •  {n_dup} duplicates", color)
        self.organize_btn.setEnabled(bool(results))

    def _populate_table(self, results: list) -> None:
        self.table.setRowCount(len(results))
        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(item["file"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["category"]))
            self.table.setItem(row, 2, QTableWidgetItem(item["dest"]))
            self.table.setItem(row, 3, QTableWidgetItem(human_size(item["size"])))

    # ------------------------------------------------------------------
    def _start_organize(self) -> None:
        if not self.organizer.scan_results:
            return
        n = len(self.organizer.scan_results)
        confirm = QMessageBox.question(
            self, "Confirm Organize", f"Move {n} file(s) as previewed?")
        if confirm != QMessageBox.StandardButton.Yes:
            return

        conflict_map = {
            "Rename": ConflictAction.RENAME,
            "Replace": ConflictAction.REPLACE,
            "Skip": ConflictAction.SKIP,
        }
        self.cancel_token.reset()
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.organize_btn.setEnabled(False)
        self._set_status("Starting organize…")
        self._organize_worker = OrganizeWorker(
            self.organizer, conflict_map[self.conflict_combo.currentText()], self.cancel_token)
        self._organize_worker.progress.connect(self._on_organize_progress)
        self._organize_worker.done.connect(self._on_organize_done)
        self._organize_worker.start()

    def _on_organize_progress(self, done: int, total: int, eta: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self._set_status(f"Organising… {done}/{total} • ETA {eta}")

    def _on_organize_done(self, stats: dict) -> None:
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)
        self.table.setRowCount(0)
        color = "#F85149" if stats.get("errors") else "#3FB950"
        self._set_status(
            f"✓ {stats['moved']} files organized"
            + (f" • {stats['renamed']} renamed" if stats['renamed'] else "")
            + (f" • {stats['errors']} errors" if stats['errors'] else ""),
            color,
        )
        self._refresh_undo_state()

    # ------------------------------------------------------------------
    def _undo(self) -> None:
        if not self.history.has_sessions():
            return
        n = self.history.last_session_size()
        confirm = QMessageBox.question(
            self, "Confirm Undo", f"Restore {n} file(s) from the last session?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        restored = self.organizer.undo_last_session()
        self._set_status(f"↩ {restored} file(s) restored.", "#D29922")
        self._refresh_undo_state()

    def _refresh_undo_state(self) -> None:
        self.undo_btn.setEnabled(self.history.has_sessions())
        n = self.history.session_count()
        self.undo_btn.setText(f"↩  Undo ({n})" if n else "↩  Undo")

    # ------------------------------------------------------------------
    def _open_workspace(self) -> None:
        if self._workspace_page is None:
            self._workspace_page = WorkspacePage(self.history, self.logger)
            self._workspace_page.backRequested.connect(self._close_workspace)
            self.stack.addWidget(self._workspace_page)
        if self.selected_folder:
            self._workspace_page.load_folder(self.selected_folder)
        self.stack.setCurrentWidget(self._workspace_page)
        self.setWindowTitle("Workspace — Smart File Organizer Pro")

    def _close_workspace(self) -> None:
        self.stack.setCurrentIndex(0)
        self.setWindowTitle("Smart File Organizer Pro")
