from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from metadata_comparer.metadata.comparison import CellValue, ComparisonRow
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.ui.sync_dialog import SyncDialog
from metadata_comparer.ui.sync_table import (
    CellState,
    ImageMetadata,
    SyncTable,
    SyncTableModel,
    checkbox_rect,
)

MAPPINGS = [m for m in load_mappings() if m.name in ("Rating", "Color Label")]
EXIF, XMP, SIDECAR, IPTC = (list(Source).index(source) for source in Source)


def image(name, exif_rating, xmp_rating, label="Red", has_sidecar=False):
    def cell(value, tag):
        return CellValue((value,), tag) if value else None

    rows = [
        ComparisonRow(
            "Rating",
            {
                Source.EXIF: cell(exif_rating, "Exif.Image.Rating"),
                Source.XMP_EMBEDDED: cell(xmp_rating, "Xmp.xmp.Rating"),
                Source.XMP_SIDECAR: None,
                Source.IPTC: None,
            },
        ),
        ComparisonRow(
            "Color Label",
            {
                Source.EXIF: None,
                Source.XMP_EMBEDDED: cell(label, "Xmp.xmp.Label"),
                Source.XMP_SIDECAR: None,
                Source.IPTC: None,
            },
        ),
    ]
    sidecar = Path(name).with_suffix(".xmp") if has_sidecar else None
    return ImageMetadata(Path(name), rows, sidecar)


@pytest.fixture
def model(qapp):
    model = SyncTableModel(MAPPINGS)
    model.set_images([image("a.jpg", "2", "4")])
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
    changes = model.changes()[Path("a.jpg")]
    assert [(c.target, c.values) for c in changes] == [(Source.EXIF, ("4",))]

    model.toggle_target(model.index(0, EXIF))
    assert model.changes() == {}


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

    dialog = SyncDialog([jpeg_file], MAPPINGS)
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


def test_batch_cells_summarize_all_images(qapp):
    model = SyncTableModel(MAPPINGS)
    model.set_images(
        [image("a.jpg", "2", "4"), image("b.jpg", "3", "4"), image("c.jpg", None, "4", None, True)]
    )

    assert model.data(model.index(0, XMP)) == "4"
    assert model.data(model.index(0, EXIF)) == "(mixed)"
    tooltip = model.data(model.index(0, EXIF), Qt.ItemDataRole.ToolTipRole)
    assert tooltip.splitlines() == ["1 × 2", "1 × 3", "1 × (empty)"]
    header = model.headerData(SIDECAR, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
    assert header == "XMP (sidecar)\n(1 of 3 have a file)"


def test_batch_changes_are_planned_per_image(qapp):
    model = SyncTableModel(MAPPINGS)
    model.set_images(
        [image("a.jpg", "2", "4"), image("b.jpg", "4", "4"), image("c.jpg", "5", None)]
    )
    model.click_cell(model.index(0, XMP))
    model.toggle_target(model.index(0, EXIF))

    changes = model.changes()
    assert list(changes) == [Path("a.jpg"), Path("c.jpg")]  # b.jpg already matches
    assert changes[Path("a.jpg")][0].values == ("4",)
    assert changes[Path("c.jpg")][0].values == ()  # empty truth removes the value


def test_dialog_applies_changes_to_all_images(tmp_path, qapp, monkeypatch):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    from PySide6.QtGui import QImage

    paths = []
    for name, exif_rating, xmp_rating in [("a.jpg", "1", "4"), ("b.jpg", "2", "5")]:
        path = tmp_path / name
        QImage(8, 8, QImage.Format.Format_RGB32).save(str(path), "JPG")
        image_file = exiv2.ImageFactory.open(str(path))
        image_file.readMetadata()
        image_file.exifData()["Exif.Image.Rating"] = exif_rating
        image_file.xmpData()["Xmp.xmp.Rating"] = xmp_rating
        image_file.writeMetadata()
        paths.append(path)

    dialog = SyncDialog(paths, MAPPINGS)
    confirmations = []
    monkeypatch.setattr(dialog, "confirm", lambda changes: confirmations.append(changes) or True)
    written = []
    dialog.metadata_written.connect(written.append)

    dialog.model.click_cell(dialog.model.index(0, XMP))
    dialog.model.toggle_target(dialog.model.index(0, EXIF))
    dialog.apply()

    assert len(confirmations) == 1
    assert written == paths
    ratings = [read_metadata(path).tags[Source.EXIF]["Exif.Image.Rating"] for path in paths]
    assert ratings == [["4"], ["5"]]
    assert dialog.model.data(dialog.model.index(0, EXIF)) == "(mixed)"


def test_cancelled_batch_writes_nothing(tmp_path, qapp, monkeypatch):
    dialog = SyncDialog([tmp_path / "a.jpg", tmp_path / "b.jpg"], MAPPINGS)
    dialog.model.set_images([image("a.jpg", "2", "4"), image("b.jpg", "3", "4")])
    monkeypatch.setattr(dialog, "confirm", lambda changes: False)
    monkeypatch.setattr(
        "metadata_comparer.ui.sync_table.apply_changes",
        lambda *args: pytest.fail("must not write"),
    )
    dialog.model.click_cell(dialog.model.index(0, XMP))
    dialog.model.toggle_target(dialog.model.index(0, EXIF))
    dialog.apply()
