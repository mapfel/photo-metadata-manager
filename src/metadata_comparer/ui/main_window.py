from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QToolBar,
    QWidget,
)

from metadata_comparer.config import Config, save_config
from metadata_comparer.metadata.cache import MetadataCache, cached_tags
from metadata_comparer.metadata.mapping import FieldMapping, load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import RawMetadata, Source
from metadata_comparer.metadata.sync import SyncReport, SyncStatus, check_sync
from metadata_comparer.ui.folder_tree import FolderTree
from metadata_comparer.ui.metadata_panel import MetadataPanel
from metadata_comparer.ui.sync_dialog import SyncDialog
from metadata_comparer.ui.thumbnail_view import (
    FRAME_COLORS,
    PATH_ROLE,
    ThumbnailView,
    list_images,
)

LAST_FOLDER_KEY = "last_folder"
CACHE_SAVE_INTERVAL_MS = 2000
# Thumbnail filter checkboxes in the toolbar: label, status shown, tooltip.
STATUS_FILTERS = (
    ("In sync", SyncStatus.OK, "Show images whose compared fields match the master"),
    (
        "Missing",
        SyncStatus.MISSING,
        "Show images with a yellow frame: the master has a value another source lacks",
    ),
    (
        "Conflict",
        SyncStatus.CONFLICT,
        "Show images with a red frame: another source holds a different value",
    ),
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: Config | None = None,
        mappings: list[FieldMapping] | None = None,
        settings: QSettings | None = None,
        config_path: Path | None = None,
    ):
        """`settings` stores UI state such as the last folder; None keeps nothing.
        Changes made in the UI to the configuration are saved to `config_path`, if given."""
        super().__init__()
        self.setWindowTitle("Metadata Comparer")
        self._config = config or Config()
        self._config_path = config_path
        self._mappings = mappings or load_mappings()
        self._settings = settings
        self._folder: Path | None = None
        # Metadata of the current folder while caching is on. Loader threads use it too.
        self._cache: MetadataCache | None = None
        self._cache_tags = cached_tags(self._mappings)
        self._unsavable_cache: MetadataCache | None = None  # saving failed, don't retry
        self._cache_save_timer = QTimer(self)
        self._cache_save_timer.setInterval(CACHE_SAVE_INTERVAL_MS)
        self._cache_save_timer.timeout.connect(self._save_cache)
        self._cache_save_timer.start()

        self.folder_tree = FolderTree()
        self.thumbnails = ThumbnailView(self._check_sync)
        self.thumbnails.set_check_all(self._config.cache_enabled)
        self.metadata_panel = MetadataPanel(
            self._mappings,
            self._config.master_source,
            frozenset(self._config.compared_fields),
            frozenset(self._config.compared_sources),
            reader=self._read_metadata,
        )

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.thumbnails)
        right.addWidget(self.metadata_panel)
        right.setSizes([550, 350])

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(self.folder_tree)
        main.addWidget(right)
        main.setSizes([300, 1100])
        self.setCentralWidget(main)

        self.sync_action = QAction("Synchronize metadata…", self)
        self.sync_action.setToolTip("Synchronize the metadata of the selected images")
        self.sync_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.sync_action.setEnabled(False)
        self.sync_action.triggered.connect(self._sync_selected_images)
        self.rescan_action = QAction("Rescan metadata", self)
        self.rescan_action.setToolTip(
            "Read the folder and the metadata again, e.g. after another program changed them"
        )
        self.rescan_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.rescan_action.setEnabled(False)
        self.rescan_action.triggered.connect(self.rescan)
        toolbar = QToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self.sync_action)
        toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        toolbar.addWidget(self._create_status_filter())
        toolbar.addSeparator()
        self.cache_box = QCheckBox("Cache metadata")
        self.cache_box.setToolTip(
            "Keep the metadata of each folder in a .mcs-cache file there, so frames and "
            "table show up fast. Rescan metadata reads the files again."
        )
        self.cache_box.setChecked(self._config.cache_enabled)
        self.cache_box.toggled.connect(self.set_cache_enabled)
        toolbar.addWidget(self.cache_box)
        self.addToolBar(toolbar)

        self.folder_tree.folder_selected.connect(self._show_folder)
        self.thumbnails.image_selected.connect(self._show_metadata)
        self.thumbnails.image_activated.connect(lambda image: self._open_sync_dialog([image]))
        self.thumbnails.selection_changed.connect(self._update_sync_action)
        self.metadata_panel.metadata_written.connect(self._forget_metadata)
        self.metadata_panel.compared_field_toggled.connect(self.toggle_compared_field)
        self.metadata_panel.compared_source_toggled.connect(self.toggle_compared_source)

        self.folder_tree.select_folder(self._start_folder())

    def rescan(self) -> None:
        """Pick up changes made by other programs; unapplied table choices are dropped."""
        if self._folder is None:
            return
        if self._cache is not None:
            self._cache.clear()
        self.thumbnails.rescan()
        current = self.thumbnails.currentIndex()
        if current.isValid():
            self._show_metadata(current.data(PATH_ROLE))
        else:
            self.metadata_panel.show_image(None)
        count = self.thumbnails.thumbnail_model.rowCount()
        self.statusBar().showMessage(f"Rescanned {self._folder} – {count} image(s)")

    def _create_status_filter(self) -> QWidget:
        """Checkboxes that combine to a thumbnail filter; none checked shows all images."""
        group = QWidget()
        group.setObjectName("status_filter")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(QLabel("Show only:"))
        self.status_filter_boxes: dict[SyncStatus, QCheckBox] = {}
        for label, status, tooltip in STATUS_FILTERS:
            box = QCheckBox(label)
            box.setIcon(_frame_icon(FRAME_COLORS.get(status)))
            box.setToolTip(f"{tooltip}. With no box ticked, all images are shown.")
            box.toggled.connect(self._apply_status_filter)
            layout.addWidget(box)
            self.status_filter_boxes[status] = box
        return group

    def _apply_status_filter(self) -> None:
        statuses = frozenset(
            status for status, box in self.status_filter_boxes.items() if box.isChecked()
        )
        self.thumbnails.set_status_filter(statuses)

    def toggle_compared_field(self, field: str) -> None:
        """Include or exclude `field` from the thumbnail frames and re-check the thumbnails."""
        fields = self._config.compared_fields
        if field in fields:
            fields = tuple(name for name in fields if name != field)
        else:
            mapping_order = [mapping.name for mapping in self._mappings]
            fields = tuple(sorted({*fields, field}, key=mapping_order.index))
        self._update_config(replace(self._config, compared_fields=fields))
        self.metadata_panel.model.set_compared_fields(frozenset(fields))

    def toggle_compared_source(self, source: Source) -> None:
        """Include or exclude `source` from the comparison with the master."""
        if source == self._config.master_source:
            self.statusBar().showMessage(f"{source.label} is the master and is always compared.")
            return
        sources = set(self._config.compared_sources) ^ {source}
        ordered = tuple(candidate for candidate in Source if candidate in sources)
        self._update_config(replace(self._config, compared_sources=ordered))
        self.metadata_panel.model.set_compared_sources(frozenset(ordered))

    def set_cache_enabled(self, enabled: bool) -> None:
        """Turn the metadata cache on or off. Turning it on rebuilds the cache of the
        current folder from its files, as they may have changed meanwhile."""
        if enabled == self._config.cache_enabled:
            return
        self._save_cache()
        self._cache = None
        if enabled and self._folder is not None:
            self._cache = MetadataCache(self._folder, self._cache_tags)
        self._update_config(replace(self._config, cache_enabled=enabled))
        self.thumbnails.set_check_all(enabled)
        self.cache_box.setChecked(enabled)

    def _update_config(self, config: Config) -> None:
        """Use and save `config`, then re-check the thumbnails."""
        # Loader threads read self._config; swapping the reference keeps that safe.
        self._config = config
        if self._config_path is not None:
            try:
                save_config(self._config_path, config)
            except OSError as error:
                self.statusBar().showMessage(f"Could not save the configuration: {error}")
        # Only the thumbnails depend on it; the table keeps its unapplied choices.
        self.thumbnails.rescan()

    def _start_folder(self) -> Path:
        last = self._settings.value(LAST_FOLDER_KEY) if self._settings else None
        if last and Path(last).is_dir():
            return Path(last)
        return _default_folder()

    def _show_folder(self, folder: Path) -> None:
        self._save_cache()
        self._folder = folder
        self._cache = None
        if self._config.cache_enabled:
            # A folder without a cache file is scanned completely to build it.
            self._cache = MetadataCache.load(folder, self._cache_tags)
            self._cache.keep_only({image.name for image in list_images(folder)})
        self.rescan_action.setEnabled(True)
        if self._settings is not None:
            self._settings.setValue(LAST_FOLDER_KEY, str(folder))
        self.thumbnails.set_folder(folder)
        self.metadata_panel.show_image(None)
        count = self.thumbnails.thumbnail_model.rowCount()
        self.statusBar().showMessage(f"{folder} – {count} image(s)")

    def _read_metadata(self, image: Path, fresh: bool = False) -> RawMetadata:
        """The metadata of `image`, from the cache if it has them, unless `fresh`.
        Metadata read from the file are added to the cache. Thread-safe."""
        cache = self._cache
        if cache is None or image.parent != cache.folder:
            return read_metadata(image)
        if not fresh:
            raw = cache.get(image)
            if raw is not None:
                return raw
        return cache.put(image, read_metadata(image))

    def _forget_metadata(self, image: Path) -> None:
        """`image` was written: drop its cached metadata and re-check its frame."""
        if self._cache is not None:
            self._cache.discard(image)
        self.thumbnails.thumbnail_model.refresh(image)

    def _save_cache(self) -> None:
        cache = self._cache
        if cache is None or not cache.dirty or cache is self._unsavable_cache:
            return
        try:
            cache.save()
        except OSError as error:
            # E.g. a read-only folder: the cache then lives in memory only.
            self._unsavable_cache = cache
            self.statusBar().showMessage(f"Could not save the metadata cache: {error}")

    def closeEvent(self, event) -> None:
        self._save_cache()
        super().closeEvent(event)

    def _check_sync(self, image: Path) -> SyncReport:
        # Runs on thumbnail loader threads; reads one immutable Config snapshot.
        config = self._config
        return check_sync(
            self._read_metadata(image),
            self._mappings,
            config.master_source,
            config.compared_fields,
            config.compared_sources,
        )

    def _update_sync_action(self) -> None:
        self.sync_action.setEnabled(bool(self.thumbnails.selected_images()))

    def _sync_selected_images(self) -> None:
        images = self.thumbnails.selected_images()
        if images:
            self._open_sync_dialog(images)

    def _open_sync_dialog(self, images: list[Path]) -> None:
        by_name = {mapping.name: mapping for mapping in self._mappings}
        sync_mappings = [by_name[name] for name in self._config.sync_fields]
        # Synchronizing reads the images afresh, which also updates their cached metadata.
        dialog = SyncDialog(
            images, sync_mappings, self, lambda image: self._read_metadata(image, fresh=True)
        )
        for image in images:
            self.thumbnails.thumbnail_model.refresh(image)
        dialog.metadata_written.connect(self._on_metadata_written)
        dialog.exec()

    def _on_metadata_written(self, image: Path) -> None:
        self._forget_metadata(image)
        current = self.thumbnails.currentIndex()
        if current.isValid() and current.data(PATH_ROLE) == image:
            self._show_metadata(image)

    def _show_metadata(self, image: Path | None) -> None:
        self.metadata_panel.show_image(image)
        if image is None:
            return
        metadata = self.metadata_panel.current
        if metadata.errors:
            self.statusBar().showMessage(" | ".join(metadata.errors))
        elif metadata.sidecar_path:
            self.statusBar().showMessage(f"{image.name} – sidecar: {metadata.sidecar_path.name}")
        else:
            self.statusBar().showMessage(f"{image.name} – no sidecar")


def _frame_icon(color: QColor | None) -> QIcon:
    """A small thumbnail-like square with the frame `color`; grey outline for none."""
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(235, 235, 235))
    painter.setPen(QPen(color, 3) if color else QPen(QColor(150, 150, 150), 1))
    painter.drawRect(pixmap.rect().adjusted(1, 1, -2, -2))
    painter.end()
    return QIcon(pixmap)


def _default_folder() -> Path:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return Path(pictures) if pictures and Path(pictures).is_dir() else Path.home()
