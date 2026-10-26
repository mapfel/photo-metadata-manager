from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FieldMapping:
    name: str
    tags: dict[str, tuple[str, ...]]  # family ("exif", "xmp", "iptc") -> exiv2 keys by priority
    empty_values: frozenset[str] = frozenset()  # values that mean "not set", e.g. rating 0


def load_mappings(path: Path | None = None) -> list[FieldMapping]:
    """Load field mappings from `path`, or from the bundled mapping.yaml."""
    if path is None:
        text = resources.files(__package__).joinpath("mapping.yaml").read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    return parse_mappings(yaml.safe_load(text))


def parse_mappings(document: dict) -> list[FieldMapping]:
    mappings = []
    for entry in document.get("fields", []):
        options = {"name", "empty_values"}
        tags = {family: tuple(keys) for family, keys in entry.items() if family not in options}
        empty_values = frozenset(str(value) for value in entry.get("empty_values", []))
        mappings.append(FieldMapping(name=entry["name"], tags=tags, empty_values=empty_values))
    return mappings
