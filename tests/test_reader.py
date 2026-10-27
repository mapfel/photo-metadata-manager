import pytest

from metadata_comparer.metadata.reader import find_sidecar, parse_lang_alt, read_metadata
from metadata_comparer.metadata.sources import Source


def test_parse_lang_alt_prefers_x_default():
    text = 'lang="de-DE" Strand, lang="x-default" Beach, at sunset'
    assert parse_lang_alt(text) == "Beach, at sunset"


def test_parse_lang_alt_falls_back_to_first_entry():
    assert parse_lang_alt('lang="de-DE" Strand, lang="fr-FR" Plage') == "Strand"


def test_parse_lang_alt_passes_plain_text_through():
    assert parse_lang_alt("Beach") == "Beach"


@pytest.mark.parametrize("sidecar_name", ["photo.xmp", "photo.jpg.xmp"])
def test_find_sidecar(tmp_path, sidecar_name):
    image = tmp_path / "photo.jpg"
    image.touch()
    (tmp_path / sidecar_name).touch()
    assert find_sidecar(image) == tmp_path / sidecar_name


def test_find_sidecar_returns_none_without_sidecar(tmp_path):
    image = tmp_path / "photo.jpg"
    image.touch()
    assert find_sidecar(image) is None


def test_reads_all_sources(jpeg_file):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)

    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    exif = image.exifData()
    exif["Exif.Image.Artist"] = "Ann"
    exif["Exif.Photo.UserComment"] = "charset=Unicode Grüße"
    xp_author = exiv2.Value.create(exiv2.TypeId.unsignedByte)
    xp_author.read(" ".join(str(b) for b in "Jürgen".encode("utf-16-le") + bytes(2)))
    exif["Exif.Image.XPAuthor"] = xp_author
    xmp = image.xmpData()
    xmp["Xmp.dc.description"] = "lang=x-default Beach"
    xmp["Xmp.dc.subject"] = "sea"
    xmp["Xmp.dc.subject"] = "sand"
    iptc = image.iptcData()
    for keyword in ("sea", "sand"):
        iptc.add(exiv2.IptcKey("Iptc.Application2.Keywords"), exiv2.StringValue(keyword))
    image.writeMetadata()

    sidecar = jpeg_file.with_suffix(".xmp")
    sidecar.write_text(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="4"/>'
        "</rdf:RDF></x:xmpmeta>",
        encoding="utf-8",
    )

    raw = read_metadata(jpeg_file)

    assert raw.errors == []
    assert raw.tags[Source.EXIF]["Exif.Image.Artist"] == ["Ann"]
    assert raw.tags[Source.EXIF]["Exif.Image.XPAuthor"] == ["Jürgen"]
    assert raw.tags[Source.EXIF]["Exif.Photo.UserComment"] == ["Grüße"]
    assert raw.tags[Source.XMP_EMBEDDED]["Xmp.dc.subject"] == ["sea", "sand"]
    assert raw.tags[Source.XMP_EMBEDDED]["Xmp.dc.description"] == ["Beach"]
    assert raw.tags[Source.IPTC]["Iptc.Application2.Keywords"] == ["sea", "sand"]
    assert raw.tags[Source.XMP_SIDECAR]["Xmp.xmp.Rating"] == ["4"]


@pytest.mark.parametrize(("orientation", "size"), [(1, (32, 24)), (6, (24, 32))])
def test_reads_image_size_as_displayed(jpeg_file, orientation, size):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = exiv2.ImageFactory.open(str(jpeg_file))
    image.readMetadata()
    image.exifData()["Exif.Image.Orientation"] = exiv2.UShortValue(orientation)
    image.writeMetadata()

    assert read_metadata(jpeg_file).image_size == size


def test_reads_non_ascii_file_name(jpeg_file):
    pytest.importorskip("exiv2", exc_type=ImportError)
    renamed = jpeg_file.rename(jpeg_file.with_name("Größe_ü.jpg"))
    raw = read_metadata(renamed)
    assert not raw.errors
    assert raw.image_size == (32, 24)
