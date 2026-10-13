"""Workspace Mode: a visual, manual, draggable file-organization canvas.

Nothing is written to disk until the user clicks 'Apply Organization'.
"""

import random
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QThread, Signal, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsScene,
    QGraphicsView, QPushButton, QLabel, QFileDialog, QInputDialog,
    QMessageBox, QFrame, QComboBox,
)

from core.workspace_plan import WorkspacePlan
from core.history import HistoryManager, CancelToken
from core.file_operations import ConflictAction

from .file_item import FileItem
from .folder_item import FolderItem, SIZE as FOLDER_SIZE

SCENE_W, SCENE_H = 3000, 2000


class ApplyWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(dict)

    def __init__(self, plan: WorkspacePlan, history: HistoryManager,
                 conflict_action: str, cancel: CancelToken):
        super().__init__()
        self.plan = plan
        self.history = history
        self.conflict_action = conflict_action
        self.cancel = cancel

    def run(self) -> None:
        stats = self.plan.apply(
            self.history, conflict_action=self.conflict_action,
            cancel=self.cancel,
            progress_cb=lambda d, t: self.progress.emit(d, t),
        )
        self.finished_ok.emit(stats)


class WorkspacePage(QWidget):
    """
    The interactive canvas, embedded as a page inside the main window's
    QStackedWidget (not a separate top-level window) — 'Workspace' swaps
    the whole window's content in place, and 'Back' swaps it back.
    """

    backRequested = Signal()

    def __init__(self, history: HistoryManager, logger, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.history = history
        self.logger = logger
        self.plan: Optional[WorkspacePlan] = None
        self.cancel_token = CancelToken()

        self._file_items: dict[str, FileItem] = {}
        self._folder_items: dict[str, FolderItem] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setStyleSheet("background:#161B22; border-bottom:1px solid #30363D;")
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(12, 8, 12, 8)

        back_btn = QPushButton("←  Back to Organizer")
        back_btn.clicked.connect(self.backRequested.emit)
        top_l.addWidget(back_btn)

        self.folder_label = QLabel("No folder loaded — click Open Folder to begin")
        self.folder_label.setStyleSheet("color:#9AA4AF; font-weight:600;")
        top_l.addWidget(self.folder_label)
        top_l.addStretch()

        open_btn = QPushButton("📂  Open Folder")
        open_btn.clicked.connect(self._open_folder)
        top_l.addWidget(open_btn)

        add_folder_btn = QPushButton("🕳️  Add Folder")
        add_folder_btn.clicked.connect(self._add_folder)
        top_l.addWidget(add_folder_btn)

        layout.addWidget(top)

        # Canvas
        self.scene = QGraphicsScene(0, 0, SCENE_W, SCENE_H)
        self.scene.setBackgroundBrush(QColor("#0E1117"))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(self.view.renderHints())
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setRenderHints(self.view.renderHints())
        layout.addWidget(self.view, stretch=1)

        # Bottom bar
        bottom = QFrame()
        bottom.setStyleSheet("background:#161B22; border-top:1px solid #30363D;")
        bottom_l = QHBoxLayout(bottom)
        bottom_l.setContentsMargins(12, 8, 12, 8)

        self.summary_label = QLabel("0 files  •  0 folders to create  •  0 duplicates")
        self.summary_label.setStyleSheet("color:#9AA4AF; font-weight:600;")
        bottom_l.addWidget(self.summary_label)
        bottom_l.addStretch()

        bottom_l.addWidget(QLabel("On conflict:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["Rename", "Replace", "Skip"])
        bottom_l.addWidget(self.conflict_combo)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.backRequested.emit)
        bottom_l.addWidget(cancel_btn)

        self.apply_btn = QPushButton("✓  Apply Organization")
        self.apply_btn.setStyleSheet(
            "QPushButton{background:#3FB950;color:#0E1117;font-weight:600;padding:6px 14px;border-radius:6px;}"
        )
        self.apply_btn.clicked.connect(self._apply)
        bottom_l.addWidget(self.apply_btn)

        layout.addWidget(bottom)

    # ------------------------------------------------------------------
    def load_folder(self, folder: Path) -> None:
        self.plan = WorkspacePlan(folder, self.logger)
        self.plan.load_folder()
        self.folder_label.setText(f"✓  {folder}")
        self.folder_label.setStyleSheet("color:#3FB950; font-weight:600;")
        self._render_scene()

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open folder in Workspace")
        if folder:
            self.load_folder(Path(folder))

    # ------------------------------------------------------------------
    # Rendering: rebuild graphics items from the plan's current state
    # ------------------------------------------------------------------
    def _render_scene(self) -> None:
        if self.plan is None:
            return
        self.scene.clear()
        self._file_items.clear()
        self._folder_items.clear()

        rnd = random.Random(42)

        # Folders first (lower z), arranged along the top
        fx = 40
        for fo in self.plan.folders.values():
            item = FolderItem(fo.id, fo.name, is_existing=fo.existing_path is not None)
            item.setPos(fx, 30)
            item.file_count = sum(1 for f in self.plan.files.values() if f.folder_id == fo.id)
            item.doubleClicked.connect(self._on_folder_opened)
            item.renameRequested.connect(self._on_folder_rename)
            item.deleteRequested.connect(self._on_folder_delete)
            item.mergeRequested.connect(self._on_folder_merge)
            self.scene.addItem(item)
            self._folder_items[fo.id] = item
            fx += FOLDER_SIZE + 30

        # Unassigned files scattered in the open canvas area
        ux, uy = 60, 220
        col = 0
        for f in self.plan.files.values():
            if f.folder_id is not None:
                continue
            item = FileItem(f.id, f.name, f.category if hasattr(f, "category") else self._guess_category(f), False)
            item.setPos(ux + col * 110, uy + rnd.randint(-10, 10))
            item.droppedOnFolder.connect(self._on_file_dropped)
            self.scene.addItem(item)
            self._file_items[f.id] = item
            col += 1
            if col > 20:
                col = 0
                uy += 130

        self._update_summary()

    def _guess_category(self, f) -> str:
        from core.categories import DEFAULT_CATEGORIES
        for cat, exts in DEFAULT_CATEGORIES.items():
            if f.ext in exts:
                return cat
        return "Others"

    # ------------------------------------------------------------------
    # Interaction callbacks
    # ------------------------------------------------------------------
    def _add_folder(self) -> None:
        if self.plan is None:
            QMessageBox.information(self, "No Folder", "Open a folder first.")
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            self.plan.create_folder(name.strip())
            self._render_scene()

    def _on_folder_opened(self, folder_id: str) -> None:
        if self.plan is None:
            return
        self.plan.open_existing_folder(folder_id)
        self._render_scene()

    def _on_folder_rename(self, folder_id: str) -> None:
        if self.plan is None:
            return
        current = self.plan.folders[folder_id].name
        name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=current)
        if ok and name.strip():
            self.plan.rename_folder(folder_id, name.strip())
            self._render_scene()

    def _on_folder_delete(self, folder_id: str) -> None:
        if self.plan is None:
            return
        self.plan.delete_folder(folder_id)
        self._render_scene()

    def _on_folder_merge(self, src_id: str, dest_id: str) -> None:
        if self.plan is None:
            return
        self.plan.merge_folders(src_id, dest_id)
        self._render_scene()

    def _on_file_dropped(self, file_id: str, folder_id: str) -> None:
        if self.plan is None:
            return
        # Move every selected file card, not just the one under the cursor.
        selected_ids = [fid for fid, item in self._file_items.items() if item.isSelected()]
        ids = selected_ids if file_id in selected_ids and len(selected_ids) > 1 else [file_id]
        self.plan.assign_files(ids, folder_id)
        self._render_scene()

    # ------------------------------------------------------------------
    def _update_summary(self) -> None:
        if self.plan is None:
            return
        s = self.plan.summary()
        self.summary_label.setText(
            f"{s['files_to_move']} files will move  •  "
            f"{s['folders_to_create']} folder(s) to create  •  "
            f"{s['duplicates']} duplicate(s)"
        )

    # ------------------------------------------------------------------
    def _apply(self) -> None:
        if self.plan is None:
            return
        s = self.plan.summary()
        if s["files_to_move"] == 0:
            QMessageBox.information(self, "Nothing To Apply", "No files are assigned to a folder yet.")
            return
        confirm = QMessageBox.question(
            self, "Apply Organization",
            f"Move {s['files_to_move']} file(s) into {s['folders_to_create']} new "
            f"folder(s) (plus existing ones)?\n\nThis cannot be undone from here, "
            f"but the main window's Undo can restore it afterwards.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        conflict_map = {
            "Rename": ConflictAction.RENAME,
            "Replace": ConflictAction.REPLACE,
            "Skip": ConflictAction.SKIP,
        }
        conflict_action = conflict_map[self.conflict_combo.currentText()]

        self.apply_btn.setEnabled(False)
        self.cancel_token.reset()
        self._worker = ApplyWorker(self.plan, self.history, conflict_action, self.cancel_token)
        self._worker.finished_ok.connect(self._on_applied)
        self._worker.start()

    def _on_applied(self, stats: dict) -> None:
        self.apply_btn.setEnabled(True)
        QMessageBox.information(
            self, "Organization Applied",
            f"✓ {stats['moved']} file(s) moved"
            + (f", {stats['renamed']} renamed" if stats['renamed'] else "")
            + (f", {stats['errors']} error(s)" if stats['errors'] else ""),
        )
        if self.plan is not None:
            self.load_folder(self.plan.root)
