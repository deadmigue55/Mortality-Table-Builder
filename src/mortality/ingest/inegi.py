"""INEGI registered deaths (Estadísticas de Defunciones Registradas).

One ZIP per registration year holds ``DEFUNyy.dbf`` (one row per death) plus code
catalogs and a PDF description. Two things matter for mortality rates:

* ``EDAD`` is a 4-digit code: first digit is the unit (1 hours, 2 days, 3 months,
  4 years), the last three the value. ``4998`` means age not specified.
* Each file also contains deaths that *occurred* in earlier years but were registered
  late. Always group by year of occurrence (``occ_year``) across *all* files, and treat
  the most recent year as incomplete until the next year's file is loaded.

INEGI has moved its files between folders over time and answers bad URLs with an HTML
page, so each year lists several candidate URLs and the downloader verifies a real ZIP.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dbfread import DBF

from mortality.config import Paths, get_paths
from mortality.ingest.download import Download, NotAFileError, fetch

SOURCE = "inegi"
BASE = "https://www.inegi.org.mx/contenidos/programas"

# Years whose URL has been confirmed to return a ZIP (checked October 2026).
CONFIRMED_YEARS = range(2020, 2025)

# Columns kept from the 74 in the raw file, with the names we use.
KEEP = {
    "SEXO": "sex_code",
    "EDAD": "edad",
    "ENT_RESID": "state",
    "ANIO_OCUR": "occ_year",
    "MES_OCURR": "occ_month",
    "ANIO_REGIS": "reg_year",
    "TIPO_DEFUN": "death_type",
    "CAUSA_DEF": "cause",
    "LISTA_MEX": "cause_list",
}
REQUIRED = ("SEXO", "EDAD", "ENT_RESID", "ANIO_OCUR", "ANIO_REGIS")

SEX = {1: "M", 2: "F"}  # 9 = not specified
UNKNOWN_AGE = 4998
UNKNOWN_YEAR = 9999


def zip_name(year: int) -> str:
    return f"defunciones_base_datos_{year}_dbf.zip"


def candidate_urls(year: int) -> list[str]:
    """Places INEGI has published the death microdata ZIP for ``year``, best guess first."""
    name = zip_name(year)
    folders = (
        f"edr/microdatos/defunciones/{year}",  # 2023 onward
        f"mortalidad/microdatos/defunciones/{year}",  # 2020-2022
    )
    if year >= 2023:
        return [f"{BASE}/{f}/{name}" for f in folders]
    return [f"{BASE}/{f}/{name}" for f in reversed(folders)]


def download_year(
    year: int,
    *,
    force: bool = False,
    session: requests.Session | None = None,
    paths: Paths | None = None,
) -> Download:
    """Download one year's ZIP, trying each candidate URL until one is a real ZIP."""
    paths = paths or get_paths()
    target = paths.raw / SOURCE / zip_name(year)
    if target.exists() and not force:
        return fetch(candidate_urls(year)[0], source=SOURCE, filename=zip_name(year), paths=paths)

    errors: list[str] = []
    for url in candidate_urls(year):
        try:
            return fetch(
                url,
                source=SOURCE,
                filename=zip_name(year),
                force=force,
                session=session,
                paths=paths,
            )
        except (NotAFileError, requests.HTTPError) as err:
            errors.append(str(err))
    raise FileNotFoundError(
        f"INEGI deaths ZIP for {year} not found at any known address.\n  "
        + "\n  ".join(errors)
        + "\nDownload it from https://www.inegi.org.mx/programas/edr/ (Microdatos, DBF) and "
        f"save it as data/raw/inegi/{zip_name(year)}."
    )


# ── Cleaning ────────────────────────────────────────────────────────────────


def decode_edad(edad: pd.Series) -> pd.DataFrame:
    """Split INEGI's 4-digit age code into unit, value and completed years.

    Deaths under one year (hours, days, months) get ``age_years = 0``. Unknown or invalid
    codes get ``<NA>``.
    """
    code = pd.to_numeric(edad, errors="coerce").astype("Int64")
    unit_digit = code // 1000
    value = code % 1000
    valid_unit = unit_digit.isin([1, 2, 3, 4])
    known = valid_unit & (code != UNKNOWN_AGE) & (value > 0)

    unit = pd.Series(pd.NA, index=code.index, dtype="string")
    for digit, label in ((1, "hours"), (2, "days"), (3, "months"), (4, "years")):
        unit = unit.mask(unit_digit == digit, label)

    age_years = pd.Series(pd.NA, index=code.index, dtype="Int64")
    age_years = age_years.mask(known & (unit_digit < 4), 0)
    age_years = age_years.mask(known & (unit_digit == 4), value)
    return pd.DataFrame(
        {
            "age_unit": unit.where(known),
            "age_value": value.where(known),
            "age_years": age_years,
        }
    )


def clean_deaths(raw: pd.DataFrame, file_year: int) -> pd.DataFrame:
    """Turn the selected raw columns into the analysis table (one row per death)."""
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise KeyError(f"Missing expected INEGI columns: {missing}")

    out = pd.DataFrame(index=raw.index)
    out["file_year"] = np.int16(file_year)

    sex_code = pd.to_numeric(raw["SEXO"], errors="coerce").astype("Int64")
    out["sex"] = sex_code.map(SEX).astype("string")

    out = out.join(decode_edad(raw["EDAD"]))

    state = raw["ENT_RESID"].astype("string").str.strip().str.zfill(2)
    out["state"] = state
    out["resident_in_mexico"] = state.str.fullmatch(r"(0[1-9]|[12]\d|3[0-2])").fillna(False)

    for src, dst in (
        ("ANIO_OCUR", "occ_year"),
        ("MES_OCURR", "occ_month"),
        ("ANIO_REGIS", "reg_year"),
    ):
        if src in raw.columns:
            out[dst] = pd.to_numeric(raw[src], errors="coerce").astype("Int64")
    out["occ_year"] = out["occ_year"].mask(out["occ_year"] == UNKNOWN_YEAR)
    out["occ_month"] = out["occ_month"].where(out["occ_month"].between(1, 12))

    for src, dst in (
        ("TIPO_DEFUN", "death_type"),
        ("CAUSA_DEF", "cause"),
        ("LISTA_MEX", "cause_list"),
    ):
        if src in raw.columns:
            out[dst] = raw[src].astype("string").str.strip()
    return out


def _find_member(archive: zipfile.ZipFile, pattern: str) -> str:
    for name in archive.namelist():
        if re.fullmatch(pattern, Path(name).name, flags=re.IGNORECASE):
            return name
    raise FileNotFoundError(f"No file matching {pattern!r} in the ZIP.")


def read_deaths_zip(zip_path: Path, file_year: int) -> pd.DataFrame:
    """Read ``DEFUNyy.dbf`` straight out of the ZIP and return the cleaned table."""
    with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory() as tmp:
        member = _find_member(archive, r"DEFUN\d{2}\.dbf")
        dbf_path = Path(archive.extract(member, tmp))
        table = DBF(dbf_path, encoding="latin-1", char_decode_errors="replace", lowernames=False)
        wanted = [c for c in KEEP if c in table.field_names]
        rows = ([rec[c] for c in wanted] for rec in table)
        raw = pd.DataFrame(rows, columns=wanted)
    return clean_deaths(raw, file_year)


def process_year(year: int, *, force: bool = False, paths: Paths | None = None) -> Path:
    """Convert a downloaded ZIP into ``data/processed/inegi/deaths_<year>.parquet``."""
    paths = (paths or get_paths()).ensure()
    zip_path = paths.raw / SOURCE / zip_name(year)
    if not zip_path.exists():
        raise FileNotFoundError(f"{zip_path} not found. Run the download first.")
    out_dir = paths.processed / SOURCE
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"deaths_{year}.parquet"
    if target.exists() and not force:
        return target
    df = read_deaths_zip(zip_path, year)
    df.to_parquet(target, index=False)
    return target


def parse_years(spec: Iterable[str]) -> list[int]:
    """Accept ``2020 2022`` or ``2020-2024`` style arguments."""
    years: set[int] = set()
    for item in spec:
        for part in str(item).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = (int(x) for x in part.split("-", 1))
                if start > end:
                    raise ValueError(f"Bad year range: {part}")
                years.update(range(start, end + 1))
            else:
                years.add(int(part))
    return sorted(years)
