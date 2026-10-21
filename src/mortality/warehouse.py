"""The warehouse: every processed source in one SQLite database.

``build()`` loads the Parquet files written by the ``ingest`` modules into
``data/mortality.sqlite`` and creates a few derived tables. Sources that have not been
downloaded yet are skipped, so a partial warehouse still builds.

Why SQLite: it ships with Python, so it also runs where Windows application control blocks
native packages such as DuckDB. To keep it small, INEGI deaths are stored as counts per
cell (year, month, state, sex, age); the row-level files, with cause of death, stay in
Parquet under ``data/processed/inegi``.
"""

from __future__ import annotations

import csv
import glob
import sqlite3
from dataclasses import dataclass

import pandas as pd

from mortality import excess, experience, graduation, lifetable, pricing, projection, quality, rates
from mortality.config import Paths, get_paths


@dataclass(frozen=True)
class Source:
    """A processed Parquet file that becomes one warehouse table."""

    table: str
    pattern: str  # relative to data/processed
    description: str
    index: tuple[str, ...] = ()  # columns to index together


SOURCES: tuple[Source, ...] = (
    Source(
        "inegi_cube_registered",
        "inegi/cube_registered_grouped.parquet",
        "INEGI interactive-table exports: deaths by year of REGISTRATION, five-year age group "
        "and sex, national (imported by hand)",
        ("reg_year", "sex", "age_lo"),
    ),
    Source(
        "conapo_population",
        "conapo/population_mid_year.parquet",
        "CONAPO mid-year population by year, state, single age and sex (the exposure)",
        ("year", "state_code", "sex", "age"),
    ),
    Source(
        "conapo_deaths",
        "conapo/deaths_modelled.parquet",
        "CONAPO modelled deaths, a cross-check on INEGI",
        ("year", "state_code", "sex", "age"),
    ),
    Source(
        "conapo_life_expectancy",
        "conapo/life_expectancy_at_birth.parquet",
        "CONAPO life expectancy at birth by year, state and sex",
        ("year", "state_code", "sex"),
    ),
    Source(
        "hmd_deaths",
        "hmd/deaths.parquet",
        "HMD deaths by country, year, age and sex",
        ("country", "year", "sex", "age"),
    ),
    Source(
        "hmd_exposures",
        "hmd/exposures.parquet",
        "HMD exposure-to-risk, same layout as deaths",
        ("country", "year", "sex", "age"),
    ),
    Source(
        "hmd_life_tables",
        "hmd/life_tables.parquet",
        "HMD period life tables (1x1)",
        ("country", "sex", "year", "age"),
    ),
    Source("soa_catalog", "soa/catalog.parquet", "SOA tables: names, groups and source references"),
    Source(
        "soa_rates",
        "soa/rates.parquet",
        "SOA table rates by age (and duration)",
        ("table_id", "sub_table", "age"),
    ),
    Source(
        "cnsf_rates",
        "cnsf/rates.parquet",
        "CNSF 2013 regulatory rates by table, variant and age",
        ("table", "variant", "age"),
    ),
)

INEGI_TABLE = "inegi_deaths_cells"
INEGI_DESCRIPTION = (
    "INEGI registered deaths as counts per cell: file year, year and month of occurrence, state, "
    "sex, completed age and type of death. Cause of death stays in the Parquet files"
)
INEGI_CELL_COLUMNS = (
    "file_year",
    "occ_year",
    "occ_month",
    "state",
    "resident_in_mexico",
    "sex",
    "age_years",
    "death_type",
)

DERIVED_SQL: dict[str, tuple[str, str]] = {
    "dim_state": (
        "State codes: CONAPO integer code, INEGI two-digit text code and name",
        """
        SELECT DISTINCT state_code,
               printf('%02d', state_code) AS state_code_text,
               state AS state_name
        FROM conapo_population
        """,
    ),
    "deaths_by_occurrence": (
        "INEGI deaths of Mexican residents by year of occurrence, state, sex and age "
        "(unknown sex, age or year excluded; see deaths_unallocated)",
        f"""
        SELECT occ_year AS year, state AS state_code_text, sex, age_years AS age,
               SUM(deaths) AS deaths
        FROM {INEGI_TABLE}
        WHERE resident_in_mexico = 1 AND occ_year IS NOT NULL
          AND sex IS NOT NULL AND age_years IS NOT NULL
        GROUP BY occ_year, state, sex, age_years
        """,
    ),
    "deaths_unallocated": (
        "INEGI deaths by year of occurrence that could not be placed in a sex-age cell",
        f"""
        SELECT occ_year AS year,
               SUM(deaths) FILTER (WHERE sex IS NULL) AS unknown_sex,
               SUM(deaths) FILTER (WHERE age_years IS NULL) AS unknown_age,
               SUM(deaths) FILTER (WHERE resident_in_mexico = 0) AS non_residents,
               SUM(deaths) AS all_deaths
        FROM {INEGI_TABLE}
        WHERE occ_year IS NOT NULL
        GROUP BY occ_year
        ORDER BY occ_year
        """,
    ),
    "inegi_completeness": (
        "Per year of occurrence: deaths found, whether that year's own INEGI file and the "
        "following year's file (which carries late registrations) are loaded, and so whether "
        "the year is complete",
        f"""
        SELECT occ_year AS year,
               SUM(deaths) AS deaths,
               MIN(file_year) AS first_file_year,
               MAX(file_year) AS last_file_year,
               COALESCE(SUM(deaths) FILTER (WHERE file_year > occ_year), 0) AS registered_late,
               occ_year IN (SELECT DISTINCT file_year FROM {INEGI_TABLE}) AS file_loaded,
               (occ_year + 1) IN (SELECT DISTINCT file_year FROM {INEGI_TABLE}) AS next_file_loaded,
               (occ_year IN (SELECT DISTINCT file_year FROM {INEGI_TABLE})
                AND (occ_year + 1) IN (SELECT DISTINCT file_year FROM {INEGI_TABLE})) AS complete
        FROM {INEGI_TABLE}
        WHERE occ_year IS NOT NULL
        GROUP BY occ_year
        ORDER BY occ_year
        """,
    ),
}


def aggregate_inegi(deaths: pd.DataFrame) -> pd.DataFrame:
    """Collapse row-level deaths into counts per cell (keeps unknowns as missing values)."""
    # Older files lack some columns (death_type only exists from 2022); fill them as missing
    df = deaths.reindex(columns=list(INEGI_CELL_COLUMNS))
    df["death_type"] = df["death_type"].astype("string")
    df["resident_in_mexico"] = df["resident_in_mexico"].astype("boolean").astype("Int64")
    cells = (
        df.groupby(list(INEGI_CELL_COLUMNS), dropna=False, observed=True)
        .size()
        .rename("deaths")
        .reset_index()
    )
    return cells


def _sqlite_ready(df: pd.DataFrame) -> pd.DataFrame:
    """Turn pandas nullable types into plain Python values SQLite understands."""
    out = df.copy()
    for column in out.columns:
        dtype = out[column].dtype
        if pd.api.types.is_bool_dtype(dtype):
            out[column] = out[column].astype("Int64")
        if pd.api.types.is_extension_array_dtype(out[column].dtype):
            out[column] = out[column].astype(object).where(out[column].notna(), None)
    return out


def _store(
    con: sqlite3.Connection, name: str, df: pd.DataFrame, index: tuple[str, ...] = ()
) -> None:
    _sqlite_ready(df).to_sql(name, con, if_exists="replace", index=False, chunksize=100_000)
    if index:
        cols = ", ".join(f'"{c}"' for c in index)
        con.execute(f'CREATE INDEX "ix_{name}" ON "{name}" ({cols})')


def _load_manifest(con: sqlite3.Connection, paths: Paths) -> bool:
    if not paths.manifest.exists():
        return False
    with paths.manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    con.execute("DROP TABLE IF EXISTS source_manifest")
    con.execute(
        "CREATE TABLE source_manifest (source TEXT, file TEXT, url TEXT, downloaded_at TEXT, "
        "bytes INTEGER, sha256 TEXT)"
    )
    con.executemany(
        "INSERT INTO source_manifest VALUES (?, ?, ?, ?, ?, ?)",
        [
            (r["source"], r["file"], r["url"], r["downloaded_at"], int(r["bytes"]), r["sha256"])
            for r in rows
        ],
    )
    return True


def table_names(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def build(*, paths: Paths | None = None) -> dict[str, int]:
    """(Re)build the warehouse from scratch. Returns ``{table: row_count}``."""
    paths = (paths or get_paths()).ensure()
    tmp = paths.database.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    docs: list[tuple[str, str]] = []

    con = sqlite3.connect(tmp)
    try:
        for source in SOURCES:
            file = paths.processed / source.pattern
            if file.exists():
                _store(con, source.table, pd.read_parquet(file), source.index)
                docs.append((source.table, source.description))

        inegi_files = sorted(glob.glob(str(paths.processed / "inegi" / "deaths_*.parquet")))
        if inegi_files:
            # file_year is part of the cell key, so cells from different files never overlap
            cells = pd.concat(
                (aggregate_inegi(pd.read_parquet(f)) for f in inegi_files),
                ignore_index=True,
            )
            _store(con, INEGI_TABLE, cells, ("occ_year", "state", "sex", "age_years"))
            docs.append((INEGI_TABLE, INEGI_DESCRIPTION))

        existing = table_names(con)
        derived = []
        if "conapo_population" in existing:
            derived.append("dim_state")
        if INEGI_TABLE in existing:
            derived += ["deaths_by_occurrence", "deaths_unallocated", "inegi_completeness"]
        for name in derived:
            description, sql = DERIVED_SQL[name]
            con.execute(f'CREATE TABLE "{name}" AS {sql}')
            docs.append((name, description))

        docs += quality.build_tables(con)
        docs += quality.cause_tables(con, inegi_files)
        docs += rates.build_tables(con)
        docs += graduation.build_tables(con)
        docs += lifetable.build_tables(con)
        docs += projection.build_tables(con)
        docs += experience.build_tables(con)
        docs += excess.build_tables(con)
        docs += pricing.build_tables(con)

        if _load_manifest(con, paths):
            docs.append(("source_manifest", "Every downloaded file: URL, date, size and SHA-256"))

        con.execute("CREATE TABLE table_docs (table_name TEXT, description TEXT)")
        con.executemany("INSERT INTO table_docs VALUES (?, ?)", docs)
        counts = {
            name: con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name, _ in sorted(docs)
        }
        con.commit()
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    tmp.replace(paths.database)
    return counts


def connect(paths: Paths | None = None, *, read_only: bool = True) -> sqlite3.Connection:
    """Open the warehouse (read-only by default)."""
    paths = paths or get_paths()
    if not paths.database.exists():
        raise FileNotFoundError(f"{paths.database} not found. Run `mortality db build` first.")
    uri = f"file:{paths.database.as_posix()}?mode={'ro' if read_only else 'rw'}"
    return sqlite3.connect(uri, uri=True)
