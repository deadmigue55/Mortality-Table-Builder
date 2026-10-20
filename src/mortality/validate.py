"""Data checks on the warehouse.

Each check is a SQL query that counts violations. Severity decides what a violation means:

* ``FAIL``: the data is wrong or unusable; fix before analysing.
* ``WARN``: legitimate but needs a human eye (known gaps, differences between sources).

A check whose tables are missing is reported as ``SKIP`` rather than silently passing.
Results are stored in the ``validation_results`` table.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from dataclasses import dataclass

from mortality.config import Paths, get_paths
from mortality.warehouse import INEGI_TABLE, table_names


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # "FAIL" or "WARN"
    needs: tuple[str, ...]  # tables that must exist
    sql: str  # returns one number: how many violations
    what: str  # plain-language description of the rule


# Plain GLOB patterns keep these queries portable (SQLite has no SIMILAR TO)
_VALID_STATE = (
    "state GLOB '[0-9][0-9]' AND (CAST(state AS INTEGER) BETWEEN 1 AND 35 OR state = '99')"
)

CHECKS: tuple[Check, ...] = (
    # ── INEGI deaths ────────────────────────────────────────────────────────
    Check(
        "inegi_sex_values",
        "FAIL",
        (INEGI_TABLE,),
        f"SELECT COALESCE(SUM(deaths), 0) FROM {INEGI_TABLE} "
        "WHERE sex IS NOT NULL AND sex NOT IN ('M', 'F')",
        "Sex is M, F or unknown",
    ),
    Check(
        "inegi_age_range",
        "FAIL",
        (INEGI_TABLE,),
        f"SELECT COALESCE(SUM(deaths), 0) FROM {INEGI_TABLE} "
        "WHERE age_years < 0 OR age_years > 125",
        "Completed age is between 0 and 125",
    ),
    Check(
        "inegi_state_codes",
        "FAIL",
        (INEGI_TABLE,),
        f"SELECT COALESCE(SUM(deaths), 0) FROM {INEGI_TABLE} WHERE NOT ({_VALID_STATE})",
        "State of residence is 01-32 (states), 33-35 (USA and other countries) or 99 (unknown)",
    ),
    Check(
        "inegi_dates_plausible",
        "FAIL",
        (INEGI_TABLE,),
        f"SELECT COALESCE(SUM(deaths), 0) FROM {INEGI_TABLE} "
        "WHERE occ_year > file_year OR occ_year < 1900 "
        "OR (occ_month IS NOT NULL AND occ_month NOT BETWEEN 1 AND 12)",
        "Death occurs no later than the file that records it, in a real month",
    ),
    Check(
        "inegi_unknown_age_share",
        "WARN",
        (INEGI_TABLE,),
        "SELECT COUNT(*) FROM (SELECT file_year FROM "
        f"{INEGI_TABLE} GROUP BY file_year "
        "HAVING 1.0 * COALESCE(SUM(deaths) FILTER (WHERE age_years IS NULL), 0)"
        " / SUM(deaths) > 0.02)",
        "Under 2% of deaths per file have an unknown age",
    ),
    Check(
        "inegi_pre_covid_baseline",
        "WARN",
        (INEGI_TABLE,),
        "SELECT CASE WHEN COALESCE(SUM(deaths) FILTER (WHERE occ_year BETWEEN 2015 AND 2019), 0) "
        f"> 1000000 THEN 0 ELSE 1 END FROM {INEGI_TABLE}",
        "Pre-COVID years (2015-2019) are loaded; needed for a baseline and excess mortality",
    ),
    Check(
        "inegi_latest_year_complete",
        "WARN",
        ("inegi_completeness",),
        "SELECT COUNT(*) FROM inegi_completeness WHERE complete = 0 "
        "AND year = (SELECT MAX(last_file_year) FROM inegi_completeness)",
        "The latest year is complete: its file and the next one (late registrations) are loaded",
    ),
    # ── CONAPO ──────────────────────────────────────────────────────────────
    Check(
        "conapo_no_negative",
        "FAIL",
        ("conapo_population",),
        "SELECT COUNT(*) FROM conapo_population WHERE population < 0 OR population IS NULL",
        "Population is present and non-negative",
    ),
    Check(
        "conapo_states_sum_to_national",
        "FAIL",
        ("conapo_population",),
        "SELECT COUNT(*) FROM ("
        " SELECT year FROM conapo_population GROUP BY year"
        " HAVING COUNT(DISTINCT state_code) = 33 AND ABS("
        "  SUM(population) FILTER (WHERE state_code > 0)"
        "  - SUM(population) FILTER (WHERE state_code = 0)) > 1)",
        "The 32 states add up to the national population in every year",
    ),
    Check(
        "conapo_complete_grid",
        "FAIL",
        ("conapo_population",),
        "SELECT COUNT(*) FROM (SELECT year, state_code, sex FROM conapo_population"
        " WHERE sex IN ('M', 'F') GROUP BY year, state_code, sex"
        " HAVING COUNT(*) <> 110 OR MIN(age) <> 0 OR MAX(age) <> 109)",
        "Every year, state and sex has single ages 0 to 109",
    ),
    # ── HMD ─────────────────────────────────────────────────────────────────
    Check(
        "hmd_keys_unique",
        "FAIL",
        ("hmd_deaths", "hmd_exposures"),
        "SELECT (SELECT COUNT(*) FROM (SELECT 1 FROM hmd_deaths"
        "  GROUP BY country, year, age, sex HAVING COUNT(*) > 1))"
        " + (SELECT COUNT(*) FROM (SELECT 1 FROM hmd_exposures"
        "  GROUP BY country, year, age, sex HAVING COUNT(*) > 1))",
        "One row per country, year, age and sex",
    ),
    Check(
        "hmd_counts_non_negative",
        "FAIL",
        ("hmd_deaths", "hmd_exposures"),
        "SELECT (SELECT COUNT(*) FROM hmd_deaths WHERE value < 0)"
        " + (SELECT COUNT(*) FROM hmd_exposures WHERE value < 0)",
        "Deaths and exposures are not negative",
    ),
    Check(
        "hmd_life_table_qx_range",
        "WARN",
        ("hmd_life_tables",),
        "SELECT COUNT(*) FROM hmd_life_tables WHERE qx IS NOT NULL AND (qx < 0 OR qx > 1)",
        "Life-table qx is a probability",
    ),
    # ── SOA ─────────────────────────────────────────────────────────────────
    Check(
        "soa_rates_are_probabilities",
        "FAIL",
        ("soa_rates",),
        "SELECT COUNT(*) FROM soa_rates WHERE rate < 0 OR rate > 1",
        "SOA rates are probabilities",
    ),
    Check(
        "soa_every_table_has_rates",
        "FAIL",
        ("soa_catalog", "soa_rates"),
        "SELECT COUNT(*) FROM soa_catalog c"
        " WHERE NOT EXISTS (SELECT 1 FROM soa_rates r WHERE r.table_id = c.table_id)",
        "Every catalogued SOA table has rates",
    ),
    Check(
        "soa_mexico_tables_present",
        "WARN",
        ("soa_catalog",),
        "SELECT CASE WHEN COUNT(*) >= 10 THEN 0 ELSE 1 END FROM soa_catalog "
        "WHERE \"group\" LIKE 'mexico%'",
        "At least 10 Mexican tables are loaded from the SOA site",
    ),
    # ── CNSF ────────────────────────────────────────────────────────────────
    Check(
        "cnsf_complete",
        "FAIL",
        ("cnsf_rates",),
        'SELECT (SELECT COUNT(*) FROM (SELECT 1 FROM cnsf_rates GROUP BY "table", variant'
        "  HAVING COUNT(*) <> 111 OR MIN(age) <> 0 OR MAX(age) <> 110))"
        ' + CASE WHEN (SELECT COUNT(*) FROM (SELECT DISTINCT "table", variant FROM cnsf_rates)) = 9'
        "  THEN 0 ELSE 1 END",
        "Nine CNSF tables, each with ages 0 to 110",
    ),
    Check(
        "cnsf_percentiles_bracket_base",
        "FAIL",
        ("cnsf_rates",),
        "SELECT COUNT(*) FROM cnsf_rates b JOIN cnsf_rates hi"
        ' ON hi."table" = b."table" AND hi.age = b.age AND hi.variant = \'p99.5\''
        " WHERE b.variant = 'base' AND hi.qx < b.qx",
        "The 99.5th percentile rates are never below the base rates",
    ),
    # ── Across sources ──────────────────────────────────────────────────────
    Check(
        "inegi_vs_conapo_deaths",
        "WARN",
        ("deaths_by_occurrence", "conapo_deaths", "inegi_completeness"),
        "SELECT COUNT(*) FROM ("
        " SELECT d.year FROM deaths_by_occurrence d"
        " JOIN (SELECT year, SUM(deaths) AS deaths FROM conapo_deaths"
        "       WHERE state_code = 0 GROUP BY year) c ON c.year = d.year"
        " JOIN inegi_completeness k ON k.year = d.year"
        " WHERE k.complete = 1 AND d.year >= 2000"
        " GROUP BY d.year, c.deaths"
        " HAVING SUM(d.deaths) / c.deaths < 0.85 OR SUM(d.deaths) / c.deaths > 1.15)",
        "For complete years, INEGI deaths are within 15% of CONAPO's modelled deaths",
    ),
)


@dataclass(frozen=True)
class Result:
    name: str
    severity: str
    status: str  # PASS, FAIL, WARN, SKIP
    violations: int | None
    what: str


def run_checks(con: sqlite3.Connection) -> list[Result]:
    available = table_names(con)
    results: list[Result] = []
    for check in CHECKS:
        if not set(check.needs) <= available:
            results.append(Result(check.name, check.severity, "SKIP", None, check.what))
            continue
        violations = int(con.execute(check.sql).fetchone()[0])
        status = "PASS" if violations == 0 else check.severity
        results.append(Result(check.name, check.severity, status, violations, check.what))
    return results


def check_manifest(paths: Paths | None = None) -> Result:
    """Every file in the manifest still exists and matches its recorded SHA-256."""
    paths = paths or get_paths()
    what = "Raw files on disk match the checksums in the manifest"
    if not paths.manifest.exists():
        return Result("manifest_integrity", "FAIL", "SKIP", None, what)
    with paths.manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    bad = 0
    for row in rows:
        file = paths.raw / row["file"]
        if not file.exists():
            bad += 1
            continue
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        bad += digest.hexdigest() != row["sha256"]
    return Result("manifest_integrity", "FAIL", "PASS" if bad == 0 else "FAIL", bad, what)


def save_results(con: sqlite3.Connection, results: list[Result]) -> None:
    con.execute("DROP TABLE IF EXISTS validation_results")
    con.execute(
        "CREATE TABLE validation_results (name TEXT, severity TEXT, status TEXT, "
        "violations INTEGER, what TEXT, checked_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    con.executemany(
        "INSERT INTO validation_results (name, severity, status, violations, what) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r.name, r.severity, r.status, r.violations, r.what) for r in results],
    )
    con.commit()


def validate(paths: Paths | None = None) -> list[Result]:
    """Run every check against the warehouse and store the results in it."""
    paths = paths or get_paths()
    con = sqlite3.connect(paths.database)
    try:
        results = run_checks(con)
        results.append(check_manifest(paths))
        save_results(con, results)
    finally:
        con.close()
    return results


def has_failures(results: list[Result]) -> bool:
    return any(r.status == "FAIL" for r in results)
