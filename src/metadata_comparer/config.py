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
    fields = document.get("compared_fields", list(defaults.compared_fields))
    if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields):
        raise ConfigError(f"{path}: compared_fields must be a list of field names")
    unknown = [name for name in fields if name not in known_fields]
    if unknown:
        raise ConfigError(f"{path}: unknown compared_fields {unknown}")
    return Config(master_source=SOURCE_IDS[source_id], compared_fields=tuple(fields))


def write_default_config(path: Path) -> None:
    defaults = Config()
    document = {
        "master_source": _source_id(defaults.master_source),
        "compared_fields": list(defaults.compared_fields),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _source_id(source: Source) -> str:
    return source.name.lower()
