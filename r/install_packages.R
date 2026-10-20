# Installs the R packages used by this project (only the missing ones).
# Run from the project root:  Rscript r/install_packages.R

packages <- c(
  "StMoMo",           # stochastic mortality models: Lee-Carter, CBD, APC
  "MortalityLaws",    # parametric laws: Gompertz, Makeham, Heligman-Pollard, Kannisto
  "demography",       # demographic data structures, Lee-Carter variants, smoothing
  "lifecontingencies",# life tables, actuarial present values, commutation functions
  "mortSOA",          # read Society of Actuaries MORT tables by table ID
  "duckdb",           # read the project's DuckDB warehouse
  "DBI",
  "data.table",
  "ggplot2"
)

# Install into the personal library when the system library isn't writable
lib <- Sys.getenv("R_LIBS_USER")
if (!dir.exists(lib)) dir.create(lib, recursive = TRUE)
.libPaths(c(lib, .libPaths()))

repos <- c(CRAN = "https://cloud.r-project.org")
missing <- setdiff(packages, rownames(installed.packages()))

if (length(missing)) {
  message("Installing: ", paste(missing, collapse = ", "))
  install.packages(missing, lib = lib, repos = repos)
} else {
  message("All packages already installed.")
}

# Report what loaded
for (p in packages) {
  ok <- requireNamespace(p, quietly = TRUE)
  ver <- if (ok) as.character(packageVersion(p)) else "FAILED"
  message(sprintf("  %-18s %s", p, ver))
}

if (!all(vapply(packages, requireNamespace, logical(1), quietly = TRUE))) {
  quit(status = 1)
}
