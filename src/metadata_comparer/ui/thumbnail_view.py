from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QApplication, QListView, QStyle

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff", ".png"}
THUMBNAIL_SIZE = QSize(160, 160)
PATH_ROLE = Qt.ItemDataRole.UserRole


def list_images(folder: Path) -> list[Path]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    images = [entry for entry in entries if entry.suffix.lower() in IMAGE_SUFFIXES]
    return sorted((image for image in images if image.is_file()), key=lambda p: p.name.lower())


class _LoaderSignals(QObject):
    loaded = Signal(int, int, QImage)  # generation, row, thumbnail


class _ThumbnailLoader(QRunnable):
    def __init__(self, signals: _LoaderSignals, generation: int, row: int, path: Path) -> None:
        super().__init__()
        self._signals = signals
        self._generation = generation
        self._row = row
        self._path = path

    def run(self) -> None:
        reader = QImageReader(str(self._path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            # Lets the JPEG decoder downscale while decoding, which is much faster.
            reader.setScaledSize(size.scaled(THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio))
        self._signals.loaded.emit(self._generation, self._row, reader.read())


class ThumbnailModel(QAbstractListModel):
    """Images of one folder. Thumbnails load in the background when first displayed."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paths: list[Path] = []
        self._thumbnails: dict[int, QPixmap] = {}
        self._requested: set[int] = set()
        self._generation = 0
        self._pool = QThreadPool(self)
        self._signals = _LoaderSignals(self)
        self._signals.loaded.connect(self._on_loaded)

    def set_folder(self, folder: Path) -> None:
        self._pool.clear()
        self.beginResetModel()
        self._generation += 1
        self._paths = list_images(folder)
        self._thumbnails.clear()
        self._requested.clear()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        row = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._paths[row].name
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(self._paths[row])
        if role == PATH_ROLE:
            return self._paths[row]
        if role == Qt.ItemDataRole.DecorationRole:
            return self._thumbnail(row)
        return None

    def _thumbnail(self, row: int) -> QPixmap:
        if row in self._thumbnails:
            return self._thumbnails[row]
        if row not in self._requested:
            self._requested.add(row)
            loader = _ThumbnailLoader(self._signals, self._generation, row, self._paths[row])
            self._pool.start(loader)
        # A full-size blank keeps the item layout stable until the thumbnail arrives.
        return _loading_pixmap()

    def _on_loaded(self, generation: int, row: int, image: QImage) -> None:
        if generation != self._generation:
            return
        if image.isNull():
            self._thumbnails[row] = _placeholder()
        else:
            self._thumbnails[row] = QPixmap.fromImage(image)
        index = self.index(row)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])


def _loading_pixmap() -> QPixmap:
    pixmap = QPixmap(THUMBNAIL_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _placeholder() -> QPixmap:
    icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    return icon.pixmap(THUMBNAIL_SIZE)


class ThumbnailView(QListView):
    image_selected = Signal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.thumbnail_model = ThumbnailModel(self)
        self.setModel(self.thumbnail_model)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(THUMBNAIL_SIZE)
        self.setGridSize(THUMBNAIL_SIZE + QSize(24, 40))
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_folder(self, folder: Path) -> None:
        self.thumbnail_model.set_folder(folder)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.image_selected.emit(current.data(PATH_ROLE))
