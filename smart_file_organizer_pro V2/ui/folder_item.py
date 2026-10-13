"""Graphics item representing a proposed (or existing) organization folder.

Visually styled as a small black-hole / portal: a dark radial gradient
with a glowing rim, since files are conceptually 'pulled into' it.
"""

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPen, QBrush, QRadialGradient
from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem, QMenu

RADIUS = 46
SIZE = RADIUS * 2 + 10


class FolderItem(QGraphicsObject):
    """A draggable, droppable folder ('portal') on the workspace canvas."""

    doubleClicked = Signal(str)          # folder_id
    renameRequested = Signal(str)        # folder_id
    deleteRequested = Signal(str)        # folder_id
    mergeRequested = Signal(str, str)    # src_folder_id, dest_folder_id (this one)

    def __init__(self, folder_id: str, name: str, is_existing: bool = False):
        super().__init__()
        self.folder_id = folder_id
        self.name = name
        self.is_existing = is_existing
        self.file_count = 0
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(-1)   # portals sit behind file cards visually

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, SIZE, SIZE + 22)

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        center = QRectF(5, 5, RADIUS * 2, RADIUS * 2).center()

        grad = QRadialGradient(center, RADIUS)
        if self.is_existing:
            grad.setColorAt(0.0, QColor("#0E1117"))
            grad.setColorAt(0.65, QColor("#1C2128"))
            grad.setColorAt(1.0, QColor("#3FB950"))
        else:
            grad.setColorAt(0.0, QColor("#000000"))
            grad.setColorAt(0.6, QColor("#161B22"))
            grad.setColorAt(1.0, QColor("#00D4FF"))

        painter.setBrush(QBrush(grad))
        pen_color = QColor("#1F6FEB") if self.isSelected() else QColor("#30363D")
        painter.setPen(QPen(pen_color, 2))
        painter.drawEllipse(QRectF(5, 5, RADIUS * 2, RADIUS * 2))

        painter.setFont(QFont("Segoe UI Semibold", 9))
        painter.setPen(QPen(QColor("#E6EDF3")))
        label = self.name if len(self.name) <= 14 else self.name[:12] + "…"
        painter.drawText(QRectF(0, RADIUS * 2 + 6, SIZE, 18),
                          Qt.AlignmentFlag.AlignCenter, label)

        if self.file_count:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#8B949E")))
            painter.drawText(QRectF(0, RADIUS * 2 + 22, SIZE, 14),
                              Qt.AlignmentFlag.AlignCenter, f"{self.file_count} file(s)")

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit(self.folder_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu()
        rename_act = menu.addAction("Rename")
        delete_act = menu.addAction("Delete (files stay unassigned)")
        chosen = menu.exec(event.screenPos())
        if chosen == rename_act:
            self.renameRequested.emit(self.folder_id)
        elif chosen == delete_act:
            self.deleteRequested.emit(self.folder_id)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None:
            return
        for other in self.collidingItems():
            if isinstance(other, FolderItem):
                self.mergeRequested.emit(other.folder_id, self.folder_id)
                break
