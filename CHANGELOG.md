# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the versions follow
[Semantic Versioning](https://semver.org/).

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
