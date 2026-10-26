from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

from metadata_comparer.config import Config
from metadata_comparer.metadata.comparison import compare
from metadata_comparer.metadata.mapping import FieldMapping, load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sync import SyncReport, check_sync
from metadata_comparer.ui.folder_tree import FolderTree
from metadata_comparer.ui.metadata_table import MetadataTable
from metadata_comparer.ui.thumbnail_view import ThumbnailView


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

        self.folder_tree.folder_selected.connect(self._show_folder)
        self.thumbnails.image_selected.connect(self._show_metadata)

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
