from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Source(Enum):
    """A place where metadata can live. `family` selects the tag names in mapping.yaml."""

    EXIF = ("Exif", "exif")
    XMP_EMBEDDED = ("XMP (embedded)", "xmp")
    XMP_SIDECAR = ("XMP (sidecar)", "xmp")
    IPTC = ("IPTC", "iptc")

    def __init__(self, label: str, family: str) -> None:
        self.label = label
        self.family = family


@dataclass
class RawMetadata:
    """All tags found per source, as exiv2 key -> list of display strings."""

    tags: dict[Source, dict[str, list[str]]] = field(default_factory=dict)
    sidecar_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    # Width and height in pixels as displayed, i.e. with the Exif orientation applied.
    image_size: tuple[int, int] | None = None

    @property
    def orientation(self) -> str | None:
        """The shape as displayed, from `image_size`: "portrait", or "landscape" (also for
        square images)."""
        if self.image_size is None:
            return None
        width, height = self.image_size
        return "portrait" if height > width else "landscape"
