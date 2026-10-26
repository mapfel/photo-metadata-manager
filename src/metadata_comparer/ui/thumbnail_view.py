from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QMargins,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from metadata_comparer.metadata.sync import SyncReport, SyncStatus

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff", ".png"}
THUMBNAIL_SIZE = QSize(160, 160)
FRAME_WIDTH = 4
# Thumbnails are centered on a fixed canvas: labels line up and the frame has room.
CANVAS_MARGIN = FRAME_WIDTH + 2
CANVAS_SIZE = THUMBNAIL_SIZE.grownBy(QMargins(*[CANVAS_MARGIN] * 4))
PATH_ROLE = Qt.ItemDataRole.UserRole
SYNC_ROLE = Qt.ItemDataRole.UserRole + 1
IMAGE_SIZE_ROLE = Qt.ItemDataRole.UserRole + 2  # size of the thumbnail within the canvas
FRAME_COLORS = {
    SyncStatus.CONFLICT: QColor(220, 30, 30),
    SyncStatus.MISSING: QColor(255, 225, 100),
}

SyncChecker = Callable[[Path], SyncReport]


def list_images(folder: Path) -> list[Path]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    images = [entry for entry in entries if entry.suffix.lower() in IMAGE_SUFFIXES]
    return sorted((image for image in images if image.is_file()), key=lambda p: p.name.lower())


class _LoaderSignals(QObject):
    loaded = Signal(int, int, QImage, object)  # generation, row, thumbnail, SyncReport


class _ThumbnailLoader(QRunnable):
    """Decodes the thumbnail and checks the metadata sync status off the GUI thread."""

    def __init__(
        self,
        signals: _LoaderSignals,
        checker: SyncChecker,
        generation: int,
        row: int,
        path: Path,
    ) -> None:
        super().__init__()
        self._signals = signals
        self._checker = checker
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
        image = reader.read()
        if image.isNull():
            image = _placeholder_image()
        report = self._checker(self._path)
        self._signals.loaded.emit(self._generation, self._row, image, report)


class ThumbnailModel(QAbstractListModel):
    """Images of one folder. Thumbnails load in the background when first displayed."""

    def __init__(self, checker: SyncChecker, parent=None) -> None:
        super().__init__(parent)
        self._checker = checker
        self._paths: list[Path] = []
        self._thumbnails: dict[int, QPixmap] = {}
        self._image_sizes: dict[int, QSize] = {}
        self._reports: dict[int, SyncReport] = {}
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
        self._image_sizes.clear()
        self._reports.clear()
        self._requested.clear()
        self.endResetModel()

    def refresh(self, path: Path) -> None:
        """Reload thumbnail and sync status of `path`; the old thumbnail stays until then."""
        if path in self._paths:
            self._start_loader(self._paths.index(path))

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        row = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._paths[row].name
        if role == Qt.ItemDataRole.ToolTipRole:
            report = self._reports.get(row)
            issues = report.issues if report else ()
            return "\n".join([str(self._paths[row]), *issues])
        if role == SYNC_ROLE:
            return self._reports.get(row)
        if role == PATH_ROLE:
            return self._paths[row]
        if role == IMAGE_SIZE_ROLE:
            return self._image_sizes.get(row)
        if role == Qt.ItemDataRole.DecorationRole:
            return self._thumbnail(row)
        return None

    def _thumbnail(self, row: int) -> QPixmap:
        if row in self._thumbnails:
            return self._thumbnails[row]
        if row not in self._requested:
            self._start_loader(row)
        return _empty_canvas()

    def _start_loader(self, row: int) -> None:
        self._requested.add(row)
        loader = _ThumbnailLoader(
            self._signals, self._checker, self._generation, row, self._paths[row]
        )
        self._pool.start(loader)

    def _on_loaded(self, generation: int, row: int, image: QImage, report: SyncReport) -> None:
        if generation != self._generation:
            return
        self._reports[row] = report
        self._image_sizes[row] = image.size()
        canvas = _empty_canvas()
        painter = QPainter(canvas)
        target = QRect(QPoint(0, 0), image.size())
        target.moveCenter(canvas.rect().center())
        painter.drawImage(target, image)
        painter.end()
        self._thumbnails[row] = canvas
        index = self.index(row)
        changed_roles = [Qt.ItemDataRole.DecorationRole, SYNC_ROLE, IMAGE_SIZE_ROLE]
        self.dataChanged.emit(index, index, changed_roles)


def _empty_canvas() -> QPixmap:
    pixmap = QPixmap(CANVAS_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _placeholder_image() -> QImage:
    # QIcon.pixmap() and QStyle are GUI-thread only, so draw a neutral box instead.
    image = QImage(
        THUMBNAIL_SIZE.width() // 2, THUMBNAIL_SIZE.height() // 2, QImage.Format.Format_ARGB32
    )
    image.fill(QColor(200, 200, 200))
    return image


class ThumbnailDelegate(QStyledItemDelegate):
    """Draws a frame around the thumbnail when its metadata is out of sync with the master."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        report = index.data(SYNC_ROLE)
        color = FRAME_COLORS.get(report.status) if report else None
        if color is None:
            return

        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        style = item_option.widget.style() if item_option.widget else QApplication.style()
        area = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemDecoration, item_option, item_option.widget
        )
        frame = QRect(QPoint(0, 0), index.data(IMAGE_SIZE_ROLE))
        frame.moveCenter(area.center())
        offset = FRAME_WIDTH // 2 + 1
        frame.adjust(-offset, -offset, offset, offset)

        painter.save()
        pen = QPen(color, FRAME_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        painter.restore()


class ThumbnailView(QListView):
    image_selected = Signal(Path)
    image_activated = Signal(Path)  # double click

    def __init__(self, checker: SyncChecker, parent=None) -> None:
        super().__init__(parent)
        self.thumbnail_model = ThumbnailModel(checker, self)
        self.setModel(self.thumbnail_model)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(CANVAS_SIZE)
        self.setGridSize(CANVAS_SIZE + QSize(16, 32))
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.doubleClicked.connect(lambda index: self.image_activated.emit(index.data(PATH_ROLE)))

    def set_folder(self, folder: Path) -> None:
        self.thumbnail_model.set_folder(folder)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.image_selected.emit(current.data(PATH_ROLE))
