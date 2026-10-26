from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from metadata_comparer.metadata.comparison import CellValue, ComparisonRow
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.ui.metadata_panel import MetadataPanel
from metadata_comparer.ui.sync_table import (
    CUSTOM_COLUMN,
    CellState,
    ImageMetadata,
    SyncTable,
    SyncTableModel,
)

MAPPINGS = [m for m in load_mappings() if m.name in ("Rating", "Keywords")]
KEYWORDS, RATING = 0, 1  # mapping.yaml order
EXIF, XMP, SIDECAR, IPTC = range(4)


def image(name, exif_rating, xmp_rating):
    def cell(value, tag):
        return CellValue((value,), tag) if value else None

    empty = dict.fromkeys(Source)
    rows = [
        ComparisonRow("Keywords", empty),
        ComparisonRow(
            "Rating",
            empty
            | {
                Source.EXIF: cell(exif_rating, "Exif.Image.Rating"),
                Source.XMP_EMBEDDED: cell(xmp_rating, "Xmp.xmp.Rating"),
            },
        ),
    ]
    return ImageMetadata(Path(name), rows)


@pytest.fixture
def model(qapp):
    model = SyncTableModel(MAPPINGS)
    model.set_images([image("a.jpg", "2", "4"), image("b.jpg", None, "3")])
    return model


def custom(model, row):
    return model.index(row, CUSTOM_COLUMN)


def test_custom_column_is_a_source_only(model):
    assert model.headerData(CUSTOM_COLUMN, Qt.Orientation.Horizontal, 0) == "Custom"
    assert model.cell_state(custom(model, RATING)) == CellState.PLAIN

    model.click_cell(model.index(RATING, XMP))
    assert model.cell_state(custom(model, RATING)) == CellState.PLAIN  # never a target
    model.toggle_target(custom(model, RATING))
    assert model.cell_state(custom(model, RATING)) == CellState.PLAIN


def test_custom_cell_is_editable_only_as_truth(model):
    index = custom(model, RATING)
    assert not model.flags(index) & Qt.ItemFlag.ItemIsEditable
    assert not model.setData(index, "5", Qt.ItemDataRole.EditRole)

    model.click_cell(index)
    assert model.cell_state(index) == CellState.TRUTH
    assert model.flags(index) & Qt.ItemFlag.ItemIsEditable
    assert model.data(index) == "(type a value)"
    assert model.setData(index, "5", Qt.ItemDataRole.EditRole)
    assert model.data(index) == "5"
    assert [model.cell_state(model.index(RATING, c)) for c in (EXIF, XMP, SIDECAR)] == [
        CellState.CANDIDATE
    ] * 3


def test_custom_truth_applies_the_same_value_to_every_image(model):
    model.click_cell(custom(model, RATING))
    model.setData(custom(model, RATING), "4", Qt.ItemDataRole.EditRole)
    model.toggle_target(model.index(RATING, EXIF))
    model.toggle_target(model.index(RATING, XMP))

    changes = model.changes()
    assert {path: [(c.target, c.values) for c in cs] for path, cs in changes.items()} == {
        Path("a.jpg"): [(Source.EXIF, ("4",))],  # XMP already 4
        Path("b.jpg"): [(Source.EXIF, ("4",)), (Source.XMP_EMBEDDED, ("4",))],
    }


def test_custom_text_values_are_split(model):
    model.click_cell(custom(model, KEYWORDS))
    model.setData(custom(model, KEYWORDS), "sea; sand", Qt.ItemDataRole.EditRole)
    model.toggle_target(model.index(KEYWORDS, IPTC))
    assert model.changes()[Path("a.jpg")][0].values == ("sea", "sand")


def test_invalid_custom_value_blocks_its_row(model):
    index = custom(model, RATING)
    model.click_cell(index)
    model.setData(index, "7", Qt.ItemDataRole.EditRole)
    model.toggle_target(model.index(RATING, EXIF))

    assert model.has_invalid_input()
    assert model.changes() == {}
    assert "-1 to 5" in model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert model.data(index, Qt.ItemDataRole.ForegroundRole).color().red() == 200


def test_custom_zero_rating_means_unrated(model):
    model.click_cell(custom(model, RATING))
    model.setData(custom(model, RATING), "0", Qt.ItemDataRole.EditRole)
    model.toggle_target(model.index(RATING, EXIF))
    assert model.changes()[Path("a.jpg")][0].values == ()


def test_typed_text_survives_moving_the_truth(model):
    index = custom(model, RATING)
    model.click_cell(index)
    model.setData(index, "5", Qt.ItemDataRole.EditRole)
    model.click_cell(model.index(RATING, XMP))
    model.click_cell(index)
    assert model.data(index) == "5"


def test_clicking_custom_cell_opens_editor(model):
    table = SyncTable(model)
    table.resize(900, 200)
    table.show()
    cell = table.visualRect(custom(model, RATING)).center()

    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
    editor = table.findChild(QLineEdit)
    assert model.cell_state(custom(model, RATING)) == CellState.TRUTH
    assert editor is not None and editor.isVisible()

    QTest.keyClicks(editor, "3")  # committed while typing
    assert model.custom_texts["Rating"] == "3"


def test_panel_applies_custom_value(qapp, jpeg_file):
    pytest.importorskip("exiv2", exc_type=ImportError)
    mappings = load_mappings()
    row = [m.name for m in mappings].index("Rating")
    panel = MetadataPanel(mappings, Source.XMP_EMBEDDED)
    panel.show_image(jpeg_file)
    model = panel.model

    model.click_cell(custom(model, row))
    model.setData(custom(model, row), "abc", Qt.ItemDataRole.EditRole)
    model.toggle_target(model.index(row, EXIF))
    model.toggle_target(model.index(row, SIDECAR))
    assert not panel.apply_button.isEnabled()
    assert "Fix the red" in panel.status.text()

    model.setData(custom(model, row), "5", Qt.ItemDataRole.EditRole)
    assert panel.apply_button.isEnabled()
    panel.apply()

    tags = read_metadata(jpeg_file).tags
    assert tags[Source.EXIF]["Exif.Image.Rating"] == ["5"]
    assert tags[Source.XMP_SIDECAR]["Xmp.xmp.Rating"] == ["5"]
