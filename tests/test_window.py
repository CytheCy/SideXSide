import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_settings_directory = tempfile.TemporaryDirectory(prefix="sidexside-settings-")
os.environ["XDG_CONFIG_HOME"] = _settings_directory.name

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()

    def tearDown(self):
        self.window.dirty = [False, False]
        self.window.close()

    def wait_for_diff(self):
        deadline = time.monotonic() + 3
        expected = self.window.revision
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window.result is not None and not self.window.timer.isActive() and self.window._task.revision == expected:
                self.app.processEvents()
                if self.window.result.edit_count:
                    return
            time.sleep(.01)
        self.fail("live diff did not finish")

    def test_live_edit_save_and_external_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory, "original.md")
            revised = Path(directory, "revised.md")
            original.write_text("A quiet road.\n", encoding="utf-8")
            revised.write_text("A winding road.\n", encoding="utf-8")
            self.window.open_paths(str(original), str(revised))
            self.wait_for_diff()
            self.assertEqual(self.window.result.edit_count, 1)
            self.window.navigate(1)
            self.assertEqual(self.window.diff_badge.text(), "Diff 1 of 1")
            self.window._set_mode(True)
            self.assertIn("− A quiet road.", self.window.unified.toPlainText())
            self.assertIn("+ A winding road.", self.window.unified.toPlainText())
            self.window._set_mode(False)
            self.window.toggle_sidebar()
            self.assertEqual(self.window.root_splitter.sizes()[0], 0)
            self.window.toggle_sidebar()
            self.assertGreater(self.window.root_splitter.sizes()[0], 0)
            editor = self.window.editors[1]
            cursor = editor.textCursor()
            cursor.setPosition(len(editor.toPlainText()))
            editor.setTextCursor(cursor)
            position = cursor.position()
            editor.insertPlainText("Another sentence.")
            self.wait_for_diff()
            self.assertEqual(editor.textCursor().position(), position + len("Another sentence."))
            self.assertTrue(self.window.dirty[1])
            self.assertTrue(self.window.save_file(1))
            self.assertEqual(revised.read_text(encoding="utf-8"), editor.toPlainText())
            self.assertFalse(self.window.dirty[1])
            original.write_text("A quiet lane.\n", encoding="utf-8")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and self.window.editors[0].toPlainText() != "A quiet lane.\n":
                self.app.processEvents()
                time.sleep(.01)
            self.assertEqual(self.window.editors[0].toPlainText(), "A quiet lane.\n")

    def test_navigation_selects_each_word_change(self):
        self.window.editors[0].setPlainText("The blue door held the old key.")
        self.window.editors[1].setPlainText("The green door held the new key.")
        self.wait_for_diff()
        self.assertEqual(self.window.result.edit_count, 2)
        self.window.navigate(-1)
        self.assertEqual(self.window.current_change, 1)
        self.assertEqual(self.window.editors[0].textCursor().position(),
                         self.window.result.changes[1].left_offset)
        self.window.navigate(1)
        self.assertEqual(self.window.current_change, 0)
        self.assertEqual(self.window.editors[0].textCursor().position(),
                         self.window.result.changes[0].left_offset)

    def test_unified_view_highlights_only_changed_text_across_paragraphs(self):
        left = "Alpha beta gamma.\n\nDelta epsilon zeta."
        right = "Alpha beta gamma. Delta epsilon zeta."
        self.window.editors[0].setPlainText(left)
        self.window.editors[1].setPlainText(right)
        self.wait_for_diff()
        self.window._set_mode(True)
        shown = self.window.unified.toPlainText()
        highlighted = [shown[span.start:span.end] for span in self.window.unified.highlighter.spans]
        self.assertEqual(highlighted, ["\n", "\n", " "])


if __name__ == "__main__":
    unittest.main()
