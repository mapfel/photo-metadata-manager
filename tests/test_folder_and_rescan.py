import time

import pytest
from PySide6.QtCore import QItemSelectionModel, QSettings
from PySide6.QtGui import QImage

from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.sync import SyncStatus
from metadata_comparer.ui.main_window import LAST_FOLDER_KEY, MainWindow
from metadata_comparer.ui.thumbnail_view import SYNC_ROLE


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "state.ini"), QSettings.Format.IniFormat)


def make_jpeg(path):
    QImage(8, 8, QImage.Format.Format_RGB32).save(str(path), "JPG")
    return path


def wait_for(condition, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
    return condition()


def test_last_folder_is_remembered(qapp, tmp_path, settings):
    folder = tmp_path / "photos"
    folder.mkdir()
    window = MainWindow(settings=settings)
    window.folder_tree.select_folder(folder)
    assert settings.value(LAST_FOLDER_KEY) == str(folder)

    restarted = MainWindow(settings=settings)
    assert restarted._folder == folder


def test_missing_last_folder_falls_back_to_default(qapp, tmp_path, settings):
    settings.setValue(LAST_FOLDER_KEY, str(tmp_path / "deleted"))
    window = MainWindow(settings=settings)
    assert window._folder is not None
    assert window._folder != tmp_path / "deleted"


def test_rescan_picks_up_new_files(qapp, tmp_path):
    make_jpeg(tmp_path / "a.jpg")
    window = MainWindow()
    window._show_folder(tmp_path)
    assert window.rescan_action.isEnabled()
    assert window.thumbnails.thumbnail_model.rowCount() == 1

    make_jpeg(tmp_path / "b.jpg")
    window.rescan()
    assert window.thumbnails.thumbnail_model.rowCount() == 2


def test_rescan_reloads_externally_changed_metadata(qapp, tmp_path):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = make_jpeg(tmp_path / "a.jpg")
    make_jpeg(tmp_path / "b.jpg")
    window = MainWindow()
    window._show_folder(tmp_path)
    model = window.thumbnails.thumbnail_model
    index = model.index(0)
    model.data(index, 1)  # DecorationRole starts the background load
    assert wait_for(lambda: model.data(index, SYNC_ROLE) is not None, qapp)
    assert model.data(index, SYNC_ROLE).status == SyncStatus.OK
    selection = window.thumbnails.selectionModel()
    selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.SelectCurrent)
    selection.select(model.index(1), QItemSelectionModel.SelectionFlag.Select)

    # Another program writes a conflicting rating.
    other = exiv2.ImageFactory.open(str(image))
    other.readMetadata()
    other.exifData()["Exif.Image.Rating"] = "2"
    other.xmpData()["Xmp.xmp.Rating"] = "4"
    other.writeMetadata()
    assert read_metadata(image).tags[Source.EXIF]["Exif.Image.Rating"] == ["2"]

    window.rescan()
    assert wait_for(lambda: model.data(index, SYNC_ROLE).status == SyncStatus.CONFLICT, qapp)
    panel = window.metadata_panel.model
    rating = [m.name for m in window._mappings].index("Rating")
    assert panel.data(panel.index(rating, 0)) == "2"
    assert len(window.thumbnails.selected_images()) == 2  # selection kept
