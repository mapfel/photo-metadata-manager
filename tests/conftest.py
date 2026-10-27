import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def jpeg_file(tmp_path, qapp):
    from PySide6.QtGui import QImage

    path = tmp_path / "photo.jpg"
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(0xFF3366CC)
    assert image.save(str(path), "JPG")
    return path


@pytest.fixture(autouse=True)
def default_folder(tmp_path_factory, monkeypatch):
    """Windows start in an empty folder, not in the user's Pictures, where the metadata
    cache would be written."""
    folder = tmp_path_factory.mktemp("default_folder")
    monkeypatch.setattr("metadata_comparer.ui.main_window._default_folder", lambda: folder)
    return folder
