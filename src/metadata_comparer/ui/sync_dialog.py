from collections import Counter
from dataclasses import dataclass
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
    QProgressDialog,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
)

from metadata_comparer.metadata.comparison import CellValue, ComparisonRow, compare
from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.writer import (
    Change,
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


@dataclass(frozen=True)
class ImageMetadata:
    path: Path
    rows: list[ComparisonRow]  # one per mapping, in mapping order
    has_sidecar: bool
    errors: tuple[str, ...] = ()

    @classmethod
    def read(cls, path: Path, mappings: list[FieldMapping]) -> "ImageMetadata":
        raw = read_metadata(path)
        rows = compare(raw, mappings)
        return cls(path, rows, raw.sidecar_path is not None, tuple(raw.errors))


class SyncTableModel(QAbstractTableModel):
    """Rows are fields, columns are sources; each cell summarizes all images.

    The truth and the targets chosen per row apply to every image: each image copies
    its own value from the truth source.
    """

    selection_changed = Signal()

    def __init__(self, mappings: list[FieldMapping], parent=None) -> None:
        super().__init__(parent)
        self._mappings = mappings
        self._images: list[ImageMetadata] = []
        self.selections: dict[str, RowSelection] = {}

    def set_images(self, images: list[ImageMetadata]) -> None:
        self.beginResetModel()
        self._images = images
        self.selections.clear()
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() or not self._images else len(self._mappings)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(SOURCES)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return self._mappings[section].name
        source = SOURCES[section]
        if source == Source.XMP_SIDECAR:
            with_sidecar = sum(image.has_sidecar for image in self._images)
            if with_sidecar == 0:
                return f"{source.label}\n(no file yet)"
            if with_sidecar < len(self._images):
                return f"{source.label}\n({with_sidecar} of {len(self._images)} have a file)"
        return source.label

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        state = self.cell_state(index)
        if role == CELL_STATE_ROLE:
            return state
        if role == Qt.ItemDataRole.TextAlignmentRole:
            # Centered text stays clear of the truth frame and the corner checkbox.
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.BackgroundRole and state == CellState.TRUTH:
            return TRUTH_BRUSH
        if state == CellState.UNSUPPORTED:
            if role == Qt.ItemDataRole.DisplayRole:
                return "n/a"
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(QColor(140, 140, 140))
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"{SOURCES[index.column()].label} cannot store this field"
            return None

        summary = self._summary(index)
        value = next(iter(summary)) if len(summary) == 1 else None
        if role == Qt.ItemDataRole.DisplayRole:
            if len(summary) > 1:
                return "(mixed)"
            return value or "(empty)"
        if role == Qt.ItemDataRole.ForegroundRole and value is None:
            return QBrush(QColor(140, 140, 140))
        if role == Qt.ItemDataRole.ToolTipRole:
            if len(self._images) == 1:
                cell = self._cells(index)[0]
                return cell.tag if cell else None
            return "\n".join(
                f"{count} × {text or '(empty)'}" for text, count in summary.most_common()
            )
        return None

    def cell_state(self, index: QModelIndex | QPersistentModelIndex) -> CellState:
        mapping = self._mappings[index.row()]
        source = SOURCES[index.column()]
        if not mapping.tags.get(source.family):
            return CellState.UNSUPPORTED
        selection = self.selections.get(mapping.name)
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
        field = self._mappings[index.row()].name
        if state == CellState.TRUTH:
            del self.selections[field]
        else:
            self.selections[field] = RowSelection(truth=SOURCES[index.column()])
        self._row_changed(index.row())

    def toggle_target(self, index: QModelIndex) -> None:
        state = self.cell_state(index)
        if state not in (CellState.CANDIDATE, CellState.TARGET):
            return
        targets = self.selections[self._mappings[index.row()].name].targets
        source = SOURCES[index.column()]
        if source in targets:
            targets.remove(source)
        else:
            targets.add(source)
        self._row_changed(index.row())

    def changes(self) -> dict[Path, list[Change]]:
        """Changes per image; images that need none are left out."""
        planned = {
            image.path: plan_changes(image.rows, self._mappings, self.selections)
            for image in self._images
        }
        return {path: changes for path, changes in planned.items() if changes}

    def _cells(self, index: QModelIndex | QPersistentModelIndex) -> list[CellValue | None]:
        source = SOURCES[index.column()]
        return [image.rows[index.row()].cells[source] for image in self._images]

    def _summary(self, index: QModelIndex | QPersistentModelIndex) -> Counter[str | None]:
        return Counter(cell.text if cell else None for cell in self._cells(index))

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
    """Pick the truth per field and copy it into other metadata sources of all images."""

    metadata_written = Signal(Path)

    def __init__(self, images: list[Path], mappings: list[FieldMapping], parent=None) -> None:
        super().__init__(parent)
        subject = images[0].name if len(images) == 1 else f"{len(images)} images"
        self.setWindowTitle(f"Synchronize metadata – {subject}")
        self.resize(900, 340)
        self._images = images
        self._mappings = mappings

        text = (
            "Click a cell to mark it as the truth. Tick the checkboxes of the cells that "
            "should receive its value, then apply."
        )
        if len(images) > 1:
            text += " The choice applies to every image; each one copies its own value."
        hint = QLabel(text)
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
        if len(self._images) > 1 and not self.confirm(changes):
            return

        failures = []
        progress = _progress(self, "Writing metadata…", len(changes))
        for done, (path, image_changes) in enumerate(changes.items()):
            progress.setValue(done)
            try:
                apply_changes(path, image_changes)
            except WriteError as error:
                failures.append(f"{path.name}: {error}")
                continue
            self.metadata_written.emit(path)
        progress.setValue(len(changes))

        self._reload()
        written = len(changes) - len(failures)
        self.status.setText(f"Updated {written} of {len(changes)} image(s).")
        if failures:
            shown = failures[:20]
            if len(failures) > len(shown):
                shown.append(f"… and {len(failures) - len(shown)} more")
            QMessageBox.warning(
                self, "Synchronize metadata", "Writing failed for:\n" + "\n".join(shown)
            )

    def confirm(self, changes: dict[Path, list[Change]]) -> bool:
        """Ask before a batch write; mentions values that will be removed."""
        all_changes = [change for image_changes in changes.values() for change in image_changes]
        removals = sum(1 for change in all_changes if not change.values)
        text = f"Write {len(all_changes)} value(s) into {len(changes)} image(s)?"
        if removals:
            text += (
                f"\n\n{removals} value(s) will be removed because the truth is empty "
                "for those images."
            )
        answer = QMessageBox.question(self, "Synchronize metadata", text)
        return answer == QMessageBox.StandardButton.Yes

    def _reload(self) -> None:
        progress = _progress(self, "Reading metadata…", len(self._images))
        images = []
        for done, path in enumerate(self._images):
            progress.setValue(done)
            images.append(ImageMetadata.read(path, self._mappings))
        progress.setValue(len(self._images))

        self.model.set_images(images)
        errors = [f"{image.path.name}: {error}" for image in images for error in image.errors]
        if len(errors) > 1:
            self.status.setText(f"{len(errors)} problem(s) while reading; hover for details.")
        else:
            self.status.setText("".join(errors))
        self.status.setToolTip("\n".join(errors))

    def _update_apply_button(self) -> None:
        self.apply_button.setEnabled(bool(self.model.changes()))


def _progress(parent, label: str, maximum: int) -> QProgressDialog:
    """Shows up only when the work takes longer than half a second."""
    progress = QProgressDialog(label, "", 0, maximum, parent)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(500)
    progress.setCancelButton(None)
    return progress
