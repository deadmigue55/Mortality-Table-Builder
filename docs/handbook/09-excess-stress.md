# 9. Excess mortality and stress tests

> [!NOTE]
> **In one minute.** *Excess mortality* is how many more people died than would have died without a shock, and it has one difficulty: the comparison is with a counterfactual that nobody observed. This chapter measures the excess of the 2020 to 2022 pandemic with four different baselines and reports the range, then uses the shape of that shock to **stress-test** insurance books: what a repeat would cost a life insurer (claims rise), what a permanent rise in longevity would cost an annuity writer (reserves rise), and how far one book protects the other. The mathematics is small: a ratio, a regression, a weighted sum and an annuity. The care is in what is compared with what.
>
> **What this chapter does:** it turns the observed deaths of [chapter 3](03-crude-rates.md) into excess deaths, and the projections of [chapter 6](06-projection.md) and the life-table functions of [chapter 5](05-life-tables.md) into stress scenarios, with the policy book of the [experience study](07-experience-study.md) as the thing being stressed.
>
> **The number to remember.** About **746,000 more people died** in Mexico in 2020 to 2022 than a pre-pandemic baseline expects (the four baselines give 676,000 to 791,000), **1.56 times** the 477,562 deaths certified as COVID-19. Replaying 2021 on the life book would raise the next year's claims by **60%**, more than the **51%** the regulator's 99.5th-percentile table allows for.

Code: `src/mortality/excess.py` and `src/mortality/stress.py` · Tests: `tests/test_excess.py`, `tests/test_stress.py` and `tests/test_handbook_excess_stress.py` · Results: [excess-mortality.md](../excess-mortality.md) and [stress-tests.md](../stress-tests.md)

> [!IMPORTANT]
> The **shocks** are real: the excess profile is Mexico's own, and the improvement scenarios come from chapter 6. The **books** are illustrative: the life book is the synthetic portfolio of chapter 7 and the annuity block is invented (20,000 pensioners aged 60 to 95, a pension of 120,000 a year, 60% men). Nothing here describes a real company.

**Local symbols** (everything else is in the [notation](01-notation.md)). $`O`$ and $`E`$ are observed and expected deaths; $`P`$ the P-score; $`d`$ the dampening and $`s`$ the severity of a replay; $`\mathrm{SA}`$ the sum assured; $`\pi`$ the annual pension; $`w_x`$ the share of annuitants at age $`x`$.

**Contents.** [9.1](#91-excess-deaths-and-the-p-score) excess · [9.2](#92-four-baselines) baselines · [9.3](#93-the-central-estimate-its-range-and-years-of-life-lost) range · [9.4](#94-by-cause-by-month-by-state) cause, month, state · [9.5](#95-replaying-the-pandemic-on-a-life-book) replay · [9.6](#96-longevity-an-annuity-block) longevity · [9.7](#97-the-hedge-between-the-two-books) hedge · [9.8](#98-examples-you-can-check-by-hand) examples · [9.9](#99-validation) validation · [9.10](#910-code-map) code map · [9.11](#911-limits) limits

---

## 9.1 Excess deaths and the P-score

For an age band $`b`$ and year $`y`$, with $`O`$ observed deaths and $`E`$ the deaths a baseline expects,

$$
\mathrm{excess} = O - E, \qquad P = \frac{O - E}{E}. \tag{9.1}
$$

The **P-score** is the excess as a share of what was expected: $`P = 0.45`$ means 45% more deaths than normal. Everything depends on $`E`$, which is a *counterfactual*: the deaths that would have occurred if the pandemic had not. One baseline gives one number that looks more certain than it is, so this chapter builds four and reports the range. Observed deaths are INEGI's by year of occurrence, completed for late registration ([chapter 2](02-data-exposure-quality.md#24-late-registration-the-chain-ladder)); the exposure is CONAPO's mid-year population; everything is by five-year band and sex.

## 9.2 Four baselines

**Flat 2019.** Every band keeps its 2019 death rate, so the expected deaths are the 2019 rate times the year's exposure:

$$
E_{b,y} = m_{b,2019}\ \mathcal{E}_{b,y}. \tag{9.2}
$$

**Trend 2014 to 2019.** Within each band fit a log-linear trend to the six pre-pandemic years by Poisson regression and carry it forward:

$$
\ln m_{b,t} = a_b + \beta_b\,(t - \bar t), \qquad E_{b,y} = \mathcal{E}_{b,y}\exp\!\left(a_b + \beta_b\,(y - \bar t)\right), \qquad \bar t = 2016.5. \tag{9.3}
$$

The Poisson fit has the conservation law of (4.14), (6.4) and (7.11): the score equations are $`\sum_t (D_t - \mu_t) = 0`$ and $`\sum_t (t - \bar t)(D_t - \mu_t) = 0`$, so the trend reproduces the pre-pandemic total of every band and its time-weighted total. The standard error of the expected deaths comes from the covariance of the fit, with a dispersion pooled over all bands (a single band has only six years from which to estimate one); because the trend is extrapolated, the uncertainty grows with the distance from the fitted years.

**Interpolation to 2023.** The recovery is a second anchor: the log rate moves in a straight line from its 2019 value to its observed 2023 value,

$$
w_y = \frac{y - 2019}{2023 - 2019}, \qquad \ln m_{b,y} = (1 - w_y)\ln m_{b,2019} + w_y\ln m_{b,2023}, \tag{9.4}
$$

so the rate in 2021 is the *geometric mean* of the two. This baseline equals the observed deaths in 2023 by construction, which is why 2023 cannot be used to test it.

**Lee-Carter.** The pre-pandemic trend of CONAPO's 1970 to 2019 series ([chapter 6](06-projection.md#62-the-lee-carter-model)), restarted at CONAPO's 2019 rates, combined from single ages into the five-year bands with CONAPO's population as weights, and then **scaled band by band** to the INEGI level of 2019:

$$
E_{b,y} = \underbrace{\bar m^{\,\mathrm{LC}}_{b,y}}_{\text{banded Lee-Carter path}}\ \times\ \underbrace{\frac{m^{\mathrm{INEGI}}_{b,2019}}{m^{\mathrm{CONAPO}}_{b,2019}}}_{\text{scale}}\ \times\ \mathcal{E}_{b,y}. \tag{9.5}
$$

The scale matters: INEGI and CONAPO agree on the total but not on who dies (for men aged 15 to 39 INEGI-based rates imply 34% fewer deaths than CONAPO's models, chapter 6), and a CONAPO baseline against INEGI deaths would invent an age pattern in the excess. The baseline is proportional to the scale and to the exposure, so rescaling it to the INEGI footing changes the level of each band and nothing else.

## 9.3 The central estimate, its range and years of life lost

For each band the **central** expected deaths are the median of the four baselines; the lowest and highest give the range:

$$
E^{c} = \operatorname{median}\{E^{(1)}, \dots, E^{(4)}\}, \qquad \mathrm{excess}^{c} = O - E^{c}, \qquad \mathrm{excess}\in\bigl[\,O - E^{\max},\ O - E^{\min}\,\bigr]. \tag{9.6}
$$

The highest baseline gives the *lowest* excess. The sampling noise of the excess combines the Poisson noise of the observed count with the standard error of the trend baseline, in quadrature (the only baseline that has one):

$$
\mathrm{se} = \sqrt{O + \mathrm{se}_{\text{trend}}^{2}}. \tag{9.7}
$$

Totals add the bands, with the standard errors added in quadrature and the P-score recomputed as total excess over total expected. The excess becomes **years of life lost** by weighting each band by the remaining life expectancy of a reference life table ([chapter 5](05-life-tables.md#53-person-years-and-life-expectancy), the 2023 table):

$$
\mathrm{YLL} = \sum_{b}\ \mathrm{excess}_b\ \mathring{e}_b. \tag{9.8}
$$

**How far to trust the baselines.** Two built-in checks. First, **they agree with each other**: the spread (the sum over bands of the highest baseline minus the sum of the lowest, over the central) is 2.6% of expected deaths in 2020, 5.0% in 2021 and 7.4% in 2022, and widens to 9.7% in 2023 and 12.1% in 2024: the counterfactual becomes less certain the farther it is carried, which is the right behavior. Second, **they predict 2023**: after the pandemic, mortality should be back on the baseline. The observed 2023 deaths are 2.2% below the flat 2019 baseline, 3.7% below the trend, 2.0% above the Lee-Carter baseline and 0.5% below the central one (the interpolation is anchored there).

## 9.4 By cause, by month, by state

**By cause chapter.** There is no pre-pandemic cause-of-death microdata in the project, so the only baseline for a cause is the post-pandemic year 2023, scaled by population growth; COVID-19 has none (its baseline is zero):

$$
E_{c,y} = D_{c,2023}\ \frac{\mathrm{Pop}_y}{\mathrm{Pop}_{2023}} \quad (c \ne \text{COVID-19}), \qquad E_{\text{COVID-19},y} = 0. \tag{9.9}
$$

A cause already rising before 2020 (diabetes, heart disease) is under-counted, so the result is a *lower bound* on pandemic-related excess for those causes, and a statement about where the extra deaths were certified, not about what caused them.

**By month.** The baseline of a pandemic month is the year's central baseline times that month's average share of the year in the post-pandemic years, so winter peaks are not mistaken for excess:

$$
E_{y,m} = E^{c}_{y}\ \bar s_m, \qquad \bar s_m = \operatorname*{mean}_{y \in \{2023, 2024\}}\frac{D_{y,m}}{\sum_{m'} D_{y,m'}}, \qquad \sum_m \bar s_m = 1. \tag{9.10}
$$

**By state.** Each state's own five-year-band death rates of 2023 are applied to each pandemic year's population, which removes the state's age structure and population growth:

$$
E_{s,y} = \sum_{b}\mathcal{E}_{s,b,y}\ m_{s,b,2023}. \tag{9.11}
$$

This is excess relative to 2023, not to a pre-pandemic trend (no state-level history exists before 2020; nationally 2023 is within a few percent of trend).

## 9.5 Replaying the pandemic on a life book

The stress test is deliberately simple, so that it can be defended in front of a committee. Each policy in force has a probability of dying in the next twelve months, $`q_i`$, on the company's own basis (the experience-study table times its multipliers). The replay raises it by the **P-score** of the policy's age and sex in the chosen pandemic year. The P-score is defined by five-year bands (9.1); it is spread over the single ages of each band, the open band takes all older ages, and a negative score is set to zero, because a stress test gets no credit for the bands where deaths fell below the baseline:

$$
P_x = \max\bigl(P_{b(x)},\ 0\bigr). \tag{9.12}
$$

With two knobs, the **dampening** $`d`$ (an insured population is healthier than the general one, so its excess may be smaller: 1 takes the population's excess, 0.5 half of it) and the **severity** $`s`$ (a multiple of the observed profile, a worse pandemic), the stressed probability and claims are

$$
q'_i = \min\!\left(q_i\,\bigl(1 + d\,s\,P_{x_i}\bigr),\ 1\right), \qquad \text{claims} = \sum_i \mathrm{SA}_i\,q'_i, \qquad \text{extra claims} = d\,s\sum_i \mathrm{SA}_i\,q_i\,P_{x_i}\ \ \text{(until a } q' \text{ reaches 1).} \tag{9.13}
$$

Only the **product** $`d \times s`$ matters: halving the dampening halves the extra claims and doubling the severity doubles them, which is how the replays at half the excess and at 1.5 and 2 times it relate to the full one. The cap at certain death binds only at the very oldest ages.

**As insured lives lived it.** Version 2 of the project replaces the assumption about dampening with data: the insured lives' own death rates by age band ([chapter 11](11-insured-lives.md)). The P-score of a band is that year's rate relative to 2023, minus one, never below zero, and the ages outside the first and last band take the nearest band's value so that the whole book is stressed:

$$
P_b^{\text{insured}} = \max\!\left(\frac{m^{\text{insured}}_{b,y}}{m^{\text{insured}}_{b,2023}} - 1,\ 0\right). \tag{9.14}
$$

**The regulator's yardstick.** The shock the regulator expects a company to withstand is the 99.5th-percentile variant of the CNSF table. Its extra claims on the same book are $`\sum \mathrm{SA}_i\,(q^{99.5}_i - q_i)`$, the comparison for every replay.

## 9.6 Longevity: an annuity block

Longevity is the other risk: a permanent fall in mortality, which costs an annuity writer reserves. The reserve of one annuitant of age $`x`$ is an annuity-due paying 1 at the start of each year while alive. From the probabilities of death in each future year, $`q_0, q_1, \dots`$,

$$
\ddot a = \sum_{t \ge 0} v^{t}\prod_{k < t}\left(1 - q_k\right). \tag{9.15}
$$

For a **constant** probability $`q`$ over $`N`$ years this is a geometric series, $`\ddot a = \bigl(1 - (vp)^N\bigr)/\bigl(1 - vp\bigr)`$ with $`p = 1 - q`$ and $`vp = (1-q)/(1+i)`$.

**Along a cohort.** A life aged $`x`$ in the base year meets the mortality of year $`j`$ at age $`x + j`$: the **diagonal** of a projected table (the cohort of [section 6.6](06-projection.md#66-cohort-versus-period)). To stress the improvement, scale its logarithm by a factor $`s`$ and shift the level by $`\lambda`$:

$$
q_{x+j,\,j} = q_{x+j,\,0}\left(\frac{q_{x+j,\,j}^{\text{proj}}}{q_{x+j,\,0}}\right)^{s}\lambda. \tag{9.16}
$$

$`s = 0`$ is no improvement after the base year (the period table); $`s = 1`$ is the projection of chapter 6; $`s = 2`$ doubles the log improvement; $`\lambda = 0.8`$ is a permanent 20% fall in mortality at every age. The table closes at 110 with $`q = 1`$.

**The block's reserve.** The annuitants' ages are the survivors of a cohort from the youngest age, so the share at age $`x`$ is proportional to the probability of surviving there from age 60,

$$
w_x = \frac{\prod_{k<x-60}\left(1 - q_{60+k}\right)}{\sum_{x'}\prod_{k<x'-60}\left(1 - q_{60+k}\right)}, \qquad R = N\sum_{\text{sex}}\text{share}\times\pi\sum_{x=60}^{95} w_x\,\ddot a_x. \tag{9.17, 9.18}
$$

with $`N`$ the number of annuitants, $`\pi`$ the pension and the reserve built separately for each sex on its own table; it scales linearly with the number of lives and with the pension. The reserve is computed on nine bases (the regulator's pensions table, CNSF 2013, the population's own period table, the central projection of chapter 6, the projection with no and with double the improvement, a permanent 20% fall, and the interest rate one point lower or higher) and compared with the central projection.

## 9.7 The hedge between the two books

A pandemic **releases** annuity reserve: each extra death frees the present value of the pensions that will not be paid. An annuitant aged $`x`$ who dies in the year has already received that year's pension; the pensions of the years after the year of death are no longer owed, and their value, at the start of the year they were paid from, is $`\pi\,v\,\ddot a_{x+1}`$ (an annuity-due at age $`x+1`$, one year later, discounted for that year). With an extra probability of death $`\min(q_x\,d\,P_x,\ 1 - q_x)`$ at age $`x`$,

$$
\Delta R = -N\sum_{\text{sex}}\text{share}\ \pi\sum_x w_x\ \min(q_x\,d\,P_x,\ 1 - q_x)\ v\,\ddot a_{x+1}. \tag{9.19}
$$

The release is linear in the dampening (until a cap binds) as the loss on the life book is, so the two scale together. The **offsetting size** of the annuity block, the number of times it would have to be as large for its release to equal the life book's loss, is the loss divided by the release. A permanent fall in mortality does the opposite: it adds to the annuity reserve and *reduces* the present value of the life book's death benefits (their timing moves later, and whole life and endowment pay eventually). The hedge is **natural, not complete**: it lasts one year for a pandemic and is permanent for longevity, it acts through different ages and sums, and it needs the two blocks to sit in the same legal entity and capital pool.

## 9.8 Examples you can check by hand

**An excess and its range.** One band: 120 observed deaths, baselines of 100 (flat), 105 (trend), 95 (interpolation) and 110 (Lee-Carter). The central baseline is the median, $`(100 + 105)/2 = 102.5`$, so the excess is $`120 - 102.5 = 17.5`$ and the P-score $`17.5/102.5 = 17.1\%`$. The range comes from the extreme baselines: $`120 - 110 = 10`$ to $`120 - 95 = 25`$. If the trend baseline carries a standard error of 4, the noise is $`\sqrt{120 + 4^2} = 11.7`$.

**Interpolation.** Rates of 0.010 in 2019 and 0.016 in 2023: the rate in 2021 is $`\sqrt{0.010 \times 0.016} = 0.01265`$, not the arithmetic mean 0.013, so 1,000 person-years expect 12.65 deaths.

**A stress.** One policy: $`\mathrm{SA} = 1{,}000{,}000`$, $`q = 0.002`$ (expected claims 2,000), age-band P-score $`0.6`$, dampening 0.5, severity 1. Then $`q' = 0.002 \times (1 + 0.5 \times 0.6) = 0.0026`$, claims are 2,600 and the extra is 600 $`= 0.5 \times 0.6 \times 2{,}000`$, a 30% rise. With dampening 1 it would be 1,200 (60%); with severity 2 and dampening 0.5, also 1,200.

**An annuity.** With a constant $`q = 0.03`$ and $`i = 4\%`$, $`vp = 0.97/1.04 = 0.9327`$ and over 40 years $`\ddot a = (1 - 0.9327^{40})/(1 - 0.9327) = 13.94`$; over 25 years, 12.25; the limit as the horizon grows is $`1/(1 - vp) = 14.86`$. An extra death of a pensioner with a 120,000 pension and 25 years of expectation left frees about $`120{,}000 \times (1/1.04) \times 12.25 = 1.41`$ million.

## 9.9 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_excess_stress.py`: the flat, trend (including its conservation law and its exact continuation of a noise-free exponential trend), interpolation and Lee-Carter baselines; the central estimate, range and noise on a worked example; the years of life lost; the cause, month and state formulas on small frames; the scaling of the stress in dampening and severity, the cap and the insured P-scores; the annuity against its geometric series; the cohort paths at $`s = 0, 1, 2`$; the release by hand and its linearity; and the reserve's dependence on lives and pension. A world with a known **+40% shock above age 40** in one year is built and the analysis recovers its size within the expected spread of the baselines, with no excess found in the bands below 40 or in the year before.
2. **The data.** The quantities below are tested against the shipped database.

*Excess deaths* (central baseline; the range over the four baselines in brackets):

| | 2020 | 2021 | 2022 | 2020-22 |
|---|--:|--:|--:|--:|
| Observed deaths | 1,093,073 | 1,117,650 | 843,757 | 3,054,480 |
| Expected (central) | 760,625 | 766,871 | 780,554 | 2,308,050 |
| **Excess deaths** | **332,448** | **350,778** | **63,203** | **746,429** |
| Range | 319,970 to 339,894 | 327,669 to 365,700 | 28,295 to 85,732 | 675,934 to 791,326 |
| P-score | 43.7% | 45.7% | 8.1% | 32.3% |
| Certified COVID-19 | 201,280 | 238,093 | 38,189 | 477,562 |
| Excess per certified death | 1.65 | 1.47 | 1.65 | 1.56 |

Men account for 462,576 of the excess (62%) and women for 283,853. The excess cost **13.0 million years of life** (men 8.0 million, women 5.0 million): 17.4 years per excess death. The monthly series shows the waves: July 2020 (119,564 deaths in the month), **January 2021 (174,143 against about 74,000 expected)** and August 2021 (121,845). The age profile is steep and then flat: in 2021 men aged 45 to 49 had a P-score of 68%, aged 65 to 69 of 70%, against 66% and 56% for women of the same ages. By cause chapter, the excess certified as COVID-19 is 477,687, as circulatory 96,433, as endocrine (diabetes) 89,834 and as respiratory 53,864, with about 29,000 in the rest. By state the nation's excess is 35% of its 2023-rate expectation: Estado de México (49%), Ciudad de México (48%), Tlaxcala (48%), Sinaloa (42%) and Puebla (39%) are highest and Colima (19%), Quintana Roo (22%), Veracruz (23%), Yucatán (23%) and Chiapas (25%) lowest.

*The replay on the life book* (392,274 policies in force, expected claims in the next twelve months MXN 742 million):

| Scenario | Extra claims (MXN million) | Change in claims |
|---|--:|--:|
| 2020 replay, population excess | 445 | +60.0% |
| 2021 replay, population excess | 447 | +60.3% |
| 2022 replay, population excess | 43 | +5.8% |
| Half the excess (dampening 0.5) | about 223 | +30% |
| 2020 profile $`\times 0.5`$ / $`\times 1.5`$ / $`\times 2`$ | 223 / 668 / 890 | +30% / +90% / +120% |
| **CNSF 99.5th percentile table** | 376 | **+50.7%** |
| **2021 as insured lives lived it** | 984 | **+133%** |

A repeat of 2021 with the population's excess would exceed what the regulator's stress allows; with half the excess (insured lives healthier than the population) it would not. The data say which applies: insured lives' death rates in 2021 were 1.8 to 2.9 times their 2023 level at ages 25 to 79 (1.4 to 1.7 times for the population), so they were **not** shielded, and the regulator's own stress would not have covered 2021 on an insured book. 71% of the extra claims come from policyholders aged 50 and over, and men account for 65% of them. It is a one-year shock: by 2022 the replay is +6%.

*The annuity block on nine bases (the central projection and eight alternatives)* (central reserve, projection of chapter 6, MXN 25.0 billion):

| Basis | Reserve against central | Annuity at 65 (men / women) |
|---|--:|--:|
| CNSF 2013, pensions variant | **+16.0%** | 16.10 / 16.10 |
| CNSF 2013 | +7.8% | 14.94 / 14.94 |
| Central, interest 1 point lower | +8.1% | 13.80 / 15.00 |
| Central, mortality 20% lower for good | +5.9% | 13.55 / 14.48 |
| Projection with double the improvement | +2.3% | 12.94 / 14.00 |
| **Central projection** | 0 | 12.62 / 13.65 |
| Projection with no improvement after 2025 | -2.2% | 12.31 / 13.31 |
| Mexican population, 2023 period table | -2.9% | 12.21 / 13.21 |
| Central, interest 1 point higher | -7.0% | 11.61 / 12.50 |

**Interest matters more than the trend:** a point less interest adds 8.1%, more than a permanent 20% fall in mortality (5.9%) and three and a half times doubling the improvement (2.3%): longevity is a slow risk, the discount rate is the quick one.

*The hedge* (positive = loss, MXN million):

| Shock | Life book | Annuity block | Net |
|---|--:|--:|--:|
| 2021 pandemic replay | +447 | -374 | +74 |
| 2022 pandemic replay | +43 | -86 | -43 |
| Mortality 20% lower for good | -2,878 | +1,487 | -1,391 |

With the 2021 profile the annuity block releases 374 million, 84% of what the life book loses; an annuity block **1.2 times the size** would offset it exactly. A permanent 20% fall adds 1.5 billion to the annuity reserve and takes 2.9 billion off the life book's death benefits: of the two risks, the life book is more exposed to a pandemic and the annuity block to longevity.

## 9.10 Code map

| Formula | Function | Checked by (`tests/test_handbook_excess_stress.py`) |
|---|---|---|
| (9.1), (9.6), (9.7) | `excess.excess_by_band`, `excess.summarise` | `test_excess_toy_example_centre_range_and_p_score` |
| (9.2) | `excess.flat_baseline` | `test_flat_baseline_keeps_the_2019_rate` |
| (9.3) | `excess.trend_baseline` | `test_trend_baseline_is_a_poisson_regression_that_keeps_the_pre_pandemic_totals`, `test_trend_baseline_continues_an_exact_exponential_trend` |
| (9.4) | `excess.interpolation_baseline` | `test_interpolation_baseline_moves_the_log_rate_in_a_straight_line` |
| (9.5) | `excess.lee_carter_baseline` | `test_lee_carter_baseline_is_proportional_to_the_inegi_level_and_the_exposure` |
| (9.8) | `excess.summarise` | `test_years_of_life_lost_weight_the_excess_by_remaining_life` |
| Section 9.3 | `excess.baseline_set` | `test_the_analysis_recovers_a_known_shock_above_age_40` |
| (9.9), (9.10), (9.11) | `excess.cause_excess`, `monthly_excess`, `state_excess` | `test_cause_excess_...`, `test_monthly_baseline_...`, `test_state_excess_...` |
| (9.12) | `stress.pscore_by_age` | `test_p_scores_are_spread_over_single_ages_and_never_negative` |
| (9.13) | `stress.stressed_claims`, `pandemic_scenarios` | `test_stressed_claims_scale_...`, `test_the_scenario_table_has_...`, `test_stress_toy_example_by_hand` |
| (9.14) | `stress.insured_pscores` | `test_insured_p_scores_come_from_the_rate_relative_to_2023_and_never_below_zero` |
| (9.15) | `stress.annuity_due_from_q` | `test_the_annuity_of_a_constant_probability_is_a_geometric_series`, `test_the_constant_probability_annuity_example_by_hand` |
| (9.16) | `stress.cohort_q_paths`, `period_q_paths` | `test_cohort_paths_scale_the_log_improvement_and_the_level` |
| (9.17), (9.18) | `stress.AnnuityBlock`, `annuity_reserves` | `test_reserves_are_the_weighted_annuities_and_scale_with_lives_and_pension` |
| (9.19) | `stress.annuity_release` | `test_annuity_release_is_the_pension_value_of_each_extra_death` |
| Section 9.9, tables | `build_tables` (the warehouse) | `test_excess_numbers_match_the_database`, `test_stress_numbers_match_the_database` |

To reproduce the constant-probability annuity of section 9.8:

```python
import numpy as np
from mortality.stress import annuity_due_from_q

print(annuity_due_from_q(np.full((1, 40), 0.03), 0.04))  # [13.942]
```

## 9.11 Limits

- **The counterfactual is an assumption.** The range reflects four reasonable baselines, not every possible one: a baseline that assumed faster continuing improvement would give more excess, one that assumed the rise in diabetes mortality continued would give less.
- **Exposure is CONAPO's projection** after 2019, and the population of the pandemic years is uncertain (migration, undercount, the effect of the pandemic itself). The negative excess at the youngest ages is probably partly exposure, and is not interpreted.
- **The sources disagree by age**, which the Lee-Carter baseline corrects and the others avoid only because they use INEGI rates throughout.
- **Cause and state analyses use 2023 as the baseline,** because the project has no pre-pandemic cause or state history; 2023 is within a few percent of trend nationally.
- **Excess is not attribution.** The analysis says how many more died, when, at what age and where, and what was on the certificate. It does not say why.
- **A one-year shock on a static block.** The replay applies one year of excess to the book as it stands: no lapse reaction, no anti-selection, no multi-wave scenario, and no allowance for the lower mortality of the survivors of a wave (harvesting).
- **Dampening is an assumption**, bracketed by 1 and 0.5; a company would calibrate it from its own 2020 to 2021 A/E. The version that uses the insured lives' own rates replaces it with data, but on a synthetic book.
- **The annuity block is invented,** and its age distribution is the survivors of a cohort from age 60; real blocks have their own, with indexation, joint-life and guarantee features that are not modeled.
- **No capital.** The shocks are changes in claims and reserves, not a solvency capital requirement, which would also carry the probability of each shock and the diversification between them. The scenarios are deterministic; chapter 6's fan chart gives the probabilistic counterpart for longevity.

## References

- Karlinsky, A. and Kobak, D. (2021). Tracking excess mortality across countries during the COVID-19 pandemic with the World Mortality Dataset. *eLife* 10, e69336. (Baselines and P-scores for excess mortality.)
- Checchi, F. and Roberts, L. (2005). *Interpreting and using mortality data in humanitarian emergencies*. Humanitarian Practice Network Paper 52, Overseas Development Institute. (Excess mortality against a baseline.)
- Lee, R. D. and Carter, L. R. (1992). Modeling and forecasting U.S. mortality. *Journal of the American Statistical Association* 87(419), 659-671.
- Bowers, N. L., Gerber, H. U., Hickman, J. C., Jones, D. A. and Nesbitt, C. J. (1997). *Actuarial Mathematics*, 2nd ed. Society of Actuaries. (Annuities and the reserve of a block.)
