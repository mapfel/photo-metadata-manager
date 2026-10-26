"""Writes field values into an image file and its XMP sidecar using exiv2."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from metadata_comparer.metadata.comparison import ComparisonRow
from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.reader import exiv2, find_sidecar
from metadata_comparer.metadata.sources import Source
from metadata_comparer.metadata.values import COMPANION_TAGS, FieldKind, to_tag_values

XP_KEYWORDS = "Exif.Image.XPKeywords"
IPTC_CHARSET = "Iptc.Envelope.CharacterSet"
IPTC_UTF8 = "\x1b%G"  # ISO 2022 escape sequence for UTF-8
_XMP_ARRAY_TYPES = (
    {exiv2.TypeId.xmpBag, exiv2.TypeId.xmpSeq, exiv2.TypeId.xmpAlt} if exiv2 else set()
)


class WriteError(Exception):
    pass


@dataclass(frozen=True)
class Change:
    field: FieldMapping
    target: Source
    values: tuple[str, ...]  # canonical values; empty removes the field


@dataclass
class RowSelection:
    """In one row of the sync dialog: the source holding the truth and the sources to update."""

    truth: Source
    targets: set[Source] = field(default_factory=set)


def plan_changes(
    rows: list[ComparisonRow],
    mappings: list[FieldMapping],
    selections: Mapping[str, RowSelection],
) -> list[Change]:
    """Turn the dialog selections into changes, skipping targets that already match."""
    by_name = {mapping.name: mapping for mapping in mappings}
    changes = []
    for row in rows:
        selection = selections.get(row.field)
        if selection is None:
            continue
        truth_cell = row.cells[selection.truth]
        truth = truth_cell.values if truth_cell else ()
        for target in sorted(selection.targets, key=list(Source).index):
            target_cell = row.cells[target]
            current = target_cell.values if target_cell else ()
            if set(current) != set(truth):
                changes.append(Change(by_name[row.field], target, truth))
    return changes


def apply_changes(image_path: Path, changes: list[Change]) -> None:
    """Write `changes`; the sidecar is created next to the image if needed. Raises WriteError."""
    if exiv2 is None:
        raise WriteError("exiv2 is not available")
    image_changes = [change for change in changes if change.target != Source.XMP_SIDECAR]
    sidecar_changes = [change for change in changes if change.target == Source.XMP_SIDECAR]
    try:
        if image_changes:
            _rewrite(image_path, image_changes)
        if sidecar_changes:
            sidecar_path = find_sidecar(image_path) or image_path.with_suffix(".xmp")
            _rewrite(sidecar_path, sidecar_changes)
    except (OSError, ValueError, exiv2.Exiv2Error) as error:
        raise WriteError(str(error)) from error


def _rewrite(path: Path, changes: list[Change]) -> None:
    if path.exists():
        # Edited in memory like the reader does, then swapped in atomically.
        data = path.read_bytes()
        image = exiv2.ImageFactory.open(data)
        image.readMetadata()
    else:
        image = exiv2.ImageFactory.create(exiv2.ImageType.xmp)

    for change in changes:
        _apply(image, change)
    image.writeMetadata()
    with image.io().mmap() as buffer:
        _replace_file(path, bytes(buffer))


def _apply(image, change: Change) -> None:
    containers = {
        Source.EXIF: image.exifData,
        Source.XMP_EMBEDDED: image.xmpData,
        Source.XMP_SIDECAR: image.xmpData,
        Source.IPTC: image.iptcData,
    }
    container = containers[change.target]()
    tags = change.field.tags.get(change.target.family)
    if not tags:
        raise ValueError(f"{change.target.label} cannot store {change.field.name}")
    if len(change.values) > 1 and change.field.kind != FieldKind.TEXT:
        raise ValueError(f"{change.field.name}: expected a single value")

    if not change.values:
        # Clear every mapped tag, otherwise a lower-priority tag would still show a value.
        for tag in tags:
            for key in (tag, *COMPANION_TAGS.get(tag, ())):
                _remove(container, key)
        return
    primary = tags[0]
    for key in COMPANION_TAGS.get(primary, ()):
        _remove(container, key)
    if change.field.kind == FieldKind.TEXT:
        _remove(container, primary)
        _write_text(container, change.target, primary, change.values)
        return
    for key, text in to_tag_values(change.field.kind, primary, change.values[0]).items():
        _remove(container, key)
        container[key] = text


def _write_text(container, target: Source, tag: str, values: tuple[str, ...]) -> None:
    """Write one or more text values in the form the tag expects."""
    if target == Source.EXIF:
        text = (";" if tag == XP_KEYWORDS else "; ").join(values)
        if tag.startswith("Exif.Image.XP"):
            # Windows XP* tags are bytes holding NUL-terminated UTF-16LE text.
            text = " ".join(str(byte) for byte in text.encode("utf-16-le") + bytes(2))
        container[tag] = text
    elif target.family == "xmp":
        property_type = exiv2.XmpProperties.propertyType(exiv2.XmpKey(tag))
        if property_type in _XMP_ARRAY_TYPES:
            for value in values:
                container[tag] = value  # appends an array item
        else:
            container[tag] = "; ".join(values)
    else:
        key = exiv2.IptcKey(tag)
        if any(not value.isascii() for value in values):
            container[IPTC_CHARSET] = IPTC_UTF8
        if exiv2.IptcDataSets.dataSetRepeatable(key.tag(), key.record()):
            for value in values:
                container.add(key, exiv2.StringValue(value))
        else:
            container[tag] = "; ".join(values)


def _remove(container, key: str) -> None:
    # IPTC datasets can repeat, so remove every occurrence.
    while key in container:
        del container[key]


def _replace_file(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.metadata-comparer.tmp")
    try:
        temporary.write_bytes(data)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
