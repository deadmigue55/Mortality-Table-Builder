# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- The pricing lab now defaults to the insured-lives basis with its margin (the version 2 pricing
  basis), keeping the statutory reserve on CNSF 2013, so it reproduces the stored premium table.
- Dashboard screenshots retaken, with the Insured lives page added.

### Added
- `insured_market`: premium written, cover, lives and death claims by year for the market and for
  traditional term (premium per 1,000 of cover; claims reported and paid as a share of premium).
- A business-impact section in `docs/insured-lives.md` and the README: price at the same target
  return, return at measured mortality, room in the market and claims volatility against book size.
- A scheduled workflow (`keep-alive.yml`) that opens the live dashboard in a browser every six hours.

### Fixed
- The experience study no longer reads an unrecognised `status` (for example `Death`) as a non-death exit: values are trimmed and upper-cased, and any other value is excluded and shown in the checks and the reconciliation.
- The dashboard caps its cache of uploaded studies (3 entries, one hour) and the upload size (25 MB), and opens its database read-only.
- `pypdf` 6.21.2, which fixes three published vulnerabilities.
- `median_age_at_death` returns NaN, not the first age, when survival never falls to one half.
- Cut-off metric values on the overview and Insured lives pages, and the "one fifth to one
  seventh" wording, which did not match the 14% to 25% found.

## [2.0.0] - 2026-10-22

**The insured-lives table**: a mortality table for pricing quotes, built from the CNSF's own
individual life statistics instead of the whole population. Version 1's population table is kept
as the reference for population questions.

### Added
- Ingestion of the CNSF individual life statistics: Excel workbooks 2021 to 2025 and the older
  Access databases 2018 to 2020 (read through the Windows ODBC driver from PowerShell, with no
  extra Python package), with control totals summed from the raw cells.
- A table family: traditional term, credit life, and whole life and endowment are graduated on
  their own; other term modalities are an age-varying multiple of traditional term; the
  market-wide and term tables are exposure-weighted blends. Direct and relational P-splines,
  Gompertz-Makeham and Brass are compared by quasi-AIC (one common dispersion) and out-of-sample
  shape; one credible range per product, extended to the population above it.
- Comparisons with the population, CNSF 2013, the US 2017 Unloaded CSO and nine national tables:
  premiums, the insured/population gap, the closest national table, Brass shift and tilt.
- Analyses: improvement rates, the pandemic in insured lives, amount against count, causes of
  claims, why the 2018 to 2020 format is not pooled, a one-at-a-time sensitivity of the premium to
  every modelling choice, and a margin (15%) sized from the adverse readings.
- 13 new figures, a dashboard page ("Insured lives"), `docs/insured-lives.md` with a log of
  every decision, and 22 new data checks.
- The stress test replays 2021 *as insured lives lived it*.

### Found in the data (and handled)
- One death claim in five has no age or sex: an adjustment ledger of settlements and
  cancellations, not deaths. Excluded; the readings that add it back are sensitivities.
- About 2,300 claims blamed on a sprained ankle are endowment maturities booked under the death
  cover (ages 60 to 69, 3.6 times a normal claim). Excluded.
- Deaths are measured against the lives holding the death cover, not every life.
- Insured lives were not shielded from COVID-19: up to 2.7 times their 2023 death rate in 2021.

### Changed
- The warehouse build order puts the insured modules that need the population projection after
  it. The bundle allow-list carries the insured tables and drops every row that holds HMD data.

## [1.0.0] - 2026-10-22

The **population study**: Mexico's mortality rebuilt from INEGI registered deaths and CONAPO
population, then used the way an insurer or a reinsurer would use it.

### Added
- Ingestion of INEGI deaths (2014 to 2024), CONAPO population (1950 to 2070), the CNSF 2013
  regulatory tables, SOA tables and Human Mortality Database countries, into a SQLite warehouse
  with a SHA-256 manifest and 100 automatic data checks.
- Data quality: age-heaping tests, allocation of unknown ages and sexes, chain-ladder completion of
  late registrations, COVID-19 flags.
- Crude rates, standardised rates, state SMRs and benchmarks against CNSF, SOA and HMD tables.
- Graduation (P-spline, Whittaker-Henderson, Heligman-Pollard, Gompertz-Makeham) with a Kannisto
  closure of the old ages.
- Life tables and commutation functions, validated against HMD and CONAPO.
- Lee-Carter and CBD projection in Python, cross-checked against StMoMo in R, with a backtest.
- An insurer-style experience study (A/E, credibility, Poisson GLM, select period, claims lag)
  validated on a synthetic portfolio with planted effects.
- Applications: excess mortality 2020 to 2022, pricing and reserves of a term product, pandemic and
  longevity stress tests, reinsurance structures and a longevity swap.
- A Streamlit dashboard (nine pages), an Excel workbook with live commutation formulas, and a
  Quarto methodology report.

### Known limit that motivates 2.0
- The table describes the **whole Mexican population**. People who buy individual life insurance
  die less than the national average, so this table is the right base for population questions
  (life expectancy, excess mortality, longevity) but too heavy a base for pricing a life quote.
  Version 2.0 adds a table built from CNSF individual life insurance statistics.

[1.0.0]: https://github.com/deadmigue55/Mortality-Table-Builder/releases/tag/v1.0.0
