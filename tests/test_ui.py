import time

from PySide6.QtCore import Qt

from metadata_comparer.config import Config
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.sync import SyncReport, SyncStatus
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import SYNC_ROLE, ThumbnailModel, list_images


def test_list_images_filters_and_sorts(tmp_path):
    for name in ("b.JPG", "a.jpeg", "notes.txt", "c.png"):
        (tmp_path / name).touch()
    (tmp_path / "folder.jpg").mkdir()

    assert [path.name for path in list_images(tmp_path)] == ["a.jpeg", "b.JPG", "c.png"]


def test_selecting_image_fills_metadata_table(qapp, jpeg_file):
    window = MainWindow()
    window._show_folder(jpeg_file.parent)
    assert window.thumbnails.thumbnail_model.rowCount() == 1

    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))

    table = window.metadata_panel.model
    assert table.columnCount() == 4  # field names are the row headers
    assert table.rowCount() == len(window._mappings)
    assert table.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "Title"


def test_thumbnail_model_reports_sync_status(qapp, jpeg_file):
    report = SyncReport(SyncStatus.CONFLICT, ("Rating: Exif has '2', XMP (embedded) has '3'",))
    model = ThumbnailModel(lambda path: report)
    model.set_folder(jpeg_file.parent)
    index = model.index(0)

    model.data(index, Qt.ItemDataRole.DecorationRole)  # starts the background load
    deadline = time.monotonic() + 5
    while model.data(index, SYNC_ROLE) is None and time.monotonic() < deadline:
        qapp.processEvents()

    assert model.data(index, SYNC_ROLE) == report
    assert "Rating: Exif has '2'" in model.data(index, Qt.ItemDataRole.ToolTipRole)


def test_master_column_is_marked(qapp):
    window = MainWindow(Config(master_source=Source.IPTC))
    header = window.metadata_panel.model.headerData(3, Qt.Orientation.Horizontal, 0)
    assert header == "IPTC ★ master"


def test_sync_action_follows_selection(qapp, tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtGui import QImage

    for name in ("a.jpg", "b.jpg", "c.jpg"):
        QImage(8, 8, QImage.Format.Format_RGB32).save(str(tmp_path / name), "JPG")
    window = MainWindow()
    window._show_folder(tmp_path)
    assert not window.sync_action.isEnabled()

    model = window.thumbnails.thumbnail_model
    selection = window.thumbnails.selectionModel()
    flag = QItemSelectionModel.SelectionFlag.Select
    selection.select(model.index(2), flag)
    selection.select(model.index(0), flag)

    assert window.sync_action.isEnabled()
    assert window.thumbnails.selected_images() == [tmp_path / "a.jpg", tmp_path / "c.jpg"]

    window._show_folder(tmp_path)  # a new folder clears the selection
    assert not window.sync_action.isEnabled()


def test_thumbnails_allow_extended_selection(qapp):
    from PySide6.QtWidgets import QAbstractItemView

    window = MainWindow()
    mode = window.thumbnails.selectionMode()
    assert mode == QAbstractItemView.SelectionMode.ExtendedSelection
