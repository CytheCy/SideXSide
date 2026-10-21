"""Saved prompts and provider settings for AI document revision."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ai_revision import DEFAULT_OPENAI_KEY_PATH, PROVIDERS


@dataclass(frozen=True)
class PromptRun:
    name: str
    text: str
    destination: Path
    load_as_revised: bool
    overwrite_existing: bool = False


class PromptDialog(QDialog):
    def __init__(self, settings, parent=None, *, original_path: Path | None = None,
                 revised_path: Path | None = None):
        super().__init__(parent)
        self.settings = settings
        self.original_path = original_path
        self.revised_path = revised_path
        self.overwrite_paths: set[Path] = set()
        self.setWindowTitle("Apply Prompt")
        self.resize(820, 560)
        try:
            saved = json.loads(settings.value("prompts", "[]"))
            self.prompts = [item for item in saved if isinstance(item, dict)
                            and isinstance(item.get("name"), str)
                            and isinstance(item.get("text"), str)]
        except (TypeError, ValueError):
            self.prompts = []
        self._suggested_paths: list[Path | None] = []
        for item in self.prompts:
            self._suggested_paths.append(self._next_suggested_output_path()
                                         if "output_path" not in item else None)
        self.selected = 0 if self.prompts else -1
        self.checked = {0} if self.prompts else set()
        self._loading = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Check prompts to apply. Click a name to edit its settings."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(105)
        self.scroll.setMaximumHeight(160)
        layout.addWidget(self.scroll)
        prompt_actions = QHBoxLayout()
        add_button = QPushButton("Add Prompt")
        add_button.clicked.connect(self.add_prompt)
        prompt_actions.addWidget(add_button)
        delete_button = QPushButton("Delete Editing Prompt")
        delete_button.clicked.connect(self.delete_prompt)
        prompt_actions.addWidget(delete_button)
        prompt_actions.addStretch()
        layout.addLayout(prompt_actions)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Prompt name")
        self.name_edit.textChanged.connect(self._edit_prompt)
        form.addRow("Name:", self.name_edit)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("What should the AI change in the original document?")
        self.prompt_edit.setMinimumHeight(115)
        self.prompt_edit.textChanged.connect(self._edit_prompt)
        form.addRow("Instructions:", self.prompt_edit)
        output_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Choose an output filename and location")
        self.output_path_edit.textChanged.connect(self._edit_output_path)
        output_row.addWidget(self.output_path_edit, 1)
        self.output_browse = QPushButton("Browse…")
        self.output_browse.clicked.connect(self.browse_output)
        output_row.addWidget(self.output_browse)
        form.addRow("Output file:", output_row)
        self.load_as_revised_box = QCheckBox("Load output as Revised document")
        self.load_as_revised_box.toggled.connect(self._edit_load_as_revised)
        form.addRow("", self.load_as_revised_box)
        layout.addLayout(form)

        provider_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(PROVIDERS)
        provider = settings.value("ai_provider", "OpenAI")
        self.provider_combo.setCurrentText(provider if provider in PROVIDERS else "OpenAI")
        self._current_provider = self.provider_combo.currentText()
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        provider_row.addWidget(QLabel("AI:"))
        provider_row.addWidget(self.provider_combo)
        model_row = QHBoxLayout()
        self.model_edit = QLineEdit(settings.value(f"ai_model_{self._current_provider}",
                                                   PROVIDERS[self._current_provider]))
        self.model_edit.textChanged.connect(
            lambda value: self.settings.setValue(f"ai_model_{self._current_provider}", value))
        model_row.addWidget(QLabel("Model:"))
        model_row.addWidget(self.model_edit, 1)
        key_row = QHBoxLayout()
        default_path = DEFAULT_OPENAI_KEY_PATH if self._current_provider == "OpenAI" else ""
        self.key_path_edit = QLineEdit(settings.value(f"ai_key_path_{self._current_provider}", default_path))
        self.key_path_edit.setPlaceholderText("Path to API key .txt file")
        self.key_path_edit.textChanged.connect(
            lambda value: self.settings.setValue(f"ai_key_path_{self._current_provider}", value))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_key)
        key_row.addWidget(QLabel("API key .txt:"))
        key_row.addWidget(self.key_path_edit, 1)
        key_row.addWidget(browse)
        provider_row.addLayout(key_row, 1)
        layout.addLayout(provider_row)
        layout.addLayout(model_row)
        layout.addWidget(QLabel("The selected prompt and original document are sent to the chosen AI."))

        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self.apply_button = QPushButton("Apply Checked Prompts")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self._refresh_prompts()

    def _save_prompts(self):
        self.settings.setValue("prompts", json.dumps(self.prompts))

    def _refresh_prompts(self):
        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(3)
        self.prompt_checks = []
        self.prompt_buttons = []
        for index, item in enumerate(self.prompts):
            row = QHBoxLayout()
            check = QCheckBox("Apply")
            check.setChecked(index in self.checked)
            check.toggled.connect(lambda checked, i=index: self._toggle_prompt(i, checked))
            row.addWidget(check)
            button = QPushButton(item["name"].strip() or "Untitled prompt")
            button.setCheckable(True)
            button.setChecked(index == self.selected)
            button.clicked.connect(lambda _=False, i=index: self._select_prompt(i))
            row.addWidget(button, 1)
            rows.addLayout(row)
            self.prompt_checks.append(check)
            self.prompt_buttons.append(button)
        rows.addStretch()
        self.scroll.setWidget(holder)
        self._loading = True
        if self.selected >= 0:
            item = self.prompts[self.selected]
            self.name_edit.setText(item["name"])
            self.prompt_edit.setPlainText(item["text"])
            self.output_path_edit.setText(item.get("output_path") if "output_path" in item
                                          else str(self._suggested_paths[self.selected]))
            self.load_as_revised_box.setChecked(item.get("load_as_revised", True))
        else:
            self.name_edit.clear()
            self.prompt_edit.clear()
            self.output_path_edit.clear()
            self.load_as_revised_box.setChecked(True)
        self._loading = False
        enabled = self.selected >= 0
        self.name_edit.setEnabled(enabled)
        self.prompt_edit.setEnabled(enabled)
        self.output_path_edit.setEnabled(enabled)
        self.output_browse.setEnabled(enabled)
        self.load_as_revised_box.setEnabled(enabled)
        self.apply_button.setEnabled(bool(self.checked))

    def _select_prompt(self, index: int):
        self.selected = index
        self._refresh_prompts()

    def _toggle_prompt(self, index: int, checked: bool):
        if checked:
            self.checked.add(index)
        else:
            self.checked.discard(index)
        self.apply_button.setEnabled(bool(self.checked))

    def _edit_prompt(self):
        if self._loading or self.selected < 0:
            return
        self.prompts[self.selected].update(name=self.name_edit.text(),
                                           text=self.prompt_edit.toPlainText())
        self.prompt_buttons[self.selected].setText(self.name_edit.text().strip() or "Untitled prompt")
        self._save_prompts()

    def _edit_output_path(self, value: str):
        if self._loading or self.selected < 0:
            return
        self.prompts[self.selected]["output_path"] = value
        self._suggested_paths[self.selected] = None
        self._save_prompts()

    def _edit_load_as_revised(self, checked: bool):
        if self._loading or self.selected < 0:
            return
        self.prompts[self.selected]["load_as_revised"] = checked
        self._save_prompts()

    def _next_suggested_output_path(self) -> Path:
        desktop_location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        desktop = Path(desktop_location) if desktop_location else Path.home() / "Desktop"
        original = self.original_path or Path("document.md")
        suffix = original.suffix if original.suffix.lower() in (".md", ".markdown", ".txt") else ".md"
        stem = f"{original.stem}-revised"
        used = {path.resolve() for path in self._suggested_paths if path is not None}
        used.update(Path(item["output_path"]).expanduser().resolve()
                    for item in self.prompts if item.get("output_path"))
        destination = desktop / f"{stem}{suffix}"
        number = 2
        while destination.exists() or destination.resolve() in used:
            destination = desktop / f"{stem}-{number}{suffix}"
            number += 1
        return destination

    def _output_path(self, index: int) -> Path | None:
        item = self.prompts[index]
        value = item.get("output_path", None)
        if value is None:
            return self._suggested_paths[index].resolve()
        return Path(value.strip()).expanduser().resolve() if value.strip() else None

    def add_prompt(self):
        self.prompts.append({"name": "New prompt", "text": ""})
        self._suggested_paths.append(self._next_suggested_output_path())
        self.selected = len(self.prompts) - 1
        self.checked = {self.selected}
        self._save_prompts()
        self._refresh_prompts()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def delete_prompt(self):
        if self.selected < 0:
            return
        del self.prompts[self.selected]
        del self._suggested_paths[self.selected]
        deleted = self.selected
        self.selected = min(self.selected, len(self.prompts) - 1)
        self.checked = {index - (index > deleted) for index in self.checked if index != deleted}
        if not self.checked and self.selected >= 0:
            self.checked.add(self.selected)
        self._save_prompts()
        self._refresh_prompts()

    def _provider_changed(self, provider: str):
        self.settings.setValue("ai_provider", provider)
        self._current_provider = provider
        self.model_edit.setText(self.settings.value(f"ai_model_{provider}", PROVIDERS[provider]))
        default_path = DEFAULT_OPENAI_KEY_PATH if provider == "OpenAI" else ""
        self.key_path_edit.setText(self.settings.value(f"ai_key_path_{provider}", default_path))

    def browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose API key text file",
                                               self.key_path_edit.text(), "Text files (*.txt);;All files (*)")
        if path:
            self.key_path_edit.setText(path)

    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save AI output", self.output_path_edit.text(),
            "Markdown and text (*.md *.markdown *.txt);;All files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.output_path_edit.setText(path)

    def _apply(self):
        if not self.checked:
            QMessageBox.warning(self, "Prompt required", "Check at least one prompt to apply.")
            return
        if not self.model_edit.text().strip() or not self.key_path_edit.text().strip():
            QMessageBox.warning(self, "AI settings required", "Enter a model and an API key file path.")
            return
        destinations: dict[Path, str] = {}
        revised_loaders = []
        for index in sorted(self.checked):
            item = self.prompts[index]
            name = item["name"].strip() or "Untitled prompt"
            if not item["text"].strip():
                QMessageBox.warning(self, "Prompt required", f"Add instructions to {name}.")
                return
            destination = self._output_path(index)
            if destination is None:
                QMessageBox.warning(self, "Output file required", f"Choose an output file for {name}.")
                return
            if destination == self.original_path:
                QMessageBox.warning(self, "Choose another output file", f"{name} cannot replace the Original document.")
                return
            if destination.is_dir():
                QMessageBox.warning(self, "Choose an output file", f"The output location for {name} is a folder. Include a filename.")
                return
            load_as_revised = item.get("load_as_revised", True)
            if destination == self.revised_path and not load_as_revised:
                QMessageBox.warning(self, "Choose another output file", f"{name} targets the open Revised file. Choose another output file or load its output as Revised.")
                return
            if destination in destinations:
                QMessageBox.warning(self, "Output files conflict",
                                    f"{destinations[destination]} and {name} both use {destination}. Choose a different output file for one prompt.")
                return
            destinations[destination] = name
            if load_as_revised:
                revised_loaders.append(name)
        if len(revised_loaders) > 1:
            QMessageBox.warning(self, "Multiple Revised documents",
                                f"Only one selected prompt can load its output as Revised. Uncheck that option for all but one of: {', '.join(revised_loaders)}.")
            return
        self.overwrite_paths.clear()
        for destination, name in destinations.items():
            if not destination.exists():
                continue
            answer = QMessageBox.question(
                self, "Replace output file?", f"Replace the existing output file for {name}?\n{destination}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.overwrite_paths.add(destination)
        self.accept()

    def choices(self) -> tuple[str, str, str, list[PromptRun]]:
        runs = []
        for index in sorted(self.checked):
            item = self.prompts[index]
            destination = self._output_path(index)
            if destination is None:
                raise ValueError("Choose an output file for each checked prompt.")
            runs.append(PromptRun(item["name"].strip() or "Untitled prompt", item["text"],
                                  destination, item.get("load_as_revised", True),
                                  destination in self.overwrite_paths))
        return (self.provider_combo.currentText(), self.model_edit.text().strip(),
                self.key_path_edit.text().strip(), runs)
