import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_settings_directory = tempfile.TemporaryDirectory(prefix="sidexside-settings-")
os.environ["XDG_CONFIG_HOME"] = _settings_directory.name

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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

    def wait_for_current_diff(self):
        deadline = time.monotonic() + 3
        expected = self.window.revision
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.window.result_revision == expected:
                return
            time.sleep(.01)
        self.fail("live diff did not finish")

    def test_live_edit_save_and_external_reload(self):
        self.window.sidebar_hover_timer.stop()
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
            self.assertEqual(self.window.root_splitter.sizes()[0], 0)
            self.window.toggle_sidebar()
            self.assertGreater(self.window.root_splitter.sizes()[0], 0)
            self.window.toggle_sidebar()
            self.assertEqual(self.window.root_splitter.sizes()[0], 0)
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

    def test_sidebar_reveals_at_left_edge_and_hides_when_pointer_leaves(self):
        self.window.sidebar_hover_timer.stop()
        y = self.window.root_splitter.geometry().center().y()
        self.assertEqual(self.window.root_splitter.sizes()[0], 0)

        self.window._update_sidebar_for_position(QPoint(5, y))
        self.assertGreater(self.window.root_splitter.sizes()[0], 0)
        self.window._update_sidebar_for_position(QPoint(400, y))
        self.assertEqual(self.window.root_splitter.sizes()[0], 0)

        self.window.toggle_sidebar()
        self.assertTrue(self.window.sidebar_pinned)
        self.window._update_sidebar_for_position(QPoint(400, y))
        self.assertGreater(self.window.root_splitter.sizes()[0], 0)
        self.window.toggle_sidebar()
        self.assertEqual(self.window.root_splitter.sizes()[0], 0)

    def test_only_selected_final_file_can_be_edited_or_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory, "original.md")
            revised = Path(directory, "revised.md")
            original.write_text("Before", encoding="utf-8")
            revised.write_text("After", encoding="utf-8")
            self.window.open_paths(str(original), str(revised))

            self.assertEqual(self.window.final_file_combo.currentData(), 1)
            self.assertIn("revised.md", self.window.final_file_combo.itemText(1))
            self.assertTrue(self.window.editors[0].isReadOnly())
            self.assertFalse(self.window.editors[1].isReadOnly())
            self.window.editors[0].setFocus()
            QTest.keyClicks(self.window.editors[0], " blocked")
            self.assertEqual(self.window.editors[0].toPlainText(), "Before")
            self.assertFalse(self.window.save_file(0))

            self.window.final_file_combo.setCurrentIndex(0)
            self.assertFalse(self.window.editors[0].isReadOnly())
            self.assertTrue(self.window.editors[1].isReadOnly())
            self.window.editors[1].setFocus()
            QTest.keyClicks(self.window.editors[1], " blocked")
            self.assertEqual(self.window.editors[1].toPlainText(), "After")
            self.assertFalse(self.window.save_file(1))
            self.window.editors[0].setFocus()
            cursor = self.window.editors[0].textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.window.editors[0].setTextCursor(cursor)
            QTest.keyClicks(self.window.editors[0], " edited")
            self.assertEqual(self.window.editors[0].toPlainText(), "Before edited")
            self.window.save_button.click()
            self.assertEqual(original.read_text(encoding="utf-8"), "Before edited")
            self.assertEqual(revised.read_text(encoding="utf-8"), "After")

            self.window.new_session()
            self.assertEqual(self.window.final_file_combo.currentData(), 1)
            self.assertTrue(self.window.editors[0].isReadOnly())
            self.assertFalse(self.window.editors[1].isReadOnly())

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

    def test_navigation_boxes_and_actions_follow_selected_word(self):
        left = "The blue door held the old key."
        right = "The green door held the new key."
        self.window.editors[0].setPlainText(left)
        self.window.editors[1].setPlainText(right)
        self.wait_for_diff()
        self.assertFalse(self.window.accept_button.isEnabled())
        self.assertFalse(self.window.discard_button.isEnabled())

        self.window.navigate(1)
        self.assertEqual(self.window.editors[0].selected_diff, (4, 8))
        self.assertEqual(self.window.editors[1].selected_diff, (4, 9))
        self.assertTrue(self.window.accept_button.isEnabled())
        self.window.navigate(1)
        self.assertEqual(self.window.editors[0].selected_diff, (23, 26))
        self.assertEqual(self.window.editors[1].selected_diff, (24, 27))
        self.window.accept_button.click()
        self.assertEqual(self.window.editors[1].toPlainText(), "The green door held the old key.")
        self.assertTrue(self.window.dirty[1])
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 1)

        cursor = self.window.editors[1].textCursor()
        cursor.setPosition(5)
        self.window.editors[1].setTextCursor(cursor)
        self.assertEqual(self.window.editors[0].selected_diff, (4, 8))
        self.assertEqual(self.window.editors[1].selected_diff, (4, 9))
        self.window.discard_button.click()
        self.assertEqual(self.window.editors[0].toPlainText(), "The green door held the old key.")
        self.assertTrue(self.window.dirty[0])
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 0)
        self.assertIsNone(self.window.editors[0].selected_diff)
        self.assertIsNone(self.window.editors[1].selected_diff)

    def test_actions_handle_text_present_on_only_one_side(self):
        self.window.editors[0].setPlainText("alpha")
        self.window.editors[1].setPlainText("alpha beta")
        self.wait_for_diff()
        self.window.navigate(1)
        self.assertEqual(self.window.editors[0].selected_diff, (5, 5))
        self.assertEqual(self.window.editors[1].selected_diff, (5, 10))
        self.window.accept_button.click()
        self.assertEqual(self.window.editors[1].toPlainText(), "alpha")
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 0)

        self.window.editors[1].setPlainText("alpha beta")
        self.wait_for_current_diff()
        self.window.navigate(1)
        self.window.discard_button.click()
        self.assertEqual(self.window.editors[0].toPlainText(), "alpha beta")
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 0)

    def test_actions_handle_whole_block_and_reversed_final_side(self):
        self.window.editors[0].setPlainText("")
        self.window.editors[1].setPlainText("A whole block.\n")
        self.wait_for_diff()
        self.window.final_file_combo.setCurrentIndex(0)
        self.assertTrue(self.window.accept_button.text().startswith("←"))
        self.window.navigate(1)
        self.assertEqual(self.window.editors[0].selected_diff, (0, 0))
        self.window.accept_button.click()
        self.assertEqual(self.window.editors[0].toPlainText(), "A whole block.\n")
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 0)

    def test_use_all_confirms_and_applies_remaining_changes_as_one_edit(self):
        comparison = self.window.editors[0]
        final = self.window.editors[1]
        comparison.setPlainText("The blue door held the old key.")
        final.setPlainText("The green door held the new key.")
        self.wait_for_diff()
        self.assertTrue(self.window.use_all_button.isEnabled())

        self.window.navigate(1)
        self.window.discard_button.click()
        self.wait_for_current_diff()
        self.assertEqual(comparison.toPlainText(), "The green door held the old key.")
        self.assertEqual(self.window.result.edit_count, 1)

        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
            self.window.use_all_button.click()
        self.assertEqual(question.call_args.args[2], "Are you sure?")
        self.assertEqual(final.toPlainText(), "The green door held the new key.")

        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.use_all_button.click()
        self.assertEqual(final.toPlainText(), "The green door held the old key.")
        self.assertTrue(self.window.dirty[1])
        self.window.undo_change()
        self.assertEqual(final.toPlainText(), "The green door held the new key.")
        self.window.redo_change()
        self.assertEqual(final.toPlainText(), "The green door held the old key.")
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 0)
        self.assertFalse(self.window.use_all_button.isEnabled())

    def test_use_all_applies_multiple_changes_to_original_final(self):
        self.window.editors[0].setPlainText("The green door held the new key.")
        self.window.editors[1].setPlainText("The blue door held the old key.")
        self.wait_for_diff()
        self.window.final_file_combo.setCurrentIndex(0)
        self.assertEqual(self.window.result.edit_count, 2)
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.use_all_button.click()
        self.assertEqual(self.window.editors[0].toPlainText(), "The blue door held the old key.")
        self.window.undo_change()
        self.assertEqual(self.window.editors[0].toPlainText(), "The green door held the new key.")
        self.wait_for_current_diff()
        self.assertEqual(self.window.result.edit_count, 2)

    def test_unified_cursor_selects_matching_boxes(self):
        self.window.editors[0].setPlainText("A blue door.")
        self.window.editors[1].setPlainText("A green door.")
        self.wait_for_diff()
        self.window._set_mode(True)
        cursor = self.window.unified.textCursor()
        cursor.setPosition(self.window.unified.toPlainText().index("green") + 2)
        self.window.unified.setTextCursor(cursor)
        self.assertEqual(self.window.editors[0].selected_diff, (2, 6))
        self.assertEqual(self.window.editors[1].selected_diff, (2, 7))
        self.window.accept_button.click()
        self.assertEqual(self.window.editors[1].toPlainText(), "A blue door.")

    def test_ctrl_z_undoes_use_comparison_as_one_edit(self):
        self.window.editors[0].setPlainText("A blue door.")
        final = self.window.editors[1]
        final.setPlainText("A green door.")
        final.setFocus()
        cursor = final.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        final.setTextCursor(cursor)
        QTest.keyClicks(final, " Open")
        self.wait_for_diff()
        self.window.navigate(1)
        self.window.accept_button.click()
        self.assertEqual(final.toPlainText(), "A blue door. Open")
        self.window.accept_button.setFocus()
        QTest.keyClick(self.window.accept_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(final.toPlainText(), "A green door. Open")
        QTest.keyClick(self.window.accept_button, Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(final.toPlainText(), "A blue door. Open")

    def test_ctrl_z_undoes_discard_in_read_only_comparison(self):
        comparison = self.window.editors[0]
        comparison.setPlainText("A blue door.")
        self.window.editors[1].setPlainText("A green door.")
        self.wait_for_diff()
        self.window.navigate(1)
        self.window.discard_button.click()
        self.assertTrue(comparison.isReadOnly())
        self.assertEqual(comparison.toPlainText(), "A green door.")
        self.window.discard_button.setFocus()
        QTest.keyClick(self.window.discard_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(comparison.toPlainText(), "A blue door.")
        QTest.keyClick(self.window.discard_button, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(comparison.toPlainText(), "A green door.")

    def test_ctrl_z_still_undoes_ordinary_typing(self):
        final = self.window.editors[1]
        final.setFocus()
        QTest.keyClicks(final, "draft")
        self.assertEqual(final.toPlainText(), "draft")
        QTest.keyClick(final, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(final.toPlainText(), "")

    def test_ctrl_z_reverses_button_actions_across_both_documents(self):
        self.window.editors[0].setPlainText("The blue door held the old key.")
        self.window.editors[1].setPlainText("The green door held the new key.")
        self.wait_for_diff()
        self.window.navigate(1)
        self.window.accept_button.click()
        self.wait_for_current_diff()
        self.window.navigate(1)
        self.window.discard_button.click()
        self.assertEqual(self.window.editors[0].toPlainText(), "The blue door held the new key.")
        self.assertEqual(self.window.editors[1].toPlainText(), "The blue door held the new key.")
        self.window.discard_button.setFocus()
        QTest.keyClick(self.window.discard_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.editors[0].toPlainText(), "The blue door held the old key.")
        QTest.keyClick(self.window.discard_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.editors[1].toPlainText(), "The green door held the new key.")

    def test_document_font_shortcuts_update_every_pane_without_editing(self):
        self.window.editors[0].setPlainText("# Original")
        self.window.editors[1].setPlainText("# Revised")
        self.window.dirty = [False, False]
        editor = self.window.editors[0]
        editor.setFocus()
        self.app.processEvents()
        initial = self.window.document_font_size

        QTest.keyClick(editor, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.document_font_size, initial + 1)
        for pane in (*self.window.editors, self.window.unified):
            self.assertEqual(pane.font().pixelSize(), initial + 1)

        self.window._set_mode(True)
        self.window.unified.setFocus()
        QTest.keyClick(self.window.unified, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.document_font_size, initial)
        QTest.keyClick(self.window.unified, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.document_font_size, initial + 1)
        QTest.keyClick(self.window.unified, Qt.Key.Key_Equal,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.window.document_font_size, initial + 2)
        QTest.keyClick(self.window.unified, Qt.Key.Key_Plus,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.window.document_font_size, initial + 3)
        self.assertEqual([pane.toPlainText() for pane in self.window.editors], ["# Original", "# Revised"])
        self.assertEqual(self.window.dirty, [False, False])
        self.assertEqual(int(self.window.settings.value("document_font_size")), initial + 3)
        reopened = MainWindow()
        self.assertEqual(reopened.document_font_size, initial + 3)
        self.assertTrue(all(pane.font().pixelSize() == initial + 3
                            for pane in (*reopened.editors, reopened.unified)))
        reopened.close()

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
