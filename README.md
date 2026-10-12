# SideXSide

An offline, native Qt 6 difference viewer for Markdown prose. Choose which document is the final file to edit; differences update after a 300 ms pause in typing.

## Run

Requires Python 3.12+ and PySide6. On Fedora KDE, install Qt's Breeze style plugin if it is not already present; SideXSide also works with the available native Qt style.

```bash
python3 -m pip install -r requirements.txt
python3 main.py [original.md] [revised.md]
```

Open files using the two toolbar pickers, then use the Final file dropdown to choose which pane you can edit and save. Revised is selected by default. The other pane stays read-only; Save Final writes the selected pane back to its file. Click a highlighted difference or use Previous and Next (F7 and Shift+F7) to place white boxes around the matching locations in both panes. Use the arrow button to copy that difference into the final document, or Discard Change to copy the final version into the comparison document. Use All asks for confirmation, then applies every remaining difference to the final document, excluding changes already discarded. Ctrl+Z undoes either action or the entire Use All operation, and Ctrl+Shift+Z or Ctrl+Y redoes it. These actions update the open documents; Save Final writes final-file changes to disk. A file chosen from another location is watched and reloaded when it changes on disk. Unsaved edits trigger a confirmation before an external version replaces them. Ctrl++ (or Ctrl+=) and Ctrl+- increase and decrease the document font size in every pane. Move the pointer near the left edge to reveal the sidebar; it hides when the pointer leaves. Use the menu button or Ctrl+B to keep it open. The sidebar keeps up to 20 recent file pairs using Qt settings.

The comparison first aligns Markdown structural blocks and paragraphs, then compares words and punctuation inside changed passages, including across joined or split sentences and paragraphs. Whitespace and simple emphasis delimiter changes can be ignored separately from strict Markdown matching. Curly versus straight quotes and em dashes remain visible as edits.
