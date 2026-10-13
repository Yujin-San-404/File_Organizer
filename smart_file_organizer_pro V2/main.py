"""Smart File Organizer Pro — v2 (PySide6) entry point."""

import sys

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow, STYLE


def _dark_palette() -> QPalette:
    """
    A real QPalette (not just a stylesheet) so every widget — including
    native dialogs, dropdown popups, and checkboxes that stylesheets
    sometimes miss — renders with readable, consistent colors regardless
    of the OS's own dark/light theme.
    """
    p = QPalette()
    bg, base, text, accent = QColor("#0E1117"), QColor("#161B22"), QColor("#F0F6FC"), QColor("#00D4FF")
    disabled_text = QColor("#6E7681")

    p.setColor(QPalette.ColorRole.Window, bg)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#1C2128"))
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor("#1C2128"))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor("#F85149"))
    p.setColor(QPalette.ColorRole.Link, accent)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#0E1117"))

    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    return p


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Smart File Organizer Pro")
    # Fusion + an explicit dark palette renders consistently across
    # Windows/macOS/Linux, instead of inheriting whatever native theme
    # the OS is in (which is what was causing dark-on-dark text).
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
