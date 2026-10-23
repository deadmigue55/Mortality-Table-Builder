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


def _cnsf_vi_control_sql() -> str:
    """Count the (year, sheet, column) totals that differ from the raw control totals."""
    from mortality.ingest.cnsf_vi import SHEETS

    parts = [
        f"SELECT year, '{s.sheet}' AS sheet, '{col}' AS col, COUNT(*) AS n,"
        f" COALESCE(SUM({col}), 0) AS total FROM cnsf_vi_{s.table} GROUP BY year"
        for s in SHEETS
        for col in (*s.counts, *s.amounts)
    ]
    return (
        "SELECT COUNT(*) FROM cnsf_vi_control c LEFT JOIN ("
        + " UNION ALL ".join(parts)
        + ') w ON w.year = c.year AND w.sheet = c.sheet AND w.col = c."column"'
        " WHERE c.format = 'xlsx' AND substr(c.\"column\", 1, 1) <> '_'"
        " AND (w.total IS NULL OR w.n <> c.rows"
        "      OR ABS(w.total - c.total) > 1e-7 * MAX(1, ABS(c.total)))"
    )


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
        "inegi_pre_covid_single_ages",
        "WARN",
        (INEGI_TABLE,),
        "SELECT CASE WHEN COALESCE(SUM(deaths) FILTER (WHERE occ_year BETWEEN 2015 AND 2019), 0) "
        f"> 1000000 THEN 0 ELSE 1 END FROM {INEGI_TABLE}",
        "Single-year-of-age deaths exist for 2015-2019 (row-level files, not just 5-year groups)",
    ),
    Check(
        "inegi_pre_covid_grouped_baseline",
        "WARN",
        ("inegi_cube_registered",),
        "SELECT CASE WHEN COUNT(DISTINCT reg_year) >= 4 THEN 0 ELSE 1 END"
        " FROM inegi_cube_registered WHERE reg_year BETWEEN 2015 AND 2019",
        "At least 4 of the 5 pre-COVID years (2015-2019) exist as five-year-group tables",
    ),
    Check(
        "inegi_latest_year_complete",
        "WARN",
        ("inegi_completeness",),
        "SELECT COUNT(*) FROM inegi_completeness WHERE complete = 0 "
        "AND year = (SELECT MAX(last_file_year) FROM inegi_completeness)",
        "The latest year is complete: its file and the next one (late registrations) are loaded",
    ),
    Check(
        "inegi_cube_no_year_gaps",
        "WARN",
        ("inegi_cube_registered", INEGI_TABLE),
        "WITH have(y) AS (SELECT reg_year FROM inegi_cube_registered"
        f" UNION SELECT file_year FROM {INEGI_TABLE}),"
        " span(y) AS (SELECT MIN(y) FROM have"
        " UNION ALL SELECT y + 1 FROM span WHERE y < (SELECT MAX(y) FROM have))"
        " SELECT COUNT(*) FROM span WHERE y NOT IN (SELECT y FROM have)",
        "Registered deaths exist for every year between the first and last (tables + microdata)",
    ),
    Check(
        "inegi_cube_complete_age_groups",
        "FAIL",
        ("inegi_cube_registered",),
        "SELECT COUNT(*) FROM (SELECT reg_year FROM inegi_cube_registered"
        " WHERE age_lo IS NOT NULL GROUP BY reg_year HAVING COUNT(DISTINCT age_lo) <> 19)",
        "Each imported year has all 19 age groups (under 1, 1-4, 5-9, ... 85 and over)",
    ),
    Check(
        "adjusted_identity_holds",
        "FAIL",
        ("deaths_adjusted",),
        "SELECT COUNT(*) FROM deaths_adjusted WHERE ABS(reported + added_late_registration"
        " + added_unknown_sex + added_unknown_age + added_unknown_both - adjusted) > 0.000001"
        " OR added_late_registration < -0.000001",
        "Adjusted deaths = reported + late registrations + allocated unknowns, with no negatives",
    ),
    Check(
        "adjusted_keeps_every_reported_death",
        "FAIL",
        ("deaths_adjusted", INEGI_TABLE),
        "SELECT COUNT(*) FROM (SELECT a.year FROM"
        " (SELECT year, SUM(adjusted) AS s FROM deaths_adjusted GROUP BY year) a"
        f" JOIN (SELECT occ_year AS year, SUM(deaths) AS s FROM {INEGI_TABLE}"
        "  WHERE occ_year IS NOT NULL AND (state BETWEEN '01' AND '32' OR state = '99')"
        "  GROUP BY occ_year) c ON c.year = a.year"
        " WHERE a.s < c.s - 0.5)",
        "Every reported death in scope is still counted after the adjustments",
    ),
    Check(
        "late_registration_completion_is_modest",
        "WARN",
        ("deaths_adjusted",),
        "SELECT COUNT(*) FROM (SELECT year FROM deaths_adjusted GROUP BY year"
        " HAVING SUM(added_late_registration) / SUM(reported) > 0.05)",
        "Completing late registrations adds under 5% to any year",
    ),
    Check(
        "unknown_allocation_small",
        "WARN",
        ("deaths_adjusted",),
        "SELECT COUNT(*) FROM (SELECT year FROM deaths_adjusted GROUP BY year"
        " HAVING SUM(added_unknown_sex + added_unknown_age + added_unknown_both)"
        " / SUM(adjusted) > 0.02)",
        "Allocated unknowns are under 2% of deaths in each year with its own file",
    ),
    Check(
        "inegi_age_heaping_low",
        "WARN",
        ("quality_age_heaping",),
        "SELECT COUNT(*) FROM quality_age_heaping "
        "WHERE dataset = 'INEGI deaths' AND whipple >= 110",
        "INEGI deaths have no more than 'fairly accurate' age heaping (Whipple under 110)",
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
    # ── CNSF individual life statistics ─────────────────────────────────────
    Check(
        "cnsf_vi_years_complete",
        "FAIL",
        ("cnsf_vi_exposure", "cnsf_vi_issued", "cnsf_vi_claims"),
        "SELECT 15"
        " - (SELECT COUNT(DISTINCT year) FROM cnsf_vi_exposure WHERE year BETWEEN 2021 AND 2025)"
        " - (SELECT COUNT(DISTINCT year) FROM cnsf_vi_issued WHERE year BETWEEN 2021 AND 2025)"
        " - (SELECT COUNT(DISTINCT year) FROM cnsf_vi_claims WHERE year BETWEEN 2021 AND 2025)",
        "Exposure, issue and claim sheets exist for every year 2021 to 2025",
    ),
    Check(
        "cnsf_vi_control_reconciles",
        "FAIL",
        ("cnsf_vi_exposure", "cnsf_vi_issued", "cnsf_vi_claims", "cnsf_vi_control"),
        _cnsf_vi_control_sql(),
        "Row counts and column totals in the warehouse equal the totals summed from the raw cells",
    ),
    Check(
        "cnsf_vi_numbers_parse",
        "FAIL",
        ("cnsf_vi_control",),
        "SELECT COALESCE(SUM(non_numeric), 0) FROM cnsf_vi_control",
        "Every count and amount cell in the CNSF workbooks is a number",
    ),
    Check(
        "cnsf_vi_labels_recognised",
        "WARN",
        ("cnsf_vi_control",),
        "SELECT COALESCE(SUM(total), 0) FROM cnsf_vi_control"
        " WHERE \"column\" IN ('_unexpected_sex', '_unexpected_age')",
        "Sex and age cells hold a known label, a whole age or 'No disponible'",
    ),
    Check(
        "cnsf_vi_age_range",
        "FAIL",
        ("cnsf_vi_exposure", "cnsf_vi_claims"),
        "SELECT (SELECT COUNT(*) FROM cnsf_vi_exposure WHERE age < 0 OR age > 125)"
        " + (SELECT COUNT(*) FROM cnsf_vi_claims WHERE age < 0 OR age > 125)",
        "Ages of insured lives and claims are between 0 and 125",
    ),
    Check(
        "cnsf_vi_exposure_positive",
        "FAIL",
        ("cnsf_vi_exposure",),
        "SELECT COUNT(*) FROM cnsf_vi_exposure WHERE insured < 0",
        "The number of insured lives is never negative",
    ),
    Check(
        "cnsf_vi_exposure_matches_issue",
        "WARN",
        ("cnsf_vi_exposure", "cnsf_vi_issued"),
        "SELECT COUNT(*) FROM ("
        " SELECT e.year FROM (SELECT year, SUM(insured) AS n FROM cnsf_vi_exposure GROUP BY year) e"
        " JOIN (SELECT year, SUM(insured) AS n FROM cnsf_vi_issued"
        "       WHERE coverage = 'Fallecimiento' GROUP BY year) i ON i.year = e.year"
        " WHERE e.n / i.n < 0.8 OR e.n / i.n > 1.3)",
        "Insured lives in the exposure sheet are within 20% to 30% of those with a death cover",
    ),
    Check(
        "cnsf_vi_deaths_below_exposure",
        "FAIL",
        ("cnsf_vi_exposure", "cnsf_vi_claims"),
        "SELECT COUNT(*) FROM ("
        " SELECT c.year, c.age, c.sex, SUM(c.claims) AS d FROM cnsf_vi_claims c"
        " WHERE c.coverage = 'Fallecimiento' AND c.age IS NOT NULL AND c.sex IS NOT NULL"
        " GROUP BY c.year, c.age, c.sex) d"
        " LEFT JOIN (SELECT year, age, sex, SUM(insured) AS n FROM cnsf_vi_exposure"
        "            GROUP BY year, age, sex) e"
        " ON e.year = d.year AND e.age = d.age AND e.sex = d.sex"
        " WHERE e.n IS NULL OR d.d > e.n",
        "In every year, age and sex there are no more death claims than insured lives",
    ),
    Check(
        "cnsf_vi_no_detail_rows_are_a_ledger",
        "WARN",
        ("cnsf_vi_claims",),
        "SELECT COUNT(*) FROM ("
        " SELECT year FROM cnsf_vi_claims WHERE coverage = 'Fallecimiento' GROUP BY year"
        " HAVING SUM(CASE WHEN (age IS NULL OR sex IS NULL) AND amount_claimed > 0 THEN claims"
        "                 WHEN (age IS NULL OR sex IS NULL) AND amount_claimed < 0 THEN -claims"
        "                 ELSE 0 END)"
        "        > 0.1 * SUM(CASE WHEN age IS NOT NULL AND sex IS NOT NULL"
        "                              AND amount_claimed > 0 THEN claims ELSE 0 END))",
        "Death-claim rows without age or sex net to almost no new claims (new minus cancelled "
        "is under 10% of the known claims), so they are excluded as an adjustment ledger",
    ),
    Check(
        "cnsf_vi_reversals_are_small",
        "WARN",
        ("cnsf_vi_claims",),
        "SELECT COUNT(*) FROM ("
        " SELECT year FROM cnsf_vi_claims WHERE coverage = 'Fallecimiento'"
        "  AND age IS NOT NULL AND sex IS NOT NULL GROUP BY year"
        " HAVING SUM(CASE WHEN amount_claimed < 0 THEN claims ELSE 0 END)"
        "        > 0.1 * SUM(CASE WHEN amount_claimed > 0 THEN claims ELSE 0 END))",
        "Cancelled death claims (negative claimed amount) are under 10% of the known claims",
    ),
    # ── Insured-lives tables ────────────────────────────────────────────────
    Check(
        "insured_table_complete",
        "FAIL",
        ("insured_table",),
        "SELECT COUNT(*) FROM (SELECT segment, sex FROM insured_table GROUP BY segment, sex"
        " HAVING COUNT(*) <> 111 OR MIN(age) <> 0 OR MAX(age) <> 110"
        "  OR MIN(qx) < 0 OR MAX(qx) > 1"
        "  OR MAX(CASE WHEN age = 110 THEN qx END) <> 1)",
        "Every insured table has ages 0 to 110, probabilities in [0, 1] and q = 1 at 110",
    ),
    Check(
        "insured_old_ages_rise",
        "FAIL",
        ("insured_table",),
        "SELECT COUNT(*) FROM insured_table a JOIN insured_table b"
        " ON b.segment = a.segment AND b.sex = a.sex AND b.age = a.age + 1"
        " WHERE a.age >= 85 AND b.qx < a.qx - 1e-12",
        "From age 85 the insured mortality never falls with age",
    ),
    Check(
        "insured_never_above_population",
        "FAIL",
        ("insured_table",),
        "SELECT COUNT(*) FROM insured_table WHERE age BETWEEN 18 AND 109"
        " AND qx > q_population * 1.0001",
        "Insured mortality is never above the population's (selection and underwriting)",
    ),
    Check(
        "insured_below_cnsf_at_working_ages",
        "WARN",
        ("insured_table",),
        "SELECT COUNT(*) FROM insured_table WHERE segment = 'all' AND age BETWEEN 25 AND 60"
        " AND qx > q_cnsf2013",
        "The market insured table is below the regulatory table CNSF 2013 at ages 25 to 60",
    ),
    Check(
        "insured_women_below_men",
        "WARN",
        ("insured_table",),
        "SELECT COUNT(*) FROM insured_table f JOIN insured_table m"
        " ON m.segment = f.segment AND m.age = f.age AND m.sex = 'M'"
        " WHERE f.sex = 'F' AND f.age BETWEEN 18 AND 85 AND f.qx > m.qx",
        "Women's insured mortality is not above men's between ages 18 and 85",
    ),
    Check(
        "insured_blend_between_parts",
        "FAIL",
        ("insured_table",),
        "SELECT COUNT(*) FROM insured_table a JOIN ("
        " SELECT sex, age, MIN(qx) AS lo, MAX(qx) AS hi FROM insured_table"
        " WHERE segment IN ('term_traditional', 'credit', 'term_other', 'permanent')"
        " GROUP BY sex, age) p ON p.sex = a.sex AND p.age = a.age"
        " WHERE a.segment = 'all' AND (a.qx < p.lo - 1e-12 OR a.qx > p.hi + 1e-12)",
        "The market table lies between its product tables at every sex and age",
    ),
    Check(
        "insured_partition_adds_up",
        "FAIL",
        ("insured_crude",),
        "SELECT COUNT(*) FROM ("
        " SELECT year,"
        "  SUM(CASE WHEN segment = 'all' THEN deaths END) AS a,"
        "  SUM(CASE WHEN segment IN ('term_traditional', 'credit', 'term_other', 'permanent')"
        "      THEN deaths END) AS p"
        " FROM insured_crude GROUP BY year"
        " HAVING p > a + 1e-6 OR p < 0.95 * a)",
        "The four products hold 95% to 100% of the market's deaths in every year",
    ),
    Check(
        "insured_death_readings_are_ordered",
        "FAIL",
        ("insured_rules",),
        "SELECT COUNT(*) FROM ("
        " SELECT year,"
        "  MAX(CASE WHEN rule = 'net' THEN deaths END) AS n,"
        "  MAX(CASE WHEN rule = 'base' THEN deaths END) AS b,"
        "  MAX(CASE WHEN rule = 'plus_positive' THEN deaths END) AS pp,"
        "  MAX(CASE WHEN rule = 'plus_all' THEN deaths END) AS pa"
        " FROM insured_rules GROUP BY year"
        " HAVING NOT (n <= b AND b <= pp AND pp <= pa))",
        "Deaths rise from the net reading to the base, the positive and the all-rows readings",
    ),
    Check(
        "insured_premiums_rise_with_age",
        "FAIL",
        ("insured_premiums",),
        "SELECT COUNT(*) FROM insured_premiums a JOIN insured_premiums b"
        ' ON b."table" = a."table" AND b.sex = a.sex AND b.term = a.term'
        " AND b.issue_age = a.issue_age + 5"
        " WHERE b.premium_per_1000 < a.premium_per_1000",
        "Net term premiums rise with issue age on every table",
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
    # ── Rates ───────────────────────────────────────────────────────────────
    Check(
        "rates_single_conserve_deaths",
        "FAIL",
        ("crude_rates_single", "deaths_adjusted"),
        "SELECT COUNT(*) FROM ("
        " SELECT a.year FROM (SELECT year, SUM(adjusted) AS n FROM deaths_adjusted"
        "   GROUP BY year) a"
        " JOIN (SELECT year, SUM(deaths) AS n FROM crude_rates_single GROUP BY year) r"
        "   ON r.year = a.year"
        " WHERE ABS(a.n - r.n) > 0.5)",
        "Single-age rates use every adjusted death (pooling the open age loses none)",
    ),
    Check(
        "rates_grouped_conserve_deaths",
        "FAIL",
        ("crude_rates_grouped", "inegi_cube_registered"),
        "SELECT COUNT(*) FROM ("
        " SELECT c.reg_year FROM (SELECT reg_year, SUM(deaths) AS n FROM inegi_cube_registered"
        "   GROUP BY reg_year) c"
        " JOIN (SELECT year, SUM(deaths) AS n FROM crude_rates_grouped"
        "   WHERE sex = 'T' AND basis = 'registration' GROUP BY year) r ON r.year = c.reg_year"
        " WHERE ABS(c.n - r.n) > 0.5)",
        "Grouped rates before 2020 use every registered death, after allocating unknowns",
    ),
    Check(
        "rates_exposure_matches_conapo",
        "FAIL",
        ("crude_rates_single", "conapo_population"),
        "SELECT COUNT(*) FROM ("
        " SELECT r.year FROM (SELECT year, SUM(exposure) AS n FROM crude_rates_single"
        "   GROUP BY year) r"
        " JOIN (SELECT year, SUM(population) AS n FROM conapo_population WHERE state_code = 0"
        "   GROUP BY year) p ON p.year = r.year"
        " WHERE ABS(p.n - r.n) > 1)",
        "Exposure in the rates equals CONAPO's national population (nobody added or lost)",
    ),
    Check(
        "rates_intervals_bracket_estimate",
        "FAIL",
        ("crude_rates_single", "crude_rates_grouped"),
        "SELECT (SELECT COUNT(*) FROM crude_rates_single"
        "        WHERE mx < mx_lower - 1e-12 OR mx > mx_upper + 1e-12)"
        " + (SELECT COUNT(*) FROM crude_rates_grouped"
        "        WHERE mx < mx_lower - 1e-12 OR mx > mx_upper + 1e-12)",
        "Every 95% interval contains its own estimate",
    ),
    Check(
        "rates_are_rates",
        "FAIL",
        ("crude_rates_single",),
        "SELECT COUNT(*) FROM crude_rates_single "
        "WHERE mx < 0 OR mx > 1 OR (qx IS NOT NULL AND (qx < 0 OR qx > 1))",
        "Central rates and probabilities of death are between 0 and 1",
    ),
    Check(
        "rates_thin_cells_only_at_the_extremes",
        "WARN",
        ("crude_rates_single",),
        "SELECT COUNT(*) FROM crude_rates_single WHERE credible = 0 AND age BETWEEN 1 AND 95",
        "Single-age cells have at least 30 deaths between ages 1 and 95 (thin cells need grouping)",
    ),
    Check(
        "registration_basis_matches_occurrence",
        "WARN",
        ("basis_bridge",),
        "SELECT COUNT(*) FROM basis_bridge WHERE occurred_adjusted IS NOT NULL "
        "AND registered IS NOT NULL AND ABS(registered_to_occurred - 1) > 0.03",
        "Registered and occurred deaths are within 3% in every year where both exist, so "
        "registration-year rates before 2020 are a fair baseline",
    ),
    Check(
        "state_smr_balances",
        "FAIL",
        ("state_smr",),
        "SELECT CASE WHEN ABS(SUM(observed) - SUM(expected)) < 0.001 * SUM(observed) "
        "THEN 0 ELSE 1 END FROM state_smr",
        "State expected deaths add up to the observed total (SMRs are relative to the nation)",
    ),
    # ── Graduation ──────────────────────────────────────────────────────────
    Check(
        "graduated_table_complete",
        "FAIL",
        ("graduated_qx",),
        "SELECT COUNT(*) FROM (SELECT year, sex FROM graduated_qx GROUP BY year, sex"
        " HAVING COUNT(*) <> 111 OR MIN(age) <> 0 OR MAX(age) <> 110"
        " OR MAX(CASE WHEN age = 110 THEN qx END) <> 1)",
        "Every year and sex has a table for ages 0 to 110 that closes with q = 1 at 110",
    ),
    Check(
        "graduated_rates_are_probabilities",
        "FAIL",
        ("graduated_qx",),
        "SELECT COUNT(*) FROM graduated_qx WHERE qx < 0 OR qx > 1 OR mx <= 0",
        "Graduated q is a probability and m is positive",
    ),
    Check(
        "graduated_q_increases_from_35",
        "FAIL",
        ("graduated_qx",),
        "SELECT COUNT(*) FROM graduated_qx a JOIN graduated_qx b"
        " ON a.year = b.year AND a.sex = b.sex AND a.age = b.age + 1"
        " WHERE a.age BETWEEN 36 AND 110 AND a.qx <= b.qx",
        "q rises with every year of age from 35 to 110 (the young-adult hump is allowed to dip)",
    ),
    Check(
        "graduated_men_at_least_women",
        "FAIL",
        ("graduated_qx",),
        "SELECT COUNT(*) FROM graduated_qx m JOIN graduated_qx f"
        " ON m.year = f.year AND m.age = f.age"
        " WHERE m.sex = 'M' AND f.sex = 'F' AND m.mx < f.mx - 1e-12",
        "Graduated male rates are never below female rates at the same age",
    ),
    Check(
        "graduated_spline_conserves_deaths",
        "FAIL",
        ("graduated_rates", "crude_rates_single"),
        "SELECT COUNT(*) FROM (SELECT g.year, g.sex FROM graduated_rates g"
        " JOIN crude_rates_single c ON c.year = g.year AND c.sex = g.sex AND c.age = g.age"
        " WHERE g.method = 'pspline' GROUP BY g.year, g.sex"
        " HAVING ABS(SUM(c.exposure * g.mx) - SUM(c.deaths)) > 0.001 * SUM(c.deaths))",
        "The P-spline fit reproduces total deaths at ages 1 to 89 to within 0.1%",
    ),
    Check(
        "graduated_spline_tracks_the_crude",
        "WARN",
        ("graduation_fit_tests",),
        "SELECT COUNT(*) FROM graduation_fit_tests"
        " WHERE method = 'pspline' AND share_beyond_2 > 0.15",
        "Fewer than 15% of P-spline standardised residuals fall beyond 2 (4.6% for a perfect fit)",
    ),
    Check(
        "crude_old_age_sex_order",
        "WARN",
        ("crude_rates_single",),
        "SELECT COUNT(*) FROM crude_rates_single f JOIN crude_rates_single m"
        " ON m.year = f.year AND m.age = f.age"
        " WHERE f.sex = 'F' AND m.sex = 'M' AND f.age BETWEEN 85 AND 99 AND f.mx > m.mx",
        "Crude male rates exceed female rates at ages 85 to 99 (women overtaking men points to "
        "overstated age among the oldest men; the graduated table corrects it)",
    ),
    # ── Life tables and actuarial functions ─────────────────────────────────
    Check(
        "life_tables_complete",
        "FAIL",
        ("life_tables",),
        "SELECT COUNT(*) FROM (SELECT year, sex FROM life_tables GROUP BY year, sex"
        " HAVING COUNT(*) <> 111 OR MAX(CASE WHEN age = 0 THEN lx END) <> 100000"
        " OR MAX(CASE WHEN age = 110 THEN qx END) <> 1)",
        "Every year and sex (M, F, T) has a table for ages 0 to 110 with a radix of 100,000",
    ),
    Check(
        "life_table_deaths_add_up",
        "FAIL",
        ("life_tables",),
        "SELECT COUNT(*) FROM (SELECT year, sex FROM life_tables GROUP BY year, sex"
        " HAVING ABS(SUM(dx) - 100000) > 0.001)",
        "Deaths in the table add up to the radix (everyone dies by age 110)",
    ),
    Check(
        "life_table_expectancy_identity",
        "FAIL",
        ("life_tables",),
        "SELECT COUNT(*) FROM life_tables WHERE age = 0"
        " AND ABS(ex - total_person_years / lx) > 1e-9",
        "Life expectancy at birth equals T(0) / l(0)",
    ),
    Check(
        "life_table_reproduces_graduated_q",
        "FAIL",
        ("life_tables", "graduated_qx"),
        "SELECT COUNT(*) FROM life_tables t JOIN graduated_qx g"
        " ON g.year = t.year AND g.sex = t.sex AND g.age = t.age"
        " WHERE ABS(t.qx - g.qx) > 1e-12",
        "The male and female life tables use exactly the graduated probabilities of death",
    ),
    Check(
        "life_expectancy_women_above_men",
        "FAIL",
        ("life_summary",),
        "SELECT COUNT(*) FROM life_summary m JOIN life_summary f ON f.year = m.year"
        " WHERE m.sex = 'M' AND f.sex = 'F' AND (f.e0 <= m.e0 OR f.e65 <= m.e65)",
        "Women outlive men at birth and at 65 in every year",
    ),
    Check(
        "life_expectancy_both_sexes_between",
        "FAIL",
        ("life_summary",),
        "SELECT COUNT(*) FROM life_summary t JOIN life_summary m"
        " ON m.year = t.year AND m.sex = 'M' JOIN life_summary f ON f.year = t.year AND f.sex = 'F'"
        " WHERE t.sex = 'T' AND (t.e0 <= m.e0 OR t.e0 >= f.e0)",
        "The both-sexes life expectancy lies between the male and the female one",
    ),
    Check(
        "life_expectancy_close_to_conapo",
        "WARN",
        ("life_summary", "conapo_life_expectancy", "year_flags"),
        "SELECT COUNT(*) FROM life_summary s"
        " JOIN conapo_life_expectancy c ON c.year = s.year AND c.sex = s.sex AND c.state_code = 0"
        " JOIN year_flags f ON f.year = s.year"
        " WHERE f.covid_year = 0 AND ABS(s.e0 - c.e0) > 1.0",
        "In non-COVID years our life expectancy at birth is within 1 year of CONAPO's",
    ),
    Check(
        "hmd_life_expectancy_reproduced",
        "FAIL",
        ("life_table_comparison", "hmd_life_tables"),
        "SELECT COUNT(*) FROM life_table_comparison c JOIN hmd_life_tables h"
        ' ON h.country = SUBSTR(c."table", 1, LENGTH(c."table") - 5)'
        " AND h.year = c.year AND h.sex = c.sex AND h.age = 0"
        " WHERE c.source = 'HMD' AND ABS(c.e0 - h.ex) > 0.05",
        "Life tables built here from HMD rates reproduce HMD's published life expectancy "
        "(an end-to-end test of the life-table code)",
    ),
    Check(
        "actuarial_insurance_annuity_identity",
        "FAIL",
        ("actuarial_values",),
        "SELECT COUNT(*) FROM actuarial_values WHERE a_due IS NOT NULL"
        " AND ABS(A_whole_life - (1 - interest / (1 + interest) * a_due)) > 1e-9",
        "Whole-life insurance equals 1 minus d times the annuity-due, at every age and rate",
    ),
    Check(
        "actuarial_premium_equivalence",
        "FAIL",
        ("actuarial_values",),
        "SELECT COUNT(*) FROM actuarial_values WHERE a_due IS NOT NULL"
        " AND ABS(P_whole_life * a_due - A_whole_life) > 1e-9",
        "The net premium times the annuity-due equals the insurance value (equivalence principle)",
    ),
    # ── Projection ──────────────────────────────────────────────────────────
    Check(
        "projected_qx_complete",
        "FAIL",
        ("projected_qx",),
        "SELECT COUNT(*) FROM (SELECT year, sex FROM projected_qx GROUP BY year, sex"
        " HAVING COUNT(*) <> 111 OR MIN(qx) < 0 OR MAX(qx) > 1 OR MIN(mx) <= 0"
        " OR MAX(CASE WHEN age = 110 THEN qx END) <> 1)",
        "Every projected year and sex has a table for ages 0 to 110 with q in [0, 1] and q = 1 "
        "at 110",
    ),
    Check(
        "projected_men_at_least_women",
        "FAIL",
        ("projected_qx",),
        "SELECT COUNT(*) FROM projected_qx m JOIN projected_qx f"
        " ON m.year = f.year AND m.age = f.age"
        " WHERE m.sex = 'M' AND f.sex = 'F' AND m.mx < f.mx - 1e-12",
        "Projected male rates are never below female rates at the same age",
    ),
    Check(
        "projection_fan_is_ordered",
        "FAIL",
        ("projection_scenarios",),
        "SELECT COUNT(*) FROM projection_scenarios WHERE p05 IS NOT NULL"
        " AND NOT (p05 <= p25 AND p25 <= p50 AND p50 <= p75 AND p75 <= p95)",
        "The 5/25/50/75/95 percentiles of every simulated fan are in order",
    ),
    Check(
        "projection_restarts_at_the_observed_rates",
        "FAIL",
        ("projection_scenarios",),
        "SELECT COUNT(*) FROM projection_scenarios o JOIN projection_scenarios r"
        " ON r.sex = o.sex AND r.measure = o.measure AND r.scenario = 'rebased_long_run'"
        " WHERE o.scenario = 'observed' AND o.measure = 'e0'"
        " AND r.year = o.year + 1 AND o.year = (SELECT MAX(year) FROM projection_scenarios"
        " WHERE scenario = 'observed') AND ABS(r.p50 - o.p50) > 0.7",
        "The rebased projection's first year is within 0.7 years of the last observed life "
        "expectancy (no jump at the join)",
    ),
    Check(
        "projection_mortality_improves",
        "FAIL",
        ("projection_scenarios",),
        "SELECT COUNT(*) FROM (SELECT sex FROM projection_scenarios"
        " WHERE scenario = 'rebased_long_run' AND measure = 'e0'"
        " GROUP BY sex HAVING MAX(CASE WHEN year = 2070 THEN p50 END)"
        " <= MAX(CASE WHEN year = 2030 THEN p50 END))",
        "In the long-run scenario life expectancy at birth is higher in 2070 than in 2030",
    ),
    Check(
        "cohort_life_expectancy_not_below_period",
        "FAIL",
        ("cohort_tables",),
        "SELECT COUNT(*) FROM cohort_tables WHERE cohort_e65 < period_e65 - 1e-9"
        " OR cohort_a65 < period_a65 - 1e-9",
        "While mortality improves, the cohort lives longer than the period table says",
    ),
    Check(
        "projection_python_matches_r",
        "FAIL",
        ("projection_r_crosscheck",),
        "SELECT COUNT(*) FROM projection_r_crosscheck WHERE model = 'lee_carter'"
        " AND (quantity LIKE 'e0 in %' OR quantity LIKE 'e65 in %') AND ABS(difference) > 0.01",
        "Lee-Carter projections of life expectancy agree with StMoMo in R to within 0.01 years",
    ),
    Check(
        "projection_cbd_close_to_r",
        "WARN",
        ("projection_r_crosscheck",),
        "SELECT COUNT(*) FROM projection_r_crosscheck WHERE model = 'cbd'"
        " AND quantity LIKE 'e65 in %' AND ABS(difference) > 0.1",
        "CBD life expectancy at 65 is within 0.1 years of StMoMo's (least squares against "
        "binomial likelihood)",
    ),
    Check(
        "projection_fan_covers_the_backtest",
        "WARN",
        ("projection_backtest",),
        "SELECT CASE WHEN AVG(in_90) >= 0.8 THEN 0 ELSE 1 END FROM projection_backtest"
        " WHERE model = 'lee_carter_jump_off' AND fit_start = 1970",
        "The model's own 90% band contains the actual e65 in at least 80% of backtests "
        "(it does not: the empirical calibration widens it)",
    ),
    # ── Experience study ────────────────────────────────────────────────────
    Check(
        "experience_dq_finds_the_injected_defects",
        "FAIL",
        ("experience_dq_checks", "experience_injected_defects"),
        "SELECT COUNT(*) FROM experience_injected_defects i JOIN ("
        " SELECT 'duplicate_record' AS defect, 'duplicate_record' AS chk"
        " UNION ALL SELECT 'invalid_sex', 'invalid_sex'"
        " UNION ALL SELECT 'birth_after_issue', 'birth_missing_or_after_issue'"
        " UNION ALL SELECT 'non_positive_sum_assured', 'non_positive_sum_assured'"
        " UNION ALL SELECT 'invalid_state', 'invalid_state'"
        " UNION ALL SELECT 'exit_before_issue', 'exit_before_issue'"
        " UNION ALL SELECT 'issue_after_extract', 'issue_after_extract'"
        " UNION ALL SELECT 'death_without_notification', 'death_without_notification'"
        ") m ON m.defect = i.defect"
        ' JOIN experience_dq_checks c ON c."check" = m.chk WHERE c.records < i.records',
        "Validation of the synthetic extract catches every kind of defect injected, in full",
    ),
    Check(
        "experience_reconciliation_balances",
        "FAIL",
        ("experience_dq_reconciliation",),
        "SELECT CASE WHEN"
        " MAX(CASE WHEN step = 'records in the extract' THEN records END)"
        " = SUM(CASE WHEN step <> 'records in the extract' THEN records END)"
        " AND MAX(CASE WHEN step = 'records in the extract' THEN deaths END)"
        " = SUM(CASE WHEN step <> 'records in the extract' THEN deaths END)"
        " THEN 0 ELSE 1 END FROM experience_dq_reconciliation",
        "Records and deaths balance from the extract to the clean file: none lost unaccounted",
    ),
    Check(
        "experience_dimensions_partition_the_portfolio",
        "FAIL",
        ("experience_ae",),
        "SELECT COUNT(*) FROM (SELECT dimension, SUM(deaths) AS d, SUM(expected) AS e,"
        " SUM(exposure) AS x FROM experience_ae WHERE years = 'all_years' GROUP BY dimension) t"
        " WHERE ABS(t.d - (SELECT SUM(deaths) FROM experience_ae"
        "   WHERE years = 'all_years' AND dimension = 'sex')) > 1e-6"
        " OR ABS(t.e - (SELECT SUM(expected) FROM experience_ae"
        "   WHERE years = 'all_years' AND dimension = 'sex')) > 1e-6"
        " OR ABS(t.x - (SELECT SUM(exposure) FROM experience_ae"
        "   WHERE years = 'all_years' AND dimension = 'sex')) > 1e-6",
        "Every rating factor splits the same exposure, deaths and expected deaths (no cell lost)",
    ),
    Check(
        "experience_recovers_the_planted_effects",
        "FAIL",
        ("experience_recovery",),
        "SELECT CASE WHEN AVG(inside_interval) >= 0.8 THEN 0 ELSE 1 END FROM experience_recovery",
        "At least 80% of the planted rating effects fall inside the study's 95% intervals "
        "(95% expected): the validation of the whole method",
    ),
    Check(
        "experience_select_factors_recovered",
        "WARN",
        ("experience_select",),
        "SELECT CASE WHEN AVG(inside_interval) >= 0.7 THEN 0 ELSE 1 END FROM experience_select"
        " WHERE planted IS NOT NULL",
        "At least 70% of the planted select factors fall inside the study's intervals",
    ),
    Check(
        "experience_lag_completion_is_accurate",
        "FAIL",
        ("experience_lag_validation",),
        "SELECT COUNT(*) FROM (SELECT completed_error_pct FROM experience_lag_validation"
        " ORDER BY year DESC, quarter DESC LIMIT 2) WHERE ABS(completed_error_pct) > 0.12",
        "After the claims-lag correction the last two quarters' deaths are within 12% of the truth",
    ),
    Check(
        "experience_lag_correction_improves_the_latest_quarter",
        "FAIL",
        ("experience_lag_validation",),
        "SELECT COUNT(*) FROM (SELECT raw_error_pct, completed_error_pct"
        " FROM experience_lag_validation"
        " ORDER BY year DESC, quarter DESC LIMIT 1)"
        " WHERE ABS(completed_error_pct) >= ABS(raw_error_pct)",
        "The latest quarter is closer to the truth after the claims-lag correction than before",
    ),
    Check(
        "experience_basis_is_a_valid_table",
        "FAIL",
        ("experience_basis",),
        "SELECT COUNT(*) FROM experience_basis WHERE multiplier <= 0 OR q_experience < 0"
        " OR q_experience > 1 OR multiplier_upper < multiplier"
        " OR q_experience_prudent < q_experience - 1e-12",
        "The derived basis has positive multipliers, probabilities in [0, 1] and a prudent margin "
        "above the best estimate",
    ),
    Check(
        "experience_overall_ae_is_plausible",
        "WARN",
        ("experience_ae",),
        "SELECT COUNT(*) FROM experience_ae WHERE years = 'all_years' AND dimension = 'all'"
        " AND (ae < 0.3 OR ae > 3)",
        "The portfolio's overall actual-to-expected ratio lies between 0.3 and 3",
    ),
    # ── Excess mortality ────────────────────────────────────────────────────
    Check(
        "excess_observed_deaths_match_the_rates",
        "FAIL",
        ("excess_mortality", "crude_rates_grouped"),
        "SELECT COUNT(*) FROM (SELECT e.year, SUM(e.observed) AS a FROM excess_mortality e"
        " GROUP BY e.year) x JOIN (SELECT year, SUM(deaths) AS b FROM crude_rates_grouped"
        " WHERE sex IN ('M', 'F') GROUP BY year) y ON y.year = x.year WHERE ABS(x.a - y.b) > 0.5",
        "Observed deaths in the excess tables equal the deaths in the rates tables, year by year",
    ),
    Check(
        "excess_sexes_add_up",
        "FAIL",
        ("excess_summary",),
        "SELECT COUNT(*) FROM excess_summary t JOIN excess_summary m ON m.year = t.year"
        " AND m.sex = 'M' JOIN excess_summary f ON f.year = t.year AND f.sex = 'F'"
        " WHERE t.sex = 'T' AND (ABS(t.excess - m.excess - f.excess) > 1e-6"
        " OR ABS(t.observed - m.observed - f.observed) > 1e-6)",
        "Excess deaths and observed deaths of men and women add up to the total",
    ),
    Check(
        "excess_summary_matches_the_bands",
        "FAIL",
        ("excess_summary", "excess_mortality"),
        "SELECT COUNT(*) FROM excess_summary s JOIN (SELECT year, SUM(excess) AS x"
        " FROM excess_mortality GROUP BY year) b ON b.year = s.year"
        " WHERE s.sex = 'T' AND ABS(s.excess - b.x) > 1e-6",
        "The total excess equals the sum of the age-band excess",
    ),
    Check(
        "excess_pandemic_is_clearly_positive",
        "FAIL",
        ("excess_summary",),
        "SELECT COUNT(*) FROM excess_summary WHERE sex = 'T' AND year IN (2020, 2021)"
        " AND (excess_low <= 0 OR excess_per_covid_coded < 1)",
        "In 2020 and 2021 even the lowest baseline gives positive excess, above the certified "
        "COVID-19 deaths",
    ),
    Check(
        "excess_baselines_agree",
        "WARN",
        ("excess_summary",),
        "SELECT COUNT(*) FROM excess_summary WHERE sex = 'T' AND year IN (2020, 2021, 2022)"
        " AND (expected_high - expected_low) > 0.15 * expected_central",
        "The four baselines for the pandemic years lie within 15% of each other",
    ),
    Check(
        "excess_baselines_predict_2023",
        "WARN",
        ("excess_summary",),
        "SELECT COUNT(*) FROM excess_summary WHERE sex = 'T' AND year = 2023"
        " AND ABS(p_score) > 0.05",
        "The baselines predict 2023, after the pandemic, to within 5%: mortality returned to trend",
    ),
    Check(
        "excess_causes_cover_the_deaths",
        "WARN",
        ("excess_by_cause", "excess_summary"),
        "SELECT COUNT(*) FROM (SELECT year, SUM(observed) AS o FROM excess_by_cause"
        " GROUP BY year) c"
        " JOIN excess_summary s ON s.year = c.year AND s.sex = 'T'"
        " WHERE ABS(c.o - s.observed) > 0.02 * s.observed",
        "Deaths by cause chapter are within 2% of the completed total (late registrations)",
    ),
    Check(
        "excess_states_cover_the_nation",
        "WARN",
        ("excess_state", "excess_summary"),
        "SELECT COUNT(*) FROM (SELECT year, SUM(excess) AS x FROM excess_state GROUP BY year) e"
        " JOIN excess_summary s ON s.year = e.year AND s.sex = 'T'"
        " WHERE s.year IN (2020, 2021) AND (e.x < 0.85 * s.excess OR e.x > 1.15 * s.excess)",
        "State excess against 2023 rates adds up to within 15% of the national excess",
    ),
    # ── Pricing ─────────────────────────────────────────────────────────────
    Check(
        "pricing_premium_earns_the_hurdle",
        "FAIL",
        ("pricing_premiums",),
        "SELECT COUNT(*) FROM pricing_premiums WHERE ABS(irr - 0.10) > 0.001",
        "The solved gross premium of every product earns the 10% target return",
    ),
    Check(
        "pricing_insured_premium_earns_the_hurdle",
        "FAIL",
        ("pricing_insured",),
        "SELECT COUNT(*) FROM pricing_insured WHERE ABS(irr - 0.10) > 0.001",
        "The premium priced on the insured table earns the 10% target return",
    ),
    Check(
        "pricing_insured_premium_is_below_the_cnsf_one",
        "WARN",
        ("pricing_insured",),
        "SELECT COUNT(*) FROM pricing_insured WHERE gross_premium_per_1000 >= "
        "gross_premium_cnsf_per_1000",
        "Pricing on insured lives gives a lower premium than pricing on CNSF 2013 (a quote that "
        "is not lower says the margin or the reserve strain eats the advantage)",
    ),
    Check(
        "pricing_premium_exceeds_net_and_rises_with_age",
        "FAIL",
        ("pricing_premiums",),
        "SELECT (SELECT COUNT(*) FROM pricing_premiums"
        "        WHERE gross_premium_per_1000 <= net_premium_per_1000)"
        " + (SELECT COUNT(*) FROM pricing_premiums a JOIN pricing_premiums b"
        "      ON b.sex = a.sex AND b.term = a.term AND b.issue_age = a.issue_age + 5"
        "      WHERE b.gross_premium_per_1000 <= a.gross_premium_per_1000)",
        "The gross premium is above the net premium and rises with issue age",
    ),
    Check(
        "pricing_heavier_mortality_lowers_the_margin",
        "FAIL",
        ("pricing_adequacy",),
        "SELECT COUNT(*) FROM pricing_adequacy h JOIN pricing_adequacy b"
        " ON b.sex = h.sex AND b.issue_age = h.issue_age AND b.basis = 'cnsf'"
        " WHERE h.basis IN ('cnsf_p995', 'population') AND h.margin >= b.margin",
        "On a heavier mortality basis (99.5th percentile, the population) the margin falls",
    ),
    Check(
        "pricing_improvement_raises_the_margin",
        "FAIL",
        ("pricing_adequacy",),
        "SELECT COUNT(*) FROM pricing_adequacy i JOIN pricing_adequacy b"
        " ON b.sex = i.sex AND b.issue_age = i.issue_age AND b.basis = 'cnsf'"
        " WHERE i.basis = 'improving' AND i.margin <= b.margin",
        "Projected mortality improvement raises the margin of a term product",
    ),
    Check(
        "pricing_reserves_are_sound",
        "FAIL",
        ("pricing_reserves",),
        "SELECT COUNT(*) FROM pricing_reserves WHERE statutory_reserve_end < -1e-6"
        " OR (policy_year = 20 AND ABS(statutory_reserve_end) > 1e-6)"
        " OR (policy_year = 1 AND statutory_reserve_end <= 0)",
        "The statutory reserve is positive after year 1, never negative, and zero at expiry",
    ),
    Check(
        "pricing_sensitivities_point_the_right_way",
        "FAIL",
        ("pricing_sensitivity",),
        "SELECT COUNT(*) FROM pricing_sensitivity b JOIN pricing_sensitivity m"
        " ON m.sex = b.sex AND m.scenario = 'mortality +20%'"
        " JOIN pricing_sensitivity l ON l.sex = b.sex AND l.scenario = 'mortality -20%'"
        " JOIN pricing_sensitivity p ON p.sex = b.sex"
        " AND p.scenario = 'pandemic: year 2 mortality x2'"
        " WHERE b.scenario = 'base case'"
        " AND NOT (m.margin < b.margin AND b.margin < l.margin AND p.margin < b.margin)",
        "Heavier mortality and a pandemic year lower the margin; lighter mortality raises it",
    ),
    # ── Stress tests ────────────────────────────────────────────────────────
    Check(
        "stress_replays_add_claims_and_halve_with_dampening",
        "FAIL",
        ("stress_pandemic_book",),
        "SELECT COUNT(*) FROM stress_pandemic_book a JOIN stress_pandemic_book b"
        " ON a.kind = 'replay' AND b.kind = 'replay' AND a.year = b.year"
        " AND a.dampening = 1.0 AND b.dampening = 0.5"
        " WHERE a.extra_claims <= 0"
        " OR ABS(b.extra_claims - a.extra_claims / 2) > 1e-6 * a.base_claims",
        "Every replay adds claims, and an insured-lives dampening of 50% halves the extra claims",
    ),
    Check(
        "stress_insured_lives_were_not_shielded",
        "WARN",
        ("stress_pandemic_book",),
        "SELECT COUNT(*) FROM stress_pandemic_book o JOIN stress_pandemic_book r"
        " ON r.kind = 'replay' AND r.year = o.year AND r.dampening = 0.5"
        " WHERE o.kind = 'observed' AND o.extra_pct <= r.extra_pct",
        "The pandemic as insured lives lived it adds more claims than the replay that assumed they"
        " were half as exposed as the population",
    ),
    Check(
        "stress_severity_is_proportional",
        "FAIL",
        ("stress_pandemic_book",),
        "SELECT COUNT(*) FROM stress_pandemic_book a JOIN stress_pandemic_book b"
        " ON a.kind = 'severity' AND b.kind = 'severity' AND a.severity = 0.5 AND b.severity = 2.0"
        " WHERE ABS(b.extra_claims - 4 * a.extra_claims) > 1e-6 * a.base_claims",
        "Four times the severity gives four times the extra claims",
    ),
    Check(
        "stress_age_table_adds_up",
        "FAIL",
        ("stress_pandemic_age", "stress_pandemic_book"),
        "SELECT COUNT(*) FROM (SELECT SUM(extra_claims) AS x FROM stress_pandemic_age) a"
        " JOIN stress_pandemic_book b ON b.kind = 'replay' AND b.year = 2021 AND b.dampening = 1.0"
        " WHERE ABS(a.x - b.extra_claims) > 1e-6 * b.base_claims",
        "The age-band split of the 2021 replay adds up to the book's extra claims",
    ),
    Check(
        "stress_longevity_points_the_right_way",
        "FAIL",
        ("stress_longevity",),
        "SELECT COUNT(*) FROM stress_longevity c"
        " JOIN stress_longevity n ON n.scenario = 'no_improvement'"
        " JOIN stress_longevity d ON d.scenario = 'improvement_x2'"
        " JOIN stress_longevity l ON l.scenario = 'level_minus_20'"
        " JOIN stress_longevity i ON i.scenario = 'interest_minus_1'"
        " JOIN stress_longevity u ON u.scenario = 'interest_plus_1'"
        " WHERE c.scenario = 'central' AND NOT (n.reserve_T < c.reserve_T"
        " AND c.reserve_T < d.reserve_T AND c.reserve_T < l.reserve_T"
        " AND i.reserve_T > c.reserve_T AND c.reserve_T > u.reserve_T)",
        "Less improvement lowers the annuity reserve, more improvement, lower mortality or lower"
        " interest raise it",
    ),
    Check(
        "stress_hedge_signs",
        "FAIL",
        ("stress_hedge",),
        "SELECT COUNT(*) FROM stress_hedge WHERE (shock LIKE '%2020%' OR shock LIKE '%2021%')"
        " AND NOT (life_book_change > 0 AND annuity_change < 0)"
        " OR (shock LIKE 'Mortality%' AND NOT (life_book_change < 0 AND annuity_change > 0))",
        "A pandemic costs the life book and releases annuity reserve; longevity does the opposite",
    ),
    Check(
        "stress_pensions_table_is_prudent",
        "WARN",
        ("stress_longevity",),
        "SELECT COUNT(*) FROM stress_longevity p JOIN stress_longevity c"
        " ON c.scenario = 'central' WHERE p.scenario = 'cnsf_pensions'"
        " AND p.reserve_T <= c.reserve_T",
        "The regulatory pensions table holds a larger reserve than the central projection",
    ),
    # ── Reinsurance ─────────────────────────────────────────────────────────
    Check(
        "reinsurance_concentration_adds_up",
        "FAIL",
        ("reinsurance_concentration",),
        "SELECT COUNT(*) FROM (SELECT SUM(share_of_sum_at_risk) a, SUM(share_of_expected_claims) b,"
        " SUM(share_of_policies) c FROM reinsurance_concentration)"
        " WHERE ABS(a - 1) > 1e-9 OR ABS(b - 1) > 1e-9 OR ABS(c - 1) > 1e-9",
        "The size bands partition the policies, the sum at risk and the expected claims",
    ),
    Check(
        "reinsurance_each_source_of_risk_widens_the_tail",
        "FAIL",
        ("reinsurance_aggregate",),
        "SELECT COUNT(*) FROM reinsurance_aggregate a JOIN reinsurance_aggregate b"
        " ON a.source LIKE 'random%' AND b.source LIKE '+ uncertain%'"
        " JOIN reinsurance_aggregate c ON c.source LIKE '+ pandemic%'"
        " WHERE NOT (a.sd < b.sd AND b.sd < c.sd AND a.capital < c.capital)",
        "Adding the mortality-level and the pandemic risk widens the distribution of claims",
    ),
    Check(
        "reinsurance_simulation_matches_expected_claims",
        "FAIL",
        ("reinsurance_aggregate", "stress_pandemic_book"),
        "SELECT COUNT(*) FROM reinsurance_aggregate a JOIN (SELECT base_claims FROM"
        " stress_pandemic_book LIMIT 1) b WHERE a.source LIKE 'random%'"
        " AND ABS(a.mean / b.base_claims - 1) > 0.02",
        "Simulated mean claims of the in-force block are within 2% of its expected claims",
    ),
    Check(
        "reinsurance_covers_never_add_risk",
        "FAIL",
        ("reinsurance_structures",),
        "SELECT COUNT(*) FROM reinsurance_structures s JOIN reinsurance_structures n"
        " ON n.family = 'none' WHERE s.family <> 'none'"
        " AND (s.expected_recoveries < 0 OR s.cost < -1e-6 * n.capital"
        " OR s.capital_relief < -1e-3 * n.capital OR s.retained_mean > n.retained_mean + 1e-6)",
        "Every cover has non-negative recoveries and cost and leaves the cedant no worse off",
    ),
    Check(
        "reinsurance_retention_frontier_is_monotone",
        "FAIL",
        ("reinsurance_frontier",),
        "SELECT COUNT(*) FROM reinsurance_frontier a JOIN reinsurance_frontier b"
        " ON a.family = b.family AND a.family = 'excess of loss' AND a.parameter < b.parameter"
        " WHERE a.cost < b.cost - 1e-6 OR a.capital_relief < b.capital_relief - 1e-3",
        "A higher retention costs less and relieves less capital",
    ),
    Check(
        "reinsurance_excess_of_loss_is_cheaper_than_quota_share",
        "WARN",
        ("reinsurance_structures",),
        "SELECT COUNT(*) FROM reinsurance_structures x JOIN reinsurance_structures q"
        " ON q.structure = 'Quota share 20%' WHERE x.family = 'excess of loss'"
        " AND x.price_of_relief >= q.price_of_relief",
        "Per capital relieved, non-proportional covers cost less than a quota share",
    ),
    Check(
        "reinsurance_dearer_capital_raises_the_price",
        "FAIL",
        ("reinsurance_price_sensitivity",),
        "SELECT COUNT(*) FROM reinsurance_price_sensitivity a JOIN reinsurance_price_sensitivity b"
        " ON a.reinsurer_coc < b.reinsurer_coc"
        " WHERE a.xl_price_of_relief > b.xl_price_of_relief + 1e-9"
        " OR a.stop_loss_price_of_relief > b.stop_loss_price_of_relief + 1e-9",
        "A higher return on the reinsurer's capital raises the price of every cover",
    ),
    Check(
        "reinsurance_credibility_is_valid",
        "FAIL",
        ("reinsurance_yrt_rating",),
        "SELECT COUNT(*) FROM reinsurance_yrt_rating WHERE credibility < 0 OR credibility > 1"
        " OR experience_factor < MIN(1, ae_amount) - 1e-9"
        " OR experience_factor > MAX(1, ae_amount) + 1e-9",
        "Credibility lies in [0, 1] and the experience factor between the manual rate and the A/E",
    ),
    Check(
        "reinsurance_swap_agrees_with_the_stress_tests",
        "FAIL",
        ("reinsurance_longevity_swap", "stress_longevity"),
        "SELECT COUNT(*) FROM reinsurance_longevity_swap w JOIN stress_longevity c"
        " ON c.scenario = 'central' WHERE ABS(w.central_reserve / c.reserve_T - 1) > 1e-9"
        " OR w.capital <= 0 OR w.fee_pv <= 0",
        "The swap's central reserve is the stress tests' and it needs positive capital and a fee",
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
