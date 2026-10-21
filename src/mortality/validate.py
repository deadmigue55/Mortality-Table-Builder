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
