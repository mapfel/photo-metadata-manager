import json
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from metadata_comparer.config import Config, load_config, save_config
from metadata_comparer.metadata.sync import SyncStatus
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import SYNC_ROLE

FIELDS = {"Title", "Rating", "Color Label", "Date Taken"}


def wait_for(condition, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
    return condition()


def header(window, field, role):
    row = [m.name for m in window._mappings].index(field)
    return window.metadata_panel.model.headerData(row, Qt.Orientation.Vertical, role)


def test_save_config_keeps_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"master_source": "exif", "my_note": "keep me"}), encoding="utf-8")
    save_config(path, Config(compared_fields=("Title",)))

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["my_note"] == "keep me"
    assert load_config(path, FIELDS).compared_fields == ("Title",)


def test_compared_fields_are_bold(qapp, jpeg_file):
    window = MainWindow(Config(compared_fields=("Rating",)))
    window._show_folder(jpeg_file.parent)
    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))

    assert header(window, "Rating", Qt.ItemDataRole.FontRole).bold()
    assert header(window, "Title", Qt.ItemDataRole.FontRole) is None
    assert "Click to include" in header(window, "Title", Qt.ItemDataRole.ToolTipRole)


def test_clicking_the_field_name_toggles_and_saves(qapp, jpeg_file, tmp_path):
    config_path = tmp_path / "config.json"
    window = MainWindow(Config(compared_fields=("Rating",)), config_path=config_path)
    window.resize(1000, 800)
    window.show()
    window._show_folder(jpeg_file.parent)
    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))
    qapp.processEvents()  # let the header layout settle before computing click positions
    vertical = window.metadata_panel.table.verticalHeader()
    title_row = [m.name for m in window._mappings].index("Title")
    position = vertical.sectionViewportPosition(title_row) + vertical.sectionSize(title_row) // 2

    QTest.mouseClick(vertical.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, position))
    assert window._config.compared_fields == ("Title", "Rating")  # mapping order
    assert header(window, "Title", Qt.ItemDataRole.FontRole).bold()
    assert load_config(config_path, FIELDS).compared_fields == ("Title", "Rating")

    window.toggle_compared_field("Rating")
    assert window._config.compared_fields == ("Title",)
    assert header(window, "Rating", Qt.ItemDataRole.FontRole) is None


def test_toggle_rechecks_thumbnails_and_keeps_table_choices(qapp, jpeg_file):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = "2"
    image.xmpData()["Xmp.xmp.Rating"] = "4"
    image.writeMetadata()

    window = MainWindow(Config(compared_fields=("Rating",)))
    window._show_folder(jpeg_file.parent)
    model = window.thumbnails.thumbnail_model
    index = model.index(0)
    window.thumbnails.setCurrentIndex(index)
    model.data(index, Qt.ItemDataRole.DecorationRole)
    assert wait_for(lambda: model.data(index, SYNC_ROLE) is not None, qapp)
    assert model.data(index, SYNC_ROLE).status == SyncStatus.CONFLICT

    panel = window.metadata_panel.model
    panel.click_cell(panel.index(0, 1))  # a pending choice in the table
    window.toggle_compared_field("Rating")

    assert wait_for(lambda: model.data(index, SYNC_ROLE).status == SyncStatus.OK, qapp)
    assert panel.selections  # not discarded


def source_header(window, column, role):
    return window.metadata_panel.model.headerData(column, Qt.Orientation.Horizontal, role)


def test_compared_sources_are_bold_and_toggle_on_click(qapp, jpeg_file, tmp_path):
    from metadata_comparer.metadata.sources import Source

    config_path = tmp_path / "config.json"
    config = Config(compared_sources=(Source.EXIF, Source.XMP_EMBEDDED))
    window = MainWindow(config, config_path=config_path)
    window.resize(1000, 800)
    window.show()
    window._show_folder(jpeg_file.parent)
    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))
    bold = Qt.ItemDataRole.FontRole

    assert source_header(window, 0, bold).bold()  # Exif
    assert source_header(window, 1, bold).bold()  # master
    assert source_header(window, 2, bold) is None  # sidecar
    assert source_header(window, 4, bold) is None  # Custom is never compared

    qapp.processEvents()  # let the header layout settle before computing click positions
    horizontal = window.metadata_panel.table.horizontalHeader()
    sidecar_x = horizontal.sectionViewportPosition(2) + horizontal.sectionSize(2) // 2
    QTest.mouseClick(horizontal.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(sidecar_x, 5))
    assert window._config.compared_sources == (
        Source.EXIF,
        Source.XMP_EMBEDDED,
        Source.XMP_SIDECAR,
    )
    assert source_header(window, 2, bold).bold()
    assert load_config(config_path, FIELDS).compared_sources == window._config.compared_sources

    window.toggle_compared_source(Source.EXIF)
    assert Source.EXIF not in window._config.compared_sources
    window.toggle_compared_source(Source.XMP_EMBEDDED)  # the master cannot be excluded
    assert Source.XMP_EMBEDDED in window._config.compared_sources
    assert "always compared" in window.statusBar().currentMessage()


def test_excluding_a_source_rechecks_thumbnails(qapp, jpeg_file):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    from metadata_comparer.metadata.sources import Source

    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = "2"
    image.xmpData()["Xmp.xmp.Rating"] = "4"
    image.writeMetadata()

    window = MainWindow()
    window._show_folder(jpeg_file.parent)
    model = window.thumbnails.thumbnail_model
    index = model.index(0)
    model.data(index, Qt.ItemDataRole.DecorationRole)
    assert wait_for(lambda: model.data(index, SYNC_ROLE) is not None, qapp)
    assert model.data(index, SYNC_ROLE).status == SyncStatus.CONFLICT

    window.toggle_compared_source(Source.EXIF)
    assert wait_for(lambda: model.data(index, SYNC_ROLE).status == SyncStatus.OK, qapp)
