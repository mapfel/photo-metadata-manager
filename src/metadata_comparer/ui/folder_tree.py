from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Signal
from PySide6.QtWidgets import QFileSystemModel, QTreeView


class FolderTree(QTreeView):
    """Directory-only file system tree. Emits `folder_selected` with the chosen folder."""

    folder_selected = Signal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = QFileSystemModel(self)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self._model.setRootPath("")
        self.setModel(self._model)
        for column in range(1, self._model.columnCount()):
            self.hideColumn(column)
        self.setHeaderHidden(True)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def select_folder(self, folder: Path) -> None:
        index = self._model.index(str(folder))
        if index.isValid():
            self.setCurrentIndex(index)
            self.expand(index)
            self.scrollTo(index)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.folder_selected.emit(Path(self._model.filePath(current)))
