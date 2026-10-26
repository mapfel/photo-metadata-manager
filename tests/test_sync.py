from pathlib import Path

from metadata_comparer.metadata.mapping import parse_mappings
from metadata_comparer.metadata.sources import RawMetadata, Source
from metadata_comparer.metadata.sync import SyncStatus, check_sync

MAPPINGS = parse_mappings(
    {
        "fields": [
            {
                "name": "Rating",
                "exif": ["Exif.Image.Rating"],
                "xmp": ["Xmp.xmp.Rating"],
                "empty_values": ["0"],
            },
            {"name": "Color Label", "xmp": ["Xmp.xmp.Label"]},
            {"name": "Author", "exif": ["Exif.Image.Artist"], "xmp": ["Xmp.dc.creator"]},
        ]
    }
)
FIELDS = ("Rating", "Color Label")
SIDECAR = Path("photo.xmp")


def check(tags, sidecar_path=SIDECAR, master=Source.XMP_EMBEDDED):
    raw = RawMetadata(tags=tags, sidecar_path=sidecar_path)
    return check_sync(raw, MAPPINGS, master, FIELDS)


def test_all_sources_agree():
    report = check(
        {
            Source.EXIF: {"Exif.Image.Rating": ["3"]},
            Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": ["3"], "Xmp.xmp.Label": ["Red"]},
            Source.XMP_SIDECAR: {"Xmp.xmp.Rating": ["3"], "Xmp.xmp.Label": ["Red"]},
        }
    )
    assert report.status == SyncStatus.OK
    assert report.issues == ()


def test_empty_other_source_is_missing():
    report = check(
        {
            Source.EXIF: {"Exif.Image.Rating": ["3"]},
            Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": ["3"], "Xmp.xmp.Label": ["Red"]},
            Source.XMP_SIDECAR: {"Xmp.xmp.Rating": ["3"]},
        }
    )
    assert report.status == SyncStatus.MISSING
    assert report.issues == ("Color Label: missing in XMP (sidecar)",)


def test_different_value_is_conflict_and_wins_over_missing():
    report = check(
        {
            Source.EXIF: {"Exif.Image.Rating": ["2"]},
            Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": ["3"], "Xmp.xmp.Label": ["Red"]},
            Source.XMP_SIDECAR: {},
        }
    )
    assert report.status == SyncStatus.CONFLICT
    assert "Rating: Exif has '2', XMP (embedded) has '3'" in report.issues
    assert "Color Label: missing in XMP (sidecar)" in report.issues


def test_value_where_master_is_empty_is_conflict():
    report = check({Source.EXIF: {"Exif.Image.Rating": ["4"]}, Source.XMP_EMBEDDED: {}})
    assert report.status == SyncStatus.CONFLICT


def test_rating_zero_counts_as_empty():
    report = check(
        {Source.EXIF: {"Exif.Image.Rating": ["0"]}, Source.XMP_EMBEDDED: {}},
        sidecar_path=None,
    )
    assert report.status == SyncStatus.OK


def test_absent_sidecar_and_unmapped_sources_are_skipped():
    # IPTC and Exif cannot hold a color label; there is no sidecar file at all.
    report = check(
        {
            Source.EXIF: {"Exif.Image.Rating": ["3"]},
            Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": ["3"], "Xmp.xmp.Label": ["Red"]},
        },
        sidecar_path=None,
    )
    assert report.status == SyncStatus.OK


def test_fields_the_master_cannot_hold_are_skipped():
    report = check(
        {Source.EXIF: {"Exif.Image.Rating": ["3"]}, Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": ["1"]}},
        master=Source.IPTC,
    )
    assert report.status == SyncStatus.OK


def test_fields_outside_the_selection_are_ignored():
    report = check(
        {
            Source.EXIF: {"Exif.Image.Artist": ["Ann"]},
            Source.XMP_EMBEDDED: {"Xmp.dc.creator": ["Bob"]},
        },
        sidecar_path=None,
    )
    assert report.status == SyncStatus.OK


def test_read_errors_give_unknown():
    raw = RawMetadata(errors=["photo.jpg: corrupt"])
    report = check_sync(raw, MAPPINGS, Source.XMP_EMBEDDED, FIELDS)
    assert report.status == SyncStatus.UNKNOWN
    assert report.issues == ("photo.jpg: corrupt",)
