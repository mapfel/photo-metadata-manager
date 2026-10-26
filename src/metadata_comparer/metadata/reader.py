"""Reads raw metadata from an image file and its XMP sidecar using exiv2."""

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


_LANG_ALT_ENTRY = re.compile(r'lang="([^"]*)" ')


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
        # Opening from memory avoids exiv2's narrow-path handling of non-ASCII file names on
        # Windows. The bytes must stay referenced while the image is in use.
        data = image_path.read_bytes()
        image = _open(data)
        raw.tags[Source.EXIF] = _collect_exif(image.exifData())
        raw.tags[Source.XMP_EMBEDDED] = _collect_xmp(image.xmpData())
        raw.tags[Source.IPTC] = _collect_iptc(image.iptcData())
    except (OSError, exiv2.Exiv2Error) as error:
        raw.errors.append(f"{image_path.name}: {error}")

    if raw.sidecar_path is not None:
        try:
            sidecar_data = raw.sidecar_path.read_bytes()
            sidecar = _open(sidecar_data)
            raw.tags[Source.XMP_SIDECAR] = _collect_xmp(sidecar.xmpData())
        except (OSError, exiv2.Exiv2Error) as error:
            raw.errors.append(f"{raw.sidecar_path.name}: {error}")
    return raw


def _open(data: bytes):
    image = exiv2.ImageFactory.open(data)
    image.readMetadata()
    return image


def _collect_exif(exif_data) -> dict[str, list[str]]:
    # print() interprets values, e.g. decodes the UCS-2 Windows XP* tags.
    return _collect(exif_data, lambda datum: datum.print(exif_data))


def _collect_xmp(xmp_data) -> dict[str, list[str]]:
    def to_text(datum) -> str:
        text = datum.toString()
        return parse_lang_alt(text) if datum.typeName() == "LangAlt" else text

    return _collect(xmp_data, to_text)


def _collect_iptc(iptc_data) -> dict[str, list[str]]:
    # Repeatable datasets like Keywords appear as several datums with the same key.
    return _collect(iptc_data, lambda datum: datum.toString())


def _collect(container, to_text) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    for datum in container:
        try:
            text = to_text(datum)
        except UnicodeDecodeError:
            text = "<undecodable>"
        tags.setdefault(datum.key(), []).append(text.strip().rstrip("\x00"))
    return tags
