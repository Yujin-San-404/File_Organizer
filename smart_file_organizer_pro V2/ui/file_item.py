"""Draggable graphics item representing one file in Workspace Mode."""

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem

EXT_ICONS = {
    "images": "🖼", "papers": "📄", "videos": "🎬", "audio": "🎵",
    "code": "💻", "scripts": "📜", "configuration": "⚙", "logs": "🧾",
    "archives": "📦", "disk images": "💽", "executables": "⚡",
    "fonts": "🔤", "design files": "🎨", "3d models": "🧊", "cad": "📐",
    "databases": "🗄", "certificates": "🔐", "e-books": "📚",
    "others": "📁",
}

WIDTH, HEIGHT = 92, 100


def icon_for_category(category: str) -> str:
    return EXT_ICONS.get(category.lower(), "📄")


class FileItem(QGraphicsObject):
    """A single draggable file 'card' on the workspace canvas."""

    droppedOnFolder = Signal(str, str)   # file_id, folder_id

    def __init__(self, file_id: str, name: str, category: str, is_dup: bool = False):
        super().__init__()
        self.file_id = file_id
        self.name = name
        self.category = category
        self.is_dup = is_dup
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._hover = False

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, WIDTH, HEIGHT)

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing)

        card_rect = QRectF(2, 2, WIDTH - 4, HEIGHT - 4)
        bg = QColor("#1C2128") if not self.isSelected() else QColor("#1F6FEB")
        painter.setBrush(QBrush(bg))
        border = QColor("#F85149") if self.is_dup else QColor("#30363D")
        painter.setPen(QPen(border, 1.4))
        painter.drawRoundedRect(card_rect, 10, 10)

        painter.setFont(QFont("Segoe UI Emoji", 22))
        painter.setPen(QPen(QColor("#00D4FF")))
        painter.drawText(QRectF(0, 8, WIDTH, 34), Qt.AlignmentFlag.AlignCenter,
                          icon_for_category(self.category))

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor("#E6EDF3")))
        label = self.name if len(self.name) <= 14 else self.name[:11] + "…"
        painter.drawText(QRectF(2, 46, WIDTH - 4, 34), Qt.AlignmentFlag.AlignCenter |
                          Qt.TextFlag.TextWordWrap, label)

        if self.is_dup:
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QPen(QColor("#F85149")))
            painter.drawText(QRectF(0, HEIGHT - 16, WIDTH, 14),
                              Qt.AlignmentFlag.AlignCenter, "duplicate")

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.setScale(1.05)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.setScale(1.0)
        super().hoverLeaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None:
            return
        # Any FolderItem this card (or a sibling in the same drag) overlaps -> drop.
        from .folder_item import FolderItem
        targets = [self] + [it for it in scene.selectedItems() if it is not self]
        for card in targets:
            if not isinstance(card, FileItem):
                continue
            colliding = card.collidingItems()
            for other in colliding:
                if isinstance(other, FolderItem):
                    self.droppedOnFolder.emit(card.file_id, other.folder_id)
                    break
