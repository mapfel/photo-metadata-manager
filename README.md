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

  Until a thumbnail has been decoded, a placeholder frame in the image's shape stands in
  for it: **light grey** when its metadata came from the cache, **black** when they had to
  be read from the file. It disappears with the thumbnail, or turns red or yellow.

  In the metadata table these fields are shown in **bold**; clicking a field name there
  includes or excludes it, saves `config.json` and re-checks the thumbnails at once.
- `compared_sources`: sources checked against the master (default: all four). Shown as
  **bold** column titles in the metadata table; clicking a title toggles it the same way.
  The master is always bold and cannot be excluded.

  Sources that cannot store a field (e.g. color labels in Exif/IPTC) and a sidecar that does
  not exist are not checked. A rating of `0` counts as "unrated", i.e. empty.
- `sync_fields`: fields shown in the synchronize dialog (default: Rating, Color Label,
  Date Taken).

The app reopens the last folder (stored in `state.ini` next to `config.json`); if that
folder no longer exists, it starts in the Pictures folder.

**Rescan metadata** in the toolbar (F5 on Windows/Linux, Cmd+R on macOS) reads the folder
and the metadata again, e.g. after another program changed them. Unapplied choices in the
metadata table are discarded; the selection is kept unless files were added or removed.

## Metadata cache

With **Cache metadata** ticked in the toolbar (the default, saved as `cache_enabled` in
`config.json`), the app keeps the metadata it shows of each folder in a `.mcs-cache` file
in that folder. Frames, filters and the metadata table then come from the cache instead of
the image files; thumbnails are always decoded from the images and are not cached.

- A folder without a cache file is scanned completely in the background when it is opened;
  the status bar shows *Reading metadata: n of m* meanwhile.
- Frames are drawn from the cache (which also keeps each image's pixel size and
  orientation, portrait or landscape) before the thumbnails have been decoded.
  Images added to the folder later are read when they show up; removed ones are dropped.
- **Synchronize metadata…** reads the chosen images afresh and updates their entries, as
  does writing from the dialog or with **Apply** in the table.
- Changes made by other programs are *not* noticed: press **Rescan metadata** to read the
  whole folder again and rebuild its cache.
- Unticking the box stops using and writing cache files; existing files stay. Ticking it
  again rebuilds the cache of the current folder.
- The cache file records its cache version and the app version that wrote it. A cache of
  another cache version (written by an older or newer app) is invalid: a message says so,
  and after **OK** the folder is read again to refresh it. The app version is also recorded
  as `app_version` in `config.json`.
- Only the tags listed in `mapping.yaml` are stored; after editing it, caches are rebuilt.
  If the folder is read-only, the cache is kept in memory only.

## Filtering thumbnails

The **Show only** checkboxes in the toolbar filter the thumbnails by their frame:
**In sync** (no frame), **Missing** (yellow) and **Conflict** (red). Ticked boxes combine,
e.g. Missing + Conflict shows every image that needs attention. With no box ticked (the
default) all images are shown, including those whose metadata could not be read.

While a filter is active, the metadata of every image in the folder is checked, not just
of the visible thumbnails, so an image appears once its check is done. An image that stops
matching, e.g. after its conflict was fixed, disappears; if it was shown in the metadata
table, the table is cleared.

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

Run the tests on Windows and in WSL (see [WSL](#wsl)) before committing. A few UI tests
wait for background threads; on a busy Windows machine they can time out. Rerun them
before suspecting a bug.

### Versions

- The app version is defined only in `src/metadata_comparer/__init__.py` (`__version__`);
  `pyproject.toml` reads it from there. It is recorded in `config.json` and in each
  `.mcs-cache` file.
- Raise `CACHE_VERSION` in `metadata/cache.py` with every change to what the cache stores
  or how it is used, and note the change in the comment above it. Caches of another
  version are reported to the user and rebuilt.

### Performance on slow drives

Photo folders often live on network or cloud drives, e.g. OneDrive under WSL (`/mnt/c`).
There a `stat()` costs about 8 ms per file and reading a whole 1 MB JPEG 150–325 ms, while
`os.scandir` lists 800 entries in 13 ms. So:

- list folders with `os.scandir` and avoid a `stat()` or `is_file()` per image;
- let exiv2 open images by path, so it reads only the metadata. On Windows, paths with
  non-ASCII characters are the exception: exiv2 mishandles them, so they are read into
  memory;
- check a performance change on a copy of a real folder on such a drive, not only on the
  local disk. Never let scripts write `.mcs-cache` files into real photo folders.

## Layout

```
src/metadata_comparer/
  app.py             # entry point: config.json, state.ini, main window
  config.py          # Config and its JSON file
  metadata/          # UI-independent
    sources.py       # Source enum, RawMetadata
    reader.py        # exiv2 -> raw tags per source, sidecar lookup, image size
    mapping.yaml     # which tags make up "Author", "Description", ...
    mapping.py       # loads mapping.yaml
    values.py        # field kinds: normalizing values for comparing, formatting for writing
    comparison.py    # raw tags + mapping -> table rows
    sync.py          # sync status of an image: OK, missing, conflict
    writer.py        # writes values to Exif, XMP, sidecar and IPTC
    cache.py         # per-folder .mcs-cache
  ui/                # PySide6 widgets
    main_window.py   # toolbar, cache, wiring
    folder_tree.py
    thumbnail_view.py  # thumbnails, frames, status filter, background loading
    metadata_panel.py  # metadata table of the current image
    sync_table.py    # interactive table: pick the truth per field and its targets
    sync_dialog.py   # that table for several images at once
```

To show another field, add an entry to `mapping.yaml`; no code change is needed.

## Known issues

- **Windows Smart App Control** may block the unsigned native modules of python-exiv2
  ("An Application Control policy has blocked this file"). The app still starts, but the
  metadata table stays empty and the status bar shows the error. Developing in WSL avoids it.
