"""The demo bundle: a small, shareable slice of the warehouse for the dashboard.

The full warehouse is 170 MB and holds data that must not be redistributed (the Human Mortality
Database forbids it) or that is simply large (every INEGI death cell, CONAPO's population). The
dashboard needs neither: it needs the *results*. ``build_bundle`` copies an explicit list of derived
tables into ``app/data/demo.sqlite``, drops every row that comes from the HMD, and writes the two
small files the live labs need: the in-force block of the synthetic portfolio and a 40,000-policy
sample extract to try the experience study on.

An allow-list, not a block-list: a table added to the warehouse later does not end up in a public
repository unless someone decides it should.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from mortality import experience as ex
from mortality import portfolio as pf

# Derived tables the dashboard reads. Nothing here is raw microdata or HMD data.
BUNDLE_TABLES: tuple[str, ...] = (
    # data and quality
    "table_docs", "validation_results", "source_manifest", "inegi_cube_registered",
    "inegi_completeness", "deaths_adjusted", "year_flags", "deaths_by_cause_chapter",
    "registration_completion", "registration_factors", "registration_triangle",
    "registration_tail", "quality_age_heaping", "basis_bridge", "source_gap", "dim_state",
    # rates, graduation, life tables
    "crude_rates_grouped", "crude_rates_single", "age_standardised_rates", "state_smr",
    "benchmark_ae", "graduated_qx", "graduated_rates", "graduation_fit_tests", "life_tables",
    "life_summary", "commutation_columns", "actuarial_values", "life_table_comparison",
    "conapo_life_expectancy",
    # benchmarks that are public: CNSF regulation and SOA tables
    "cnsf_rates", "soa_catalog", "soa_rates",
    # projection
    "projected_qx", "projection_scenarios", "projection_parameters", "projection_backtest",
    "projection_calibration", "projection_r_crosscheck", "cohort_tables",
    # experience study (synthetic portfolio)
    "experience_overview", "experience_dq_checks", "experience_dq_reconciliation", "experience_ae",
    "experience_ae_age_sex", "experience_ae_covid", "experience_ae_quarterly",
    "experience_credibility", "experience_relativities", "experience_recovery",
    "experience_select", "experience_claims_lag", "experience_basis", "experience_pricing",
    "experience_impact", "experience_lag_validation", "experience_truth",
    "experience_injected_defects",
    # applications
    "excess_baselines", "excess_mortality", "excess_summary", "excess_monthly",
    "excess_by_cause", "excess_state",
    "pricing_premiums", "pricing_adequacy", "pricing_profit_test", "pricing_sensitivity",
    "pricing_reserves", "pricing_insured",
    "stress_pandemic_book", "stress_pandemic_age", "stress_longevity", "stress_hedge",
    "reinsurance_concentration", "reinsurance_aggregate", "reinsurance_structures",
    "reinsurance_frontier", "reinsurance_price_sensitivity", "reinsurance_yrt_rating",
    "reinsurance_longevity_swap", "reinsurance_longevity_distribution",
    # insured lives (version 2): aggregated CNSF statistics; the filters below drop HMD rows
    "insured_table", "insured_crude", "insured_pooled", "insured_methods", "insured_graduated",
    "insured_fit_tests", "insured_trend", "insured_relativities", "insured_comparison",
    "insured_premiums", "insured_gap", "insured_brass", "insured_improvement",
    "insured_pandemic", "insured_amount", "insured_market", "insured_causes", "insured_ledger",
    "insured_rules", "insured_sensitivity", "insured_margin", "insured_legacy",
    "insured_legacy_mix",
)  # fmt: skip

# Tables copied with some rows removed: (table, column, value to drop, case-insensitive)
ROW_FILTERS = {
    "life_table_comparison": ("source", "HMD"),
    "source_manifest": ("source", "hmd"),
    "insured_comparison": ("group", "HMD national"),
    "insured_brass": ("group", "HMD national"),
    # the US insured table over the US national table: a ratio built from HMD rates
    "insured_gap": ("comparison", "US: 2017 Unloaded CSO / national table"),
}

SAMPLE_POLICIES = 40_000
SAMPLE_SEED = 7

INFORCE_COLUMNS = ["sex", "attained_age", "duration", "years_left", "product", "sum_assured"]


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, name: str) -> int:
    df = pd.read_sql(f'SELECT * FROM "{name}"', src)
    if name in ROW_FILTERS:
        column, value = ROW_FILTERS[name]
        keep = ~df[column].astype(str).str.lower().eq(value.lower())
        df = df[keep]
    df.to_sql(name, dst, if_exists="replace", index=False)
    return len(df)


def build_sample_extract(
    q_basis: pd.Series, state_smr: dict, weights: dict, n: int = SAMPLE_POLICIES
) -> pd.DataFrame:
    """A small synthetic policy extract in the format ``mortality experience run`` reads."""
    codes = tuple(sorted(weights))
    spec = pf.PortfolioSpec(
        n_policies=n, seed=SAMPLE_SEED, q_basis=q_basis.to_numpy(), state_codes=codes,
        state_weights=tuple(weights[c] for c in codes), state_smr=state_smr,
    )  # fmt: skip
    return pf.generate_portfolio(spec).policies


def build_bundle(warehouse: Path, out_dir: Path, portfolio_policies: pd.DataFrame) -> dict:
    """Write ``demo.sqlite``, ``inforce.parquet`` and ``sample_policies.csv`` into ``out_dir``.

    Returns the rows copied per table. ``portfolio_policies`` is the full synthetic portfolio
    (its in-force block at the study end becomes the block of the reinsurance lab)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "demo.sqlite"
    target.unlink(missing_ok=True)
    src = sqlite3.connect(warehouse)
    dst = sqlite3.connect(target)
    counts: dict[str, int] = {}
    try:
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for name in BUNDLE_TABLES:
            if name in have:
                counts[name] = _copy_table(src, dst, name)
        dst.commit()
        inputs = ex.warehouse_inputs(src)
    finally:
        src.close()
        dst.execute("VACUUM")
        dst.close()
    clean = ex.validate_extract(portfolio_policies, pf.STUDY_END, pf.EXTRACT_DATE)[0]
    block = ex.inforce_block(clean, pf.STUDY_END)[INFORCE_COLUMNS].copy()
    block["product"] = block["product"].astype(str)
    block["sex"] = block["sex"].astype(str)
    block.to_parquet(out_dir / "inforce.parquet", compression="zstd", index=False)
    if inputs is not None:
        q, state_smr, weights = inputs
        sample = build_sample_extract(q, state_smr, weights)
        for column in ex.DATE_COLUMNS:
            sample[column] = pd.to_datetime(sample[column]).dt.strftime("%Y-%m-%d")
        sample.to_csv(out_dir / "sample_policies.csv", index=False)
    counts["inforce"] = len(block)
    return counts


def forbidden_in(path: Path) -> list[str]:
    """Names of tables in a bundle that should never be there (HMD, raw microdata cells)."""
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    finally:
        con.close()
    bad = (
        "hmd_",
        "benchmark_countries",
        "insured_matches",  # the closest national table: HMD rates by country and year
        "inegi_deaths_cells",
        "conapo_population",
        "conapo_deaths",
    )
    return [n for n in names if n.startswith(bad)]


def hmd_rows_in(path: Path) -> int:
    """Rows in the bundle that still carry the HMD as a source."""
    con = sqlite3.connect(path)
    try:
        total = 0
        for table, (column, value) in ROW_FILTERS.items():
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
            if table in names:
                total += con.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE LOWER("{column}") = ?', (value.lower(),)
                ).fetchone()[0]
        return int(total)
    finally:
        con.close()


def sample_has_deaths(path: Path) -> int:
    """Deaths in the sample extract (a check that it is usable for a study)."""
    df = pd.read_csv(path, usecols=["status"])
    return int(np.sum(df["status"] == "DEATH"))
