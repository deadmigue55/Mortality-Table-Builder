"""CONAPO demographic reconciliation 1950-2019 and projections 2020-2070.

A single ZIP holds Excel workbooks in long format (one row per year, state, age, sex).
We use three of them:

* ``0_Pob_Mitad``: mid-year (1 July) population, the **exposure** for death rates.
* ``1_Defunciones``: CONAPO's own modelled deaths, kept as a cross-check against INEGI.
* ``6_Esperanza_Vida_Nacer``: life expectancy at birth, a sanity check for our tables.

Years up to 2019 are CONAPO's reconciled estimates; 2020 onward are projections from the
2020 census base, so recent "exposure" is a model output, not a count.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from mortality.config import Paths, get_paths
from mortality.ingest.download import Download, fetch

SOURCE = "conapo"
URL = "https://conapo.segob.gob.mx/work/models/CONAPO/pry23/DB/ConDem50a19_ProyPob20a70.zip"
ZIP_NAME = "ConDem50a19_ProyPob20a70.zip"
FIRST_PROJECTED_YEAR = 2020

SEX = {"Hombres": "M", "Mujeres": "F", "Total": "T"}


@dataclass(frozen=True)
class Workbook:
    """One Excel file inside the ZIP and how to read it."""

    member: str  # file name inside the ZIP
    value_col: str  # numeric column in the workbook
    value_name: str  # name in our table
    output: str  # parquet file name


WORKBOOKS = {
    "population": Workbook(
        "0_Pob_Mitad_1950_2070.xlsx", "POBLACION", "population", "population_mid_year.parquet"
    ),
    "deaths": Workbook(
        "1_Defunciones_1950_2070.xlsx", "DEFUNCIONES", "deaths", "deaths_modelled.parquet"
    ),
    "e0": Workbook(
        "6_Esperanza_Vida_Nacer_1950_2070.xlsx", "EV", "e0", "life_expectancy_at_birth.parquet"
    ),
}


def download(
    *,
    force: bool = False,
    session: requests.Session | None = None,
    paths: Paths | None = None,
) -> Download:
    """Download the CONAPO ZIP (about 80 MB)."""
    return fetch(URL, source=SOURCE, filename=ZIP_NAME, force=force, session=session, paths=paths)


def clean(raw: pd.DataFrame, wb: Workbook) -> pd.DataFrame:
    """Rename columns, standardise sex and flag projected years."""
    needed = {"AÑO", "CVE_GEO", "ENTIDAD", "SEXO", wb.value_col}
    if wb.output != WORKBOOKS["e0"].output:
        needed.add("EDAD")
    missing = needed - set(raw.columns)
    if missing:
        raise KeyError(f"{wb.member}: missing columns {sorted(missing)}")

    unknown_sex = set(raw["SEXO"].dropna().unique()) - set(SEX)
    if unknown_sex:
        raise ValueError(f"{wb.member}: unexpected SEXO values {sorted(unknown_sex)}")

    out = pd.DataFrame(
        {
            "year": raw["AÑO"].astype("int16"),
            "state_code": raw["CVE_GEO"].astype("int8"),
            "state": raw["ENTIDAD"].astype("string").str.strip(),
            "sex": raw["SEXO"].map(SEX).astype("string"),
        }
    )
    if "EDAD" in raw.columns:
        out["age"] = raw["EDAD"].astype("int16")
    out[wb.value_name] = raw[wb.value_col].astype("float64")
    out["is_projection"] = out["year"] >= FIRST_PROJECTED_YEAR
    return out


def _read_workbook(zip_path: Path, wb: Workbook) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as archive:
        names = {Path(n).name: n for n in archive.namelist()}
        if wb.member not in names:
            raise FileNotFoundError(f"{wb.member} not found in {zip_path.name}")
        with archive.open(names[wb.member]) as handle:
            # calamine reads large Excel files in seconds (openpyxl takes minutes)
            return pd.read_excel(handle, engine="calamine", sheet_name=0)


def process(*, force: bool = False, paths: Paths | None = None) -> dict[str, Path]:
    """Convert the workbooks to Parquet under ``data/processed/conapo/``."""
    paths = (paths or get_paths()).ensure()
    zip_path = paths.raw / SOURCE / ZIP_NAME
    if not zip_path.exists():
        raise FileNotFoundError(f"{zip_path} not found. Run the download first.")
    out_dir = paths.processed / SOURCE
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for key, wb in WORKBOOKS.items():
        target = out_dir / wb.output
        if not target.exists() or force:
            clean(_read_workbook(zip_path, wb), wb).to_parquet(target, index=False)
        written[key] = target
    return written
