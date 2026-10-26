from dataclasses import dataclass

from metadata_comparer.metadata.mapping import FieldMapping
from metadata_comparer.metadata.sources import RawMetadata, Source


@dataclass(frozen=True)
class CellValue:
    values: tuple[str, ...]
    tag: str  # exiv2 key the values came from

    @property
    def text(self) -> str:
        return "; ".join(self.values)


@dataclass(frozen=True)
class ComparisonRow:
    field: str
    cells: dict[Source, CellValue | None]

    @property
    def has_conflict(self) -> bool:
        """True if at least two sources hold different values. Order does not matter."""
        value_sets = {frozenset(cell.values) for cell in self.cells.values() if cell is not None}
        return len(value_sets) > 1


def compare(raw: RawMetadata, mappings: list[FieldMapping]) -> list[ComparisonRow]:
    rows = []
    for mapping in mappings:
        cells = {source: _lookup(raw, mapping, source) for source in Source}
        rows.append(ComparisonRow(field=mapping.name, cells=cells))
    return rows


def _lookup(raw: RawMetadata, mapping: FieldMapping, source: Source) -> CellValue | None:
    source_tags = raw.tags.get(source, {})
    for tag in mapping.tags.get(source.family, ()):
        values = [value for value in source_tags.get(tag, []) if value]
        if values:
            return CellValue(values=tuple(values), tag=tag)
    return None
