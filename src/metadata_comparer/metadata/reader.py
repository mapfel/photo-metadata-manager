"""Reads raw metadata from an image file and its XMP sidecar using exiv2."""

import os
import re
from pathlib import Path

from metadata_comparer.metadata.sources import RawMetadata, Source

try:
    import exiv2
except ImportError as error:
    # Keeps the UI usable when the native extension cannot load, e.g. when
    # Windows Smart App Control blocks the unsigned exiv2 binaries.
    exiv2 = None
    _exiv2_import_error: ImportError | None = error
else:
    _exiv2_import_error = None
    exiv2.LogMsg.setLevel(exiv2.LogMsg.Level.error)
    # Must happen once before metadata is read from several threads (thumbnail loaders).
    exiv2.XmpParser.initialize()


_LANG_ALT_ENTRY = re.compile(r'lang="([^"]*)" ')
_COMMENT_CHARSET = re.compile(r'^charset=("[^"]*"|\S+)\s?')
_XMP_ARRAY_TYPES = {"XmpBag", "XmpSeq", "XmpAlt"}
_ORIENTATION = "Exif.Image.Orientation"
_ROTATED_ORIENTATIONS = {5, 6, 7, 8}  # turned by 90 degrees: width and height swap


def find_sidecar(image_path: Path) -> Path | None:
    """Return the XMP sidecar for `image_path`: `photo.xmp` or `photo.jpg.xmp`."""
    candidates = [
        image_path.with_suffix(".xmp"),
        image_path.with_suffix(".XMP"),
        image_path.with_name(image_path.name + ".xmp"),
        image_path.with_name(image_path.name + ".XMP"),
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def parse_lang_alt(text: str) -> str:
    """Pick the x-default (else first) entry of an exiv2 LangAlt string.

    exiv2 renders LangAlt values as `lang="x-default" Text, lang="de-DE" Text`.
    """
    parts = _LANG_ALT_ENTRY.split(text)
    if len(parts) < 3:
        return text
    # split() yields ["", lang1, text1, lang2, text2, ...]; texts end with ", " except the last.
    entries = {}
    for lang, value in zip(parts[1::2], parts[2::2], strict=True):
        entries.setdefault(lang, value.removesuffix(", "))
    return entries.get("x-default", next(iter(entries.values())))


def read_metadata(image_path: Path) -> RawMetadata:
    raw = RawMetadata(sidecar_path=find_sidecar(image_path))
    if exiv2 is None:
        raw.errors.append(f"exiv2 is not available: {_exiv2_import_error}")
        return raw

    try:
        image = _open(image_path)
        raw.image_size = _image_size(image)
        raw.tags[Source.EXIF] = _collect_exif(image.exifData())
        raw.tags[Source.XMP_EMBEDDED] = _collect_xmp(image.xmpData())
        raw.tags[Source.IPTC] = _collect_iptc(image.iptcData())
    except (OSError, exiv2.Exiv2Error) as error:
        raw.errors.append(f"{image_path.name}: {error}")

    if raw.sidecar_path is not None:
        try:
            sidecar = _open(raw.sidecar_path)
            raw.tags[Source.XMP_SIDECAR] = _collect_xmp(sidecar.xmpData())
        except (OSError, exiv2.Exiv2Error) as error:
            raw.errors.append(f"{raw.sidecar_path.name}: {error}")
    return raw


def _open(path: Path):
    if os.name != "nt" or str(path).isascii():
        # exiv2 then reads just the metadata, not the whole file: much faster, above all
        # on network and WSL drives.
        image = exiv2.ImageFactory.open(str(path))
    else:
        # Opening from memory avoids exiv2's narrow-path handling of non-ASCII file names
        # on Windows. The buffer must stay referenced while exiv2 reads from it; the
        # metadata are copied out of it.
        data = path.read_bytes()
        image = exiv2.ImageFactory.open(data)
        image.readMetadata()
        return image
    image.readMetadata()
    return image


def _image_size(image) -> tuple[int, int] | None:
    width, height = image.pixelWidth(), image.pixelHeight()
    if width <= 0 or height <= 0:
        return None
    orientation = next(
        (datum.toInt64() for datum in image.exifData() if datum.key() == _ORIENTATION), 1
    )
    return (height, width) if orientation in _ROTATED_ORIENTATIONS else (width, height)


def _collect_exif(exif_data) -> dict[str, list[str]]:
    def to_values(datum) -> list[str]:
        # print() interprets values, e.g. decodes the UCS-2 Windows XP* tags.
        text = datum.print(exif_data)
        if datum.key() == "Exif.Photo.UserComment":
            return [_COMMENT_CHARSET.sub("", text)]
        if datum.key() == "Exif.Image.XPKeywords":
            return text.split(";")
        return [text]

    return _collect(exif_data, to_values)


def _collect_xmp(xmp_data) -> dict[str, list[str]]:
    def to_values(datum) -> list[str]:
        type_name = datum.typeName()
        if type_name == "LangAlt":
            return [parse_lang_alt(datum.toString())]
        if type_name in _XMP_ARRAY_TYPES:
            return [datum.toString(i) for i in range(datum.count())]
        return [datum.toString()]

    return _collect(xmp_data, to_values)


def _collect_iptc(iptc_data) -> dict[str, list[str]]:
    # Repeatable datasets like Keywords appear as several datums with the same key.
    return _collect(iptc_data, lambda datum: [datum.toString()])


def _collect(container, to_values) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    for datum in container:
        try:
            values = to_values(datum)
        except UnicodeDecodeError:
            values = ["<undecodable>"]
        cleaned = (value.strip().rstrip("\x00") for value in values)
        tags.setdefault(datum.key(), []).extend(value for value in cleaned if value)
    return tags
