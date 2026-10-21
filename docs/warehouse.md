# The warehouse

`uv run mortality db build` loads every processed source into one SQLite file, `data/mortality.sqlite`, builds the quality tables from [data-quality.md](data-quality.md), then runs the data checks. `uv run mortality db check` re-runs only the checks.

**Why SQLite:** it ships with Python. The development machine has Windows Smart App Control, which blocks DuckDB's native module, so DuckDB could not be used. To keep the file small (about 170 MB), INEGI deaths are stored as counts per cell instead of one row per death. The row-level files, with cause of death, stay in `data/processed/inegi/*.parquet`, and R reads the Parquet files directly.

## Tables

**Start from `deaths_adjusted`** for national death counts: it is the analysis-ready table (late registrations completed, unknown sex and age allocated, every change in its own column).

| Table | Rows | What it is |
|---|---:|---|
| `deaths_adjusted` | 1,210 | **National deaths by year of occurrence, sex and single age, 2020 to 2024, analysis-ready.** Columns: `reported`, `added_late_registration`, `added_unknown_sex`, `added_unknown_age`, `added_unknown_both`, `adjusted` |
| `registration_triangle` | 117 | Deaths by age band, year of occurrence and registration lag (a chain-ladder triangle) |
| `registration_factors` | 32 | Chain-ladder development factors by age band and lag |
| `registration_completion` | 40 | Reported versus estimated final deaths by age band and year |
| `registration_tail` | 1 | Tail factor for deaths registered five or more years late |
| `quality_age_heaping` | 100 | Whipple, Myers and Noumbissi indices for INEGI, CONAPO and nine HMD countries |
| `year_flags` | 5 | Per year: COVID-coded deaths, their share, and a COVID-year flag (1% or more) |
| `deaths_by_cause_chapter` | 7,514 | Deaths by month of occurrence, sex, ICD-10 chapter letter and COVID flag |
| `inegi_deaths_cells` | 546,748 | INEGI deaths as counts per file year, year and month of occurrence, state, sex, age and type of death |
| `inegi_cube_registered` | 360 | Hand-exported INEGI tables: deaths by year of registration, five-year age group and sex, national |
| `deaths_by_occurrence` | 43,538 | Deaths of residents of a known state, by year of occurrence, state, sex and age (state-level; unspecified-residence deaths are not in it, so use `deaths_adjusted` for national totals) |
| `deaths_unallocated` | 83 | Deaths with unknown sex, age or residence, by year |
| `inegi_completeness` | 83 | Per year of occurrence: own file loaded, next file loaded (late registrations), and so whether the year is complete |
| `crude_rates_single`, `crude_rates_grouped`, `age_standardised_rates`, `basis_bridge`, `state_smr`, `benchmark_ae`, `benchmark_countries` | 1,010 / 627 / 33 / 11 / 32 / 2,574 / 5,358 | Death rates, standardisation and first benchmarks: see [crude-rates.md](crude-rates.md) |
| `conapo_population` | 737,660 | Mid-year population by year, state, age and sex (the exposure) |
| `conapo_deaths` | 737,660 | CONAPO modelled deaths, a cross-check |
| `conapo_life_expectancy` | 10,059 | CONAPO life expectancy at birth |
| `dim_state` | 33 | State codes: CONAPO integer, INEGI two-digit text, name |
| `hmd_deaths`, `hmd_exposures`, `hmd_life_tables` | 385,614 each | Human Mortality Database, nine comparison countries |
| `soa_catalog`, `soa_rates` | 29 / 2,869 | SOA tables (13 Mexican) and their rates |
| `cnsf_rates` | 999 | CNSF 2013: nine tables, ages 0 to 110 |
| `source_manifest` | 88 | Every downloaded file with URL, date, size and SHA-256 |
| `validation_results` | 36 | Latest result of every data check |
| `table_docs` | 31 | One-line description of each table above |

Row counts are from the October 2026 build and grow as more INEGI years are added.

## Querying

```python
from mortality import warehouse

con = warehouse.connect()  # read-only
rows = con.execute("""
    SELECT d.age, d.adjusted / p.population AS mx
    FROM deaths_adjusted d
    JOIN (SELECT age, sex, population FROM conapo_population
          WHERE year = 2023 AND state_code = 0) p
      ON p.age = d.age AND p.sex = d.sex
    WHERE d.year = 2023 AND d.sex = 'M'
    ORDER BY d.age
""").fetchall()  # crude male death rate by single age, 2023
```

## Data checks

Each check counts violations. `FAIL` means the data is wrong; `WARN` means a known gap or a difference to look at; `SKIP` means the tables it needs are missing.

| Check | Severity | Rule |
|---|---|---|
| `inegi_sex_values` | FAIL | Sex is M, F or unknown |
| `inegi_age_range` | FAIL | Completed age is 0 to 125 |
| `inegi_state_codes` | FAIL | State is 01-32, 33-35 (USA, other Latin America, other countries) or 99 |
| `inegi_dates_plausible` | FAIL | Occurrence is not after the file that records it; month is 1 to 12 |
| `inegi_unknown_age_share` | WARN | Under 2% of deaths per file have an unknown age |
| `inegi_pre_covid_single_ages` | WARN | Single-year-of-age deaths exist for 2015 to 2019 (row-level files) |
| `inegi_pre_covid_grouped_baseline` | WARN | At least 4 of the 5 years 2015 to 2019 exist as five-year-group tables |
| `inegi_latest_year_complete` | WARN | The latest year has its own file and the next year's file |
| `inegi_cube_no_year_gaps` | WARN | Registered deaths exist for every year between the first and last (tables plus microdata) |
| `inegi_cube_complete_age_groups` | FAIL | Each imported year has all 19 age groups |
| `adjusted_identity_holds` | FAIL | `adjusted` = reported + late registrations + allocated unknowns, no negatives |
| `adjusted_keeps_every_reported_death` | FAIL | Every reported death in scope is still counted after adjusting |
| `unknown_allocation_small` | WARN | Allocated unknowns are under 2% of deaths in each year |
| `late_registration_completion_is_modest` | WARN | Completing late registrations adds under 5% to any year |
| `inegi_age_heaping_low` | WARN | INEGI Whipple index is below 110 |
| `conapo_no_negative` | FAIL | Population present and non-negative |
| `conapo_states_sum_to_national` | FAIL | The 32 states add up to the national total |
| `conapo_complete_grid` | FAIL | Every year, state and sex has ages 0 to 109 |
| `hmd_keys_unique`, `hmd_counts_non_negative`, `hmd_life_table_qx_range` | FAIL / FAIL / WARN | One row per country-year-age-sex; no negative counts; qx is a probability |
| `soa_rates_are_probabilities`, `soa_every_table_has_rates` | FAIL | SOA rates in [0, 1]; every catalogued table has rates |
| `soa_mexico_tables_present` | WARN | At least 10 Mexican SOA tables |
| `cnsf_complete`, `cnsf_percentiles_bracket_base` | FAIL | Nine tables with 111 ages; 99.5th percentile never below base |
| `inegi_vs_conapo_deaths` | WARN | For complete years, INEGI is within 15% of CONAPO's modelled deaths |
| `manifest_integrity` | FAIL | Raw files match their recorded SHA-256 |

The rate tables of [step 4](crude-rates.md) add eight more checks:

| Check | Severity | Rule |
|---|---|---|
| `rates_single_conserve_deaths` | FAIL | Single-age rates use every adjusted death |
| `rates_grouped_conserve_deaths` | FAIL | Grouped rates before 2020 use every registered death |
| `rates_exposure_matches_conapo` | FAIL | Exposure equals CONAPO's national population |
| `rates_intervals_bracket_estimate` | FAIL | Every 95% interval contains its estimate |
| `rates_are_rates` | FAIL | Central rates and q are between 0 and 1 |
| `rates_thin_cells_only_at_the_extremes` | WARN | At least 30 deaths per single-age cell between ages 1 and 95 |
| `registration_basis_matches_occurrence` | WARN | Registered and occurred deaths within 3% where both exist |
| `state_smr_balances` | FAIL | State expected deaths add up to the observed total |

**Current state (October 2026):** 34 pass, 2 warnings, 0 failures. The warnings are known gaps: no row-level (single-age) data before 2020, and 2024 still awaiting the 2025 file's late registrations (the quality tables estimate and add them).

## What the checks have already caught

- **State code 35** ("other countries") appears in the 2020 and 2021 files. INEGI's code list defines 33 to 35, so the check was widened.
- **"Complete year" logic:** an early version treated 2019 as complete because the 2020 file was loaded, although the 2019 file itself was not. A year now needs its own file and the next one.
- **A mislabeled export:** the file named `2017.csv` contained registration year 2025. The importer reads the year from inside the file and warns; the gap check then flagged 2017 as missing until the right file was imported.
- **`death_type`** (type of death) does not exist in the 2020 and 2021 files, only from 2022, so it is missing for those years.
- **Unspecified residence:** about 1.1% of deaths have no state of residence, and the first national table silently dropped them. The national table now includes them.
