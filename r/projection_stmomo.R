# Independent check of the Python projection models with StMoMo.
#
# Reads the long file written by mortality.projection.run_r_crosscheck, fits Lee-Carter and
# Cairns-Blake-Dowd (M5) per sex with StMoMo (a different fitting routine: gnm), forecasts the
# central path as a random walk with drift, and writes CSVs the Python side compares with its own.
#
#   Rscript r/projection_stmomo.R <input.csv> <output_dir> <first_year> <last_year> <horizon>

args <- commandArgs(trailingOnly = TRUE)
input <- args[1]
out_dir <- args[2]
first_year <- as.integer(args[3])
last_year <- as.integer(args[4])
horizon <- as.integer(args[5])

lib <- Sys.getenv("R_LIBS_USER")
if (nzchar(lib)) .libPaths(c(lib, .libPaths()))
suppressMessages({
  library(StMoMo)
  library(forecast)
})

dat <- read.csv(input)
ages <- 0:99
years <- first_year:last_year

as_data <- function(sex) {
  d <- dat[dat$sex == sex & dat$year >= first_year & dat$year <= last_year, ]
  d <- d[order(d$year, d$age), ]
  structure(
    list(
      Dxt = matrix(d$deaths, nrow = length(ages), dimnames = list(ages, years)),
      Ext = matrix(d$exposure, nrow = length(ages), dimnames = list(ages, years)),
      ages = ages, years = years, type = "central", series = sex, label = "Mexico"
    ),
    class = "StMoMoData"
  )
}

lc_params <- list(); lc_kt <- list(); lc_fc <- list(); cbd_kappa <- list(); cbd_fc <- list()

for (sex in c("M", "F")) {
  data <- as_data(sex)

  lc_fit <- suppressMessages(fit(lc(link = "log"), data = data, ages.fit = ages, verbose = FALSE))
  lc_f <- forecast(lc_fit, h = horizon)
  lc_params[[sex]] <- data.frame(
    sex = sex, age = ages, ax = as.numeric(lc_fit$ax), bx = as.numeric(lc_fit$bx)
  )
  lc_kt[[sex]] <- data.frame(sex = sex, year = years, kt = as.numeric(lc_fit$kt))
  fut <- (last_year + 1):(last_year + horizon)
  lc_fc[[sex]] <- data.frame(
    sex = sex,
    year = rep(fut, each = length(ages)),
    age = rep(ages, times = horizon),
    rate = as.numeric(lc_f$rates)
  )

  cbd_ages <- 60:99
  cbd_fit <- suppressMessages(fit(cbd(link = "logit"), data = data, ages.fit = cbd_ages, verbose = FALSE))
  cbd_f <- forecast(cbd_fit, h = horizon)
  cbd_kappa[[sex]] <- data.frame(
    sex = sex, year = years, kappa1 = cbd_fit$kt[1, ], kappa2 = cbd_fit$kt[2, ]
  )
  cbd_fc[[sex]] <- data.frame(
    sex = sex,
    year = rep(fut, each = length(cbd_ages)),
    age = rep(cbd_ages, times = horizon),
    rate = as.numeric(cbd_f$rates)
  )
}

write_all <- function(x, name) {
  write.csv(do.call(rbind, x), file.path(out_dir, name), row.names = FALSE)
}
write_all(lc_params, "lc_params.csv")
write_all(lc_kt, "lc_kt.csv")
write_all(lc_fc, "lc_forecast.csv")
write_all(cbd_kappa, "cbd_kappa.csv")
write_all(cbd_fc, "cbd_forecast.csv")
cat("StMoMo", as.character(packageVersion("StMoMo")), "done\n")
