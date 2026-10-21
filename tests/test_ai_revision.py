import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_settings_directory = tempfile.TemporaryDirectory(prefix="sidexside-ai-settings-")
os.environ["XDG_CONFIG_HOME"] = _settings_directory.name

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from ai_revision import generate_revision
from ui.main_window import MainWindow
from ui.prompt_dialog import PromptDialog, PromptRun


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_provider_responses_and_incomplete_output(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory, "key.txt")
            key_file.write_text("private-key\n", encoding="utf-8")
            cases = [
                ("OpenAI", {"status": "completed", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "# Revised"}]}]}),
                ("Anthropic", {"stop_reason": "end_turn", "content": [
                    {"type": "text", "text": "# Revised"}]}),
                ("Google Gemini", {"candidates": [{"finishReason": "STOP", "content": {
                    "parts": [{"text": "# Revised"}]}}]}),
            ]
            for provider, response in cases:
                with self.subTest(provider=provider), patch("ai_revision._post_json", return_value=response) as post:
                    self.assertEqual(generate_revision(provider, "model", str(key_file),
                                                       "Make it clearer", "# Original"), "# Revised")
                    self.assertNotIn("private-key", str(post.call_args.args[2]))
            with patch("ai_revision._post_json", return_value={"status": "incomplete", "output": []}):
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    generate_revision("OpenAI", "model", str(key_file), "Revise", "Before")

    def test_saved_prompts_and_provider_specific_settings(self):
        settings = QSettings("SideXSideTests", "PromptDialog")
        settings.clear()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory, "proofread.md")
            second = Path(directory, "shorten.txt")
            dialog = PromptDialog(settings)
            dialog.add_prompt()
            dialog.name_edit.setText("Proofread")
            dialog.prompt_edit.setPlainText("Fix spelling")
            dialog.output_path_edit.setText(str(first))
            dialog.load_as_revised_box.setChecked(False)
            dialog.add_prompt()
            dialog.name_edit.setText("Shorten")
            dialog.prompt_edit.setPlainText("Remove repetition")
            dialog.output_path_edit.setText(str(second))
            dialog.prompt_buttons[0].click()
            dialog.prompt_checks[1].setChecked(False)
            dialog.prompt_checks[0].setChecked(True)
            self.assertEqual(dialog.choices()[3], [PromptRun("Proofread", "Fix spelling", first, False)])
            dialog.prompt_buttons[1].click()
            dialog.prompt_checks[0].setChecked(False)
            dialog.prompt_checks[1].setChecked(True)
            self.assertEqual(dialog.choices()[3], [PromptRun("Shorten", "Remove repetition", second, True)])
            dialog.provider_combo.setCurrentText("Anthropic")
            dialog.key_path_edit.setText("/tmp/anthropic.txt")
            dialog.provider_combo.setCurrentText("OpenAI")
            self.assertIn("OpenAI.txt", dialog.key_path_edit.text())
            dialog.close()
            reopened = PromptDialog(settings)
            self.assertEqual(reopened.prompts, [
                {"name": "Proofread", "text": "Fix spelling", "output_path": str(first),
                 "load_as_revised": False},
                {"name": "Shorten", "text": "Remove repetition", "output_path": str(second)},
            ])
            self.assertEqual(reopened.choices()[3], [PromptRun("Proofread", "Fix spelling", first, False)])
            reopened.provider_combo.setCurrentText("Anthropic")
            self.assertEqual(reopened.key_path_edit.text(), "/tmp/anthropic.txt")
            reopened.close()

    def test_default_output_name_is_unique_and_existing_custom_file_needs_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            desktop = Path(directory, "Desktop")
            desktop.mkdir()
            (desktop / "essay-revised.md").write_text("existing", encoding="utf-8")
            settings = QSettings("SideXSideTests", "OutputDialog")
            settings.clear()
            with patch("ui.prompt_dialog.QStandardPaths.writableLocation", return_value=str(desktop)):
                dialog = PromptDialog(settings, original_path=Path(directory, "essay.md"))
                dialog.add_prompt()
                self.assertEqual(Path(dialog.output_path_edit.text()), desktop / "essay-revised-2.md")
                dialog.prompt_edit.setPlainText("Revise")
                dialog.load_as_revised_box.setChecked(False)
                self.assertNotIn("output_path", dialog.prompts[0])
                (desktop / "essay-revised-2.md").write_text("another revision", encoding="utf-8")
                self.assertEqual(dialog.choices()[3][0].destination, desktop / "essay-revised-2.md")
                dialog.close()
                dialog = PromptDialog(settings, original_path=Path(directory, "essay.md"))
                self.assertEqual(Path(dialog.output_path_edit.text()), desktop / "essay-revised-3.md")
                self.assertFalse(dialog.load_as_revised_box.isChecked())
                dialog.output_path_edit.setText(str(desktop / "essay-revised.md"))
                with patch("ui.prompt_dialog.QMessageBox.question",
                           return_value=QMessageBox.StandardButton.No) as question:
                    dialog._apply()
                question.assert_called_once()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertEqual((desktop / "essay-revised.md").read_text(), "existing")
                dialog.close()

    def test_multiple_prompts_require_distinct_outputs_and_one_revised_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            settings = QSettings("SideXSideTests", "MultiplePrompts")
            settings.clear()
            with patch("ui.prompt_dialog.QStandardPaths.writableLocation", return_value=str(directory)):
                dialog = PromptDialog(settings, original_path=directory / "essay.md")
                dialog.add_prompt()
                dialog.name_edit.setText("Proofread")
                dialog.prompt_edit.setPlainText("Fix typos")
                first_path = Path(dialog.output_path_edit.text())
                dialog.add_prompt()
                dialog.name_edit.setText("Shorten")
                dialog.prompt_edit.setPlainText("Cut repetition")
                second_path = Path(dialog.output_path_edit.text())
                self.assertNotEqual(first_path, second_path)
                dialog.prompt_checks[0].setChecked(True)
                with patch("ui.prompt_dialog.QMessageBox.warning") as warning:
                    dialog._apply()
                self.assertIn("Only one selected prompt", warning.call_args.args[2])
                dialog.load_as_revised_box.setChecked(False)
                dialog.output_path_edit.setText(str(first_path))
                with patch("ui.prompt_dialog.QMessageBox.warning") as warning:
                    dialog._apply()
                self.assertIn("both use", warning.call_args.args[2])
                dialog.output_path_edit.setText(str(second_path))
                dialog._apply()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual([job.name for job in dialog.choices()[3]], ["Proofread", "Shorten"])
                dialog.close()

    def test_apply_prompt_saves_unique_desktop_file_and_loads_right_pane(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            original = directory / "essay.md"
            original.write_text("# Original\n", encoding="utf-8")
            desktop = directory / "Desktop"
            desktop.mkdir()
            (desktop / "essay-revised.md").write_text("older revision", encoding="utf-8")
            window = MainWindow()
            window.show()
            window.load_file(0, original)
            self.assertTrue(window.apply_prompt_button.isEnabled())
            with (patch("ui.prompt_dialog.QStandardPaths.writableLocation", return_value=str(desktop)),
                  patch("ui.main_window.PromptDialog.exec", return_value=QDialog.DialogCode.Accepted),
                  patch("ui.main_window.PromptDialog.choices",
                        return_value=("OpenAI", "model", "/tmp/key.txt", [
                            PromptRun("Revise", "Revise", desktop / "essay-revised-2.md", True)])),
                  patch("ui.main_window.generate_revision", return_value="# Revised\n")):
                window.open_prompt_dialog()
                deadline = time.monotonic() + 3
                while window._revision_task is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(window._revision_task)
            self.assertEqual((desktop / "essay-revised.md").read_text(), "older revision")
            self.assertEqual((desktop / "essay-revised-2.md").read_text(), "# Revised\n")
            self.assertEqual(window.paths[1], (desktop / "essay-revised-2.md").resolve())
            self.assertEqual(window.editors[1].toPlainText(), "# Revised\n")
            self.assertFalse(window.dirty[1])
            window.editors[1].insertPlainText("local edit")
            with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                self.assertIsNotNone(window._save_revision(
                    PromptRun("Revise", "Revise", desktop / "essay-revised-3.md", True), "# Second\n"))
            self.assertFalse((desktop / "essay-revised-3.md").exists())
            self.assertTrue(window.dirty[1])
            window.dirty = [False, False]
            window.close()

    def test_output_can_be_saved_without_loading_or_discarding_revised_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            original = directory / "essay.md"
            original.write_text("# Original\n", encoding="utf-8")
            destination = directory / "results" / "alternate.txt"
            window = MainWindow()
            window.show()
            window.load_file(0, original)
            window.editors[1].setPlainText("Unsaved revised text")
            with (patch("ui.main_window.PromptDialog.exec", return_value=QDialog.DialogCode.Accepted),
                  patch("ui.main_window.PromptDialog.choices",
                        return_value=("OpenAI", "model", "/tmp/key.txt", [
                            PromptRun("Revise", "Revise", destination, False)])),
                  patch("ui.main_window.generate_revision", return_value="Saved output"),
                  patch("ui.main_window.QMessageBox.question") as question):
                window.open_prompt_dialog()
                deadline = time.monotonic() + 3
                while window._revision_task is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(window._revision_task)
            self.assertEqual(destination.read_text(encoding="utf-8"), "Saved output")
            self.assertIsNone(window.paths[1])
            self.assertEqual(window.editors[1].toPlainText(), "Unsaved revised text")
            self.assertTrue(window.dirty[1])
            question.assert_not_called()
            window.dirty = [False, False]
            window.close()

    def test_multiple_prompts_save_distinct_files_and_load_only_chosen_output(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            original = directory / "essay.md"
            original.write_text("# Original\n", encoding="utf-8")
            proofread = directory / "proofread.md"
            shorten = directory / "shorten.md"
            window = MainWindow()
            window.show()
            window.load_file(0, original)
            jobs = [PromptRun("Proofread", "Fix typos", proofread, False),
                    PromptRun("Shorten", "Cut repetition", shorten, True)]
            responses = {"Fix typos": "Proofread result", "Cut repetition": "Short result"}
            with (patch("ui.main_window.PromptDialog.exec", return_value=QDialog.DialogCode.Accepted),
                  patch("ui.main_window.PromptDialog.choices",
                        return_value=("OpenAI", "model", "/tmp/key.txt", jobs)),
                  patch("ui.main_window.generate_revision",
                        side_effect=lambda _provider, _model, _key, prompt, _original: responses[prompt]) as generate):
                window.open_prompt_dialog()
                deadline = time.monotonic() + 3
                while window._revision_context is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(window._revision_context)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(proofread.read_text(encoding="utf-8"), "Proofread result")
            self.assertEqual(shorten.read_text(encoding="utf-8"), "Short result")
            self.assertEqual(window.paths[1], shorten.resolve())
            self.assertEqual(window.editors[1].toPlainText(), "Short result")
            window.close()

    def test_later_prompt_runs_after_earlier_generation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            original = directory / "essay.md"
            original.write_text("# Original\n", encoding="utf-8")
            first = directory / "first.md"
            second = directory / "second.md"
            window = MainWindow()
            window.show()
            window.load_file(0, original)

            def generate(_provider, _model, _key, prompt, _original):
                if prompt == "Fail":
                    raise RuntimeError("service unavailable")
                return "Second result"

            with (patch("ui.main_window.PromptDialog.exec", return_value=QDialog.DialogCode.Accepted),
                  patch("ui.main_window.PromptDialog.choices",
                        return_value=("OpenAI", "model", "/tmp/key.txt", [
                            PromptRun("First", "Fail", first, False),
                            PromptRun("Second", "Succeed", second, False)])),
                  patch("ui.main_window.generate_revision", side_effect=generate),
                  patch("ui.main_window.QMessageBox.warning") as warning):
                window.open_prompt_dialog()
                deadline = time.monotonic() + 3
                while window._revision_context is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertIsNone(window._revision_context)
            self.assertFalse(first.exists())
            self.assertEqual(second.read_text(encoding="utf-8"), "Second result")
            self.assertIn("First: service unavailable", warning.call_args.args[2])
            window.close()


if __name__ == "__main__":
    unittest.main()
