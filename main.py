"""SideXSide native Qt entry point."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.main_window import MainWindow


STYLE = """
QWidget { color: #dcdbe3; background: #19181d; font-family: "Inter", "Noto Sans", sans-serif; font-size: 12px; }
QLabel { background: transparent; }
QMainWindow, QSplitter { background: #19181d; }
QWidget#sidebar { background: #1e1e24; border-right: 1px solid #2d2d35; }
QWidget#toolbar { background: #1e1e24; border-bottom: 1px solid #2d2d35; }
QLabel#brand { color: #b9a6f4; font-weight: 700; font-size: 15px; letter-spacing: 2px; padding-bottom: 5px; }
QLabel#sectionLabel { color: #8d8a99; font-weight: 700; font-size: 10px; letter-spacing: 1px; padding-top: 8px; }
QLabel#statValue { color: #efeef4; font-weight: 700; }
QLabel#badge { color: #b9a6f4; background: #282334; border: 1px solid #44385f; border-radius: 9px; padding: 5px 9px; }
QLabel#paneHeading { color: #a9a6b4; background: #1e1e24; border-bottom: 1px solid #2d2d35; padding: 9px 14px; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QPlainTextEdit { background: #141417; color: #e6e2e9; border: 0; selection-background-color: #8a70d6; selection-color: #ffffff; padding: 10px 7px 10px 0; font-family: "Lora", "Noto Serif", "Georgia", serif; font-size: 14px; }
QPushButton, QToolButton { background: #292830; color: #e2e0e8; border: 1px solid #393841; border-radius: 6px; padding: 6px 10px; }
QPushButton:hover, QToolButton:hover { background: #35313f; border-color: #6e5a9f; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked { background: #483a64; border-color: #8a70d6; color: #ffffff; }
QPushButton#primaryButton { background: #51406f; border-color: #715a9c; color: #ffffff; font-weight: 700; text-align: left; }
QPushButton#fileButton { text-align: left; background: #222127; }
QCheckBox { spacing: 6px; color: #bcb9c6; }
QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; background: #292830; border: 1px solid #615b6e; }
QCheckBox::indicator:checked { background: #8a70d6; border-color: #a58de6; }
QListWidget { background: transparent; border: 0; outline: 0; color: #c8c5d0; }
QListWidget::item { border-radius: 5px; padding: 8px 5px; }
QListWidget::item:selected { background: #403552; color: #ffffff; }
QListWidget::item:hover { background: #302b39; }
QScrollBar:vertical { background: #19181d; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #4c4855; min-height: 20px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #78689e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #19181d; height: 9px; }
QScrollBar::handle:horizontal { background: #4c4855; min-width: 20px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #2d2d35; }
QStatusBar { background: #1e1e24; color: #9996a3; border-top: 1px solid #2d2d35; }
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Native, offline Markdown prose difference viewer")
    parser.add_argument("original", nargs="?", help="Original Markdown file")
    parser.add_argument("revised", nargs="?", help="Revised Markdown file")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("SideXSide")
    app.setOrganizationName("SideXSide")
    app.setDesktopFileName("SideXSide")
    # KDE supplies Breeze through Qt's native style plugin when available.
    if "Breeze" in QStyleFactory.keys():
        app.setStyle("Breeze")
    system_palette = app.palette()
    system_dark = (app.styleHints().colorScheme() == Qt.ColorScheme.Dark or
                   system_palette.color(QPalette.ColorRole.Window).lightness() < 128)
    app.setStyleSheet(STYLE)
    if not system_dark:
        # The document surface stays dark even when KDE is in a light session.
        # On Breeze Dark, retain KDE's native palette for dialogs and controls.
        palette = QPalette(system_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor("#19181d"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#141417"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#e6e2e9"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#dcdbe3"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#8a70d6"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)
    window = MainWindow()
    saved = window.settings.value("geometry")
    if saved:
        window.restoreGeometry(saved)
    window.open_paths(args.original, args.revised)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
