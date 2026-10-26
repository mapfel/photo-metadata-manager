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

### WSL

When working on the Windows checkout from WSL, keep the Linux environment outside the
project so it does not clash with the Windows `.venv`:

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/metadata-comparer"
uv sync
QT_QPA_PLATFORM=offscreen uv run pytest
```

Running the GUI through WSLg additionally needs Qt's X11 libraries:
`sudo apt install libxcb-cursor0 libxkbcommon-x11-0`.

## Configuration

On first start the app writes `config.json` to the user configuration folder and shows its
path in the status bar:

| OS      | Location                                            |
|---------|-----------------------------------------------------|
| Windows | `%LOCALAPPDATA%\metadata-comparer\config.json`      |
| macOS   | `~/Library/Preferences/metadata-comparer/config.json` |
| Linux   | `~/.config/metadata-comparer/config.json`           |

```json
{
  "master_source": "xmp_embedded",
  "compared_fields": ["Rating", "Color Label"]
}
```

- `master_source`: `exif`, `xmp_embedded`, `xmp_sidecar` or `iptc`. Marked with ★ in the table.
- `compared_fields`: field names from `mapping.yaml` that are checked against the master for
  every thumbnail:
  - **red frame**: another source holds a different value (or a value the master lacks),
  - **yellow frame**: the master has a value that another source is missing.

  In the metadata table these fields are shown in **bold**; clicking a field name there
  includes or excludes it, saves `config.json` and re-checks the thumbnails at once.

  Sources that cannot store a field (e.g. color labels in Exif/IPTC) and a sidecar that does
  not exist are not checked. A rating of `0` counts as "unrated", i.e. empty.
- `sync_fields`: fields shown in the synchronize dialog (default: Rating, Color Label,
  Date Taken).

The app reopens the last folder (stored in `state.ini` next to `config.json`); if that
folder no longer exists, it starts in the Pictures folder.

**Rescan metadata** in the toolbar (F5 on Windows/Linux, Cmd+R on macOS) reads the folder
and the metadata again, e.g. after another program changed them. Unapplied choices in the
metadata table are discarded; the selection is kept unless files were added or removed.

## Synchronizing metadata

The metadata table below the thumbnails works the same way as the dialog described next,
for all fields of the clicked image: click the truth, tick the targets, press **Apply**
(bottom right). Rows where the sources disagree are highlighted. Switching to another
image discards choices that were not applied.

Both tables have a **Custom** column for typing the truth yourself. Click a Custom cell to
make it the truth and type into it (clicking it again edits the value; click another cell
to move the truth away). It is never a target. Several text values are separated by `;`,
ratings are `-1`–`5` (`0` = unrated, i.e. removes the rating), dates are
`YYYY-MM-DD[ HH:MM[:SS]]`. Invalid input turns red and blocks **Apply**. In the batch
dialog the typed value goes to every selected image.

Text fields with several values (e.g. keywords) are written as XMP arrays and repeated
IPTC datasets, and joined with `; ` where a tag holds a single string. Non-ASCII IPTC text
sets the UTF-8 character set marker. Writing an XMP language alternative (title,
description, rights) keeps only the default language.

Double-click a thumbnail to open the synchronize dialog. To synchronize several images,
select them (Ctrl+click, Shift+click, Ctrl+A) and press **Synchronize metadata…** in the
toolbar (Ctrl+Shift+S). Cells then summarize all images: a value shared by all, `(empty)`,
or `(mixed)` (hover for the distribution). The truth and target choice applies to every
image, and each image copies its *own* value from the truth source. A batch write asks for
confirmation first and reports how many values would be removed because the truth is empty. Click the cell that holds the
truth (green frame), tick the checkboxes of the cells that should receive its value and
press **Apply**. Choosing an empty cell as the truth removes the value from the targets.

- Only the metadata is rewritten; the image data stays untouched. Files are replaced
  atomically, but **keep backups of important photos** while this tool is young.
- The first tag of a family in `mapping.yaml` is written (e.g. `Xmp.photoshop.DateCreated`).
- A missing sidecar is created as `<name>.xmp`.
- Writing an Exif rating also sets the Windows `RatingPercent` tag.
- Dates are compared and written without time zone and fractional seconds.

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

- **Windows Smart App Control** may block the unsigned native modules of python-exiv2
  ("An Application Control policy has blocked this file"). The app still starts, but the
  metadata table stays empty and the status bar shows the error. Developing in WSL avoids it.
