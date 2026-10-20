"""INEGI interactive tables ("consulta interactiva"), exported by hand from the browser.

INEGI's online cube for registered deaths (https://www.inegi.org.mx/sistemas/olap/consulta/
general_ver4/MDXQueryDatos.asp?c=11144) covers 1990 onward but only answers inside a live
browser session, so it cannot be downloaded by script. Export one CSV per year (rows: age,
columns: sex) and import them with ``mortality ingest inegi-cube <zip or csv files>``.

What these files are, and are not:

* counts by **year of registration**, not year of occurrence;
* **five-year age groups** (under 1, 1-4, 5-9, ... 85 and over), national, by sex;
* the year is read from the header *inside* each file; the file name is not trusted (a file
  named ``2017.csv`` was found to contain 2025).
"""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from mortality.config import Paths, get_paths
from mortality.ingest.download import Download, register_local

SOURCE = "inegi_cube"
CUBE_URL = "https://www.inegi.org.mx/sistemas/olap/consulta/general_ver4/MDXQueryDatos.asp?c=11144"
MAX_CSV_BYTES = 5_000_000

SEX_BY_COLUMN = {"Total": "T", "Hombre": "M", "Mujer": "F", "No especificado": "U"}
EXPECTED_COLUMNS = ["Total", "Hombre", "Mujer", "No especificado"]

_YEAR = re.compile(r"A.o de registro\s*:\s*(\d{4})")
_FILTER = re.compile(r"^,\s*([^,:]+?)\s*:\s*(.+?)\s*$")
_UNDER_ONE = re.compile(r"^Menores de 1 a")
_RANGE = re.compile(r"^(\d{1,3})-(\d{1,3}) a")
_OPEN = re.compile(r"^(\d{1,3}) a.{1,4}os y m")


class CubeError(ValueError):
    """The exported file is not in the layout we expect, or its totals do not add up."""


@dataclass(frozen=True)
class Imported:
    download: Download
    year: int
    original_name: str

    @property
    def renamed(self) -> bool:
        return Path(self.original_name).stem != str(self.year)


def decode(raw: bytes) -> str:
    """INEGI exports Windows-1252; accept UTF-8 too."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def age_bounds(label: str) -> tuple[int | None, int | None] | None:
    """(low, high) of an age-group label; high is None for the open group; None if not a group."""
    label = label.strip()
    if _UNDER_ONE.match(label):
        return 0, 0
    if match := _RANGE.match(label):
        return int(match[1]), int(match[2])
    if match := _OPEN.match(label):
        return int(match[1]), None
    return None


def _number(cell: str) -> int:
    cell = cell.replace("\xa0", " ").strip().replace(",", "")
    if not cell:
        return 0  # INEGI leaves empty cells where there are no deaths
    if not cell.isdigit():
        raise CubeError(f"Not a count: {cell!r}")
    return int(cell)


def parse_csv(text: str) -> tuple[int, pd.DataFrame]:
    """Parse one export into (registration year, tidy counts by age group and sex)."""
    lines = text.replace("\r", "").replace("\xa0", " ").split("\n")

    year_matches = [m for line in lines[:12] if (m := _YEAR.search(line))]
    if len(year_matches) != 1:
        raise CubeError("Could not find a single 'Año de registro' line in the header.")
    year = int(year_matches[0][1])

    filters = []
    for line in lines[:12]:
        if (m := _FILTER.match(line)) and not _YEAR.search(line):
            filters.append(f"{m[1]}: {m[2]}")

    try:
        header_at = next(i for i, line in enumerate(lines) if "Hombre" in line and "Mujer" in line)
    except StopIteration:
        raise CubeError("Could not find the column header (Total, Hombre, Mujer).") from None
    columns = [c.strip() for c in next(csv.reader([lines[header_at]]))]
    columns = [c for c in columns if c]
    if columns != EXPECTED_COLUMNS:
        raise CubeError(f"Unexpected columns {columns}; expected {EXPECTED_COLUMNS}.")

    rows: dict[str, list[int]] = {}
    for line in lines[header_at + 1 :]:
        if not line.strip() or line.strip().startswith("Fuente"):
            break
        cells = next(csv.reader([line]))
        if len(cells) != 5:
            raise CubeError(f"Row has {len(cells)} cells, expected 5: {line!r}")
        label = cells[0].strip()
        if label in rows:
            raise CubeError(f"Row {label!r} appears twice.")
        rows[label] = [_number(c) for c in cells[1:]]

    if "Total" not in rows:
        raise CubeError("No 'Total' row.")
    total = rows.pop("Total")
    unknown_row = rows.pop("No especificado", None)

    records = []
    for label, values in rows.items():
        bounds = age_bounds(label)
        if bounds is None:
            raise CubeError(f"Unrecognised age group {label!r}.")
        records.append((label, bounds[0], bounds[1], values))
    if unknown_row is not None:
        records.append(("No especificado", None, None, unknown_row))
    if not records:
        raise CubeError("No age groups found.")

    # The table must add up both ways: across sexes and down age groups
    for label, _, _, v in records:
        if v[0] != sum(v[1:]):
            raise CubeError(f"{label}: sexes do not add up to the row total.")
    for i, name in enumerate(EXPECTED_COLUMNS):
        if sum(r[3][i] for r in records) != total[i]:
            raise CubeError(f"Column {name!r}: age groups do not add up to the Total row.")

    out = [
        {
            "reg_year": year,
            "age_group": label,
            "age_lo": lo,
            "age_hi": hi,
            "sex": SEX_BY_COLUMN[column],
            "deaths": values[i],
            "filters": "; ".join(filters),
        }
        for label, lo, hi, values in records
        for i, column in enumerate(EXPECTED_COLUMNS)
        if column != "Total"
    ]
    frame = pd.DataFrame(out).astype(
        {"reg_year": "int16", "age_lo": "Int16", "age_hi": "Int16", "deaths": "int64"}
    )
    return year, frame


# ── Import and processing ───────────────────────────────────────────────────


def _csv_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for info in archive.infolist():
        name = info.filename
        if info.is_dir() or not name.lower().endswith(".csv"):
            continue
        if "/" in name or "\\" in name or name.startswith("."):
            raise CubeError(f"Unexpected path inside the ZIP: {name!r}")
        if info.file_size > MAX_CSV_BYTES:
            raise CubeError(f"{name} is too large to be an INEGI table export.")
        members.append(info)
    if not members:
        raise CubeError("No CSV files found in the ZIP.")
    return members


def import_files(sources: list[Path], *, paths: Paths | None = None) -> list[Imported]:
    """Copy exported CSVs (loose files or ZIPs) into ``data/raw/inegi_cube`` and log them.

    Each file is stored under the year found *inside* it, as ``registered_<year>.csv``.
    """
    paths = (paths or get_paths()).ensure()
    folder = paths.raw / SOURCE
    folder.mkdir(parents=True, exist_ok=True)

    blobs: list[tuple[str, bytes]] = []
    for source in sources:
        source = Path(source)
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                blobs += [(m.filename, archive.read(m)) for m in _csv_members(archive)]
        elif source.suffix.lower() == ".csv":
            if source.stat().st_size > MAX_CSV_BYTES:
                raise CubeError(f"{source.name} is too large to be an INEGI table export.")
            blobs.append((source.name, source.read_bytes()))
        else:
            raise CubeError(f"{source.name}: give a .csv or .zip file.")

    parsed: list[tuple[str, int, bytes]] = []
    for name, data in blobs:
        year, _ = parse_csv(decode(data))  # validates before anything is written
        parsed.append((name, year, data))
    years = [y for _, y, _ in parsed]
    duplicates = sorted({y for y in years if years.count(y) > 1})
    if duplicates:
        raise CubeError(f"More than one file for registration year(s) {duplicates}.")

    imported = []
    for name, year, data in sorted(parsed, key=lambda item: item[1]):
        target = folder / f"registered_{year}.csv"
        target.write_bytes(data)
        result = register_local(
            target,
            source=SOURCE,
            url=f"{CUBE_URL} (exported by hand from the browser as {name})",
            paths=paths,
        )
        imported.append(Imported(result, year, name))
    return imported


def process(*, paths: Paths | None = None) -> Path:
    """Parse every imported export into ``data/processed/inegi/cube_registered_grouped.parquet``."""
    paths = (paths or get_paths()).ensure()
    files = sorted((paths.raw / SOURCE).glob("registered_*.csv"))
    if not files:
        raise FileNotFoundError(
            "No exported tables found. Run `mortality ingest inegi-cube` first."
        )
    frames = []
    for file in files:
        year, frame = parse_csv(decode(file.read_bytes()))
        if file.stem != f"registered_{year}":
            raise CubeError(f"{file.name} contains registration year {year}.")
        frames.append(frame)
    out_dir = paths.processed / "inegi"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "cube_registered_grouped.parquet"
    pd.concat(frames, ignore_index=True).to_parquet(target, index=False)
    return target
