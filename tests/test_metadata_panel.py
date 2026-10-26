import pytest
from PySide6.QtCore import Qt

from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.metadata_panel import MetadataPanel
from metadata_comparer.ui.sync_table import CONFLICT_BRUSH, CellState

MAPPINGS = load_mappings()
ROW = {mapping.name: row for row, mapping in enumerate(MAPPINGS)}
EXIF, XMP, SIDECAR, IPTC = range(4)


@pytest.fixture
def rated_jpeg(jpeg_file):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = "2"
    image.xmpData()["Xmp.xmp.Rating"] = "4"
    image.xmpData()["Xmp.dc.subject"] = "sea"
    image.xmpData()["Xmp.dc.subject"] = "sand"
    image.writeMetadata()
    return jpeg_file


def test_empty_panel(qapp):
    panel = MetadataPanel(MAPPINGS, Source.XMP_EMBEDDED)
    assert panel.model.rowCount() == 0
    assert panel.current is None
    assert not panel.apply_button.isEnabled()


def test_conflicts_are_highlighted_but_not_the_truth(qapp, rated_jpeg):
    panel = MetadataPanel(MAPPINGS, Source.XMP_EMBEDDED)
    panel.show_image(rated_jpeg)
    model = panel.model
    rating_exif = model.index(ROW["Rating"], EXIF)

    assert model.data(rating_exif, Qt.ItemDataRole.BackgroundRole) == CONFLICT_BRUSH
    assert model.data(model.index(ROW["Keywords"], XMP)) == "sea; sand"

    model.click_cell(rating_exif)
    assert model.data(rating_exif, Qt.ItemDataRole.BackgroundRole) != CONFLICT_BRUSH


def test_apply_writes_ticked_cells(qapp, rated_jpeg):
    panel = MetadataPanel(MAPPINGS, Source.XMP_EMBEDDED)
    panel.show_image(rated_jpeg)
    written = []
    panel.metadata_written.connect(written.append)
    model = panel.model

    model.click_cell(model.index(ROW["Rating"], XMP))
    model.toggle_target(model.index(ROW["Rating"], EXIF))
    model.click_cell(model.index(ROW["Keywords"], XMP))
    model.toggle_target(model.index(ROW["Keywords"], IPTC))
    model.toggle_target(model.index(ROW["Keywords"], EXIF))
    assert panel.apply_button.isEnabled()
    panel.apply()

    assert written == [rated_jpeg]
    tags = read_metadata(rated_jpeg).tags
    assert tags[Source.EXIF]["Exif.Image.Rating"] == ["4"]
    assert tags[Source.IPTC]["Iptc.Application2.Keywords"] == ["sea", "sand"]
    assert tags[Source.EXIF]["Exif.Image.XPKeywords"] == ["sea", "sand"]
    assert model.cell_state(model.index(ROW["Rating"], XMP)) == CellState.PLAIN  # reloaded
    assert model.data(model.index(ROW["Rating"], EXIF)) == "4"
    assert not panel.apply_button.isEnabled()
    assert panel.status.text() == "3 value(s) written."


def test_main_window_shows_clicked_image_in_panel(qapp, rated_jpeg):
    window = MainWindow()
    window._show_folder(rated_jpeg.parent)
    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))

    assert window.metadata_panel.current.path == rated_jpeg
    model = window.metadata_panel.model
    assert model.data(model.index(ROW["Rating"], XMP)) == "4"

    window._show_folder(rated_jpeg.parent)
    assert window.metadata_panel.current is None
