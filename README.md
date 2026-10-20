# Mortality Table Builder

**An end-to-end actuarial mortality pipeline for Mexico, from raw death certificates to priced insurance products.**

This project builds complete, graduated and projected mortality tables for the Mexican population from official government microdata. It benchmarks them against Mexico's regulatory tables (CNSF), US industry tables (SOA) and international data (Human Mortality Database), and uses them for real pricing, reserving and longevity-risk work, the kind of analysis a life reinsurer runs every day.

> **Status:** 🚧 In active development. See the [roadmap](#roadmap) for what's built and what's next.

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

1. **Ingestion and storage:** download scripts load raw files into a local **DuckDB** database with a documented SQL schema and data validation.
2. **Data quality:** age-heaping diagnostics (Whipple and Myers indices), redistribution of unknown ages, year of occurrence vs year of registration, and flags for the COVID years.
3. **Crude rates:** central exposure, crude m<sub>x</sub> and q<sub>x</sub> with Poisson confidence intervals.
4. **Graduation:** Whittaker–Henderson, P-splines, and the Gompertz–Makeham and Heligman–Pollard laws, with old-age closure (Kannisto). Fits are checked with standard actuarial tests: chi-square, standardized deviations, signs and runs.
5. **Life table functions:** l<sub>x</sub>, d<sub>x</sub>, L<sub>x</sub>, T<sub>x</sub>, e<sub>x</sub>, plus commutation functions D<sub>x</sub>, N<sub>x</sub>, C<sub>x</sub>, M<sub>x</sub> at any interest rate.
6. **Actuarial present values:** insurances, annuities and premiums, connecting life contingencies to interest theory (SOA Exam FM).
7. **Projection:** Lee–Carter and CBD models, bootstrap uncertainty, improvement scales, cohort tables.
8. **Benchmarking and applications:** A/E studies, pricing, reserves, risk capital, reinsurance structures, COVID excess mortality.
9. **Interactive dashboard:** explore tables, compare benchmarks and price products live.

## Tech stack

- **Python:** pandas, NumPy, SciPy, statsmodels, DuckDB, Plotly, Streamlit, pytest
- **R:** StMoMo (stochastic mortality models), MortalityLaws, demography, lifecontingencies, used for projections and to cross-check the Python results
- **SQL:** DuckDB for storage, transformations and A/E queries
- **Excel:** exported pricing and table workbooks for actuaries who live in spreadsheets
- **Tooling:** GitHub Actions CI, ruff, pre-commit, Quarto for the methodology report

## Roadmap

- [x] **0. Repository setup:** README, data-source documentation, license
- [ ] **1. Project skeleton:** Python package layout, environment, tests, linting, CI
- [ ] **2. Data ingestion:** download scripts for INEGI, CONAPO, SOA, CNSF and HMD; DuckDB schema; validation
- [ ] **3. Data quality:** age-heaping indices, unknown-age redistribution, registration lag
- [ ] **4. Crude rates and exposure:** m<sub>x</sub>, q<sub>x</sub>, confidence intervals, by sex, state and year
- [ ] **5. Graduation:** Whittaker–Henderson, P-splines, parametric laws, old-age closure, fit tests
- [ ] **6. Life tables and actuarial functions:** full tables, commutation functions, APVs
- [ ] **7. Mortality projection:** Lee–Carter and CBD (Python and R), fan charts, cohort tables
- [ ] **8. Benchmarking:** A/E vs CNSF, SOA and HMD
- [ ] **9. Applications:** pricing, reserves, longevity and pandemic stress, reinsurance, COVID excess mortality
- [ ] **10. Dashboard and report:** Streamlit app and Quarto methodology write-up

## Project structure (planned)

```
Mortality-Table-Builder/
├── data/            # raw/ and processed/ (git-ignored, filled by download scripts)
├── docs/            # data sources, methodology notes
├── sql/             # DuckDB schema and queries
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
