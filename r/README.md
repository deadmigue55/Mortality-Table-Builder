# R scripts

R is used where its packages are the industry reference, mainly **StMoMo** for stochastic mortality projection (Lee–Carter, CBD) and **MortalityLaws** for parametric laws. Results are cross-checked against the Python implementation.

R reads the same processed data as Python. The Python side loads everything into the SQLite warehouse (`data/mortality.sqlite`); R queries the Parquet files in `data/processed/` directly with the `duckdb` package, so the two never pass files around by hand:

```r
library(DBI); library(duckdb)
con <- dbConnect(duckdb())
dbGetQuery(con, "SELECT year, SUM(population) AS pop
                 FROM read_parquet('data/processed/conapo/population_mid_year.parquet')
                 WHERE state_code = 0 GROUP BY year")
```

## Setup

```sh
Rscript r/install_packages.R
```

This installs only missing packages into your personal R library and reports each package's version.

## Notes

- **Windows Smart App Control** can block some compiled package files. On the development machine it blocks `cli`, `RSQLite` (through `bit`), Python's `duckdb`, `cryptography` and `pdfium`. The core R packages (StMoMo, MortalityLaws, demography, lifecontingencies, mortSOA, duckdb) load and run, which is why R reads Parquet through `duckdb` rather than the SQLite file, and why Human Mortality Database downloads are done in Python.
