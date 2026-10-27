"""Per-folder cache of the metadata the app shows, persisted as `.mcs-cache` in the folder."""

import json
import os
import threading
from collections.abc import Collection
from pathlib import Path

from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.sources import RawMetadata, Source
from metadata_comparer.metadata.values import COMPANION_TAGS

CACHE_FILE_NAME = ".mcs-cache"
CACHE_VERSION = 2  # 2: image sizes, so frames can be drawn before the thumbnails
_SOURCE_IDS = {source.name.lower(): source for source in Source}


def cached_tags(mappings: list[FieldMapping]) -> frozenset[str]:
    """The tags the mappings read, including companions such as the IPTC time."""
    tags = {tag for mapping in mappings for keys in mapping.tags.values() for tag in keys}
    return frozenset(tags | {extra for tag in tags for extra in COMPANION_TAGS.get(tag, ())})


class MetadataCache:
    """Metadata of the images in `folder`, reduced to the `tags` the mappings use.

    Entries are keyed by file name and change only through put(), discard() and clear();
    the files themselves are not watched. Thread-safe.
    """

    def __init__(self, folder: Path, tags: frozenset[str]) -> None:
        self.folder = folder
        self._tags = tags
        self._entries: dict[str, RawMetadata] = {}
        self._lock = threading.Lock()
        self._dirty = False

    @property
    def path(self) -> Path:
        return self.folder / CACHE_FILE_NAME

    @property
    def dirty(self) -> bool:
        """Changed since it was loaded or saved."""
        return self._dirty

    @classmethod
    def load(cls, folder: Path, tags: frozenset[str]) -> "MetadataCache":
        """The cache stored in `folder`; empty if there is none or it is unusable, e.g.
        written for other mappings or by another version."""
        cache = cls(folder, tags)
        try:
            document = json.loads(cache.path.read_text(encoding="utf-8"))
            if document["version"] != CACHE_VERSION or set(document["tags"]) != tags:
                return cache
            cache._entries = {
                name: _raw_from_json(folder, entry) for name, entry in document["images"].items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            cache._entries = {}
        return cache

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, image: Path) -> RawMetadata | None:
        with self._lock:
            return self._entries.get(image.name)

    def put(self, image: Path, raw: RawMetadata) -> RawMetadata:
        """Store the cached part of `raw` and return it. Metadata that could not be read
        completely is returned unchanged and not stored, so it is read again next time."""
        if raw.errors:
            return raw
        reduced = RawMetadata(
            tags={
                source: {tag: list(values) for tag, values in tags.items() if tag in self._tags}
                for source, tags in raw.tags.items()
            },
            sidecar_path=raw.sidecar_path,
            image_size=raw.image_size,
        )
        with self._lock:
            self._entries[image.name] = reduced
            self._dirty = True
        return reduced

    def discard(self, image: Path) -> None:
        with self._lock:
            if self._entries.pop(image.name, None) is not None:
                self._dirty = True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._dirty = True

    def keep_only(self, names: Collection[str]) -> None:
        """Drop the entries of images that are no longer in the folder."""
        with self._lock:
            gone = self._entries.keys() - set(names)
            for name in gone:
                del self._entries[name]
            self._dirty = self._dirty or bool(gone)

    def save(self) -> None:
        """Write the cache file atomically. Raises OSError."""
        with self._lock:
            document = {
                "version": CACHE_VERSION,
                "tags": sorted(self._tags),
                "images": {name: _raw_to_json(raw) for name, raw in self._entries.items()},
            }
            self._dirty = False
        temporary = self.path.with_name(CACHE_FILE_NAME + ".tmp")
        try:
            temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            self._dirty = True
            temporary.unlink(missing_ok=True)
            raise


def _raw_to_json(raw: RawMetadata) -> dict:
    return {
        "sidecar": raw.sidecar_path.name if raw.sidecar_path else None,
        "size": list(raw.image_size) if raw.image_size else None,
        "tags": {source.name.lower(): tags for source, tags in raw.tags.items()},
    }


def _raw_from_json(folder: Path, entry: dict) -> RawMetadata:
    tags = {}
    for source_id, source_tags in entry["tags"].items():
        tags[_SOURCE_IDS[source_id]] = {
            str(tag): [str(value) for value in values] for tag, values in source_tags.items()
        }
    sidecar = entry["sidecar"]
    size = entry["size"]
    return RawMetadata(
        tags=tags,
        sidecar_path=folder / sidecar if sidecar else None,
        image_size=(int(size[0]), int(size[1])) if size else None,
    )
