import sqlite3

import pandas as pd
import pytest

from mortality import validate, warehouse
from mortality.config import Paths
from mortality.ingest import download


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


def deaths(file_year, rows):
    """rows: (occ_year, state, sex, age, n) -> row-level frame like the INEGI parquet."""
    records = []
    for occ_year, state, sex, age, n in rows:
        records += [
            {
                "file_year": file_year,
                "sex": sex,
                "age_unit": "years",
                "age_value": age,
                "age_years": age,
                "state": state,
                "resident_in_mexico": state not in ("33", "99"),
                "occ_year": occ_year,
                "occ_month": 3,
                "reg_year": file_year,
                "cause": "I219",
                "cause_list": "28",
            }
        ] * n
    return pd.DataFrame(records).astype(
        {"age_years": "Int64", "occ_year": "Int64", "occ_month": "Int64", "sex": "string"}
    )


def write_inegi(paths, file_year, rows):
    folder = paths.processed / "inegi"
    folder.mkdir(parents=True, exist_ok=True)
    deaths(file_year, rows).to_parquet(folder / f"deaths_{file_year}.parquet", index=False)


def write_conapo(paths, year=2023):
    folder = paths.processed / "conapo"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for state_code, state in ((0, "Rep"), (1, "Ags"), (2, "BC")):
        for sex in ("M", "F"):
            for age in range(110):
                pop = 100.0 if state_code else 200.0
                rows.append((year, state_code, state, sex, age, pop, True))
    cols = ["year", "state_code", "state", "sex", "age", "population", "is_projection"]
    pd.DataFrame(rows, columns=cols).to_parquet(folder / "population_mid_year.parquet")
    modelled = pd.DataFrame(
        {
            "year": [year, year],
            "state_code": [0, 1],
            "state": ["Rep", "Ags"],
            "sex": ["M", "M"],
            "age": [50, 50],
            "deaths": [10.0, 5.0],
            "is_projection": [True, True],
        }
    )
    modelled.to_parquet(folder / "deaths_modelled.parquet")


# ── aggregation ─────────────────────────────────────────────────────────────


def test_aggregate_inegi_counts_cells_and_keeps_unknowns():
    rows = deaths(2023, [(2023, "09", "M", 40, 3), (2022, "09", "F", 40, 1)])
    unknown = deaths(2023, [(2023, "09", "M", 40, 2)]).assign(
        sex=pd.NA, age_years=pd.array([pd.NA, pd.NA], dtype="Int64")
    )
    cells = warehouse.aggregate_inegi(pd.concat([rows, unknown], ignore_index=True))
    assert cells["deaths"].sum() == 6
    assert cells[cells.sex.isna()]["deaths"].sum() == 2
    assert "death_type" in cells.columns  # filled as missing when the file lacks it
    assert cells["death_type"].isna().all()


# ── build ───────────────────────────────────────────────────────────────────


def test_build_creates_tables_and_documents_them(paths):
    write_inegi(
        paths, 2023, [(2023, "09", "M", 40, 4), (2023, "09", "F", 40, 2), (2022, "01", "M", 60, 1)]
    )
    write_inegi(paths, 2024, [(2024, "09", "M", 40, 5), (2023, "09", "M", 41, 1)])
    write_conapo(paths)
    counts = warehouse.build(paths=paths)

    assert {"deaths_by_occurrence", "deaths_unallocated", "inegi_completeness", "dim_state"} <= set(
        counts
    )

    con = warehouse.connect(paths)
    total = con.execute("SELECT SUM(deaths) FROM inegi_deaths_cells").fetchone()[0]
    assert total == 4 + 2 + 1 + 5 + 1  # every death from both files is kept
    docs = dict(con.execute("SELECT table_name, description FROM table_docs").fetchall())
    assert set(docs) == set(counts)
    by_year = dict(
        con.execute("SELECT year, SUM(deaths) FROM deaths_by_occurrence GROUP BY year").fetchall()
    )
    assert by_year == {2022: 1, 2023: 7, 2024: 5}  # 2023: 4 + 2 + 1 late registered in 2024
    assert con.execute("SELECT state_code_text FROM dim_state WHERE state_code = 1").fetchone() == (
        "01",
    )


def test_build_creates_quality_tables_that_conserve_deaths(paths):
    rows = [(2023, "09", "M", a, 3) for a in range(20, 70)]
    rows += [(2023, "09", "F", a, 2) for a in range(20, 70)]
    rows += [(2023, "99", "M", 40, 4)]  # unknown state of residence: still counted nationally
    rows += [(2023, "33", "M", 40, 5)]  # lives abroad: left out
    write_inegi(paths, 2023, rows)
    warehouse.build(paths=paths)
    con = warehouse.connect(paths)
    total = con.execute("SELECT SUM(adjusted) FROM deaths_adjusted WHERE year = 2023").fetchone()[0]
    assert total == pytest.approx(3 * 50 + 2 * 50 + 4)
    names = {r[0] for r in con.execute("SELECT table_name FROM table_docs")}
    assert "deaths_adjusted" in names


def test_validate_checks_conservation_and_runs_clean_on_good_data(paths):
    rows = [(2023, "09", "M", a, 3) for a in range(20, 70)]
    write_inegi(paths, 2023, rows)
    warehouse.build(paths=paths)
    results = {r.name: r for r in validate.validate(paths)}
    assert results["adjusted_identity_holds"].status == "PASS"
    assert results["adjusted_keeps_every_reported_death"].status == "PASS"
    assert results["unknown_allocation_small"].status == "PASS"


def test_build_skips_missing_sources(paths):
    write_conapo(paths)
    counts = warehouse.build(paths=paths)
    assert "inegi_deaths_cells" not in counts and "hmd_deaths" not in counts
    assert counts["conapo_population"] == 3 * 2 * 110


def test_build_is_repeatable_and_atomic(paths, monkeypatch):
    write_conapo(paths)
    warehouse.build(paths=paths)
    first = paths.database.stat().st_size
    warehouse.build(paths=paths)
    assert paths.database.stat().st_size == first

    def explode(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(warehouse.pd, "read_parquet", explode)
    with pytest.raises(RuntimeError):
        warehouse.build(paths=paths)
    assert paths.database.stat().st_size == first  # old database untouched
    assert not paths.database.with_suffix(".sqlite.tmp").exists()


def test_connect_requires_a_built_warehouse(paths):
    with pytest.raises(FileNotFoundError):
        warehouse.connect(paths)


def test_connect_is_read_only(paths):
    write_conapo(paths)
    warehouse.build(paths=paths)
    with pytest.raises(sqlite3.OperationalError):
        warehouse.connect(paths).execute("DROP TABLE conapo_population")


def test_completeness_needs_own_file_and_next_file(paths):
    write_inegi(paths, 2023, [(2023, "09", "M", 40, 3), (2022, "09", "M", 40, 1)])
    write_inegi(paths, 2024, [(2024, "09", "M", 40, 3)])
    warehouse.build(paths=paths)
    rows = {
        r[0]: r[1:]
        for r in warehouse.connect(paths).execute(
            "SELECT year, file_loaded, next_file_loaded, complete FROM inegi_completeness"
        )
    }
    assert rows[2022] == (0, 1, 0)  # its own file is missing, so not complete
    assert rows[2023] == (1, 1, 1)
    assert rows[2024] == (1, 0, 0)  # latest year: still waiting for the 2025 file


# ── validation ──────────────────────────────────────────────────────────────


def status(results):
    return {r.name: r.status for r in results}


def test_validate_flags_the_known_gaps(paths):
    write_inegi(paths, 2024, [(2024, "09", "M", 40, 3)])
    write_conapo(paths, 2024)
    warehouse.build(paths=paths)
    results = status(validate.validate(paths))
    assert results["inegi_state_codes"] == "PASS"
    assert results["conapo_complete_grid"] == "PASS"
    assert results["inegi_pre_covid_single_ages"] == "WARN"
    assert results["inegi_latest_year_complete"] == "WARN"
    assert results["hmd_keys_unique"] == "SKIP"  # no HMD data in this tiny warehouse


def test_validate_catches_bad_inegi_values(paths):
    write_inegi(
        paths, 2024, [(2024, "09", "M", 40, 3), (2024, "77", "F", 30, 2), (2024, "09", "X", 30, 1)]
    )
    warehouse.build(paths=paths)
    results = {r.name: r for r in validate.validate(paths)}
    assert (
        results["inegi_state_codes"].status == "FAIL"
        and results["inegi_state_codes"].violations == 2
    )
    assert (
        results["inegi_sex_values"].status == "FAIL" and results["inegi_sex_values"].violations == 1
    )
    assert validate.has_failures(list(results.values()))


def test_validate_catches_impossible_ages_and_dates(paths):
    write_inegi(paths, 2024, [(2024, "09", "M", 130, 2), (2025, "09", "M", 40, 1)])
    warehouse.build(paths=paths)
    results = {r.name: r for r in validate.validate(paths)}
    assert results["inegi_age_range"].violations == 2
    assert (
        results["inegi_dates_plausible"].violations == 1
    )  # died in 2025 but recorded in the 2024 file


def test_validate_stores_results_in_the_warehouse(paths):
    write_conapo(paths)
    warehouse.build(paths=paths)
    validate.validate(paths)
    rows = (
        warehouse.connect(paths).execute("SELECT name, status FROM validation_results").fetchall()
    )
    assert ("manifest_integrity", "SKIP") in rows
    assert len(rows) == len(validate.CHECKS) + 1


def test_manifest_integrity_detects_changed_files(paths):
    folder = paths.raw / "demo"
    folder.mkdir(parents=True)
    file = folder / "a.txt"
    file.write_text("hello")
    download.register_local(file, source="demo", url="https://example.org/a", paths=paths)
    assert validate.check_manifest(paths).status == "PASS"
    file.write_text("tampered")
    result = validate.check_manifest(paths)
    assert result.status == "FAIL" and result.violations == 1
    file.unlink()
    assert validate.check_manifest(paths).violations == 1


def test_all_check_sql_is_valid(paths):
    """Every check must execute without SQL errors, even on an empty-but-complete schema."""
    con = sqlite3.connect(":memory:")
    schemas = {
        warehouse.INEGI_TABLE: (
            "file_year, occ_year, occ_month, state, resident_in_mexico, sex, age_years, "
            "death_type, deaths"
        ),
        "inegi_completeness": (
            "year, deaths, last_file_year, complete, next_file_loaded, file_loaded"
        ),
        "inegi_cube_registered": "reg_year, age_lo, sex, deaths",
        "registration_completion": "occ_year, band, factor",
        "deaths_adjusted": (
            "year, sex, age, reported, added_late_registration, added_unknown_sex, "
            "added_unknown_age, added_unknown_both, adjusted"
        ),
        "quality_age_heaping": "dataset, year, sex, whipple",
        "deaths_by_occurrence": "year, state_code_text, sex, age, deaths",
        "conapo_population": "year, state_code, state, sex, age, population",
        "conapo_deaths": "year, state_code, sex, age, deaths",
        "hmd_deaths": "country, year, age, sex, value",
        "hmd_exposures": "country, year, age, sex, value",
        "hmd_life_tables": "country, sex, year, age, qx",
        "soa_rates": "table_id, sub_table, age, rate",
        "soa_catalog": 'table_id, "group"',
        "cnsf_rates": '"table", variant, age, qx',
    }
    for name, cols in schemas.items():
        con.execute(f'CREATE TABLE "{name}" ({cols})')
    results = validate.run_checks(con)
    assert all(r.status in ("PASS", "WARN", "FAIL") for r in results)  # none skipped, none crashed
