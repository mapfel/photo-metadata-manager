import time

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QImage

from metadata_comparer.metadata.sync import SyncReport, SyncStatus
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import PATH_ROLE, SYNC_ROLE, ImageStatus, ThumbnailView

# The fake checker derives the status from the file name.
STATUS_BY_NAME = {
    "ok.jpg": SyncStatus.OK,
    "missing.jpg": SyncStatus.MISSING,
    "conflict.jpg": SyncStatus.CONFLICT,
    "unreadable.jpg": SyncStatus.UNKNOWN,
}


def fake_checker(path):
    return ImageStatus(SyncReport(STATUS_BY_NAME[path.name]))


def wait_for(condition, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
    return condition()


def make_folder(tmp_path):
    for name in STATUS_BY_NAME:
        QImage(8, 8, QImage.Format.Format_RGB32).save(str(tmp_path / name), "JPG")
    return tmp_path


def shown(view):
    model = view.model()
    return {model.index(row, 0).data(PATH_ROLE).name for row in range(model.rowCount())}


def test_no_filter_shows_all_images(qapp, tmp_path):
    view = ThumbnailView(fake_checker)
    view.set_folder(make_folder(tmp_path))
    assert shown(view) == set(STATUS_BY_NAME)  # without waiting for the status


def test_filter_loads_status_of_all_images(qapp, tmp_path):
    view = ThumbnailView(fake_checker)
    view.set_folder(make_folder(tmp_path))

    # Nothing is displayed, so only the filter can have started the loading.
    view.set_status_filter(frozenset({SyncStatus.OK}))
    assert wait_for(lambda: shown(view) == {"ok.jpg"}, qapp)


def test_filters_combine(qapp, tmp_path):
    view = ThumbnailView(fake_checker)
    view.set_status_filter(frozenset({SyncStatus.MISSING, SyncStatus.CONFLICT}))
    view.set_folder(make_folder(tmp_path))  # also applies to a newly opened folder
    assert wait_for(lambda: shown(view) == {"missing.jpg", "conflict.jpg"}, qapp)

    view.set_status_filter(frozenset())
    assert shown(view) == set(STATUS_BY_NAME)


def test_filtered_out_images_leave_selection_and_table(qapp, tmp_path):
    view = ThumbnailView(fake_checker)
    view.set_folder(make_folder(tmp_path))
    view.thumbnail_model.load_all()
    rows = {path.name: row for row, path in enumerate(view.thumbnail_model._paths)}
    assert wait_for(
        lambda: all(view.view_index(row).data(SYNC_ROLE) for row in rows.values()), qapp
    )
    selection = view.selectionModel()
    selection.setCurrentIndex(
        view.view_index(rows["conflict.jpg"]), QItemSelectionModel.SelectionFlag.SelectCurrent
    )
    selection.select(view.view_index(rows["ok.jpg"]), QItemSelectionModel.SelectionFlag.Select)
    selected = []
    view.image_selected.connect(selected.append)

    view.set_status_filter(frozenset({SyncStatus.OK}))

    assert selected == [None]  # the table no longer shows the hidden current image
    assert [path.name for path in view.selected_images()] == ["ok.jpg"]


def test_toolbar_checkboxes_drive_the_filter(qapp, tmp_path):
    window = MainWindow()
    boxes = window.status_filter_boxes
    assert set(boxes) == {SyncStatus.OK, SyncStatus.MISSING, SyncStatus.CONFLICT}
    assert not any(box.isChecked() for box in boxes.values())  # default: all images

    boxes[SyncStatus.OK].setChecked(True)
    boxes[SyncStatus.CONFLICT].setChecked(True)
    assert window.thumbnails.status_filter.statuses == {SyncStatus.OK, SyncStatus.CONFLICT}

    boxes[SyncStatus.OK].setChecked(False)
    boxes[SyncStatus.CONFLICT].setChecked(False)
    assert window.thumbnails.status_filter.statuses == frozenset()
