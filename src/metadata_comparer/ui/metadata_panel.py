from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableView

from metadata_comparer.metadata.comparison import ComparisonRow
from metadata_comparer.metadata.sources import Source

SOURCES = list(Source)
CONFLICT_BRUSH = QBrush(QColor(255, 200, 80, 90))


class MetadataTableModel(QAbstractTableModel):
    """One row per field; column 0 is the field name, then one column per source."""

    def __init__(self, master: Source, parent=None) -> None:
        super().__init__(parent)
        self._master = master
        self._rows: list[ComparisonRow] = []

    def set_rows(self, rows: list[ComparisonRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else 1 + len(SOURCES)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if section == 0:
            return "Field"
        source = SOURCES[section - 1]
        return f"{source.label} ★ master" if source == self._master else source.label

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if index.column() == 0:
            return row.field if role == Qt.ItemDataRole.DisplayRole else None

        cell = row.cells[SOURCES[index.column() - 1]]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell.text if cell else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return cell.tag if cell else None
        if role == Qt.ItemDataRole.BackgroundRole and cell and row.has_conflict:
            return CONFLICT_BRUSH
        return None


class MetadataTable(QTableView):
    def __init__(self, master: Source, parent=None) -> None:
        super().__init__(parent)
        self.table_model = MetadataTableModel(master, self)
        self.setModel(self.table_model)
        self.setWordWrap(True)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_model.modelReset.connect(self.resizeRowsToContents)

    def set_rows(self, rows: list[ComparisonRow]) -> None:
        self.table_model.set_rows(rows)
