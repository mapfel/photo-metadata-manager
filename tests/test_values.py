import pytest

from metadata_comparer.metadata.values import FieldKind, normalize, parse_input, to_tag_values


@pytest.mark.parametrize(
    ("tag", "raw", "expected"),
    [
        ("Exif.Photo.DateTimeOriginal", "2024:01:02 03:04:05", "2024-01-02 03:04:05"),
        ("Xmp.photoshop.DateCreated", "2024-01-02T03:04:05.123+02:00", "2024-01-02 03:04:05"),
        ("Xmp.photoshop.DateCreated", "2024-01-02T03:04", "2024-01-02 03:04:00"),
        ("Xmp.photoshop.DateCreated", "2024-01-02", "2024-01-02"),
        ("Exif.Photo.DateTimeOriginal", "    :  :     ", "    :  :     "),
    ],
)
def test_normalize_datetime(tag, raw, expected):
    assert normalize(FieldKind.DATETIME, tag, [raw], {}) == [expected]


def test_iptc_date_is_combined_with_time():
    source_tags = {"Iptc.Application2.TimeCreated": ["03:04:05+00:00"]}
    values = normalize(
        FieldKind.DATETIME, "Iptc.Application2.DateCreated", ["2024-01-02"], source_tags
    )
    assert values == ["2024-01-02 03:04:05"]


@pytest.mark.parametrize(("raw", "expected"), [("3", "3"), ("3.0", "3"), ("-1", "-1"), ("x", "x")])
def test_normalize_rating(raw, expected):
    assert normalize(FieldKind.RATING, "Xmp.xmp.Rating", [raw], {}) == [expected]


@pytest.mark.parametrize(
    ("tag", "value", "expected"),
    [
        (
            "Exif.Photo.DateTimeOriginal",
            "2024-01-02 03:04:05",
            {"Exif.Photo.DateTimeOriginal": "2024:01:02 03:04:05"},
        ),
        (
            "Exif.Photo.DateTimeOriginal",
            "2024-01-02",
            {"Exif.Photo.DateTimeOriginal": "2024:01:02 00:00:00"},
        ),
        (
            "Xmp.photoshop.DateCreated",
            "2024-01-02 03:04:05",
            {"Xmp.photoshop.DateCreated": "2024-01-02T03:04:05"},
        ),
        ("Xmp.photoshop.DateCreated", "2024-01-02", {"Xmp.photoshop.DateCreated": "2024-01-02"}),
        (
            "Iptc.Application2.DateCreated",
            "2024-01-02 03:04:05",
            {
                "Iptc.Application2.DateCreated": "2024-01-02",
                "Iptc.Application2.TimeCreated": "03:04:05",
            },
        ),
        (
            "Iptc.Application2.DateCreated",
            "2024-01-02",
            {"Iptc.Application2.DateCreated": "2024-01-02"},
        ),
    ],
)
def test_datetime_to_tag_values(tag, value, expected):
    assert to_tag_values(FieldKind.DATETIME, tag, value) == expected


def test_exif_rating_writes_windows_percentage():
    assert to_tag_values(FieldKind.RATING, "Exif.Image.Rating", "4") == {
        "Exif.Image.Rating": "4",
        "Exif.Image.RatingPercent": "75",
    }


def test_exif_cannot_store_rejected_rating():
    with pytest.raises(ValueError):
        to_tag_values(FieldKind.RATING, "Exif.Image.Rating", "-1")


def test_invalid_datetime_cannot_be_written():
    with pytest.raises(ValueError):
        to_tag_values(FieldKind.DATETIME, "Xmp.photoshop.DateCreated", "yesterday")


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        (FieldKind.TEXT, " sea ;sand; ", ("sea", "sand")),
        (FieldKind.TEXT, "", ()),
        (FieldKind.RATING, " 4 ", ("4",)),
        (FieldKind.RATING, "-1", ("-1",)),
        (FieldKind.RATING, "", ()),
        (FieldKind.DATETIME, "2024-01-02 03:04", ("2024-01-02 03:04:00",)),
        (FieldKind.DATETIME, "2024:01:02 03:04:05", ("2024-01-02 03:04:05",)),
        (FieldKind.DATETIME, "2024-01-02", ("2024-01-02",)),
    ],
)
def test_parse_input(kind, text, expected):
    assert parse_input(kind, text) == expected


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (FieldKind.RATING, "6"),
        (FieldKind.RATING, "3.5"),
        (FieldKind.RATING, "--3"),
        (FieldKind.DATETIME, "yesterday"),
        (FieldKind.DATETIME, "2024-01-02 03:04 extra"),
    ],
)
def test_parse_input_rejects_invalid_text(kind, text):
    with pytest.raises(ValueError):
        parse_input(kind, text)
