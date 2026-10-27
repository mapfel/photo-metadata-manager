import itertools
import os
from collections.abc import Callable
from dataclasses import dataclass
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
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    QTimer,
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
FRAME_COLOR_ROLE = Qt.ItemDataRole.UserRole + 3  # QColor of the frame, None for no frame
FRAME_COLORS = {
    SyncStatus.CONFLICT: QColor(220, 30, 30),
    SyncStatus.MISSING: QColor(255, 225, 100),
}
# Frames that stand in for a thumbnail until it is decoded: light grey when the metadata
# came from the cache, black when they had to be read from the file. A red or yellow frame
# replaces either; otherwise they disappear with the thumbnail.
CACHED_PLACEHOLDER_COLOR = QColor(200, 200, 200)
PLACEHOLDER_COLOR = QColor(0, 0, 0)


@dataclass(frozen=True)
class ImageStatus:
    """What a checker found out about an image, without decoding it."""

    report: SyncReport
    image_size: tuple[int, int] | None = None  # pixels as displayed, i.e. after rotation
    cached: bool = False  # the metadata came from the cache, not from the file


SyncChecker = Callable[[Path], ImageStatus]
# Answers from cached metadata only, without reading the file; None if not cached. Fast
# enough for the GUI thread.
CachedSyncChecker = Callable[[Path], ImageStatus | None]
# Thread pool priorities: frames of displayed images first, then their thumbnails, then the
# status of the rest of the folder.
URGENT_STATUS_PRIORITY = 2
THUMBNAIL_PRIORITY = 1
BACKGROUND_STATUS_PRIORITY = 0


def list_images(folder: Path) -> list[Path]:
    # scandir knows the entry types from the directory listing; a stat() per file is
    # slow on network and WSL drives.
    try:
        with os.scandir(folder) as entries:
            names = [
                entry.name
                for entry in entries
                if Path(entry.name).suffix.lower() in IMAGE_SUFFIXES and _is_file(entry)
            ]
    except OSError:
        return []
    return [folder / name for name in sorted(names, key=str.lower)]


def _is_file(entry: os.DirEntry) -> bool:
    try:
        return entry.is_file()
    except OSError:
        return False


class _LoaderSignals(QObject):
    thumbnail_loaded = Signal(int, int, QImage)  # generation, row, thumbnail
    status_loaded = Signal(int, int, int, object)  # generation, row, job id, ImageStatus


class _ThumbnailLoader(QRunnable):
    """Decodes a thumbnail off the GUI thread."""

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
        image = reader.read()
        if image.isNull():
            image = _placeholder_image()
        self._signals.thumbnail_loaded.emit(self._generation, self._row, image)


class _StatusLoader(QRunnable):
    """Checks the metadata sync status of an image off the GUI thread."""

    def __init__(
        self,
        signals: _LoaderSignals,
        checker: SyncChecker,
        generation: int,
        row: int,
        path: Path,
        job_id: int,
        urgent: bool,
    ) -> None:
        super().__init__()
        self._signals = signals
        self._checker = checker
        self._generation = generation
        self._row = row
        self._path = path
        self.job_id = job_id
        self.urgent = urgent
        self.cancelled = False  # set when a newer job for the same image replaces this one

    def run(self) -> None:
        if self.cancelled:
            return
        try:
            status = self._checker(self._path)
        except Exception as error:  # noqa: BLE001 - one broken image must not stall the rest
            status = ImageStatus(SyncReport(SyncStatus.UNKNOWN, (f"{self._path.name}: {error}",)))
        self._signals.status_loaded.emit(self._generation, self._row, self.job_id, status)


class ThumbnailModel(QAbstractListModel):
    """Images of one folder. Thumbnails load in the background when first displayed; the
    sync status (and with it the frame) of a displayed image comes ahead of its thumbnail.

    With load_all the sync status is checked for every image, displayed or not.
    """

    statuses_progress = Signal(int, int)  # images with a known status, all images

    def __init__(
        self,
        checker: SyncChecker,
        parent=None,
        cached_checker: CachedSyncChecker | None = None,
    ) -> None:
        super().__init__(parent)
        self._checker = checker
        self._cached_checker = cached_checker
        self._folder: Path | None = None
        self._paths: list[Path] = []
        self._thumbnails: dict[int, QPixmap] = {}
        self._image_sizes: dict[int, QSize] = {}
        self._reports: dict[int, SyncReport] = {}
        self._from_cache: set[int] = set()  # status known from cached metadata
        self._requested: set[int] = set()  # thumbnail loading started
        self._status_jobs: dict[int, _StatusLoader] = {}  # pending status checks
        self._job_ids = itertools.count()
        self._load_all = False
        self._generation = 0
        self._pool = QThreadPool(self)
        self._signals = _LoaderSignals(self)
        self._signals.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._signals.status_loaded.connect(self._on_status_loaded)

    def set_folder(self, folder: Path) -> None:
        self._pool.clear()
        self.beginResetModel()
        self._folder = folder
        self._generation += 1
        self._paths = list_images(folder)
        self._thumbnails.clear()
        self._image_sizes.clear()
        self._reports.clear()
        self._from_cache.clear()
        self._requested.clear()
        self._status_jobs.clear()
        self.endResetModel()
        if self._load_all:
            self.load_all()
        self._report_progress()

    def set_load_all(self, load_all: bool) -> None:
        """Check the sync status of every image, not just of those displayed, e.g. so
        they can be filtered by it."""
        self._load_all = load_all
        if load_all:
            self.load_all()
        self._report_progress()

    @property
    def paths(self) -> list[Path]:
        return list(self._paths)

    @property
    def loads_all(self) -> bool:
        return self._load_all

    def load_all(self) -> None:
        for row in range(len(self._paths)):
            if row not in self._reports:
                self._request_status(row, urgent=False)

    def rescan(self) -> None:
        """Re-read the folder. If its images are unchanged, reload thumbnails and sync
        status of those already loaded (keeps the selection); otherwise start over."""
        if self._folder is None:
            return
        if list_images(self._folder) != self._paths:
            self.set_folder(self._folder)
            return
        for row in sorted(self._requested):
            self._request_status(row, urgent=True, force=True)
            self._start_thumbnail_loader(row)
        for row in sorted((self._reports.keys() | self._status_jobs.keys()) - self._requested):
            self._request_status(row, urgent=False, force=True)
        if self._load_all:
            self.load_all()

    def refresh(self, path: Path) -> None:
        """Re-check the sync status of `path`; the old status stays until then."""
        if path in self._paths:
            self._request_status(self._paths.index(path), urgent=True, force=True)

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
        if role == FRAME_COLOR_ROLE:
            return self._frame_color(row)
        if role == Qt.ItemDataRole.DecorationRole:
            return self._thumbnail(row)
        return None

    def _thumbnail(self, row: int) -> QPixmap:
        if row in self._thumbnails:
            return self._thumbnails[row]
        if row not in self._requested:
            # The frame does not wait for the thumbnail: the status check goes first, and
            # cached metadata answer it right away, before the frame is first painted.
            if row not in self._reports and not self._use_cached_status(row):
                self._request_status(row, urgent=True)
            self._start_thumbnail_loader(row)
        return _empty_canvas()

    def _frame_color(self, row: int) -> QColor | None:
        report = self._reports.get(row)
        if report is not None and report.status in FRAME_COLORS:
            return FRAME_COLORS[report.status]
        if row in self._thumbnails:
            return None
        return CACHED_PLACEHOLDER_COLOR if row in self._from_cache else PLACEHOLDER_COLOR

    def _use_cached_status(self, row: int) -> bool:
        """Take the status of `row` from the cache, if it has the metadata."""
        status = self._cached_checker(self._paths[row]) if self._cached_checker else None
        if status is None:
            return False
        pending = self._status_jobs.pop(row, None)
        if pending is not None:
            pending.cancelled = True
        self._set_status(row, status)
        # Called while the view paints: tell it (and the filter) about the change later.
        generation = self._generation
        QTimer.singleShot(0, self, lambda: self._announce_status(generation, row))
        return True

    def _announce_status(self, generation: int, row: int) -> None:
        if generation == self._generation:
            index = self.index(row)
            self.dataChanged.emit(index, index, [SYNC_ROLE, IMAGE_SIZE_ROLE, FRAME_COLOR_ROLE])

    def _start_thumbnail_loader(self, row: int) -> None:
        self._requested.add(row)
        loader = _ThumbnailLoader(self._signals, self._generation, row, self._paths[row])
        self._pool.start(loader, THUMBNAIL_PRIORITY)

    def _request_status(self, row: int, urgent: bool, force: bool = False) -> None:
        """Check the status of `row` unless that is pending already. An urgent request
        replaces a pending background one; `force` replaces any, e.g. after a write."""
        pending = self._status_jobs.get(row)
        if pending is not None:
            if not force and (pending.urgent or not urgent):
                return
            pending.cancelled = True
        job = _StatusLoader(
            self._signals,
            self._checker,
            self._generation,
            row,
            self._paths[row],
            next(self._job_ids),
            urgent,
        )
        self._status_jobs[row] = job
        priority = URGENT_STATUS_PRIORITY if urgent else BACKGROUND_STATUS_PRIORITY
        self._pool.start(job, priority)

    def _on_status_loaded(
        self, generation: int, row: int, job_id: int, status: ImageStatus
    ) -> None:
        if generation != self._generation:
            return
        pending = self._status_jobs.get(row)
        if pending is not None and pending.job_id == job_id:
            del self._status_jobs[row]
        self._set_status(row, status)
        index = self.index(row)
        self.dataChanged.emit(index, index, [SYNC_ROLE, IMAGE_SIZE_ROLE, FRAME_COLOR_ROLE])

    def _set_status(self, row: int, status: ImageStatus) -> None:
        self._reports[row] = status.report
        if status.cached:
            self._from_cache.add(row)
        else:
            self._from_cache.discard(row)
        if row not in self._thumbnails and status.image_size:
            # Lets the frame be drawn before the thumbnail arrives.
            self._image_sizes[row] = QSize(*status.image_size).scaled(
                THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio
            )
        self._report_progress()

    def _on_thumbnail_loaded(self, generation: int, row: int, image: QImage) -> None:
        if generation != self._generation:
            return
        self._image_sizes[row] = image.size()
        canvas = _empty_canvas()
        painter = QPainter(canvas)
        target = QRect(QPoint(0, 0), image.size())
        target.moveCenter(canvas.rect().center())
        painter.drawImage(target, image)
        painter.end()
        self._thumbnails[row] = canvas
        index = self.index(row)
        self.dataChanged.emit(
            index, index, [Qt.ItemDataRole.DecorationRole, IMAGE_SIZE_ROLE, FRAME_COLOR_ROLE]
        )

    def _report_progress(self) -> None:
        self.statuses_progress.emit(len(self._reports), len(self._paths))


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
    """Draws a frame around the thumbnail when its metadata is out of sync with the master,
    and a placeholder frame while the thumbnail is being decoded."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        color = index.data(FRAME_COLOR_ROLE)
        if color is None:
            return
        # Until the metadata or the thumbnail tell the image size, the frame takes the
        # whole thumbnail area.
        image_size = index.data(IMAGE_SIZE_ROLE) or THUMBNAIL_SIZE

        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        style = item_option.widget.style() if item_option.widget else QApplication.style()
        area = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemDecoration, item_option, item_option.widget
        )
        frame = QRect(QPoint(0, 0), image_size)
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


class SyncStatusFilter(QSortFilterProxyModel):
    """Shows only images with one of the chosen sync statuses; none chosen shows all.

    While a filter is active, images whose status is not known yet are hidden."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._statuses: frozenset[SyncStatus] = frozenset()
        self.setFilterRole(SYNC_ROLE)  # re-filter a row when its status arrives

    @property
    def statuses(self) -> frozenset[SyncStatus]:
        return self._statuses

    def set_statuses(self, statuses: frozenset[SyncStatus]) -> None:
        if not hasattr(self, "beginFilterChange"):  # Qt < 6.10
            self._statuses = statuses
            self.invalidateFilter()
            return
        self.beginFilterChange()
        self._statuses = statuses
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not self._statuses:
            return True
        index = self.sourceModel().index(source_row, 0, source_parent)
        report = index.data(SYNC_ROLE)
        return report is not None and report.status in self._statuses


class ThumbnailView(QListView):
    image_selected = Signal(object)  # Path, or None when the current image was filtered out
    image_activated = Signal(Path)  # double click
    selection_changed = Signal()

    def __init__(
        self,
        checker: SyncChecker,
        parent=None,
        cached_checker: CachedSyncChecker | None = None,
    ) -> None:
        super().__init__(parent)
        self.thumbnail_model = ThumbnailModel(checker, self, cached_checker)
        self.status_filter = SyncStatusFilter(self)
        self.status_filter.setSourceModel(self.thumbnail_model)
        # Connected before setModel(), so it runs before the selection model would move
        # the current index to a neighbour of a row that is filtered out.
        self.status_filter.rowsAboutToBeRemoved.connect(self._on_rows_about_to_be_removed)
        self.setModel(self.status_filter)
        self._check_all = False
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(CANVAS_SIZE)
        self.setGridSize(CANVAS_SIZE + QSize(16, 32))
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # Ctrl+click toggles an image, Shift+click selects a range.
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.selectionModel().selectionChanged.connect(self.selection_changed)
        self.thumbnail_model.modelReset.connect(self.selection_changed)
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.doubleClicked.connect(lambda index: self.image_activated.emit(index.data(PATH_ROLE)))

    def set_folder(self, folder: Path) -> None:
        self.thumbnail_model.set_folder(folder)

    def rescan(self) -> None:
        self.thumbnail_model.rescan()

    def images(self) -> list[Path]:
        """All images of the folder, shown or filtered out."""
        return self.thumbnail_model.paths

    def set_status_filter(self, statuses: frozenset[SyncStatus]) -> None:
        """Show only images with these sync statuses; an empty set shows all."""
        self.status_filter.set_statuses(statuses)
        self._update_load_all()
        self.selection_changed.emit()

    def set_check_all(self, check_all: bool) -> None:
        """Check the sync status of every image of a folder, e.g. to fill a cache."""
        self._check_all = check_all
        self._update_load_all()

    def _update_load_all(self) -> None:
        self.thumbnail_model.set_load_all(self._check_all or bool(self.status_filter.statuses))

    def view_index(self, row: int) -> QModelIndex:
        """The view's index of image `row` of the thumbnail model (invalid if hidden)."""
        return self.status_filter.mapFromSource(self.thumbnail_model.index(row))

    def selected_images(self) -> list[Path]:
        indexes = sorted(self.selectionModel().selectedIndexes(), key=QModelIndex.row)
        return [index.data(PATH_ROLE) for index in indexes]

    def _on_rows_about_to_be_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        current = self.currentIndex()
        if current.isValid() and first <= current.row() <= last:
            self.selectionModel().clearCurrentIndex()

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            self.image_selected.emit(current.data(PATH_ROLE))
        elif previous.isValid():
            self.image_selected.emit(None)
