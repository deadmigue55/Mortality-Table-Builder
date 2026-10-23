# 2. Data, exposure and quality

> [!NOTE]
> **In one minute.** Every rate in this project is a count of deaths over a count of years lived, so everything depends on getting those two counts right. This chapter covers what is counted and who is left out; how to tell whether ages on death certificates were rounded; how to deal with deaths whose sex or age is missing; how to complete the most recent year, whose late-registered deaths have not arrived yet (the **chain-ladder** method, borrowed from claims reserving); and how, for an insurer's own policies, to turn dates into exact exposure (the **Lexis split**). Each correction is small, but each one is made openly, in its own column, so that nothing is hidden.
>
> **What this chapter does:** it turns the raw INEGI death records and CONAPO population into the **analysis-ready** table of deaths and exposure that [chapter 3](03-crude-rates.md) divides.
>
> **The number to remember.** Late registration adds **2.27%** to the deaths of 2024 and at most 0.32% to any earlier year, and missing sex and age add 0.45% to 0.61% in every year. The 2024 estimate is 814,221 deaths, within 1% of the 820,400 that CONAPO projects independently.

Code: `src/mortality/quality.py` and `src/mortality/lexis.py` · Tests: `tests/test_quality.py`, `tests/test_lexis.py` and `tests/test_handbook_data.py` · Results: [data-quality.md](../data-quality.md)

**Local symbols** (everything else is in the [notation](01-notation.md)). $`R_{s,x}`$ are recorded deaths of sex $`s`$ at age (or age group) $`x`$; $`U_x`$ deaths of unknown sex at age $`x`$; $`V_s`$ deaths of unknown age and sex $`s`$; $`W`$ deaths of unknown sex and age. $`C_{y,l}`$ are cumulative deaths of occurrence year $`y`$ registered by lag $`l`$. $`f_l`$ and $`\tau`$ are development and tail factors.

**Contents.** [2.1](#21-what-is-counted) scope · [2.2](#22-do-certificates-round-ages-heaping-indices) heaping · [2.3](#23-deaths-with-missing-sex-or-age) unknowns · [2.4](#24-late-registration-the-chain-ladder) late registration · [2.5](#25-the-pandemic-flag) pandemic flag · [2.6](#26-exposure-from-dates-the-lexis-split) Lexis · [2.7](#27-examples-you-can-check-by-hand) examples · [2.8](#28-validation) validation · [2.9](#29-code-map) code map · [2.10](#210-limits) limits

---

## 2.1 What is counted

**Deaths** come from the INEGI death-certificate microdata, one record per death: 4,676,249 records in the files for 2020 to 2024. Each record carries the year and month the death *occurred*, the state of residence, sex and age. **Exposure** comes from CONAPO's mid-year population ([section 3.1](03-crude-rates.md#31-exposure-and-the-central-rate)). A rate is only meaningful when the people in the numerator are the people in the denominator, so the first decision is **scope**: who counts.

| Group (by state of residence) | Share of deaths, 2020 to 2024 | Treatment |
|---|--:|---|
| Residents of the 32 states | 98.6% to 99.0% | counted |
| State of residence unspecified (code 99) | 0.9% to 1.2% | **counted nationally**: they died in Mexico and almost all are residents |
| Known residents abroad (codes 33 to 35) | 0.10% to 0.21% | excluded: the population does not include them |

An early version dropped the unspecified-residence deaths, which understated every national rate by about 1%. They are kept in national tables (and would have to be spread across states for state tables).

## 2.2 Do certificates round ages? Heaping indices

When ages are reported carelessly, records pile up on ages ending in 0 and 5 (**age heaping**, a kind of digit preference). It matters here because graduation ([chapter 4](04-graduation.md)) should remove random noise, not systematic rounding. Three standard indices measure it. Throughout, $`c_a`$ is the number of records at single age $`a`$.

**Whipple's index.** The share of records on ages ending in 0 or 5, scaled so that no preference gives 100:

$$
\mathrm{Whipple} = 500 \times \frac{\sum_{a \in \{25, 30, \dots, 60\}} c_a}{\sum_{a=23}^{62} c_a}. \tag{2.1}
$$

Eight of the forty ages from 23 to 62 end in 0 or 5, exactly a fifth, so a flat age profile scores $`500 \times \tfrac{8}{40} = 100`$; if *every* record sat on a 0 or a 5 the score would be 500. The United Nations scale reads below 105 as "highly accurate", below 110 "fairly accurate", below 125 "approximate", below 175 "rough" and above that "very rough". Because the eight heaped ages have the same average age (42.5) as the forty, any *straight-line* trend in the profile cancels exactly: the index is 100 for every linear profile. A smooth curve moves it by less than a point (a death profile rising 9% per year of age scores 99.2).

**Myers' blended index.** Whipple looks at two digits and one age range. Myers' index looks at all ten terminal digits over ages 10 to 99 and removes the effect of a changing age profile. For each digit $`d`$, count the records on ages ending in $`d`$ twice: from age 10 up and from age 20 up, then blend the two with weights that cancel a linear change in the profile:

$$
B_d = (d+1)\sum_{k=1}^{8} c_{10k+d} \;+\; (9-d)\sum_{k=2}^{9} c_{10k+d}, \qquad \mathrm{Myers} = \frac12 \sum_{d=0}^{9}\left| \frac{100\, B_d}{\sum_j B_j} - 10 \right|. \tag{2.2}
$$

With no digit preference each digit takes 10% of the blended total and the index is 0; if every record is on one digit it is 90. The weights $`(d+1)`$ and $`(9-d)`$ are what make the index exactly 0 for any straight-line profile, so a falling or rising age distribution is not mistaken for heaping.

**Noumbissi's index.** For one digit $`d`$ (in practice 0 and 5), compare its ages with the average of their two neighbors:

$$
N_d = \frac{\sum_{a \in A_d} c_a}{\tfrac13\sum_{a \in A_d}\left(c_{a-1} + c_a + c_{a+1}\right)}, \qquad A_d = \{a \in [20, 69] : a \equiv d \pmod{10}\}. \tag{2.3}
$$

It is 1 when the digit is not preferred, above 1 when it is. For a straight-line profile the neighbors' average equals the center, so $`N_d = 1`$ exactly.

> [!NOTE]
> The population from CONAPO is **not** evidence of anything here: it is a smoothed model output, which is why its Myers index is the lowest of all. These indices are applied to deaths.

## 2.3 Deaths with missing sex or age

Some certificates have no sex, no age, or neither. Dropping them would understate every rate; the project instead allocates them **in proportion** to what is known, in three steps and in this order, within each year. Let $`R_{s,x}`$ be the recorded deaths of sex $`s \in \{M, F\}`$ at age $`x`$.

**Step 1: unknown sex, known age.** The $`U_x`$ deaths at age $`x`$ are split between men and women as the known deaths at that age are (as the whole year is split if that age has no known deaths, with $`\pi_M = \sum_x R_{M,x} / \sum_{s,x} R_{s,x}`$):

$$
A^{(1)}_{M,x} = U_x\,\frac{R_{M,x}}{R_{M,x} + R_{F,x}}, \qquad A^{(1)}_{F,x} = U_x - A^{(1)}_{M,x}. \tag{2.4}
$$

**Step 2: known sex, unknown age.** With $`T = R + A^{(1)}`$ the table so far, the $`V_s`$ deaths of sex $`s`$ are spread over ages as that sex's deaths are:

$$
A^{(2)}_{s,x} = V_s\,\frac{T_{s,x}}{\sum_{x'} T_{s,x'}}. \tag{2.5}
$$

**Step 3: unknown sex and age.** With $`T' = T + A^{(2)}`$, the $`W`$ deaths are spread over the whole sex-by-age table:

$$
A^{(3)}_{s,x} = W\,\frac{T'_{s,x}}{\sum_{s',x'} T'_{s',x'}}. \tag{2.6}
$$

The adjusted deaths keep every correction in its own column, so nothing is hidden, and no death is created or lost:

$$
\mathrm{adjusted}_{s,x} = R_{s,x} + A^{(1)}_{s,x} + A^{(2)}_{s,x} + A^{(3)}_{s,x}, \qquad \sum_{s,x}\mathrm{adjusted}_{s,x} = \sum R + \sum_x U_x + \sum_s V_s + W. \tag{2.7}
$$

The assumption is that a missing label is unrelated to the person's sex and age (missing at random; Rubin, 1976). The corrections add 0.45% to 0.61% of each year's deaths, so any error from the assumption is a small fraction of that. The hand-exported tables for 2014 to 2019 use a simpler version of the same idea ([section 3.5](03-crude-rates.md#35-unknown-sex-and-unknown-age)).

## 2.4 Late registration: the chain ladder

A death is registered some time after it occurs, and each yearly INEGI file contains deaths from earlier years registered late. Deaths of year $`y`$ keep arriving in the files for $`y+1`$, $`y+2`$, and so on, so **the latest year is always incomplete**. This is exactly the shape of an insurer's claims-development triangle (a claim is reported some time after the loss), so the actuarial **chain-ladder** method applies.

**The triangle.** Rows are the year of occurrence $`y`$, columns the **lag** $`l`$ (the year of the file minus the year of occurrence, so lag 0 means registered in the year of death). Let $`D_{y,l}`$ be the deaths registered at lag $`l`$ and

$$
C_{y,l} = \sum_{j \le l} D_{y,j} \tag{2.8}
$$

the cumulative deaths. Registration depends strongly on age (infants are registered almost on time, the very old and records of unknown age much later), so there is **one triangle per age band**: 0, 1-14, 15-29, 30-44, 45-64, 65-79, 80+ and "unknown".

**Development factors.** The chain-ladder assumption is that later registrations are proportional to what has arrived so far, $`E[C_{y,l+1} \mid C_{y,l}] = f_l\, C_{y,l}`$, with a factor depending only on the lag. The **volume-weighted** estimate uses every occurrence year seen at both lags:

$$
\hat f_l = \frac{\sum_y C_{y,l+1}}{\sum_y C_{y,l}}. \tag{2.9}
$$

This is not an arbitrary average: it is the weighted least-squares slope through the origin, the value of $`f`$ that minimizes $`\sum_y (C_{y,l+1} - f\,C_{y,l})^2 / C_{y,l}`$ (Mack, 1993), so large years count in proportion to their size.

**Completion.** For an occurrence year seen up to lag $`k_y`$, the estimated final count is the reported count times the product of the remaining factors and a tail factor $`\tau`$ for deaths registered after the last observed lag:

$$
\hat C_y = C_{y,k_y} \times F_y, \qquad F_y = \tau \prod_{l \ge k_y} \hat f_l. \tag{2.10}
$$

The **tail** covers deaths registered five or more years after occurrence, which no file in the triangle can show. It is estimated from the older years whose registration is essentially complete, as the late deaths $`L`$ over the registered base $`B`$:

$$
\tau = 1 + \frac{L}{B}. \tag{2.11}
$$

Here $`\tau = 1.00074`$ (from 2014 and 2015, where the late deaths are 0.066% and 0.081% of the year).

## 2.5 The pandemic flag

ICD-10 codes beginning `U07` (U07.1 and U07.2) are COVID-19. A year in which at least 1% of deaths carry such a code is flagged, so that models can leave it out of baselines:

$$
\mathrm{covid\ share}_y = \frac{\text{COVID-coded deaths in } y}{\text{all deaths in } y}, \qquad \text{COVID year} \iff \mathrm{share}_y \ge 0.01. \tag{2.12}
$$

Coded deaths undercount the pandemic's total toll (many were never tested), which is why chapter 9 measures the rest by excess mortality against a baseline.

## 2.6 Exposure from dates: the Lexis split

The population exposure of chapter 3 is approximate. For an insurer's own policies the exact dates are known, and exposure can be computed exactly. A policy is observed from an **entry** date to an **exit** date (death, lapse, expiry, or the end of the study). Mortality depends on three clocks that tick at different moments: the **policy duration** and the **attained age** change at each policy anniversary, and the **calendar year** changes on 1 January.

**The Lexis split** cuts each policy's observation period $`[\text{entry}, \text{exit})`$ at every policy anniversary and every 1 January. Inside a piece nothing changes, so every day of exposure, and every death, belongs to exactly one combination of age, duration and calendar year. The exposure of a piece is its length in years,

$$
t_{\text{piece}} = \frac{\text{end} - \text{start (in days)}}{365.25}, \qquad \sum_{\text{pieces of a policy}} t_{\text{piece}} = \frac{\text{exit} - \text{entry (in days)}}{365.25}, \tag{2.13}
$$

and the sum over pieces equals the observation time exactly (2.13): the cuts never create or destroy time. A policy with $`A`$ anniversaries and $`J`$ New Years strictly inside its period has $`1 + A + J`$ pieces (fewer when an anniversary falls on 1 January); only the **last** piece records an exit event.

**Why divide deaths by this exposure.** Assume the force of mortality is a constant $`\mu`$ inside a piece. A piece observed for time $`t`$ with death indicator $`\delta \in \{0, 1\}`$ contributes $`\mu^{\delta} e^{-\mu t}`$ to the likelihood: survive for time $`t`$, and if the life dies, die at rate $`\mu`$. For a group of pieces that share the same $`\mu`$,

$$
\log L(\mu) = \sum \left(\delta \log \mu - \mu\, t\right) = D \log \mu - \mu\, E, \qquad \hat\mu = \frac{D}{E}. \tag{2.14}
$$

The maximum-likelihood rate is **deaths over exact exposure**, the central rate of (3.1), and (2.14) is the Poisson likelihood of [section 4.1](04-graduation.md#41-the-model-deaths-are-poisson-counts) up to a constant. So the split makes $`\text{expected deaths} = \text{exposure} \times \text{rate}`$ *exact* for each cell, not an approximation. (Counting a year as 365.25 days means a policy observed for one non-leap year earns 0.9993 of exposure, an error of 0.07%, small and consistent across cells.)

## 2.7 Examples you can check by hand

**Heaping.** Take a flat age profile and then put three times as many records on ages ending in 0 or 5. Whipple's index becomes $`500 \times 24/(24 + 32) = 214.3`$ (24 = eight heaped ages at weight 3, 32 = the other thirty-two at weight 1); Noumbissi's index for digit 0 is $`3 / \tfrac{1+3+1}{3} = 1.8`$; Myers' index is $`22.9`$, since each of the digits 0 and 5 takes $`21.4\%`$ of the blended total instead of 10%.

**Allocating unknowns.** One year, ages 30 and 40. Recorded deaths $`R`$: men 60 and 90, women 20 and 30 (200 in all). Unknown: 20 deaths of unknown sex at age 30, 12 men of unknown age, 8 of unknown sex and age (40 in all).

| Step | Men 30 | Women 30 | Men 40 | Women 40 | Total |
|---|--:|--:|--:|--:|--:|
| Recorded | 60 | 20 | 90 | 30 | 200 |
| 1: 20 split 3 : 1 at age 30 (2.4) | +15 | +5 | | | 220 |
| 2: 12 men over $`(75, 90)`$ (2.5) | +5.455 | | +6.545 | | 232 |
| 3: 8 over the table, factor $`1 + 8/232`$ (2.6) | | | | | 240 |
| **Adjusted** | **83.229** | 25.862 | 99.875 | 31.034 | **240** |

In step 3 every cell is scaled by $`240/232 = 1.0345`$, for example men at 30: $`(75 + 5.455) \times 1.0345 = 83.229`$.

**Chain ladder.** Deaths at age 40 (band 30-44), registered by file year:

| Occurrence | Lag 0 | Lag 1 | Lag 2 | Cumulative at lag 0, 1, 2 |
|---|--:|--:|--:|---|
| 2020 | 1000 | 50 | 10 | 1000, 1050, 1060 |
| 2021 | 2000 | 100 | | 2000, 2100 |
| 2022 | 1500 | | | 1500 |

By (2.9), $`\hat f_0 = (1050 + 2100)/(1000 + 2000) = 1.05`$ and $`\hat f_1 = 1060/1050 = 1.00952`$ (only 2020 has lag 2). With no tail, the completion factors (2.10) are $`1`$ for 2020, $`\hat f_1 = 1.00952`$ for 2021 and $`\hat f_0 \hat f_1 = 1.05 \times 1060/1050 = 1.06`$ for 2022, so 2022's estimated final count is $`1500 \times 1.06 = 1590`$ and 2021's is $`2100 \times 1.00952 = 2120`$. With a tail of 1.01 every factor is multiplied by 1.01.

**Lexis.** A policy issued on 15 June 2018, observed until the death on 1 March 2020:

| Piece | From | To | Days | Duration | Calendar year | Exposure (years) |
|--:|---|---|--:|:-:|:-:|--:|
| 1 | 15 Jun 2018 | 1 Jan 2019 | 200 | 1 | 2018 | 0.54757 |
| 2 | 1 Jan 2019 | 15 Jun 2019 | 165 | 1 | 2019 | 0.45175 |
| 3 | 15 Jun 2019 | 1 Jan 2020 | 200 | 2 | 2019 | 0.54757 |
| 4 | 1 Jan 2020 | 1 Mar 2020 | 60 | 2 | 2020 | 0.16427 |

The four pieces add to 625 days, $`625/365.25 = 1.71116`$ years, the time from entry to exit (2.13). The death falls in piece 4, in duration 2 and calendar year 2020.

## 2.8 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_data.py`: the value of each index on flat, straight-line, heaped and extreme profiles; the allocation example and the conservation identity (2.7); the chain-ladder example, the least-squares property of (2.9) and the tail; and, for the Lexis split, the exact sum of pieces on 300 random policies, the one-duration-one-calendar-year property of every piece, the count of pieces against an independent enumeration of cut dates, and the maximum-likelihood property of (2.14).
2. **The data.** The quantities below are tested against the shipped database, apart from the scope shares and CONAPO's total, which need the full warehouse (they were computed there on the day of writing).

| Year | Reported (sex and age known) | Late registration added | Unknown allocated | **Adjusted** | Late deaths still missing, as a share of those registered |
|---|--:|--:|--:|--:|--:|
| 2020 | 1,086,923 | 802 | 5,348 | **1,093,073** | +0.07% |
| 2021 | 1,111,210 | 1,372 | 5,068 | **1,117,650** | +0.13% |
| 2022 | 837,037 | 1,553 | 5,167 | **843,757** | +0.20% |
| 2023 | 791,387 | 2,334 | 4,335 | **798,055** | +0.32% |
| 2024 | 792,709 | 17,301 | 4,212 | **814,221** | **+2.27%** |

(Rows can differ from the adjusted column by one death because of rounding; the last column is the completion of section 2.4 measured on the deaths registered so far.) The first-year development factor by age band (lag 0 to 1) is 1.002 for infants, 1.012 to 1.019 for ages 1 to 79, 1.024 at 80 and over and **1.181 for records of unknown age**: 18% of those arrive a year late. The lag-1 registrations are 1.6% to 2.3% of lag 0 in each year, which makes the 2024 completion uncertain by roughly 0.35%.

3. **An independent check.** CONAPO projects 820,400 deaths for 2024, within 1% of the 814,221 estimated here.
4. **Heaping.** INEGI deaths show essentially no heaping in any year from 2020 to 2024: Whipple 98 to 101 ("highly accurate"), Myers 0.4 to 0.9, Noumbissi 0.98 to 1.02, comparable to the Human Mortality Database countries. (Chapter 4 finds a small digit preference in men's deaths, a 1.25% to 2.46% excess at ages ending in 0 and 5, that these averaged indices cannot see.)
5. **The pandemic flag.** COVID-coded deaths are 18.4% (2020), 21.3% (2021), 4.5% (2022), 0.6% (2023) and 0.2% (2024) of all deaths, so 2020 to 2022 are flagged and 2023 is the first clean year.

## 2.9 Code map

| Formula | Function | Checked by (`tests/test_handbook_data.py`) |
|---|---|---|
| (2.1) | `quality.whipple_index`, `whipple_class` | `test_whipple_counts_the_fifth_of_ages_that_end_in_0_or_5`, `test_whipple_is_exactly_100_for_any_straight_line_profile`, `test_whipple_scale_classes` |
| (2.2) | `quality.myers_index` | `test_myers_blend_is_zero_for_any_straight_line_and_ninety_at_the_extreme`, `test_myers_blended_tallies_by_hand_for_one_digit` |
| (2.3) | `quality.noumbissi_index` | `test_noumbissi_compares_a_digit_with_its_neighbours` |
| (2.4), (2.5), (2.6) | `quality.allocate_unknowns` | `test_allocation_toy_example_step_by_step`, `test_allocation_without_known_deaths_at_an_age_uses_the_whole_year_split` |
| (2.7) | `quality.allocate_unknowns` | `test_allocation_conserves_every_death_and_adds_up_column_by_column` |
| (2.8) | `quality.build_triangle`, `age_band` | `test_chain_ladder_toy_example`, `test_age_bands_cover_every_age_once` |
| (2.9) | `quality.chain_ladder_factors` | `test_the_volume_weighted_factor_is_the_weighted_least_squares_slope` |
| (2.10), (2.11) | `quality.completion_factors`, `tail_factor`, `complete_cells` | `test_the_tail_factor_multiplies_every_completion_factor`, `test_complete_cells_scales_reported_deaths_by_the_age_band_factor` |
| (2.12) | `quality.COVID_SHARE_THRESHOLD` | `test_a_year_is_a_covid_year_from_one_percent_coded_deaths` |
| (2.13) | `lexis.lexis_split` | `test_lexis_toy_example_pieces_and_days`, `test_pieces_add_up_to_the_observation_time_for_random_policies`, `test_each_piece_sits_inside_one_duration_and_one_calendar_year`, `test_the_number_of_pieces_is_one_plus_the_cut_dates_inside` |
| (2.14) | the experience study (chapter 7) | `test_the_central_rate_is_the_maximum_likelihood_estimate` |
| Section 2.8, tables | `quality.build_tables` | `test_chapter_numbers_match_the_database` |

To reproduce the Lexis example of section 2.7:

```python
import numpy as np
from mortality.lexis import lexis_split

day = lambda s: np.array([s], dtype="datetime64[D]")
print(lexis_split(day("2018-06-15"), day("2018-06-15"), day("2020-03-01")))
```

## 2.10 Limits

- **Single-year ages before 2020.** The 2014 to 2019 data are five-year groups by year of registration; no row-level files for those years were found at any address INEGI serves, so single-age rates and graduation start in 2020.
- **Missing at random.** The allocation of unknown sex and age assumes the missing label carries no information. It adds under 0.7% of deaths a year, but it is an assumption.
- **The chain ladder assumes stable development.** The lag-1 share has varied between years, lag-3 factors rest on a single year, and the 2024 completion carries an uncertainty of about 2,800 deaths (0.35%). The table `registration_completion` keeps the pieces, so any assumption can be changed and the build rerun. The method gives a point estimate; it does not give a prediction interval.
- **The heaping indices average over age ranges and over both sexes.** A rounding effect confined to one sex, such as the small one found in chapter 4, can hide inside a "highly accurate" index.
- **The tail is estimated from two years.** Deaths registered five or more years late are 0.07% of the total; even a large error in that estimate moves no figure by more than a few hundred deaths.
- **Exposure by date is exact only for the policies in the extract.** If the extract omits lives or misdates exits, the split reproduces the error exactly: it cleans no data, it only avoids adding a second source of error. Chapter 7 validates the extract before the split.

## References

- Whipple, G. C. (1919). *Vital Statistics: An Introduction to the Science of Demography*. Wiley.
- Myers, R. J. (1940). Errors and bias in the reporting of ages in census data. *Transactions of the Actuarial Society of America* 41, 395-415.
- Noumbissi, A. (1992). L'indice de Whipple modifié: une application aux données du Cameroun, du Togo et du Burundi. *Population* 47(4), 1038-1041.
- Siegel, J. S. and Swanson, D. A. (2004). *The Methods and Materials of Demography*, 2nd ed. Elsevier. (Age heaping and its indices.)
- Rubin, D. B. (1976). Inference and missing data. *Biometrika* 63(3), 581-592.
- Mack, T. (1993). Distribution-free calculation of the standard error of chain ladder reserve estimates. *ASTIN Bulletin* 23(2), 213-225.
- Keiding, N. (1990). Statistical inference in the Lexis diagram. *Philosophical Transactions of the Royal Society A* 332, 487-509.
