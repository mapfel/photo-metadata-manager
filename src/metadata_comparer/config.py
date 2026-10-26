"""User configuration, stored as JSON."""

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from metadata_comparer.metadata.sources import Source

SOURCE_IDS = {source.name.lower(): source for source in Source}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    master_source: Source = Source.XMP_EMBEDDED
    # Fields whose disagreement with the master is shown as a frame around the thumbnail.
    compared_fields: tuple[str, ...] = ("Rating", "Color Label")
    # Fields offered in the synchronize dialog.
    sync_fields: tuple[str, ...] = ("Rating", "Color Label", "Date Taken")
    # Sources checked against the master for the thumbnail frames.
    compared_sources: tuple[Source, ...] = tuple(Source)


def load_config(path: Path, known_fields: Collection[str]) -> Config:
    """Read `path`; missing keys fall back to the defaults. A missing file gives the defaults."""
    if not path.is_file():
        return Config()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise ConfigError(f"{path}: expected a JSON object")

    defaults = Config()
    source_id = document.get("master_source", _source_id(defaults.master_source))
    if source_id not in SOURCE_IDS:
        raise ConfigError(
            f"{path}: unknown master_source {source_id!r}, expected one of {', '.join(SOURCE_IDS)}"
        )
    return Config(
        master_source=SOURCE_IDS[source_id],
        compared_fields=_field_list(document, "compared_fields", path, known_fields),
        sync_fields=_field_list(document, "sync_fields", path, known_fields),
        compared_sources=_source_list(document, "compared_sources", path),
    )


def _source_list(document: dict, key: str, path: Path) -> tuple[Source, ...]:
    ids = document.get(key, [_source_id(source) for source in getattr(Config(), key)])
    if not isinstance(ids, list) or not all(isinstance(source_id, str) for source_id in ids):
        raise ConfigError(f"{path}: {key} must be a list of source names")
    unknown = [source_id for source_id in ids if source_id not in SOURCE_IDS]
    if unknown:
        raise ConfigError(
            f"{path}: unknown {key} {unknown}, expected some of {', '.join(SOURCE_IDS)}"
        )
    # Kept in the fixed source order, without duplicates.
    return tuple(source for source in Source if _source_id(source) in ids)


def _field_list(
    document: dict, key: str, path: Path, known_fields: Collection[str]
) -> tuple[str, ...]:
    fields = document.get(key, list(getattr(Config(), key)))
    if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields):
        raise ConfigError(f"{path}: {key} must be a list of field names")
    unknown = [name for name in fields if name not in known_fields]
    if unknown:
        raise ConfigError(f"{path}: unknown {key} {unknown}")
    return tuple(fields)


def write_default_config(path: Path) -> None:
    save_config(path, Config())


def save_config(path: Path, config: Config) -> None:
    """Write `config` to `path`, keeping keys of an existing file that Config does not know."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = {}
    if not isinstance(document, dict):
        document = {}
    document |= {
        "master_source": _source_id(config.master_source),
        "compared_fields": list(config.compared_fields),
        "sync_fields": list(config.sync_fields),
        "compared_sources": [_source_id(source) for source in config.compared_sources],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _source_id(source: Source) -> str:
    return source.name.lower()
