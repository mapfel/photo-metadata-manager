import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from metadata_comparer.metadata.comparison import CellValue, ComparisonRow
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.ui.sync_dialog import (
    CellState,
    SyncDialog,
    SyncTable,
    SyncTableModel,
    checkbox_rect,
)

MAPPINGS = [m for m in load_mappings() if m.name in ("Rating", "Color Label")]
EXIF, XMP, SIDECAR, IPTC = (list(Source).index(source) for source in Source)


@pytest.fixture
def model(qapp):
    model = SyncTableModel(MAPPINGS)
    rows = [
        ComparisonRow(
            "Rating",
            {
                Source.EXIF: CellValue(("2",), "Exif.Image.Rating"),
                Source.XMP_EMBEDDED: CellValue(("4",), "Xmp.xmp.Rating"),
                Source.XMP_SIDECAR: None,
                Source.IPTC: None,
            },
        ),
        ComparisonRow(
            "Color Label",
            {
                Source.EXIF: None,
                Source.XMP_EMBEDDED: CellValue(("Red",), "Xmp.xmp.Label"),
                Source.XMP_SIDECAR: None,
                Source.IPTC: None,
            },
        ),
    ]
    model.set_rows(rows, has_sidecar=False)
    return model


def states(model, row):
    return [model.cell_state(model.index(row, column)) for column in range(4)]


def test_initial_states(model):
    assert states(model, 0) == [CellState.PLAIN] * 3 + [CellState.UNSUPPORTED]
    assert states(model, 1) == [
        CellState.UNSUPPORTED,
        CellState.PLAIN,
        CellState.PLAIN,
        CellState.UNSUPPORTED,
    ]
    assert model.data(model.index(0, IPTC)) == "n/a"
    assert model.data(model.index(0, SIDECAR)) == "(empty)"


def test_truth_makes_other_cells_candidates_and_targets_toggle(model):
    model.click_cell(model.index(0, XMP))
    assert states(model, 0) == [
        CellState.CANDIDATE,
        CellState.TRUTH,
        CellState.CANDIDATE,
        CellState.UNSUPPORTED,
    ]
    assert states(model, 1)[1] == CellState.PLAIN  # other rows are independent

    model.toggle_target(model.index(0, EXIF))
    assert model.cell_state(model.index(0, EXIF)) == CellState.TARGET
    assert [(c.target, c.values) for c in model.changes()] == [(Source.EXIF, ("4",))]

    model.toggle_target(model.index(0, EXIF))
    assert model.changes() == []


def test_choosing_another_truth_resets_targets(model):
    model.click_cell(model.index(0, XMP))
    model.toggle_target(model.index(0, EXIF))
    model.click_cell(model.index(0, EXIF))
    assert states(model, 0)[:3] == [CellState.TRUTH, CellState.CANDIDATE, CellState.CANDIDATE]


def test_clicking_the_truth_again_clears_the_row(model):
    model.click_cell(model.index(0, XMP))
    model.click_cell(model.index(0, XMP))
    assert states(model, 0)[:3] == [CellState.PLAIN] * 3


def test_mouse_clicks_on_cell_and_checkbox(model):
    table = SyncTable(model)
    table.resize(800, 200)
    table.show()
    xmp_cell = table.visualRect(model.index(0, XMP))
    exif_cell = table.visualRect(model.index(0, EXIF))

    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=xmp_cell.center())
    assert model.cell_state(model.index(0, XMP)) == CellState.TRUTH

    checkbox = checkbox_rect(exif_cell).center()
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=checkbox)
    assert model.cell_state(model.index(0, EXIF)) == CellState.TARGET

    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=exif_cell.center())
    assert model.cell_state(model.index(0, EXIF)) == CellState.TRUTH


def test_dialog_applies_changes(jpeg_file, qapp):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = "2"
    image.xmpData()["Xmp.xmp.Rating"] = "4"
    image.writeMetadata()

    dialog = SyncDialog(jpeg_file, MAPPINGS)
    written = []
    dialog.metadata_written.connect(written.append)
    assert not dialog.apply_button.isEnabled()

    dialog.model.click_cell(dialog.model.index(0, XMP))
    dialog.model.toggle_target(dialog.model.index(0, EXIF))
    dialog.model.toggle_target(dialog.model.index(0, SIDECAR))
    assert dialog.apply_button.isEnabled()
    dialog.apply()

    assert written == [jpeg_file]
    raw = read_metadata(jpeg_file)
    assert raw.tags[Source.EXIF]["Exif.Image.Rating"] == ["4"]
    assert raw.tags[Source.XMP_SIDECAR]["Xmp.xmp.Rating"] == ["4"]
    assert states(dialog.model, 0)[:3] == [CellState.PLAIN] * 3  # reloaded, selection cleared
    assert not dialog.apply_button.isEnabled()
