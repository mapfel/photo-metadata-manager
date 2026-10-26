from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.sources import Source
from metadata_comparer.ui.sync_table import (
    ImageMetadata,
    SyncTable,
    SyncTableModel,
    show_failures,
    write_changes,
)


class MetadataPanel(QWidget):
    """Metadata of the current image, editable like the sync dialog, with an Apply button."""

    metadata_written = Signal(Path)

    def __init__(self, mappings: list[FieldMapping], master: Source, parent=None) -> None:
        super().__init__(parent)
        self._mappings = mappings
        self._image: Path | None = None
        self.model = SyncTableModel(mappings, master, self)
        self.table = SyncTable(self.model)
        self.status = QLabel()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Copy the truth into the ticked cells")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        self.model.selection_changed.connect(self._update_apply_button)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status, stretch=1)
        bottom.addWidget(self.apply_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(bottom)

    @property
    def current(self) -> ImageMetadata | None:
        images = self.model.images
        return images[0] if images else None

    def show_image(self, image: Path | None) -> None:
        """Show `image` (None clears the table); pending truth/target choices are dropped."""
        self._image = image
        self.model.set_images([] if image is None else [ImageMetadata.read(image, self._mappings)])
        self.status.setText("")

    def apply(self) -> None:
        changes = self.model.changes()
        failures = write_changes(self, changes, self.metadata_written.emit)
        self.show_image(self._image)
        if not failures:
            values = sum(len(image_changes) for image_changes in changes.values())
            self.status.setText(f"{values} value(s) written.")
        show_failures(self, failures)

    def _update_apply_button(self) -> None:
        invalid = self.model.has_invalid_input()
        self.apply_button.setEnabled(bool(self.model.changes()) and not invalid)
        if invalid:
            self.status.setText("Fix the red custom value before applying.")
        elif self.status.text().startswith("Fix the red"):
            self.status.setText("")
