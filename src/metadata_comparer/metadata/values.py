"""Field kinds: how tag values are normalized for comparison and formatted for writing.

Normalized ("canonical") values are what the table shows and what sources are compared by:
- rating:   "-1".."5"
- datetime: "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"; time zones and fractions are ignored
- text:     unchanged
"""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum


class FieldKind(StrEnum):
    TEXT = "text"
    RATING = "rating"
    DATETIME = "datetime"


# IPTC keeps date and time in two datasets; the time belongs to the date.
IPTC_DATE = "Iptc.Application2.DateCreated"
IPTC_TIME = "Iptc.Application2.TimeCreated"
EXIF_RATING = "Exif.Image.Rating"
# Windows keeps a percentage next to the Exif rating and shows that one.
EXIF_RATING_PERCENT = "Exif.Image.RatingPercent"
_RATING_PERCENT = {0: 0, 1: 1, 2: 25, 3: 50, 4: 75, 5: 99}

# Tags that are written and removed together with the mapped tag.
COMPANION_TAGS = {IPTC_DATE: (IPTC_TIME,), EXIF_RATING: (EXIF_RATING_PERCENT,)}

_DATETIME = re.compile(r"(\d{4})[:-](\d{2})[:-](\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?")


def normalize(
    kind: FieldKind, tag: str, values: Sequence[str], source_tags: Mapping[str, list[str]]
) -> list[str]:
    if kind == FieldKind.RATING:
        return [_normalize_rating(value) for value in values]
    if kind == FieldKind.DATETIME:
        if tag == IPTC_DATE and source_tags.get(IPTC_TIME):
            time = source_tags[IPTC_TIME][0]
            values = [f"{value}T{time}" for value in values]
        return [_normalize_datetime(value) for value in values]
    return list(values)


def to_tag_values(kind: FieldKind, tag: str, value: str) -> dict[str, str]:
    """Format a canonical `value` for `tag`; may include companion tags. Raises ValueError."""
    if kind == FieldKind.RATING and tag == EXIF_RATING:
        rating = int(value)
        if rating not in _RATING_PERCENT:
            raise ValueError(f"Exif cannot store rating {value}")
        return {tag: value, EXIF_RATING_PERCENT: str(_RATING_PERCENT[rating])}
    if kind == FieldKind.DATETIME:
        match = _DATETIME.fullmatch(value)
        if not match:
            raise ValueError(f"not a date/time: {value!r}")
        year, month, day, hour, minute, second = match.groups()
        time = f"{hour}:{minute}:{second or '00'}" if hour else None
        if tag.startswith("Exif."):
            return {tag: f"{year}:{month}:{day} {time or '00:00:00'}"}
        if tag == IPTC_DATE:
            date_values = {tag: f"{year}-{month}-{day}"}
            return date_values | {IPTC_TIME: time} if time else date_values
        return {tag: f"{year}-{month}-{day}T{time}" if time else f"{year}-{month}-{day}"}
    return {tag: value}


def _normalize_rating(value: str) -> str:
    try:
        return str(int(float(value)))
    except ValueError:
        return value


def _normalize_datetime(value: str) -> str:
    match = _DATETIME.match(value.strip())
    if not match:
        return value
    year, month, day, hour, minute, second = match.groups()
    if hour is None:
        return f"{year}-{month}-{day}"
    return f"{year}-{month}-{day} {hour}:{minute}:{second or '00'}"
