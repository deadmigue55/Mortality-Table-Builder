# R scripts

R is used where its packages are the industry reference, mainly **StMoMo** for stochastic mortality projection (Lee–Carter, CBD) and **MortalityLaws** for parametric laws. Results are cross-checked against the Python implementation.

R reads and writes the same DuckDB database as Python (`data/mortality.duckdb`), so the two never pass files around by hand.

## Setup

```sh
Rscript r/install_packages.R
```

This installs only missing packages into your personal R library and reports each package's version.

## Notes

- **Windows Smart App Control** can block some compiled package files (seen with `cli.dll`). The project's core packages load and run without it, and Human Mortality Database downloads are done in Python, so no R download package is needed.
