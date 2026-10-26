from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QSplitter, QToolBar

from metadata_comparer.config import Config
from metadata_comparer.metadata.comparison import compare
from metadata_comparer.metadata.mapping import FieldMapping, load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sync import SyncReport, check_sync
from metadata_comparer.ui.folder_tree import FolderTree
from metadata_comparer.ui.metadata_table import MetadataTable
from metadata_comparer.ui.sync_dialog import SyncDialog
from metadata_comparer.ui.thumbnail_view import PATH_ROLE, ThumbnailView


class MainWindow(QMainWindow):
    def __init__(self, config: Config | None = None, mappings: list[FieldMapping] | None = None):
        super().__init__()
        self.setWindowTitle("Metadata Comparer")
        self._config = config or Config()
        self._mappings = mappings or load_mappings()

        self.folder_tree = FolderTree()
        self.thumbnails = ThumbnailView(self._check_sync)
        self.metadata_table = MetadataTable(self._config.master_source)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.thumbnails)
        right.addWidget(self.metadata_table)
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
        toolbar = QToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self.sync_action)
        self.addToolBar(toolbar)

        self.folder_tree.folder_selected.connect(self._show_folder)
        self.thumbnails.image_selected.connect(self._show_metadata)
        self.thumbnails.image_activated.connect(lambda image: self._open_sync_dialog([image]))
        self.thumbnails.selection_changed.connect(self._update_sync_action)

        self.folder_tree.select_folder(_start_folder())

    def _show_folder(self, folder: Path) -> None:
        self.thumbnails.set_folder(folder)
        self.metadata_table.set_rows([])
        count = self.thumbnails.thumbnail_model.rowCount()
        self.statusBar().showMessage(f"{folder} – {count} image(s)")

    def _check_sync(self, image: Path) -> SyncReport:
        # Runs on thumbnail loader threads; only reads immutable state.
        return check_sync(
            read_metadata(image),
            self._mappings,
            self._config.master_source,
            self._config.compared_fields,
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
        dialog = SyncDialog(images, sync_mappings, self)
        dialog.metadata_written.connect(self._on_metadata_written)
        dialog.exec()

    def _on_metadata_written(self, image: Path) -> None:
        self.thumbnails.thumbnail_model.refresh(image)
        current = self.thumbnails.currentIndex()
        if current.isValid() and current.data(PATH_ROLE) == image:
            self._show_metadata(image)

    def _show_metadata(self, image: Path) -> None:
        raw = read_metadata(image)
        self.metadata_table.set_rows(compare(raw, self._mappings))
        if raw.errors:
            self.statusBar().showMessage(" | ".join(raw.errors))
        elif raw.sidecar_path:
            self.statusBar().showMessage(f"{image.name} – sidecar: {raw.sidecar_path.name}")
        else:
            self.statusBar().showMessage(f"{image.name} – no sidecar")


def _start_folder() -> Path:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return Path(pictures) if pictures and Path(pictures).is_dir() else Path.home()
