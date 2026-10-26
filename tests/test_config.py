import json

import pytest

from metadata_comparer.config import Config, ConfigError, load_config, write_default_config
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
