from metadata_comparer.metadata.comparison import CellValue, compare
from metadata_comparer.metadata.mapping import load_mappings, parse_mappings
from metadata_comparer.metadata.sources import RawMetadata, Source

MAPPINGS = parse_mappings(
    {
        "fields": [
            {
                "name": "Author",
                "exif": ["Exif.Image.Artist", "Exif.Image.XPAuthor"],
                "xmp": ["Xmp.dc.creator"],
                "iptc": ["Iptc.Application2.Byline"],
            },
            {"name": "Rating", "exif": ["Exif.Image.Rating"], "xmp": ["Xmp.xmp.Rating"]},
        ]
    }
)


def test_bundled_mapping_loads():
    names = [mapping.name for mapping in load_mappings()]
    assert {"Title", "Description", "Author", "Rating", "Keywords"} <= set(names)


def test_values_are_looked_up_per_source():
    raw = RawMetadata(
        tags={
            Source.EXIF: {"Exif.Image.XPAuthor": ["Ann"]},
            Source.XMP_EMBEDDED: {"Xmp.dc.creator": ["Ann"]},
            Source.XMP_SIDECAR: {"Xmp.dc.creator": ["Bob"]},
            Source.IPTC: {"Iptc.Application2.Byline": ["Ann", "Bob"]},
        }
    )
    author = compare(raw, MAPPINGS)[0]

    assert author.cells[Source.EXIF] == CellValue("Ann", "Exif.Image.XPAuthor")
    assert author.cells[Source.XMP_SIDECAR] == CellValue("Bob", "Xmp.dc.creator")
    assert author.cells[Source.IPTC] == CellValue("Ann; Bob", "Iptc.Application2.Byline")
    assert author.has_conflict


def test_first_tag_with_value_wins():
    raw = RawMetadata(
        tags={Source.EXIF: {"Exif.Image.Artist": [""], "Exif.Image.XPAuthor": ["Ann"]}}
    )
    assert compare(raw, MAPPINGS)[0].cells[Source.EXIF].tag == "Exif.Image.XPAuthor"


def test_missing_values_are_none_and_not_a_conflict():
    raw = RawMetadata(tags={Source.EXIF: {"Exif.Image.Rating": ["3"]}})
    rating = compare(raw, MAPPINGS)[1]

    assert rating.cells[Source.IPTC] is None
    assert rating.cells[Source.XMP_EMBEDDED] is None
    assert not rating.has_conflict
