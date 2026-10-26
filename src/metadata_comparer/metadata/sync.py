"""Checks whether the other sources agree with the master source on selected fields."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import IntEnum

from metadata_comparer.metadata.comparison import compare
from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.sources import RawMetadata, Source


class SyncStatus(IntEnum):
    """Ordered by severity, so the worst status of several fields is their max()."""

    UNKNOWN = -1  # metadata could not be read
    OK = 0
    MISSING = 1  # master has a value, another source has none
    CONFLICT = 2  # another source holds a different value


@dataclass(frozen=True)
class SyncReport:
    status: SyncStatus
    issues: tuple[str, ...] = ()


def check_sync(
    raw: RawMetadata,
    mappings: list[FieldMapping],
    master: Source,
    fields: Collection[str],
    sources: Collection[Source] = tuple(Source),
) -> SyncReport:
    """Compare `fields` of the other `sources` against `master`.

    Sources that cannot hold a field (no tags mapped for their family) are skipped,
    as is the sidecar when the image has none. Fields the master cannot hold are skipped.
    """
    if raw.errors:
        return SyncReport(SyncStatus.UNKNOWN, tuple(raw.errors))

    selected = [mapping for mapping in mappings if mapping.name in fields]
    status = SyncStatus.OK
    issues = []
    for mapping, row in zip(selected, compare(raw, selected), strict=True):
        if not mapping.tags.get(master.family):
            continue
        master_cell = row.cells[master]
        for source in _compared_sources(raw, mapping, master, sources):
            cell = row.cells[source]
            if cell is None and master_cell is not None:
                status = max(status, SyncStatus.MISSING)
                issues.append(f"{row.field}: missing in {source.label}")
            elif cell is not None and (
                master_cell is None or set(cell.values) != set(master_cell.values)
            ):
                status = max(status, SyncStatus.CONFLICT)
                master_text = f"'{master_cell.text}'" if master_cell else "none"
                issues.append(
                    f"{row.field}: {source.label} has '{cell.text}', "
                    f"{master.label} has {master_text}"
                )
    return SyncReport(status, tuple(issues))


def _compared_sources(
    raw: RawMetadata, mapping: FieldMapping, master: Source, sources: Collection[Source]
) -> list[Source]:
    return [
        source
        for source in Source
        if source != master
        and source in sources
        and mapping.tags.get(source.family)
        and not (source == Source.XMP_SIDECAR and raw.sidecar_path is None)
    ]
