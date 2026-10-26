from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.writer import Change
from metadata_comparer.ui.sync_table import (
    SyncTable,
    SyncTableModel,
    read_images,
    show_failures,
    write_changes,
)


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

        failures = write_changes(self, changes, self.metadata_written.emit)
        self._reload()
        written = len(changes) - len(failures)
        self.status.setText(f"Updated {written} of {len(changes)} image(s).")
        show_failures(self, failures)

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
        images = read_images(self, self._images, self._mappings)
        self.model.set_images(images)
        errors = [f"{image.path.name}: {error}" for image in images for error in image.errors]
        if len(errors) > 1:
            self.status.setText(f"{len(errors)} problem(s) while reading; hover for details.")
        else:
            self.status.setText("".join(errors))
        self.status.setToolTip("\n".join(errors))

    def _update_apply_button(self) -> None:
        invalid = self.model.has_invalid_input()
        self.apply_button.setEnabled(bool(self.model.changes()) and not invalid)
        if invalid:
            self.status.setText("Fix the red custom value before applying.")
        elif self.status.text().startswith("Fix the red"):
            self.status.setText("")
