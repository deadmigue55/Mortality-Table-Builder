# Data quality

Step 3 asks whether the death and population data can be trusted before any rate is computed, and corrects what can be corrected. All numbers below are from the October 2026 build and are reproduced by `uv run mortality db build`.

The output is the table **`deaths_adjusted`**: national deaths by year of occurrence, sex and single age, with every correction in its own column so nothing is hidden:

`adjusted = reported + added_late_registration + added_unknown_sex + added_unknown_age + added_unknown_both`

| Year | Reported (sex and age known) | Late registration added | Unknown sex/age allocated | **Adjusted** |
|---|---:|---:|---:|---:|
| 2020 | 1,086,923 | 802 | 5,348 | **1,093,073** |
| 2021 | 1,111,210 | 1,372 | 5,068 | **1,117,650** |
| 2022 | 837,037 | 1,553 | 5,167 | **843,757** |
| 2023 | 791,387 | 2,334 | 4,335 | **798,055** |
| 2024 | 792,709 | 17,301 | 4,212 | **814,221** |

## 1. Who is counted (scope)

Rates divide deaths by the mid-year population of people living in Mexico, so the deaths must be the same people.

| Group | Share of deaths | Treatment |
|---|---:|---|
| Residents of the 32 states | 98.6% to 98.9% | counted |
| State of residence unspecified (code 99) | 0.9% to 1.3% | **counted nationally** (they died in Mexico; almost all are residents) |
| Known residents abroad (codes 33 to 35) | 0.10% to 0.21% | excluded |

An early version of the national table dropped the unspecified-residence deaths, which would have understated every national rate by about 1%. State-level tables will need those deaths spread across states; that belongs to the state analysis, not here.

## 2. Age heaping (do certificates round ages?)

When ages are reported carelessly, records pile up on ages ending in 0 and 5. Three standard indices measure it:

- **Whipple** (ages 23 to 62): 100 means no preference; the UN scale calls under 105 "highly accurate".
- **Myers** (ages 10 to 99): 0 means no preference, 90 is the maximum.
- **Noumbissi** (digits 0 and 5): compares those ages with their neighbours, so a rising trend in deaths is not mistaken for heaping. 1.00 means none.

| Dataset (2022; female / male) | Whipple | Myers |
|---|---|---|
| **INEGI deaths** | 98.2 / 99.8 | 0.85 / 0.53 |
| HMD Sweden | 95.6 / 103.0 | 1.00 / 1.06 |
| HMD Canada | 99.1 / 96.7 | 0.94 / 1.01 |
| HMD United States | 99.2 / 99.6 | 0.80 / 0.72 |
| HMD Chile | 97.9 / 103.1 | 1.31 / 1.12 |
| HMD Spain | 99.7 / 99.4 | 2.27 / 1.77 |
| CONAPO population | 100.0 / 100.0 | 0.14 / 0.11 |

**Finding:** Mexican death certificates show essentially no age heaping in any year from 2020 to 2024 (Whipple 98 to 101, Myers 0.4 to 0.9, Noumbissi 0.98 to 1.02), comparable to the Human Mortality Database comparison countries above. Smoothing in step 5 therefore has to remove random noise, not digit preference.

The CONAPO population is *not* evidence of anything here: it is a smoothed model output, which is why its Myers index is lowest of all.

## 3. Unknown sex and age

| | Share of deaths |
|---|---:|
| Unknown sex | 0.06% to 0.12% |
| Unknown age | 0.48% to 0.63% |

These deaths are allocated, not dropped, in this order, within each year:

1. **Unknown sex, known age:** split between men and women as the known deaths at that age are (or as the whole year is, if that age has no known deaths).
2. **Known sex, unknown age:** spread over ages as that sex's known deaths are.
3. **Unknown sex and age:** spread over the whole sex-by-age table.

This is the standard proportional method. It assumes the unknowns resemble the knowns, and it adds 0.45% to 0.61% of deaths a year, so any error from that assumption is a small fraction of that. The allocation creates or loses no death (tested, and checked on every build).

## 4. Late registration (a chain-ladder triangle)

Each yearly INEGI file also contains deaths from earlier years, registered late. Deaths of year *Y* therefore keep arriving in the files for *Y+1*, *Y+2* and so on, and the latest year is always incomplete. This is exactly the shape of an insurer's claims-development triangle, so the actuarial **chain-ladder method** applies.

| Occurrence year | Lag 0 | Lag 1 | Lag 2 | Lag 3 | Lag 4 | Lag 1 as % of lag 0 |
|---|---:|---:|---:|---:|---:|---:|
| 2020 | 1,068,865 | 20,586 | 1,504 | 731 | 581 | 1.93% |
| 2021 | 1,096,676 | 17,766 | 1,107 | 690 | | 1.62% |
| 2022 | 824,214 | 16,798 | 1,100 | | | 2.04% |
| 2023 | 777,593 | 17,927 | | | | 2.31% |
| 2024 | 796,123 | | | | | |

**Late registration depends strongly on age,** so there is one triangle per age band. The factor for the first year of development (lag 0 to 1):

| Age band | 0 | 1-14 | 15-29 | 30-44 | 45-64 | 65-79 | 80+ | Unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Factor | 1.002 | 1.012 | 1.015 | 1.016 | 1.016 | 1.019 | 1.024 | **1.181** |

Infants are registered almost on time; the very old are slower; records with **unknown age are the slowest of all** (18% arrive a year late). Sex makes no difference (1.92% for women, 1.94% for men).

**Method:** volume-weighted development factors per band and lag; a tail factor of **1.00074** for deaths registered five or more years later, estimated from 2014 and 2015 deaths (0.066% and 0.081% of each year's registered total) against the imported INEGI registration totals. The completion factor for a year is the product of the remaining development factors times the tail.

| Year | Reported | Estimated final | Missing |
|---|---:|---:|---:|
| 2020 | 1,092,267 | 1,093,073 | +0.07% |
| 2021 | 1,116,239 | 1,117,650 | +0.13% |
| 2022 | 842,112 | 843,757 | +0.20% |
| 2023 | 795,520 | 798,055 | +0.32% |
| 2024 | 796,123 | 814,221 | **+2.27%** |

**Check from outside:** CONAPO's independent projection for 2024 is 820,400 deaths, within 1% of the 814,221 estimated here.

**Limits:** the lag-1 share has varied from 1.6% to 2.3% between years, so the 2024 completion carries an uncertainty of roughly 2,800 deaths (0.35%); lag-3 factors rest on a single year; the method assumes development stays stable. The table `registration_completion` keeps the pieces, so any of these assumptions can be changed and rerun.

## 5. The pandemic years

ICD-10 codes beginning `U07` (U07.1, U07.2) are COVID-19. A year with at least 1% of its deaths coded that way is flagged in `year_flags`, so models can exclude it from baselines:

| Year | Deaths | COVID-coded | Share | COVID year |
|---|---:|---:|---:|:---:|
| 2020 | 1,093,398 | 201,280 | 18.4% | yes |
| 2021 | 1,117,935 | 238,093 | 21.3% | yes |
| 2022 | 843,782 | 38,189 | 4.5% | yes |
| 2023 | 797,216 | 4,625 | 0.6% | no |
| 2024 | 797,566 | 1,353 | 0.2% | no |

`deaths_by_cause_chapter` holds monthly counts by ICD-10 chapter, which shows the pandemic waves (for example 64,741 COVID-coded deaths in January 2021). Coded deaths undercount the pandemic's total toll; excess mortality against a pre-COVID baseline (step 9) captures the rest.

## 6. Registration year versus occurrence year

The imported 2014 to 2019 tables count deaths by year of **registration**, the row-level files by year of **occurrence**. Comparing the two for 2020 to 2024 (occurrence counts completed for late registration):

| Year | Registered in the year | Occurred in the year (adjusted) | Difference |
|---|---:|---:|---:|
| 2020 | 1,085,636 | 1,093,073 | -0.7% |
| 2021 | 1,120,588 | 1,117,650 | +0.3% |
| 2022 | 846,026 | 843,757 | +0.3% |
| 2023 | 798,166 | 798,055 | 0.0% |
| 2024 | 818,171 | 814,221 | +0.5% |

The bases differ by well under 1%, with 2020 lower on a registration basis because the first pandemic months delayed civil registration. Any series that mixes the two must say so. Step 4 uses the registration basis for 2014 to 2019 and the occurrence basis from 2020.

## What the checks guard

Every rule above is also an automatic check (see [warehouse.md](warehouse.md)): the adjustment identity, that no reported death is lost, that completion stays under 5% of any year, that unknowns stay under 2%, and that INEGI heaping stays below the "fairly accurate" line.

## Known gaps

- **Single-year ages before 2020.** The 2014 to 2019 data are five-year groups by registration year. Row-level files for those years were not found at any address INEGI serves.
- **State-level tables** need unspecified-residence deaths allocated across states.
