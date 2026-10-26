import pytest

from metadata_comparer.metadata.comparison import CellValue, ComparisonRow, compare
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.reader import read_metadata
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.writer import (
    Change,
    RowSelection,
    WriteError,
    apply_changes,
    plan_changes,
)

MAPPINGS = {mapping.name: mapping for mapping in load_mappings()}


@pytest.fixture
def exiv2():
    return pytest.importorskip("exiv2", exc_type=ImportError)


@pytest.fixture
def tagged_jpeg(jpeg_file, exiv2):
    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = "2"
    image.exifData()["Exif.Photo.DateTimeOriginal"] = "2024:01:02 03:04:05"
    xmp = image.xmpData()
    xmp["Xmp.xmp.Rating"] = "4"
    xmp["Xmp.xmp.Label"] = "Red"
    xmp["Xmp.xmp.CreateDate"] = "2020-05-05T05:05:05"
    image.writeMetadata()
    return jpeg_file


def cells(image_path, field):
    row = compare(read_metadata(image_path), [MAPPINGS[field]])[0]
    return {source: cell.text if cell else None for source, cell in row.cells.items()}


def test_plan_skips_targets_that_already_match():
    row = ComparisonRow(
        "Rating",
        {
            Source.EXIF: CellValue(("2",), "Exif.Image.Rating"),
            Source.XMP_EMBEDDED: CellValue(("4",), "Xmp.xmp.Rating"),
            Source.XMP_SIDECAR: CellValue(("4",), "Xmp.xmp.Rating"),
            Source.IPTC: None,
        },
    )
    selection = RowSelection(Source.XMP_EMBEDDED, {Source.EXIF, Source.XMP_SIDECAR})
    changes = plan_changes([row], list(MAPPINGS.values()), {"Rating": selection})
    assert changes == [Change(MAPPINGS["Rating"], Source.EXIF, ("4",))]


def test_writes_rating_into_exif_and_new_sidecar(tagged_jpeg, exiv2):
    apply_changes(
        tagged_jpeg,
        [
            Change(MAPPINGS["Rating"], Source.EXIF, ("4",)),
            Change(MAPPINGS["Rating"], Source.XMP_SIDECAR, ("4",)),
            Change(MAPPINGS["Color Label"], Source.XMP_SIDECAR, ("Red",)),
        ],
    )

    assert tagged_jpeg.with_suffix(".xmp").is_file()
    assert cells(tagged_jpeg, "Rating") == {
        Source.EXIF: "4",
        Source.XMP_EMBEDDED: "4",
        Source.XMP_SIDECAR: "4",
        Source.IPTC: None,
    }
    assert cells(tagged_jpeg, "Color Label")[Source.XMP_SIDECAR] == "Red"
    raw = read_metadata(tagged_jpeg)
    assert raw.tags[Source.EXIF]["Exif.Image.RatingPercent"] == ["75"]


def test_writes_datetime_in_each_format(tagged_jpeg):
    value = ("2024-01-02 03:04:05",)
    apply_changes(
        tagged_jpeg,
        [
            Change(MAPPINGS["Date Taken"], Source.XMP_EMBEDDED, value),
            Change(MAPPINGS["Date Taken"], Source.IPTC, value),
        ],
    )

    raw = read_metadata(tagged_jpeg)
    assert raw.tags[Source.XMP_EMBEDDED]["Xmp.photoshop.DateCreated"] == ["2024-01-02T03:04:05"]
    assert raw.tags[Source.IPTC]["Iptc.Application2.DateCreated"] == ["2024-01-02"]
    assert set(cells(tagged_jpeg, "Date Taken").values()) == {"2024-01-02 03:04:05", None}


def test_empty_truth_clears_all_mapped_tags(tagged_jpeg):
    apply_changes(tagged_jpeg, [Change(MAPPINGS["Date Taken"], Source.XMP_EMBEDDED, ())])

    raw = read_metadata(tagged_jpeg)
    assert "Xmp.xmp.CreateDate" not in raw.tags[Source.XMP_EMBEDDED]
    assert cells(tagged_jpeg, "Date Taken")[Source.XMP_EMBEDDED] is None


def test_unsupported_target_raises_and_leaves_file_untouched(tagged_jpeg):
    before = tagged_jpeg.read_bytes()
    with pytest.raises(WriteError):
        apply_changes(tagged_jpeg, [Change(MAPPINGS["Color Label"], Source.EXIF, ("Red",))])
    assert tagged_jpeg.read_bytes() == before
    assert not list(tagged_jpeg.parent.glob(".*.tmp"))


def test_image_data_is_preserved(tagged_jpeg, qapp):
    from PySide6.QtGui import QImage

    before = QImage(str(tagged_jpeg))
    apply_changes(tagged_jpeg, [Change(MAPPINGS["Rating"], Source.EXIF, ("5",))])
    assert QImage(str(tagged_jpeg)) == before


def test_writes_several_text_values_per_family(tagged_jpeg):
    keywords = ("Grüße", "sea")
    apply_changes(
        tagged_jpeg,
        [
            Change(MAPPINGS["Keywords"], target, keywords)
            for target in (Source.EXIF, Source.XMP_EMBEDDED, Source.IPTC)
        ]
        + [Change(MAPPINGS["Title"], Source.EXIF, ("Grüße",))],
    )

    raw = read_metadata(tagged_jpeg)
    assert raw.tags[Source.EXIF]["Exif.Image.XPKeywords"] == ["Grüße", "sea"]
    assert raw.tags[Source.EXIF]["Exif.Image.XPTitle"] == ["Grüße"]
    assert raw.tags[Source.XMP_EMBEDDED]["Xmp.dc.subject"] == ["Grüße", "sea"]
    assert raw.tags[Source.IPTC]["Iptc.Application2.Keywords"] == ["Grüße", "sea"]
    assert raw.tags[Source.IPTC]["Iptc.Envelope.CharacterSet"] == ["\x1b%G"]


def test_non_repeatable_targets_join_values(tagged_jpeg):
    authors = ("Ann", "Bob")
    apply_changes(
        tagged_jpeg,
        [
            Change(MAPPINGS["Author"], Source.EXIF, authors),
            Change(MAPPINGS["Description"], Source.IPTC, authors),
        ],
    )

    raw = read_metadata(tagged_jpeg)
    assert raw.tags[Source.EXIF]["Exif.Image.Artist"] == ["Ann; Bob"]
    assert raw.tags[Source.IPTC]["Iptc.Application2.Caption"] == ["Ann; Bob"]


def test_rating_with_several_values_is_rejected(tagged_jpeg):
    with pytest.raises(WriteError):
        apply_changes(tagged_jpeg, [Change(MAPPINGS["Rating"], Source.EXIF, ("1", "2"))])
