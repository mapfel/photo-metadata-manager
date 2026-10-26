from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
)

from metadata_comparer.metadata.comparison import ComparisonRow, compare
from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.writer import (
    RowSelection,
    WriteError,
    apply_changes,
    plan_changes,
)

SOURCES = list(Source)
CELL_STATE_ROLE = Qt.ItemDataRole.UserRole
TRUTH_COLOR = QColor(40, 160, 70)
TRUTH_BRUSH = QBrush(QColor(40, 160, 70, 40))
CHECKBOX_SIZE = 16
CHECKBOX_MARGIN = 4


class CellState(Enum):
    UNSUPPORTED = auto()  # the source cannot store this field
    PLAIN = auto()  # no truth chosen in this row yet
    TRUTH = auto()
    CANDIDATE = auto()  # may receive the truth, not ticked
    TARGET = auto()  # ticked to receive the truth


class SyncTableModel(QAbstractTableModel):
    """Rows are fields, columns are sources. Tracks the truth and the targets per row."""

    selection_changed = Signal()

    def __init__(self, mappings: list[FieldMapping], parent=None) -> None:
        super().__init__(parent)
        self._mappings = mappings
        self._rows: list[ComparisonRow] = []
        self._has_sidecar = False
        self.selections: dict[str, RowSelection] = {}

    @property
    def rows(self) -> list[ComparisonRow]:
        return self._rows

    def set_rows(self, rows: list[ComparisonRow], has_sidecar: bool) -> None:
        self.beginResetModel()
        self._rows = rows
        self._has_sidecar = has_sidecar
        self.selections.clear()
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(SOURCES)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return self._rows[section].field
        source = SOURCES[section]
        if source == Source.XMP_SIDECAR and not self._has_sidecar:
            return f"{source.label}\n(no file yet)"
        return source.label

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        state = self.cell_state(index)
        cell = self._rows[index.row()].cells[SOURCES[index.column()]]
        if role == CELL_STATE_ROLE:
            return state
        if role == Qt.ItemDataRole.DisplayRole:
            if state == CellState.UNSUPPORTED:
                return "n/a"
            return cell.text if cell else "(empty)"
        if role == Qt.ItemDataRole.ForegroundRole and (
            state == CellState.UNSUPPORTED or cell is None
        ):
            return QBrush(QColor(140, 140, 140))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            # Centered text stays clear of the truth frame and the corner checkbox.
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.BackgroundRole and state == CellState.TRUTH:
            return TRUTH_BRUSH
        if role == Qt.ItemDataRole.ToolTipRole:
            if state == CellState.UNSUPPORTED:
                return f"{SOURCES[index.column()].label} cannot store this field"
            return cell.tag if cell else None
        return None

    def cell_state(self, index: QModelIndex | QPersistentModelIndex) -> CellState:
        field = self._rows[index.row()].field
        source = SOURCES[index.column()]
        if not self._mapping(field).tags.get(source.family):
            return CellState.UNSUPPORTED
        selection = self.selections.get(field)
        if selection is None:
            return CellState.PLAIN
        if selection.truth == source:
            return CellState.TRUTH
        return CellState.TARGET if source in selection.targets else CellState.CANDIDATE

    def click_cell(self, index: QModelIndex) -> None:
        """Make the cell the truth of its row, or clear the row if it already is."""
        state = self.cell_state(index)
        if state == CellState.UNSUPPORTED:
            return
        field = self._rows[index.row()].field
        if state == CellState.TRUTH:
            del self.selections[field]
        else:
            self.selections[field] = RowSelection(truth=SOURCES[index.column()])
        self._row_changed(index.row())

    def toggle_target(self, index: QModelIndex) -> None:
        state = self.cell_state(index)
        if state not in (CellState.CANDIDATE, CellState.TARGET):
            return
        targets = self.selections[self._rows[index.row()].field].targets
        source = SOURCES[index.column()]
        if source in targets:
            targets.remove(source)
        else:
            targets.add(source)
        self._row_changed(index.row())

    def changes(self):
        return plan_changes(self._rows, self._mappings, self.selections)

    def _mapping(self, field: str) -> FieldMapping:
        return next(mapping for mapping in self._mappings if mapping.name == field)

    def _row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(SOURCES) - 1))
        self.selection_changed.emit()


def checkbox_rect(cell: QRect) -> QRect:
    """The checkbox sits in the upper right corner of a cell."""
    return QRect(
        cell.right() - CHECKBOX_SIZE - CHECKBOX_MARGIN + 1,
        cell.top() + CHECKBOX_MARGIN,
        CHECKBOX_SIZE,
        CHECKBOX_SIZE,
    )


class SyncCellDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        state = index.data(CELL_STATE_ROLE)
        if state == CellState.TRUTH:
            painter.save()
            pen = QPen(TRUTH_COLOR, 3)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(2, 2, -2, -2))
            painter.restore()
        elif state in (CellState.CANDIDATE, CellState.TARGET):
            checkbox = QStyleOptionViewItem(option)
            checkbox.rect = checkbox_rect(option.rect)
            checkbox.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On
                if state == CellState.TARGET
                else QStyle.StateFlag.State_Off
            )
            style = option.widget.style() if option.widget else QApplication.style()
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
                checkbox,
                painter,
                option.widget,
            )

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + CHECKBOX_SIZE + 2 * CHECKBOX_MARGIN, max(hint.height(), 40))


class SyncTable(QTableView):
    """Click a cell to mark it as the truth; click a checkbox to mark a target."""

    def __init__(self, model: SyncTableModel, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegate(SyncCellDelegate(self))
        self.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        if not index.isValid() or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        model: SyncTableModel = self.model()
        on_checkbox = checkbox_rect(self.visualRect(index)).contains(event.position().toPoint())
        state = model.cell_state(index)
        if on_checkbox and state in (CellState.CANDIDATE, CellState.TARGET):
            model.toggle_target(index)
        else:
            model.click_cell(index)


class SyncDialog(QDialog):
    """Pick the truth per field and copy it into other metadata sources."""

    metadata_written = Signal(Path)

    def __init__(self, image: Path, mappings: list[FieldMapping], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Synchronize metadata – {image.name}")
        self.resize(900, 320)
        self._image = image
        self._mappings = mappings

        hint = QLabel(
            "Click a cell to mark it as the truth. Tick the checkboxes of the cells that "
            "should receive its value, then apply."
        )
        hint.setWordWrap(True)
        self.model = SyncTableModel(mappings, self)
        self.table = SyncTable(self.model)
        self.status = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        self.model.selection_changed.connect(self._update_apply_button)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self._reload()

    def apply(self) -> None:
        changes = self.model.changes()
        try:
            apply_changes(self._image, changes)
        except WriteError as error:
            QMessageBox.critical(self, "Synchronize metadata", f"Writing failed:\n{error}")
            self._reload()
            return
        self._reload()
        self.status.setText(f"{len(changes)} value(s) written.")
        self.metadata_written.emit(self._image)

    def _reload(self) -> None:
        raw = read_metadata(self._image)
        self.model.set_rows(compare(raw, self._mappings), raw.sidecar_path is not None)
        self.status.setText(" | ".join(raw.errors))

    def _update_apply_button(self) -> None:
        self.apply_button.setEnabled(bool(self.model.changes()))
