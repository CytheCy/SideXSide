"""Editable two-pane prose comparison window."""

from __future__ import annotations

from bisect import bisect_right
import json
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QRect, QRunnable, QSettings, QSignalBlocker, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollBar, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from prose_diff import Block, DiffResult, Span, compare


DEFAULT_DOCUMENT_FONT_SIZE = 14
MIN_DOCUMENT_FONT_SIZE = 8
MAX_DOCUMENT_FONT_SIZE = 32
SIDEBAR_EDGE_WIDTH = 12
SIDEBAR_WIDTH = 220


def _format(kind: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    colors = {
        "insert": (QColor(80, 250, 123, 58), QColor(31, 145, 72)),
        "delete": (QColor(255, 85, 85, 58), QColor(220, 77, 77)),
        "replace": (QColor(241, 250, 140, 58), QColor(193, 183, 73)),
    }
    background, accent = colors[kind]
    fmt.setBackground(background)
    fmt.setUnderlineColor(accent)
    fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
    if kind == "delete":
        fmt.setFontStrikeOut(True)
    return fmt


class DiffHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.spans: tuple[Span, ...] = ()
        self.ends: list[int] = []
        self.formats = {kind: _format(kind) for kind in ("insert", "delete", "replace")}

    def set_spans(self, spans: tuple[Span, ...]) -> None:
        self.spans = tuple(sorted(spans, key=lambda span: (span.start, span.end)))
        self.ends = [span.end for span in self.spans]
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        block_start = self.currentBlock().position()
        block_end = block_start + len(text)
        index = bisect_right(self.ends, block_start)
        while index < len(self.spans) and self.spans[index].start < block_end:
            span = self.spans[index]
            start = max(span.start, block_start)
            end = min(span.end, block_end)
            if end > start:
                self.setFormat(start - block_start, end - start, self.formats[span.kind])
            index += 1


class LineNumberArea(QWidget):
    def __init__(self, editor: "ProseEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#19181d"))
        block = self.editor.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.editor.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                kind = self.editor.diff_lines.get(number)
                if kind:
                    accent = {"insert": "#50fa7b", "delete": "#ff5555", "replace": "#f1fa8c"}[kind]
                    painter.fillRect(self.width() - 3, top + 2, 2, max(2, height - 4), QColor(accent))
                painter.setPen(QColor("#777582") if number + 1 == self.editor.textCursor().blockNumber() + 1 else QColor("#575660"))
                painter.drawText(0, top, self.width() - 8, self.editor.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            top += height
            block = block.next()
            number += 1


class ProseEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self.line_area.update)
        self._update_gutter_width()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setPlaceholderText("Open a Markdown file, or start typing…")
        self.diff_lines: dict[int, str] = {}
        self.highlighter = DiffHighlighter(self.document())
        self.selected_diff: tuple[int, int] | None = None

    def set_selected_diff(self, start: int | None, end: int | None):
        self.selected_diff = (start, end) if start is not None and end is not None else None
        self.viewport().update()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if self.selected_diff is None:
            return
        start, end = self.selected_diff
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if start == end:
            caret = QTextCursor(self.document())
            caret.setPosition(start)
            rect = self.cursorRect(caret)
            painter.drawRect(QRect(rect.x() - 2, rect.y(), 7, rect.height() - 1))
            return
        lines: dict[int, list[int]] = {}
        cursor = QTextCursor(self.document())
        for position in range(start, end):
            cursor.setPosition(position)
            rect = self.cursorRect(cursor)
            if rect.bottom() < event.rect().top() or rect.top() > event.rect().bottom():
                continue
            cursor.setPosition(position + 1)
            following = self.cursorRect(cursor)
            width = following.x() - rect.x() if following.y() == rect.y() else 7
            right = rect.x() + max(7, width)
            bounds = lines.setdefault(rect.y(), [rect.x(), right, rect.height()])
            bounds[0] = min(bounds[0], rect.x())
            bounds[1] = max(bounds[1], right)
        for y, (left, right, height) in lines.items():
            painter.drawRect(QRect(left - 2, y, right - left + 3, height - 1))

    def set_document_font_size(self, size: int):
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._update_gutter_width()
        rect = self.contentsRect()
        self.line_area.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))
        self.line_area.update()

    def set_diff_spans(self, spans: tuple[Span, ...]):
        self.highlighter.set_spans(spans)
        self.diff_lines = {}
        for span in spans:
            first = self.document().findBlock(span.start).blockNumber()
            last = self.document().findBlock(max(span.start, span.end - 1)).blockNumber()
            for number in range(first, last + 1):
                self.diff_lines[number] = span.kind
        self.line_area.update()

    def gutter_width(self) -> int:
        return 19 + self.fontMetrics().horizontalAdvance("9") * len(str(max(1, self.blockCount())))

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(0, rect.y(), self.line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.line_area.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))


class Connector(QWidget):
    """Quiet curves make corresponding paragraph positions visible."""

    def __init__(self, left: ProseEditor, right: ProseEditor):
        super().__init__()
        self.left, self.right = left, right
        self.result: DiffResult | None = None
        self.result_revision = -1
        self.setFixedWidth(28)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#19181d"))
        if self.result is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(138, 112, 214, 82), 1))
        for li, ri in self.result.alignments:
            left_block = self.left.document().findBlockByNumber(self.result.left_blocks[li].line - 1)
            right_block = self.right.document().findBlockByNumber(self.result.right_blocks[ri].line - 1)
            if not left_block.isValid() or not right_block.isValid():
                continue
            y1 = self.left.blockBoundingGeometry(left_block).translated(self.left.contentOffset()).top() + 8
            y2 = self.right.blockBoundingGeometry(right_block).translated(self.right.contentOffset()).top() + 8
            if max(y1, y2) < -20 or min(y1, y2) > self.height() + 20:
                continue
            path = QPainterPath()
            path.moveTo(0, y1)
            path.cubicTo(10, y1, 18, y2, 28, y2)
            painter.drawPath(path)


class DiffSignals(QObject):
    finished = Signal(int, object)


class DiffTask(QRunnable):
    def __init__(self, revision: int, left: str, right: str, ignore: bool, strict: bool):
        super().__init__()
        self.revision, self.left, self.right = revision, left, right
        self.ignore, self.strict = ignore, strict
        self.signals = DiffSignals()

    def run(self):
        result = compare(self.left, self.right, ignore_whitespace=self.ignore, strict_markdown=self.strict)
        self.signals.finished.emit(self.revision, result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SideXSide")
        self.resize(1450, 900)
        self.settings = QSettings("SideXSide", "SideXSide")
        try:
            saved_size = int(self.settings.value("document_font_size", DEFAULT_DOCUMENT_FONT_SIZE))
        except (TypeError, ValueError):
            saved_size = DEFAULT_DOCUMENT_FONT_SIZE
        self.document_font_size = max(MIN_DOCUMENT_FONT_SIZE, min(MAX_DOCUMENT_FONT_SIZE, saved_size))
        self.paths: list[Path | None] = [None, None]
        self.dirty = [False, False]
        self.final_side = 1
        self.sidebar_pinned = False
        self._sidebar_width = SIDEBAR_WIDTH
        try:
            self.recent: list[list[str]] = json.loads(self.settings.value("recent", "[]"))
        except (TypeError, ValueError):
            self.recent = []
        self.result: DiffResult | None = None
        self.revision = 0
        self.current_change = -1
        self._action_undo_sides: list[int] = []
        self._action_redo_sides: list[int] = []
        self._last_edited_side: int | None = None
        self._applying_change = False
        self._running_undo_redo = False
        self._syncing = False
        self._running = False
        self._opening_pair = False
        self._updating_unified = False
        self._reload_pending: set[str] = set()
        self._task: DiffTask | None = None
        self.pool = QThreadPool.globalInstance()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed)
        self.watcher.directoryChanged.connect(self._directory_changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._start_diff)
        self._build_ui()
        self.sidebar_hover_timer = QTimer(self)
        self.sidebar_hover_timer.setInterval(100)
        self.sidebar_hover_timer.timeout.connect(self._update_sidebar_hover)
        self.sidebar_hover_timer.start()
        self._refresh_recent()
        self._schedule_diff()

    def _build_ui(self):
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setChildrenCollapsible(False)
        self.root_splitter = root
        self.setCentralWidget(root)

        sidebar = QWidget()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 15, 14, 14)
        side_layout.setSpacing(12)
        title = QLabel("SIDEXSIDE")
        title.setObjectName("brand")
        side_layout.addWidget(title)
        new_button = QPushButton("＋  New Session")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self.new_session)
        side_layout.addWidget(new_button)
        side_layout.addWidget(self._section_label("RECENT PAIRS"))
        self.recent_list = QListWidget()
        self.recent_list.itemActivated.connect(self._open_recent)
        side_layout.addWidget(self.recent_list, 1)
        side_layout.addWidget(self._section_label("DOCUMENT STATS"))
        self.stats = {}
        for key, label in (("original", "Original words"), ("revised", "Revised words"),
                           ("net", "Net difference"), ("edits", "Total edits")):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 2, 0, 2)
            layout.addWidget(QLabel(label))
            value = QLabel("0")
            value.setObjectName("statValue")
            layout.addWidget(value, alignment=Qt.AlignmentFlag.AlignRight)
            side_layout.addWidget(row)
            self.stats[key] = value
        root.addWidget(sidebar)
        root.setCollapsible(0, True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(15, 10, 15, 10)
        toolbar_layout.setSpacing(8)
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        sidebar_button = QToolButton()
        sidebar_button.setText("☰")
        sidebar_button.setToolTip("Keep sidebar open or hide it (Ctrl+B)")
        sidebar_button.clicked.connect(self.toggle_sidebar)
        file_row.addWidget(sidebar_button)
        self.file_buttons = []
        for side, text in enumerate(("Original (Before)", "Revised (After)")):
            button = QPushButton(text + "  ·  Choose file…")
            button.setObjectName("fileButton")
            button.setToolTip("Open a Markdown file")
            button.clicked.connect(lambda _=False, s=side: self.choose_file(s))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            file_row.addWidget(button, 1)
            self.file_buttons.append(button)
        toolbar_layout.addLayout(file_row)

        final_row = QHBoxLayout()
        final_row.setSpacing(8)
        final_row.addWidget(QLabel("Final file:"))
        self.final_file_combo = QComboBox()
        self.final_file_combo.addItem("Original (Before)", 0)
        self.final_file_combo.addItem("Revised (After)", 1)
        self.final_file_combo.setCurrentIndex(self.final_side)
        self.final_file_combo.setToolTip("Choose the file you can edit and save")
        self.final_file_combo.currentIndexChanged.connect(self._set_final_side)
        final_row.addWidget(self.final_file_combo, 1)
        self.save_button = QPushButton("Save Final")
        self.save_button.clicked.connect(lambda: self.save_file(self.final_side))
        final_row.addWidget(self.save_button)
        toolbar_layout.addLayout(final_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.side_button = QToolButton()
        self.side_button.setText("Side-by-Side")
        self.side_button.setCheckable(True)
        self.side_button.setChecked(True)
        self.side_button.clicked.connect(lambda: self._set_mode(False))
        self.inline_button = QToolButton()
        self.inline_button.setText("Unified Inline")
        self.inline_button.setCheckable(True)
        self.inline_button.clicked.connect(lambda: self._set_mode(True))
        controls.addWidget(self.side_button)
        controls.addWidget(self.inline_button)
        self.ignore_box = QCheckBox("Ignore whitespace / spacing")
        self.ignore_box.toggled.connect(self._schedule_diff)
        controls.addWidget(self.ignore_box)
        self.strict_box = QCheckBox("Strict Markdown")
        self.strict_box.toggled.connect(self._schedule_diff)
        controls.addWidget(self.strict_box)
        controls.addStretch()
        self.accept_button = QPushButton()
        self.accept_button.clicked.connect(lambda: self.apply_change(self.final_side))
        controls.addWidget(self.accept_button)
        self.use_all_button = QPushButton("Use All")
        self.use_all_button.setToolTip("Apply all remaining differences to the final document")
        self.use_all_button.setEnabled(False)
        self.use_all_button.clicked.connect(self.apply_all_changes)
        controls.addWidget(self.use_all_button)
        self.discard_button = QPushButton("Discard Change")
        self.discard_button.setToolTip("Make the comparison document match the final document at this difference")
        self.discard_button.clicked.connect(lambda: self.apply_change(1 - self.final_side))
        controls.addWidget(self.discard_button)
        previous = QPushButton("← Previous")
        previous.clicked.connect(lambda: self.navigate(-1))
        controls.addWidget(previous)
        self.diff_badge = QLabel("Diff 0 of 0")
        self.diff_badge.setObjectName("badge")
        controls.addWidget(self.diff_badge)
        following = QPushButton("Next →")
        following.clicked.connect(lambda: self.navigate(1))
        controls.addWidget(following)
        toolbar_layout.addLayout(controls)
        content_layout.addWidget(toolbar)

        self.stack = QStackedWidget()
        self.panes = QSplitter(Qt.Orientation.Horizontal)
        self.panes.setChildrenCollapsible(False)
        self.editors: list[ProseEditor] = []
        self.pane_headings: list[QLabel] = []
        wrappers = []
        for side, title_text in enumerate(("ORIGINAL  /  BEFORE", "REVISED  /  AFTER")):
            wrapper = QWidget()
            layout = QVBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            heading = QLabel(title_text)
            heading.setObjectName("paneHeading")
            layout.addWidget(heading)
            editor = ProseEditor()
            editor.textChanged.connect(lambda s=side: self._text_changed(s))
            editor.cursorPositionChanged.connect(lambda s=side: self._cursor_at_change(s))
            editor.verticalScrollBar().valueChanged.connect(lambda _value, s=side: self._sync_scroll(s))
            layout.addWidget(editor)
            self.editors.append(editor)
            self.pane_headings.append(heading)
            wrappers.append(wrapper)
        self._update_final_side_ui()
        self.connector = Connector(*self.editors)
        self.panes.addWidget(wrappers[0])
        self.panes.addWidget(self.connector)
        self.panes.addWidget(wrappers[1])
        self.panes.setStretchFactor(0, 1)
        self.panes.setStretchFactor(2, 1)
        self.stack.addWidget(self.panes)
        self.unified = ProseEditor()
        self.unified.setReadOnly(True)
        self.unified.cursorPositionChanged.connect(self._unified_cursor_at_change)
        for editor in (*self.editors, self.unified):
            editor.set_document_font_size(self.document_font_size)
        self.unified_positions: dict[tuple[int | None, int | None], int] = {}
        self.unified_source_map: list[tuple[int, int, int, int]] = []
        self.stack.addWidget(self.unified)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content)
        root.setStretchFactor(1, 1)
        root.setSizes([0, 1230])

        QShortcut(QKeySequence("F7"), self, activated=lambda: self.navigate(1))
        QShortcut(QKeySequence("Shift+F7"), self, activated=lambda: self.navigate(-1))
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_change)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_change)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo_change)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)
        for sequence in ("Ctrl++", "Ctrl+=", "Ctrl+Shift++", "Ctrl+Shift+="):
            QShortcut(QKeySequence(sequence), self, activated=lambda: self.change_document_font_size(1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.change_document_font_size(-1))
        self.statusBar()

    def change_document_font_size(self, step: int):
        size = max(MIN_DOCUMENT_FONT_SIZE, min(MAX_DOCUMENT_FONT_SIZE, self.document_font_size + step))
        if size == self.document_font_size:
            return
        self.document_font_size = size
        for editor in (*self.editors, self.unified):
            editor.set_document_font_size(size)
        self.connector.update()
        self.settings.setValue("document_font_size", size)

    def toggle_sidebar(self):
        visible = self.root_splitter.sizes()[0] > 0
        self.sidebar_pinned = not visible
        self._set_sidebar_visible(not visible)

    def _set_sidebar_visible(self, visible: bool):
        sizes = self.root_splitter.sizes()
        currently_visible = sizes[0] > 0
        if visible == currently_visible:
            return
        total = sum(sizes)
        if visible:
            self.root_splitter.setSizes([self._sidebar_width, max(0, total - self._sidebar_width)])
        else:
            self._sidebar_width = sizes[0]
            self.root_splitter.setSizes([0, total])

    def _update_sidebar_hover(self):
        if self.isVisible() and not self.sidebar_pinned:
            self._update_sidebar_for_position(self.mapFromGlobal(QCursor.pos()))

    def _update_sidebar_for_position(self, position):
        if self.sidebar_pinned:
            return
        area = self.root_splitter.geometry()
        if not area.contains(position):
            self._set_sidebar_visible(False)
            return
        x = position.x() - area.x()
        if x <= SIDEBAR_EDGE_WIDTH:
            self._set_sidebar_visible(True)
        elif x > self.root_splitter.sizes()[0] + SIDEBAR_EDGE_WIDTH:
            self._set_sidebar_visible(False)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _set_mode(self, inline: bool):
        self.side_button.setChecked(not inline)
        self.inline_button.setChecked(inline)
        self.stack.setCurrentIndex(1 if inline else 0)
        if inline and self.result:
            self._update_unified(self.result)

    def _set_final_side(self, index: int):
        side = self.final_file_combo.itemData(index)
        if side not in (0, 1):
            return
        self.final_side = side
        self._update_final_side_ui()

    def _update_final_side_ui(self):
        for side, editor in enumerate(self.editors):
            editor.setReadOnly(side != self.final_side)
            title = "ORIGINAL  /  BEFORE" if side == 0 else "REVISED  /  AFTER"
            role = "FINAL · EDITABLE" if side == self.final_side else "READ ONLY"
            heading = self.pane_headings[side]
            heading.setText(f"{title}  ·  {role}")
            heading.setProperty("isFinal", side == self.final_side)
            heading.style().unpolish(heading)
            heading.style().polish(heading)
            heading.update()
        self.save_button.setToolTip(f"Save the selected final file ({'Original' if self.final_side == 0 else 'Revised'})")
        self.accept_button.setText("→ Use Comparison" if self.final_side == 1 else "← Use Comparison")
        self.accept_button.setToolTip("Make the final document match the comparison document at this difference")

    def _text_changed(self, side: int):
        self._last_edited_side = side
        if not self._applying_change and not self._running_undo_redo:
            self._action_undo_sides.clear()
            self._action_redo_sides.clear()
        self.dirty[side] = True
        self._update_file_button(side)
        self._schedule_diff()

    def _schedule_diff(self, *_):
        self.revision += 1
        if hasattr(self, "accept_button"):
            self._clear_change_selection()
        self.timer.start()

    def _start_diff(self):
        if self._running:
            return
        task = DiffTask(self.revision, self.editors[0].toPlainText(), self.editors[1].toPlainText(),
                        self.ignore_box.isChecked(), self.strict_box.isChecked())
        task.signals.finished.connect(self._finish_diff)
        self._task = task
        self._running = True
        self.pool.start(task)

    def _finish_diff(self, revision: int, result: DiffResult):
        self._running = False
        if revision != self.revision:
            if not self.timer.isActive():
                self._start_diff()
            return
        state = [(QTextCursor(editor.textCursor()), self._scroll_fraction(editor.verticalScrollBar()))
                 for editor in self.editors]
        self.result = result
        self.result_revision = revision
        with QSignalBlocker(self.editors[0]), QSignalBlocker(self.editors[1]):
            self.editors[0].set_diff_spans(result.left_spans)
            self.editors[1].set_diff_spans(result.right_spans)
            for editor, (cursor, fraction) in zip(self.editors, state):
                editor.setTextCursor(cursor)
                self._set_scroll_fraction(editor.verticalScrollBar(), fraction)
        self.connector.result = result
        self.connector.update()
        self.stats["original"].setText(f"{result.left_words:,}")
        self.stats["revised"].setText(f"{result.right_words:,}")
        net = result.right_words - result.left_words
        self.stats["net"].setText(f"{net:+,}")
        self.stats["edits"].setText(f"{result.edit_count:,}")
        self._select_change(-1)
        if self.stack.currentIndex() == 1:
            self._update_unified(result)
        if self.stack.currentIndex() == 1 and self.unified.hasFocus():
            self._unified_cursor_at_change()
        else:
            for side, editor in enumerate(self.editors):
                if editor.hasFocus():
                    self._cursor_at_change(side)
                    break

    @staticmethod
    def _scroll_fraction(bar: QScrollBar) -> float:
        span = bar.maximum() - bar.minimum()
        return (bar.value() - bar.minimum()) / span if span else 0.0

    @staticmethod
    def _set_scroll_fraction(bar: QScrollBar, fraction: float):
        bar.setValue(bar.minimum() + round(fraction * (bar.maximum() - bar.minimum())))

    def _sync_scroll(self, side: int):
        if self._syncing:
            return
        self._syncing = True
        try:
            source = self.editors[side].verticalScrollBar()
            target = self.editors[1 - side].verticalScrollBar()
            self._set_scroll_fraction(target, self._scroll_fraction(source))
            self.connector.update()
        finally:
            self._syncing = False

    def _update_badge(self):
        count = self.result.edit_count if self.result else 0
        self.diff_badge.setText(f"Diff {self.current_change + 1 if self.current_change >= 0 else 0} of {count}")

    def _clear_change_selection(self):
        self.current_change = -1
        for editor in self.editors:
            editor.set_selected_diff(None, None)
        self.accept_button.setEnabled(False)
        self.discard_button.setEnabled(False)
        self.use_all_button.setEnabled(
            self.result is not None and self.result_revision == self.revision and self.result.edit_count > 0
        )
        self._update_badge()

    def _select_change(self, index: int):
        if self.result is None or not 0 <= index < self.result.edit_count:
            self._clear_change_selection()
            return
        self.current_change = index
        change = self.result.changes[index]
        self.editors[0].set_selected_diff(change.left_offset, change.left_end)
        self.editors[1].set_selected_diff(change.right_offset, change.right_end)
        self.accept_button.setEnabled(True)
        self.discard_button.setEnabled(True)
        self._update_badge()

    def _cursor_at_change(self, side: int):
        if self.result is None or self.result_revision != self.revision:
            return
        position = self.editors[side].textCursor().position()
        self._select_change_at_position(side, position)

    def _select_change_at_position(self, side: int, position: int):
        for index, change in enumerate(self.result.changes):
            start, end = ((change.left_offset, change.left_end) if side == 0
                          else (change.right_offset, change.right_end))
            if start is not None and (start <= position < end or start == end == position):
                self._select_change(index)
                return
        self._select_change(-1)

    def _unified_cursor_at_change(self):
        if self._updating_unified or self.result is None or self.result_revision != self.revision:
            return
        position = self.unified.textCursor().position()
        for side, start, end, target in self.unified_source_map:
            if target <= position < target + end - start:
                self._select_change_at_position(side, start + position - target)
                return
        self._select_change(-1)

    def apply_change(self, target_side: int):
        if (self.result is None or self.result_revision != self.revision
                or not 0 <= self.current_change < self.result.edit_count):
            return
        change = self.result.changes[self.current_change]
        if target_side == 0:
            start, end = change.left_offset, change.left_end
            source_start, source_end = change.right_offset, change.right_end
        else:
            start, end = change.right_offset, change.right_end
            source_start, source_end = change.left_offset, change.left_end
        if None in (start, end, source_start, source_end):
            return
        replacement = self.editors[1 - target_side].toPlainText()[source_start:source_end]
        cursor = QTextCursor(self.editors[target_side].document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._applying_change = True
        try:
            cursor.beginEditBlock()
            cursor.insertText(replacement)
            cursor.endEditBlock()
        finally:
            self._applying_change = False
        self._action_undo_sides.append(target_side)
        self._action_redo_sides.clear()
        self.statusBar().showMessage("Difference applied to final document" if target_side == self.final_side
                                     else "Difference discarded in comparison document")

    def apply_all_changes(self):
        if self.result is None or self.result_revision != self.revision or not self.result.changes:
            return
        revision = self.revision
        answer = QMessageBox.question(
            self, "Use all changes", "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if (answer != QMessageBox.StandardButton.Yes or self.revision != revision
                or self.result_revision != revision):
            return

        target_side = self.final_side
        source = self.editors[1 - target_side].toPlainText()
        edits = []
        for index, change in enumerate(self.result.changes):
            if target_side == 0:
                start, end = change.left_offset, change.left_end
                source_start, source_end = change.right_offset, change.right_end
            else:
                start, end = change.right_offset, change.right_end
                source_start, source_end = change.left_offset, change.left_end
            if None in (start, end, source_start, source_end):
                return
            edits.append((start, index, end, source[source_start:source_end]))

        cursor = QTextCursor(self.editors[target_side].document())
        self._applying_change = True
        try:
            cursor.beginEditBlock()
            for start, _index, end, replacement in sorted(edits, reverse=True):
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(replacement)
            cursor.endEditBlock()
        finally:
            self._applying_change = False
        self._action_undo_sides.append(target_side)
        self._action_redo_sides.clear()
        self.statusBar().showMessage("All remaining differences applied to final document")

    def _history_editor(self) -> ProseEditor | None:
        for editor in self.editors:
            if editor.hasFocus() and not editor.isReadOnly():
                return editor
        if self._last_edited_side is not None:
            return self.editors[self._last_edited_side]
        return None

    def undo_change(self):
        action_side = self._action_undo_sides[-1] if self._action_undo_sides else None
        editor = self.editors[action_side] if action_side is not None else self._history_editor()
        if editor is None or not editor.document().isUndoAvailable():
            return
        self._running_undo_redo = True
        try:
            editor.undo()
        finally:
            self._running_undo_redo = False
        if action_side is not None:
            self._action_undo_sides.pop()
            self._action_redo_sides.append(action_side)

    def redo_change(self):
        action_side = self._action_redo_sides[-1] if self._action_redo_sides else None
        editor = self.editors[action_side] if action_side is not None else self._history_editor()
        if editor is None or not editor.document().isRedoAvailable():
            return
        self._running_undo_redo = True
        try:
            editor.redo()
        finally:
            self._running_undo_redo = False
        if action_side is not None:
            self._action_redo_sides.pop()
            self._action_undo_sides.append(action_side)

    def navigate(self, direction: int):
        if not self.result or not self.result.changes:
            return
        if self.current_change < 0:
            self.current_change = 0 if direction > 0 else self.result.edit_count - 1
        else:
            self.current_change = (self.current_change + direction) % self.result.edit_count
        index = self.current_change
        change = self.result.changes[index]
        self._select_change(index)
        if self.stack.currentIndex() == 1:
            position = self.unified_positions.get((change.left, change.right), 0)
            source_side = 1 if change.kind == "insert" else 0
            source_offset = change.right_offset if source_side else change.left_offset
            if source_offset is not None:
                for side, start, end, target in self.unified_source_map:
                    if side == source_side and start <= source_offset < end:
                        position = target + source_offset - start
                        break
            editor = self.unified
        else:
            side = 1 if change.kind == "insert" else 0
            editor = self.editors[side]
            block = (self.result.right_blocks[change.right] if side else self.result.left_blocks[change.left])
            position = (change.right_offset if side else change.left_offset) or block.start
        cursor = editor.textCursor()
        cursor.setPosition(position)
        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()
        self._select_change(index)

    def _update_unified(self, result: DiffResult):
        chunks: list[str] = []
        spans: list[Span] = []
        positions: dict[tuple[int | None, int | None], int] = {}
        source_map: list[tuple[int, int, int, int]] = []
        offset = 0
        sorted_spans = (
            tuple(sorted(result.left_spans, key=lambda span: span.start)),
            tuple(sorted(result.right_spans, key=lambda span: span.start)),
        )
        span_ends = ([span.end for span in sorted_spans[0]], [span.end for span in sorted_spans[1]])

        def changed(block: Block, side: int) -> bool:
            index = bisect_right(span_ends[side], block.start)
            return index < len(sorted_spans[side]) and sorted_spans[side][index].start < block.end

        def add(block: Block, prefix: str, side: int, apply_spans: bool = False):
            nonlocal offset
            source_offset = block.start
            for line in block.text.splitlines(keepends=True):
                display = prefix + line
                chunks.append(display)
                line_end = source_offset + len(line)
                source_map.append((side, source_offset, line_end, offset + len(prefix)))
                if apply_spans:
                    index = bisect_right(span_ends[side], source_offset)
                    while index < len(sorted_spans[side]) and sorted_spans[side][index].start < line_end:
                        span = sorted_spans[side][index]
                        start = max(span.start, source_offset)
                        end = min(span.end, line_end)
                        if end > start:
                            spans.append(Span(offset + len(prefix) + start - source_offset,
                                              offset + len(prefix) + end - source_offset, span.kind))
                        index += 1
                offset += len(display)
                source_offset = line_end
            if block.text and not block.text.endswith(("\n", "\r")):
                chunks.append("\n")
                offset += 1

        for li, ri in result.rows:
            positions[(li, ri)] = offset
            if li is not None and ri is not None:
                if changed(result.left_blocks[li], 0) or changed(result.right_blocks[ri], 1):
                    add(result.left_blocks[li], "− ", 0, True)
                    add(result.right_blocks[ri], "+ ", 1, True)
                else:
                    add(result.left_blocks[li], "  ", 0)
            elif li is not None:
                block = result.left_blocks[li]
                add(block, "− " if changed(block, 0) else "  ", 0, True)
            elif ri is not None:
                block = result.right_blocks[ri]
                add(block, "+ " if changed(block, 1) else "  ", 1, True)
        cursor = QTextCursor(self.unified.textCursor())
        fraction = self._scroll_fraction(self.unified.verticalScrollBar())
        self._updating_unified = True
        self.unified.setPlainText("".join(chunks))
        self.unified.highlighter.set_spans(tuple(spans))
        cursor.setPosition(min(cursor.position(), len(self.unified.toPlainText())))
        self.unified.setTextCursor(cursor)
        self._set_scroll_fraction(self.unified.verticalScrollBar(), fraction)
        self.unified_positions = positions
        self.unified_source_map = source_map
        self._updating_unified = False

    def choose_file(self, side: int):
        initial = str(self.paths[side].parent) if self.paths[side] else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(self, "Open Markdown document", initial,
                                                   "Markdown and text (*.md *.markdown *.txt);;All files (*)")
        if filename:
            self.load_file(side, Path(filename))

    def load_file(self, side: int, path: Path):
        if self.dirty[side] and not self._confirm_discard(side):
            return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            QMessageBox.critical(self, "Cannot open file", str(exc))
            return
        old = self.paths[side]
        if old and str(old) in self.watcher.files():
            self.watcher.removePath(str(old))
        self.paths[side] = path.resolve()
        self._replace_editor_text(side, text)
        self._watch_path(self.paths[side])
        self._update_file_button(side)
        if not self._opening_pair:
            self._remember_pair()

    def open_paths(self, left: str | None, right: str | None):
        self._opening_pair = True
        try:
            if left:
                self.load_file(0, Path(left))
            if right:
                self.load_file(1, Path(right))
        finally:
            self._opening_pair = False
        self._remember_pair()

    def _replace_editor_text(self, side: int, text: str):
        self._action_undo_sides.clear()
        self._action_redo_sides.clear()
        editor = self.editors[side]
        cursor_position = editor.textCursor().position()
        fraction = self._scroll_fraction(editor.verticalScrollBar())
        with QSignalBlocker(editor):
            editor.setPlainText(text)
        cursor = editor.textCursor()
        cursor.setPosition(min(cursor_position, len(text)))
        editor.setTextCursor(cursor)
        self._set_scroll_fraction(editor.verticalScrollBar(), fraction)
        self.dirty[side] = False
        self._update_file_button(side)
        self._schedule_diff()

    def _watch_path(self, path: Path):
        if path.exists() and str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))
        directory = str(path.parent)
        if directory not in self.watcher.directories():
            self.watcher.addPath(directory)

    def _file_changed(self, filename: str):
        self._queue_reload(filename)

    def _directory_changed(self, directory: str):
        for path in self.paths:
            if path and str(path.parent) == directory:
                self._queue_reload(str(path))

    def _queue_reload(self, filename: str):
        if filename in self._reload_pending:
            return
        self._reload_pending.add(filename)
        QTimer.singleShot(180, lambda: self._run_queued_reload(filename))

    def _run_queued_reload(self, filename: str):
        self._reload_pending.discard(filename)
        self._reload_external(filename)

    def _reload_external(self, filename: str):
        path = Path(filename)
        self._watch_path(path)  # Atomic replacement removes a QFileSystemWatcher path.
        for side, current in enumerate(self.paths):
            if current != path or not path.exists():
                continue
            try:
                disk_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if disk_text == self.editors[side].toPlainText():
                continue
            if self.dirty[side]:
                answer = QMessageBox.question(
                    self, "File changed on disk",
                    f"{path.name} changed outside SideXSide. Reload it and discard unsaved edits?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    continue
            self._replace_editor_text(side, disk_text)
            self.statusBar().showMessage(f"Reloaded {path.name} from disk")

    def save_file(self, side: int) -> bool:
        if side != self.final_side:
            return False
        path = self.paths[side]
        if path is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Save Markdown document", str(Path.home() / "untitled.md"),
                                                       "Markdown (*.md);;All files (*)")
            if not filename:
                return False
            path = Path(filename).resolve()
        from PySide6.QtCore import QSaveFile, QIODevice
        file = QSaveFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            QMessageBox.critical(self, "Cannot save file", file.errorString())
            return False
        data = self.editors[side].toPlainText().encode("utf-8")
        if file.write(data) != len(data) or not file.commit():
            QMessageBox.critical(self, "Cannot save file", file.errorString())
            file.cancelWriting()
            return False
        old = self.paths[side]
        if old and old != path and str(old) in self.watcher.files():
            self.watcher.removePath(str(old))
        self.paths[side] = path
        self._watch_path(path)
        self.dirty[side] = False
        self._update_file_button(side)
        self._remember_pair()
        self.statusBar().showMessage(f"Saved {path.name}")
        return True

    def _confirm_discard(self, side: int) -> bool:
        answer = QMessageBox.question(
            self, "Unsaved edits", "Discard unsaved edits in this document?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def new_session(self):
        if any(self.dirty) and any(not self._confirm_discard(side) for side in range(2) if self.dirty[side]):
            return
        for path in self.paths:
            if path and str(path) in self.watcher.files():
                self.watcher.removePath(str(path))
        self.paths = [None, None]
        for side in range(2):
            self._replace_editor_text(side, "")
        self.final_file_combo.setCurrentIndex(1)
        self.current_change = -1
        self.setWindowTitle("SideXSide")

    def _update_file_button(self, side: int):
        name = self.paths[side].name if self.paths[side] else "Choose file…"
        label = "Original (Before)" if side == 0 else "Revised (After)"
        self.file_buttons[side].setText(f"{label}  ·  {name}{'  ●' if self.dirty[side] else ''}")
        self.file_buttons[side].setToolTip(str(self.paths[side]) if self.paths[side] else label)
        self.final_file_combo.setItemText(side, f"{label} · {name}")

    def _remember_pair(self):
        if not all(self.paths):
            return
        pair = [str(path) for path in self.paths]
        self.recent = [pair] + [item for item in self.recent if item != pair]
        self.recent = self.recent[:20]
        self.settings.setValue("recent", json.dumps(self.recent))
        self._refresh_recent()
        self.setWindowTitle(f"{self.paths[0].name} ↔ {self.paths[1].name} — SideXSide")

    def _refresh_recent(self):
        self.recent_list.clear()
        for left, right in self.recent:
            self.recent_list.addItem(f"{Path(left).name}  →  {Path(right).name}")

    def _open_recent(self, item):
        pair = self.recent[self.recent_list.row(item)]
        self.open_paths(*pair)

    def closeEvent(self, event):  # noqa: N802
        for side in range(2):
            if self.dirty[side] and not self._confirm_discard(side):
                event.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()
