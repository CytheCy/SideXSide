# SideXSide

An offline, native Qt 6 difference viewer for Markdown prose. Both documents remain editable, and their differences update after a 300 ms pause in typing.

## Run

Requires Python 3.12+ and PySide6. On Fedora KDE, install Qt's Breeze style plugin if it is not already present; SideXSide also works with the available native Qt style.

```bash
python3 -m pip install -r requirements.txt
python3 main.py [original.md] [revised.md]
```

Open files using the two toolbar pickers, or type into either pane. Save buttons write each pane back to its file. A file chosen from another location is watched and reloaded when it changes on disk. Unsaved edits trigger a confirmation before an external version replaces them. F7 and Shift+F7 move through differences. The sidebar keeps up to 20 recent file pairs using Qt settings.

The comparison first aligns Markdown structural blocks and paragraphs, then compares words and punctuation inside changed passages, including across joined or split sentences and paragraphs. Whitespace and simple emphasis delimiter changes can be ignored separately from strict Markdown matching. Curly versus straight quotes and em dashes remain visible as edits.
