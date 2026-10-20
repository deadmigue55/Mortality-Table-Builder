# The warehouse

`uv run mortality db build` loads every processed source into one SQLite file, `data/mortality.sqlite`, then runs the data checks. `uv run mortality db check` re-runs only the checks.

**Why SQLite:** it ships with Python. The development machine has Windows Smart App Control, which blocks DuckDB's native module, so DuckDB could not be used. To keep the file small (about 170 MB), INEGI deaths are stored as counts per cell instead of one row per death. The row-level files, with cause of death, stay in `data/processed/inegi/*.parquet`, and R reads the Parquet files directly.

## Tables

| Table | Rows | What it is |
|---|---:|---|
| `inegi_deaths_cells` | 546,748 | INEGI deaths as counts per file year, year and month of occurrence, state, sex, age and type of death |
| `inegi_cube_registered` | 360 | Hand-exported INEGI tables: deaths by year of registration, five-year age group and sex, national |
| `deaths_by_occurrence` | 43,538 | Deaths of Mexican residents by year of occurrence, state, sex and age (the numerator of death rates) |
| `deaths_unallocated` | 83 | Deaths with unknown sex, age or residence, by year |
| `inegi_completeness` | 83 | Per year of occurrence: own file loaded, next file loaded (late registrations), and so whether the year is complete |
| `conapo_population` | 737,660 | Mid-year population by year, state, age and sex (the exposure) |
| `conapo_deaths` | 737,660 | CONAPO modelled deaths, a cross-check |
| `conapo_life_expectancy` | 10,059 | CONAPO life expectancy at birth |
| `dim_state` | 33 | State codes: CONAPO integer, INEGI two-digit text, name |
| `hmd_deaths`, `hmd_exposures`, `hmd_life_tables` | 385,614 each | Human Mortality Database, nine comparison countries |
| `soa_catalog`, `soa_rates` | 29 / 2,869 | SOA tables (13 Mexican) and their rates |
| `cnsf_rates` | 999 | CNSF 2013: nine tables, ages 0 to 110 |
| `source_manifest` | 82 | Every downloaded file with URL, date, size and SHA-256 |
| `validation_results` | 22 | Latest result of every data check |
| `table_docs` | 15 | One-line description of each table above |

Row counts are from the October 2026 build and grow as more INEGI years are added.

## Querying

```python
from mortality import warehouse

con = warehouse.connect()  # read-only
rate = con.execute("""
    SELECT d.age, 1.0 * SUM(d.deaths) / SUM(p.population) AS mx
    FROM deaths_by_occurrence d
    JOIN dim_state s ON s.state_code_text = d.state_code_text
    JOIN conapo_population p
      ON p.year = d.year AND p.state_code = s.state_code AND p.sex = d.sex AND p.age = d.age
    WHERE d.year = 2023 AND d.sex = 'M'
    GROUP BY d.age ORDER BY d.age
""").fetchall()
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
| `inegi_pre_covid_baseline` | WARN | Years 2015 to 2019 are loaded |
| `inegi_latest_year_complete` | WARN | The latest year has its own file and the next year's file |
| `inegi_cube_no_year_gaps` | WARN | Registered deaths exist for every year between the first and last (tables plus microdata) |
| `inegi_cube_complete_age_groups` | FAIL | Each imported year has all 19 age groups |
| `conapo_no_negative` | FAIL | Population present and non-negative |
| `conapo_states_sum_to_national` | FAIL | The 32 states add up to the national total |
| `conapo_complete_grid` | FAIL | Every year, state and sex has ages 0 to 109 |
| `hmd_keys_unique`, `hmd_counts_non_negative`, `hmd_life_table_qx_range` | FAIL / FAIL / WARN | One row per country-year-age-sex; no negative counts; qx is a probability |
| `soa_rates_are_probabilities`, `soa_every_table_has_rates` | FAIL | SOA rates in [0, 1]; every catalogued table has rates |
| `soa_mexico_tables_present` | WARN | At least 10 Mexican SOA tables |
| `cnsf_complete`, `cnsf_percentiles_bracket_base` | FAIL | Nine tables with 111 ages; 99.5th percentile never below base |
| `inegi_vs_conapo_deaths` | WARN | For complete years, INEGI is within 15% of CONAPO's modelled deaths |
| `manifest_integrity` | FAIL | Raw files match their recorded SHA-256 |

**Current state (October 2026):** 19 pass, 3 warnings, 0 failures. The warnings are known gaps: the 2017 table has not been exported correctly yet, no row-level pre-2020 data (only five-year groups from the tables), and 2024 still awaiting the 2025 file's late registrations.

## What the checks have already caught

- **State code 35** ("other countries") appears in the 2020 and 2021 files. INEGI's code list defines 33 to 35, so the check was widened.
- **"Complete year" logic:** an early version treated 2019 as complete because the 2020 file was loaded, although the 2019 file itself was not. A year now needs its own file and the next one.
- **A mislabeled export:** the file named `2017.csv` contained registration year 2025. The importer reads the year from inside the file and warns; the gap check then flags 2017 as missing.
- **`death_type`** (type of death) does not exist in the 2020 and 2021 files, only from 2022, so it is missing for those years.
