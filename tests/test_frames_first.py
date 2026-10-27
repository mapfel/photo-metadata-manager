import time

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage

from metadata_comparer.metadata.sync import SyncReport, SyncStatus
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import (
    CACHED_PLACEHOLDER_COLOR,
    FRAME_COLOR_ROLE,
    FRAME_COLORS,
    IMAGE_SIZE_ROLE,
    PLACEHOLDER_COLOR,
    SYNC_ROLE,
    ImageStatus,
    ThumbnailModel,
)

CONFLICT = SyncReport(SyncStatus.CONFLICT)


def wait_for(condition, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
    return condition()


def make_folder(tmp_path, count=3):
    for number in range(count):
        QImage(8, 8, QImage.Format.Format_RGB32).save(str(tmp_path / f"{number}.jpg"), "JPG")
    return tmp_path


def test_frame_size_comes_with_the_status_before_the_thumbnail(qapp, tmp_path):
    model = ThumbnailModel(lambda path: ImageStatus(CONFLICT, (4000, 3000)))
    model.set_folder(make_folder(tmp_path, 1))
    model.set_load_all(True)  # status only, no thumbnail is decoded
    index = model.index(0)

    assert wait_for(lambda: model.data(index, SYNC_ROLE) is not None, qapp)
    assert model.data(index, IMAGE_SIZE_ROLE) == QSize(160, 120)
    assert not model._thumbnails


def test_displayed_image_gets_urgent_status_check(qapp, tmp_path):
    model = ThumbnailModel(lambda path: ImageStatus(CONFLICT))
    model.set_folder(make_folder(tmp_path))
    model.set_load_all(True)
    background = model._status_jobs[1]
    assert not background.urgent

    model.data(model.index(1), Qt.ItemDataRole.DecorationRole)  # the view displays it

    assert model._status_jobs[1].urgent
    assert background.cancelled  # not read twice
    assert not model._status_jobs[0].urgent


def test_failing_check_marks_image_unknown(qapp, tmp_path):
    def broken_checker(path):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    model = ThumbnailModel(broken_checker)
    model.set_folder(make_folder(tmp_path, 1))
    model.set_load_all(True)
    index = model.index(0)

    assert wait_for(lambda: model.data(index, SYNC_ROLE) is not None, qapp)
    assert model.data(index, SYNC_ROLE).status == SyncStatus.UNKNOWN


def test_scan_progress_is_shown_while_reading_a_folder(qapp, tmp_path):
    window = MainWindow()
    progress = []
    window.thumbnails.thumbnail_model.statuses_progress.connect(
        lambda known, total: progress.append((known, total))
    )
    window._show_folder(make_folder(tmp_path))

    assert progress[0] == (0, 3)
    assert wait_for(lambda: progress[-1] == (3, 3), qapp)
    assert window.scan_progress.isHidden()


def frame(model, row=0):
    return model.data(model.index(row), FRAME_COLOR_ROLE)


def test_uncached_image_has_black_frame_until_its_thumbnail(qapp, tmp_path):
    model = ThumbnailModel(lambda path: ImageStatus(SyncReport(SyncStatus.OK), (40, 30)))
    model.set_folder(make_folder(tmp_path, 1))
    assert frame(model) == PLACEHOLDER_COLOR  # before anything is known
    model.data(model.index(0), Qt.ItemDataRole.DecorationRole)  # displayed

    assert wait_for(lambda: model.data(model.index(0), SYNC_ROLE) is not None, qapp)
    if not model._thumbnails:
        assert frame(model) == PLACEHOLDER_COLOR  # in sync: stays until the thumbnail
    assert wait_for(lambda: model._thumbnails, qapp)
    assert frame(model) is None


def test_mismatch_replaces_the_placeholder_frame(qapp, tmp_path):
    model = ThumbnailModel(lambda path: ImageStatus(CONFLICT, (40, 30)))
    model.set_folder(make_folder(tmp_path, 1))
    model.data(model.index(0), Qt.ItemDataRole.DecorationRole)
    assert wait_for(lambda: model._thumbnails, qapp)
    assert frame(model) == FRAME_COLORS[SyncStatus.CONFLICT]  # and stays


def test_cached_image_gets_grey_frame_without_waiting(qapp, tmp_path):
    def cached(path):
        return ImageStatus(SyncReport(SyncStatus.OK), (30, 40), cached=True)

    model = ThumbnailModel(lambda path: pytest.fail("read"), cached_checker=cached)
    model.set_folder(make_folder(tmp_path, 1))
    model.data(model.index(0), Qt.ItemDataRole.DecorationRole)  # the first paint

    assert frame(model) == CACHED_PLACEHOLDER_COLOR  # no thread involved
    assert model.data(model.index(0), IMAGE_SIZE_ROLE) == QSize(120, 160)  # portrait
    assert wait_for(lambda: model._thumbnails, qapp)
    assert frame(model) is None


def test_cached_status_is_announced_to_the_view(qapp, tmp_path):
    model = ThumbnailModel(
        lambda path: pytest.fail("read"),
        cached_checker=lambda path: ImageStatus(CONFLICT, cached=True),
    )
    model.set_folder(make_folder(tmp_path, 1))
    changes = []
    model.dataChanged.connect(lambda first, last, roles: changes.append(roles))
    model.data(model.index(0), Qt.ItemDataRole.DecorationRole)
    assert wait_for(lambda: any(SYNC_ROLE in roles for roles in changes), qapp)
