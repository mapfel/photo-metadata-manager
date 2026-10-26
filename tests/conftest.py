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
