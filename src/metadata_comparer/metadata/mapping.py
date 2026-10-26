from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FieldMapping:
    name: str
    tags: dict[str, tuple[str, ...]]  # family ("exif", "xmp", "iptc") -> exiv2 keys by priority


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
        tags = {family: tuple(keys) for family, keys in entry.items() if family != "name"}
        mappings.append(FieldMapping(name=entry["name"], tags=tags))
    return mappings
