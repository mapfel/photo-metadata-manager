import json

import pytest

from metadata_comparer import __version__
from metadata_comparer.config import (
    Config,
    ConfigError,
    load_config,
    save_config,
    saved_app_version,
    write_default_config,
)
from metadata_comparer.metadata.sources import Source

FIELDS = {"Rating", "Color Label", "Date Taken", "Author"}


def write(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path):
    config = load_config(tmp_path / "config.json", FIELDS)
    assert config == Config()
    assert config.master_source == Source.XMP_EMBEDDED
    assert config.compared_fields == ("Rating", "Color Label")


def test_default_file_round_trips(tmp_path):
    path = tmp_path / "nested" / "config.json"
    write_default_config(path)
    assert load_config(path, FIELDS) == Config()


def test_reads_master_and_fields(tmp_path):
    document = {"master_source": "iptc", "compared_fields": ["Author"], "sync_fields": ["Rating"]}
    path = write(tmp_path / "c.json", document)
    assert load_config(path, FIELDS) == Config(Source.IPTC, ("Author",), ("Rating",))


def test_missing_keys_fall_back_to_defaults(tmp_path):
    path = write(tmp_path / "c.json", {"master_source": "xmp_sidecar"})
    config = load_config(path, FIELDS)
    assert config.master_source == Source.XMP_SIDECAR
    assert config.compared_fields == Config().compared_fields


@pytest.mark.parametrize(
    "document",
    [
        {"master_source": "exiff"},
        {"compared_fields": ["Stars"]},
        {"compared_fields": "Rating"},
        {"sync_fields": ["Stars"]},
        {"cache_enabled": "yes"},
        ["not", "an", "object"],
    ],
)
def test_invalid_config_raises(tmp_path, document):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path / "c.json", document), FIELDS)


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ master_source: xmp }", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path, FIELDS)


def test_compared_sources(tmp_path):
    assert Config().compared_sources == tuple(Source)
    path = write(tmp_path / "c.json", {"compared_sources": ["iptc", "exif", "exif"]})
    assert load_config(path, FIELDS).compared_sources == (Source.EXIF, Source.IPTC)

    with pytest.raises(ConfigError):
        load_config(write(tmp_path / "bad.json", {"compared_sources": ["xmp"]}), FIELDS)


def test_compared_sources_round_trip(tmp_path):
    from metadata_comparer.config import save_config

    path = tmp_path / "c.json"
    config = Config(compared_sources=(Source.XMP_SIDECAR,))
    save_config(path, config)
    assert load_config(path, FIELDS) == config


def test_cache_enabled_round_trips(tmp_path):
    path = tmp_path / "config.json"
    assert Config().cache_enabled
    save_config(path, Config(cache_enabled=False))
    assert not load_config(path, FIELDS).cache_enabled


def test_saved_config_records_the_app_version(tmp_path):
    path = tmp_path / "config.json"
    assert saved_app_version(path) is None
    write(path, {"cache_enabled": False})
    assert saved_app_version(path) is None
    save_config(path, Config())
    assert saved_app_version(path) == __version__
    assert json.loads(path.read_text(encoding="utf-8"))["app_version"] == __version__
