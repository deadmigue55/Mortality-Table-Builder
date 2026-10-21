# Mortality Table Builder

**An end-to-end actuarial mortality pipeline for Mexico, from raw death certificates to priced insurance products.**

This project builds complete, graduated and projected mortality tables for the Mexican population from official government microdata. It benchmarks them against Mexico's regulatory tables (CNSF), US industry tables (SOA) and international data (Human Mortality Database), and uses them for real pricing, reserving and longevity-risk work, the kind of analysis a life reinsurer runs every day.

> **Status:** 🚧 In active development. See the [roadmap](#roadmap) for what's built and what's next.

[![CI](https://github.com/deadmigue55/Mortality-Table-Builder/actions/workflows/ci.yml/badge.svg)](https://github.com/deadmigue55/Mortality-Table-Builder/actions/workflows/ci.yml)

---

## Why this matters

Life insurers and reinsurers price and reserve with mortality tables. In Mexico the regulatory tables in force (CNSF 2013) are deliberately conservative, rest on experience that is now over a decade old, and predate COVID-19. Each insurer's own experience tables are private. This project builds a transparent, up-to-date alternative from official data and asks:

- **How far is the population from the regulatory tables?** What does Mexico's actual mortality look like by age, sex, state and year?
- **What changes in pricing?** How do term life and annuity prices, and the reserves behind them, move when you switch tables?
- **What's next?** How will mortality improve, and how much capital does longevity risk require?
- **What was COVID-19's impact?** How large was excess mortality in 2020–2022, and what does a pandemic shock do to a life portfolio?

## Real-world applications

| Application | What it shows |
|---|---|
| **Experience study / A/E analysis** | Actual-to-expected ratios against CNSF, SOA and HMD benchmarks, by age band and sex |
| **Product pricing** | Net premiums for term, whole life, endowment and annuities under each table and interest rate |
| **Reserving** | Prospective reserves and how they shift with table choice |
| **Mortality projection** | Lee–Carter and Cairns–Blake–Dowd forecasts with uncertainty fan charts; cohort vs period tables |
| **Longevity & mortality risk capital** | Solvency-style longevity shock, pandemic shock, and their impact on annuity and life books |
| **Reinsurance** | Pricing a longevity swap and a mortality catastrophe cover from the projected tables |
| **COVID-19 excess mortality** | Excess deaths by state, age and sex vs a projected baseline |

## Data sources

All data comes from official or academically recognized sources. Raw data is **not** committed to this repo. Download scripts fetch it, and each source keeps its own license and terms. See [`docs/data-sources.md`](docs/data-sources.md) for details and citations.

| Source | What we use | Access |
|---|---|---|
| **INEGI**: Estadísticas de Defunciones Registradas | Death microdata by age, sex, state, cause and year of occurrence | Open data |
| **CONAPO**: Conciliación Demográfica 1950–2019 and Proyecciones 2020–2070 | Mid-year population by age, sex and state (the exposure) | Open data |
| **CNSF**: Mexican regulatory tables (CNSF 2013 in force; CNSF 2000-I and EMSSA-09 for history) | Regulatory benchmark | Public documents |
| **SOA**: Mortality and Other Rate Tables (mort.soa.org) | US benchmarks (e.g. 2017 CSO, 2012 IAM, Pri-2012) | Free, XTbML/CSV |
| **Human Mortality Database** | International comparison countries (Mexico is not in HMD) | Free registration, scientific use |

## Methodology

1. **Ingestion and storage:** download scripts load processed files into a local **SQLite** warehouse (see [`docs/warehouse.md`](docs/warehouse.md)) with automatic data checks.
2. **Data quality:** age-heaping diagnostics (Whipple and Myers indices), redistribution of unknown ages, year of occurrence vs year of registration, and flags for the COVID years.
3. **Crude rates:** central exposure, crude m<sub>x</sub> and q<sub>x</sub> with Poisson confidence intervals.
4. **Graduation:** Whittaker–Henderson, P-splines, and the Gompertz–Makeham and Heligman–Pollard laws, with old-age closure (Kannisto). Fits are checked with standard actuarial tests: chi-square, standardized deviations, signs and runs.
5. **Life table functions:** l<sub>x</sub>, d<sub>x</sub>, L<sub>x</sub>, T<sub>x</sub>, e<sub>x</sub>, plus commutation functions D<sub>x</sub>, N<sub>x</sub>, C<sub>x</sub>, M<sub>x</sub> at any interest rate.
6. **Actuarial present values:** insurances, annuities and premiums, connecting life contingencies to interest theory (SOA Exam FM).
7. **Projection:** Lee–Carter and CBD models, bootstrap uncertainty, improvement scales, cohort tables.
8. **Benchmarking and applications:** A/E studies, pricing, reserves, risk capital, reinsurance structures, COVID excess mortality.
9. **Interactive dashboard:** explore tables, compare benchmarks and price products live.

## Tech stack

- **Python:** pandas, NumPy, SciPy, statsmodels, SQLite, Plotly, Streamlit, pytest
- **R:** StMoMo (stochastic mortality models), MortalityLaws, demography, lifecontingencies, used for projections and to cross-check the Python results
- **SQL:** SQLite for the warehouse, transformations and A/E queries (DuckDB for R, reading Parquet)
- **Excel:** exported pricing and table workbooks for actuaries who live in spreadsheets
- **Tooling:** GitHub Actions CI, ruff, pre-commit, Quarto for the methodology report

## Roadmap

- [x] **0. Repository setup:** README, data-source documentation, license
- [x] **1. Project skeleton:** Python package layout, environment, tests, linting, CI
- [ ] **2. Data ingestion:** download scripts for INEGI, CONAPO, SOA, CNSF and HMD; SQLite warehouse; validation
  - [x] Download framework with a manifest of every file
  - [x] INEGI deaths 2020 to 2024 (earlier years: in progress)
  - [x] CONAPO population and modelled deaths 1950 to 2070
  - [x] Human Mortality Database (9 comparison countries)
  - [x] SOA tables (29 tables, including 13 Mexican ones)
  - [x] CNSF 2013 (all nine tables, cross-checked against the PDF)
  - [x] SQLite warehouse with 62 automatic data checks
  - [x] INEGI 2014 to 2019 from the interactive tables (five-year age groups, all six years verified against INEGI totals)
  - [ ] INEGI before 2014 (optional, for a longer forecasting history)
- [x] **3. Data quality:** age-heaping indices, unknown-age redistribution, registration lag ([findings](docs/data-quality.md))
  - Death certificates show no age heaping (Whipple 98 to 101), comparable to the HMD countries
  - Late registrations completed with an actuarial chain-ladder triangle per age band: 2024 gains 2.3%, within 1% of CONAPO's independent projection
  - Unknown sex and age allocated proportionally (0.45% to 0.61% of deaths); unspecified-residence deaths kept in the national count
  - COVID years flagged from cause-of-death codes (2020 to 2022)
- [x] **4. Crude rates and exposure:** m<sub>x</sub>, q<sub>x</sub>, exact intervals, standardisation, state SMRs, first benchmarks ([findings](docs/crude-rates.md))
  - Mexican men die **3.0x** as fast as the CNSF 2013 table predicts at ages 25 to 84 (4.1x at 40 to 44); women 1.8x
  - Age-standardised male mortality rose **51%** in 2020 and was back at the 2019 level by 2023
  - Chihuahua and Colima run about 19% above their age mix, Sinaloa 19% below
  - Men aged 25 to 29 die at 6.7x the rate of Spanish men, 1.6x that of US men

![Mortality curve against the CNSF 2013 table](docs/img/mortality_curve.png)
![Pandemic shock by age](docs/img/covid_shock.png)
- [x] **5. Graduation:** Whittaker–Henderson, P-splines, parametric laws, old-age closure, fit tests ([findings](docs/graduation.md))
  - Four methods compared on every year and sex; smoothing chosen by a quasi-AIC whose dispersion is estimated from the crude rates themselves
  - Heligman–Pollard fits about 9x worse than the P-spline in 2023: Mexican men's young-adult plateau is not something a parametric law bends to
  - **Digit preference found in men's death records:** +1.3% to +2.5% excess deaths at ages ending in 0 and 5, every year, invisible to the Whipple index
  - **Crude old-age data are not credible:** above about 88, women's rates overtake men's (a sign of age exaggeration), so ages 90 to 110 come from a Kannisto logistic fitted on 75 to 89, with men floored at women
  - Output: `graduated_qx`, a complete 0 to 110 table per year and sex, ready for the life-table step

![Graduation fit](docs/img/graduation_fit.png)
![Old-age closure](docs/img/old_age_closure.png)
- [x] **6. Life tables and actuarial functions:** full tables, commutation functions, APVs ([findings](docs/life-tables.md))
  - Life expectancy at birth 2023: men **72.9**, women **78.9**; within 0.7 years of CONAPO in 2022 to 2024, and the same code reproduces HMD's published life expectancy to 0.007 years
  - COVID cost men **5.9 to 6.9 years** of life expectancy depending on whether INEGI or CONAPO death counts are used
  - A pension annuity at 65 costs 14.94 on CNSF 2013 and 12.21 for Mexican men: valuing the population on the regulatory table overstates it by **22%** (13% for women)
  - A 20-year term at 40 has a net premium of **6.6 per 1,000** for men on population mortality, against 1.7 on CNSF 2013
  - Mexican men's lifespans are the least equal of any country compared (disparity 14.6 years against 9.9 in Japan)
  - Full actuarial function library: insurance, annuities, premiums, reserves, at any interest rate

![Annuity values](docs/img/annuity_values.png)
![Term premiums](docs/img/term_premiums.png)
- [x] **7. Mortality projection:** Lee–Carter and CBD (Python and R), fan charts, cohort tables ([findings](docs/projection.md))
  - Lee–Carter and CBD fitted to CONAPO 1970 to 2019, with process and drift uncertainty, back-tested over four origins and **cross-checked against StMoMo in R** (agreement to 0.00002 years)
  - A forecast made in 1999 would have overshot men's 2019 life expectancy by **4.0 years**: men's improvement slowed to 15% of its earlier pace
  - Men's life expectancy reaches 77 by 2050 on the long trend, **74 if the last 20 years repeat**; CONAPO's official projection says 77
  - A pension annuity at 65 costs 6% more by 2050 on the long trend, 2% on the recent one: the longevity-risk spread
  - Pricing an annuity on a period table understates its cost by about **2.6%** against the cohort
  - Found that INEGI and CONAPO disagree on who dies: INEGI shows **34% fewer deaths for men aged 15 to 39**, 10% to 16% more above 60
  - The model's own fan is too narrow (it covered 40% to 60% of backtests); the projection carries an empirical band calibrated on the backtest errors

![Projection fan](docs/img/projection_fan_e0.png)
![Longevity risk](docs/img/longevity_risk.png)
- [ ] **8. Benchmarking:** A/E vs CNSF, SOA and HMD
- [ ] **9. Applications:** pricing, reserves, longevity and pandemic stress, reinsurance, COVID excess mortality
- [ ] **10. Dashboard and report:** Streamlit app and Quarto methodology write-up

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you) and, for the projection models, [R](https://cran.r-project.org/) 4.3+.

```sh
git clone https://github.com/deadmigue55/Mortality-Table-Builder.git
cd Mortality-Table-Builder

uv sync                         # create the environment and install Python packages
Rscript r/install_packages.R    # install R packages (optional, for projections)
cp .env.example .env            # then add your Human Mortality Database login

uv run mortality doctor         # check that everything is ready
```

Load the data (about 10 minutes, mostly INEGI; every file is logged in `data/raw/MANIFEST.csv`):

```sh
uv run mortality ingest inegi --years 2020-2024   # registered deaths
uv run mortality ingest inegi-cube 2014-2019.zip  # hand-exported INEGI tables (optional)
uv run mortality ingest conapo                    # population 1950-2070
uv run mortality ingest hmd                       # needs the login in .env
uv run mortality ingest soa                       # SOA and Mexican tables
uv run mortality ingest cnsf                      # CNSF 2013 regulatory tables
uv run mortality db build                         # SQLite warehouse + data checks
```

Development:

```sh
uv run pytest                   # tests
uv run ruff check . && uv run ruff format .   # lint and format
uv run pre-commit install       # run these checks automatically before each commit
```

## Project structure (planned)

```
Mortality-Table-Builder/
├── data/            # raw/ and processed/ (git-ignored, filled by download scripts)
├── docs/            # data sources, methodology notes
├── sql/             # SQL queries
├── src/mortality/   # Python package: ingest, quality, rates, graduation, tables, projection, pricing
├── r/               # R scripts: StMoMo projections and cross-checks
├── notebooks/       # exploratory analysis
├── app/             # Streamlit dashboard
├── reports/         # Quarto report, exported Excel workbooks
└── tests/
```

## Author

**Miguel Vilchis**: Actuarial Science, Facultad de Ciencias UNAM · Pricing & Risk Analytics at SCOR Reinsurance

[Portfolio](https://portfolio-psi-nine-sz4lsw795q.vercel.app/) · [GitHub](https://github.com/deadmigue55) · [LinkedIn](https://www.linkedin.com/in/deadmigue)

## License

Code is released under the [MIT License](LICENSE). Data belongs to its original publishers and is subject to their terms. See [`docs/data-sources.md`](docs/data-sources.md).
