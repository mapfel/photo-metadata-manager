# Metadata Comparer

Desktop tool (Windows, macOS, Linux) that shows the metadata of an image side by side from
four sources: **Exif**, **embedded XMP**, **sidecar XMP** and **IPTC**. Values that differ
between sources are highlighted; hovering a cell shows the exiv2 tag it came from.

Built with Python, [PySide6](https://doc.qt.io/qtforpython-6/) (Qt) and
[python-exiv2](https://github.com/jim-easterbrook/python-exiv2).

## Setup

With [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run metadata-comparer
```

Or with plain pip:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e . --group dev
python -m metadata_comparer
```

## Development

```sh
pytest
ruff check . && ruff format --check .
```

## Layout

```
src/metadata_comparer/
  metadata/          # UI-independent: reading, field mapping, comparison
    reader.py        # exiv2 -> raw tags per source, sidecar lookup
    mapping.yaml     # which tags make up "Author", "Description", ...
    comparison.py    # raw tags + mapping -> table rows
  ui/                # PySide6 widgets: folder tree, thumbnails, metadata table
```

To show another field, add an entry to `mapping.yaml`; no code change is needed.

## Known issues

- **Windows Smart App Control** blocks the unsigned native modules of python-exiv2
  ("An Application Control policy has blocked this file"). The app still starts, but the
  metadata table stays empty and the status bar shows the error.
