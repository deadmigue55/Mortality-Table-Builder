# 3. Crude rates and comparison

> [!NOTE]
> **In one minute.** A death rate is a count of deaths divided by the years of life the group lived. This chapter is about doing that division honestly: where the two numbers come from, how much luck is in them, and how to compare rates across years, regions and published tables without being fooled by differences in age. The tools are small (a Poisson interval, a weighted average, a ratio of observed to expected), but each one answers a question that a careless comparison gets wrong.
>
> **What this chapter does:** it turns the cleaned deaths and the population of [chapter 2](02-data-exposure-quality.md) into the crude rates that [chapter 4](04-graduation.md) smooths, and it builds the comparisons the project's headline findings rest on: against the regulator's table, across the pandemic, and between states.
>
> **The number to remember.** In 2019, before the pandemic, Mexican men aged 25 to 84 died at **3.03 times** the rate the regulator's CNSF 2013 table predicts (1.85 times for women). In 2020 the age-standardized male death rate jumped **51%**, from 637 to 960 per 100,000.

Code: `src/mortality/rates.py` · Tests: `tests/test_rates.py` and `tests/test_handbook_crude_rates.py` · Results: [crude-rates.md](../crude-rates.md)

**Local symbols** (everything else is in the [notation](01-notation.md)). $`\mathcal{D}_x`$ and $`\mathcal{E}_x`$ are the deaths and the central exposure at age $`x`$ in one year and sex; $`w_i`$ is the weight of age group $`i`$ in a standard population; $`n_i`$ and $`d_i`$ are the exposure and deaths of group $`i`$; $`O`$ and $`E`$ are observed and expected deaths.

**Contents.** [3.1](#31-exposure-and-the-central-rate) exposure · [3.2](#32-how-much-luck-is-in-a-rate-the-poisson-interval) intervals · [3.3](#33-from-a-rate-to-a-probability) rate to probability · [3.4](#34-the-open-age) open age · [3.5](#35-unknown-sex-and-unknown-age) unknowns · [3.6](#36-direct-standardization) direct standardization · [3.7](#37-indirect-standardization-the-smr) SMR · [3.8](#38-actual-versus-expected) A/E · [3.9](#39-when-is-a-rate-credible) credibility · [3.10](#310-examples-you-can-check-by-hand) examples · [3.11](#311-validation) validation · [3.12](#312-code-map) code map · [3.13](#313-limits) limits

---

## 3.1 Exposure and the central rate

The **central death rate** at age $`x`$ is deaths per person-year lived:

$$
\hat m_x = \frac{\mathcal{D}_x}{\mathcal{E}_x}. \tag{3.1}
$$

The denominator is the **exposure**: the total time lived at that age during the year by everyone who was alive. If $`P(t)`$ is the number of people of that age alive at time $`t`$ (in years, from 1 January), the exposure is $`\mathcal{E}_x = \int_0^1 P(t)\,dt`$. Censuses give a population on one date, and the standard approximation is the **mid-year population** $`P(\tfrac12)`$, the count on 1 July:

$$
\mathcal{E}_x = \int_0^1 P(t)\,dt \;\approx\; P\!\left(\tfrac12\right). \tag{3.2}
$$

This is exact when the population changes in a straight line over the year (the area of a trapezoid is its width times its middle height). If instead it grows at a steady rate $`r`$, $`P(t) = P_0 e^{rt}`$, then $`P(\tfrac12) / \int_0^1 P = r / (2\sinh(r/2)) \approx 1 - r^2/24`$: with 1% yearly growth the mid-year count is off by 4 parts in a million, and with 5% by 1 in 10,000. The approximation is excellent; the weak point of the denominator is not the arithmetic but its source (section 3.13).

## 3.2 How much luck is in a rate? The Poisson interval

A count of deaths is a random number: the same population in the same year could have produced a few more or fewer. Treat $`\mathcal{D}`$ as a Poisson count (the model of [section 4.1](04-graduation.md#41-the-model-deaths-are-poisson-counts)) and ask: *for which true means $`\lambda`$ is the observed count $`d`$ not surprising?*

The **exact (Garwood) interval** is the set of $`\lambda`$ that neither tail rejects at the 2.5% level. Its limits solve

$$
P(N \ge d \mid \lambda_L) = \tfrac{\alpha}{2}, \qquad P(N \le d \mid \lambda_U) = \tfrac{\alpha}{2}, \qquad \alpha = 0.05. \tag{3.3}
$$

These look like equations to be solved numerically, but a classical identity solves them. In a Poisson process of rate 1, the number of events by time $`\lambda`$ is at least $`d`$ exactly when the $`d`$-th event has arrived by $`\lambda`$, and that arrival time follows a gamma law with shape $`d`$ and rate 1. So $`P(N \ge d \mid \lambda) = P(\mathrm{Gamma}(d,1) \le \lambda)`$, and similarly $`P(N \le d \mid \lambda) = P(\mathrm{Gamma}(d+1,1) > \lambda)`$. The limits are therefore gamma quantiles, which are chi-square quantiles in disguise ($`\mathrm{Gamma}(k,1) = \tfrac12\chi^2_{2k}`$):

$$
\lambda_L = \tfrac12\,\chi^2_{2d,\ \alpha/2}, \qquad \lambda_U = \tfrac12\,\chi^2_{2d+2,\ 1-\alpha/2}. \tag{3.4}
$$

Dividing by the exposure (taken as known) gives the interval for the rate. Three properties matter.

**It works for fractional counts.** The gamma form needs no integer $`d`$, which matters because the deaths used here are *adjusted* (late registrations completed and unknowns spread, [chapter 2](02-data-exposure-quality.md#23-deaths-with-missing-sex-or-age)), so they are not whole numbers.

**It is conservative.** Because a Poisson count takes only whole values, an exact interval cannot cover exactly 95%; it covers *at least* 95% for every true mean:

$$
P_\lambda\!\left(\lambda_L(N) \le \lambda \le \lambda_U(N)\right) \;\ge\; 0.95 \quad \text{for all } \lambda > 0. \tag{3.5}
$$

(Computed exactly, the coverage is 98.1% at $`\lambda = 1`$, 96.2% at 3.7, 95.8% at 12, 95.3% at 50 and 95.2% at 200: it settles toward 95% from above.)

**For large counts it is the familiar normal interval.** With a count in the thousands,

$$
d \pm 1.96\sqrt{d}, \qquad \text{so the relative half-width is } \frac{1.96}{\sqrt{d}}. \tag{3.6}
$$

With 40,000 deaths the interval is $`\pm 1\%`$; with 100 deaths, $`\pm 20\%`$. Zero deaths is not zero information: the interval is $`[0,\ -\ln(0.025) = 3.69]`$.

> [!IMPORTANT]
> These intervals measure **sampling luck only**. Real death counts here scatter between neighboring ages up to three times more than luck explains ([section 4.5](04-graduation.md#45-how-smooth-is-smooth-enough)), so a crude interval is narrower than the truth. It is the right interval for "how much would this count vary if we ran the year again", not for "how wrong could the rate be".

## 3.3 From a rate to a probability

A table needs $`q_x`$, the probability of dying within the year, not $`m_x`$. [Chapter 5](05-life-tables.md#52-the-separation-factor) derives the link from the average fraction $`\phi`$ of the year lived by those who die; for rates at ages above infancy the project takes deaths to be spread evenly ($`\phi = \tfrac12`$):

$$
q_x = \frac{m_x}{1 + \tfrac12\, m_x}, \qquad\qquad m_x = \frac{q_x}{1 - \tfrac12\, q_x}. \tag{3.7, 3.8}
$$

For **infants** the assumption fails: deaths cluster in the first weeks, so those who die in the first year have lived only a small share of it. The project uses the regression of Preston, Heuveline and Guillot (2001), which makes $`\phi_0`$ depend on the level of infant mortality $`m_0`$:

$$
\phi_0 = \begin{cases} 0.045 + 2.684\, m_0 \ \text{(boys)} \quad 0.053 + 2.800\, m_0 \ \text{(girls)} & m_0 < 0.107, \\[2pt] 0.33 \ \text{(boys)} \quad 0.35 \ \text{(girls)} & m_0 \ge 0.107. \end{cases} \tag{3.9}
$$

The two regimes meet at the switch point to within 0.003. In 2020 a girl born in Mexico faced $`m_0 \approx 0.0082`$, so $`\phi_0 = 0.076`$ and $`q_0 = m_0 / (1 + (1 - 0.076)\,m_0) = 0.00814`$: the probability is *below* the rate because the average infant who dies has lived only 7.6% of the year.

> [!NOTE]
> These $`q`$ are a **bridge**: they are computed from crude rates, and at the oldest ages they inherit all the noise. The life tables of chapter 5 are built on the graduated rates of chapter 4, not on these.

## 3.4 The open age

CONAPO's population stops at age 109, and above about 100 the single-age counts are tiny. The project pools **ages 100 and over** into one row, summing deaths and exposure separately before dividing:

$$
m_{100+} = \frac{\sum_{x \ge 100} \mathcal{D}_x}{\sum_{x \ge 100} \mathcal{E}_x}. \tag{3.10}
$$

Summing both sides first (rather than averaging rates) keeps numerator and denominator over exactly the same people, and no death or person-year is lost. The pooled row has no $`q`$ (it is an open interval), and absorbing the sparse ages is why none of the 1,010 single-age cells in the data has fewer than 30 deaths.

## 3.5 Unknown sex and unknown age

The hand-exported INEGI tables for 2014 to 2019 contain deaths of unknown sex and unknown age. Dropping them would understate every rate; the project spreads them **in proportion** to what is known, in two steps, and keeps the yearly total fixed.

**Step 1, unknown sex.** Within each age group, the deaths of unknown sex $`U`$ are split between men and women in the ratio of the known deaths:

$$
M' = M + U\,\frac{M}{M + F}, \qquad F' = F + U\,\frac{F}{M + F} \tag{3.11}
$$

(half and half if $`M + F = 0`$).

**Step 2, unknown age.** For each sex, the deaths of unknown age $`U_s`$ are added to all known age groups in proportion to their size:

$$
\mathcal{D}'_{x,s} = \mathcal{D}_{x,s}\left(1 + \frac{U_s}{\sum_x \mathcal{D}_{x,s}}\right). \tag{3.12}
$$

Both steps conserve the total ($`M' + F' = M + F + U`$ and $`\sum_x \mathcal{D}'_{x,s} = \sum_x \mathcal{D}_{x,s} + U_s`$). The assumption is that a missing label is unrelated to the person's age and sex (a **missing-at-random** assumption). The unknowns are 0.5% to 0.7% of deaths in these tables, so the effect of the assumption is small; the microdata from 2020 on are treated the same way in [chapter 2](02-data-exposure-quality.md#23-deaths-with-missing-sex-or-age).

## 3.6 Direct standardization

Comparing two crude rates compares two things at once: the risk at each age and the **age mix** of the population. A country with many old people has a higher crude rate than a young country with identical age-specific risks, and a country that is aging sees its crude rate rise with no change in risk. The crude rate is $`\sum_i (n_i/N)\,m_i`$, a weighted average of age-specific rates with the population's *own* weights.

**Direct standardization** applies one fixed set of weights, a *standard population*, to every group being compared:

$$
\mathrm{ASR} = \sum_i w_i\, \hat m_i, \qquad w_i \ge 0, \quad \sum_i w_i = 1. \tag{3.13}
$$

The project uses the **Segi world standard** (18 five-year groups from 0-4 to 85+, 100,000 people in all; the heaviest weights, 12,000 and 10,000, are on the youngest two groups). The ASR answers: *what would the death rate be if this population had the standard age structure?* Two populations with the same age-specific rates then get the same ASR, however different their age mixes. The next section has the smallest possible example.

**Uncertainty.** Each group's deaths are independent Poisson counts, so the variance of the ASR is a weighted sum of their variances:

$$
v = \mathrm{Var}(\mathrm{ASR}) = \sum_i w_i^2\,\frac{d_i}{n_i^2}. \tag{3.14}
$$

A weighted sum of Poisson counts is not Poisson, so the exact interval of section 3.2 does not apply. The **Fay-Feuer interval** (1997) approximates the ASR by a gamma distribution with the same mean $`y = \mathrm{ASR}`$ and variance $`v`$ (shape $`y^2/v`$, scale $`v/y`$) and reads its limits from chi-square quantiles. The upper limit is made safe for sparse groups by adding a *dummy observation* of size $`w_m = \max_i (w_i/n_i)`$ (the largest weight per person-year):

$$
\mathrm{ASR}_L = \frac{v}{2y}\,\chi^2_{\,2y^2/v,\ \alpha/2}, \tag{3.15}
$$

$$
\mathrm{ASR}_U = \frac{v + w_m^2}{2\,(y + w_m)}\,\chi^2_{\,2(y+w_m)^2/(v + w_m^2),\ 1-\alpha/2}. \tag{3.16}
$$

**A check that the formula is right.** With a single group of weight 1, $`y = d/n`$, $`v = d/n^2`$ and $`w_m = 1/n`$, so $`2y^2/v = 2d`$, $`v/(2y) = 1/(2n)`$, $`v + w_m^2 = (d+1)/n^2`$ and $`y + w_m = (d+1)/n`$. Then (3.15) becomes $`\chi^2_{2d,\alpha/2}/(2n)`$ and (3.16) becomes $`\chi^2_{2d+2,1-\alpha/2}/(2n)`$, which is exactly the Garwood interval (3.4) divided by the exposure. The Fay-Feuer interval is the Garwood interval generalized to a weighted sum, and the two agree in the case where both apply.

## 3.7 Indirect standardization: the SMR

Direct standardization needs reliable rates in every age group, which a small region does not have. **Indirect standardization** turns the problem around: take the *rates* from a large reference population and apply them to the region's own age structure to ask how many deaths the region *should* have had.

With pooled reference rates $`r_j = \sum_{\text{regions}} d_j \,/ \sum_{\text{regions}} n_j`$ for each sex-and-age cell $`j`$, the expected deaths of region $`i`$ are

$$
E_i = \sum_j n_{ij}\, r_j, \qquad \mathrm{SMR}_i = \frac{O_i}{E_i}, \qquad \text{interval:}\ \ \frac{\lambda_L(O_i)}{E_i},\ \frac{\lambda_U(O_i)}{E_i}. \tag{3.17}
$$

An SMR of 1.10 means 10% more deaths than the region's age and sex mix predicts at national rates. Because the reference rates are the pooled ones, the expected deaths add up exactly to the observed deaths over all regions, $`\sum_i E_i = \sum_i O_i`$, so SMRs average out around 1 by construction. The interval treats $`E_i`$ as fixed and takes the Garwood limits of the observed count.

## 3.8 Actual versus expected

The same idea measures how far a *population* is from a published **table**. A table supplies $`q_x`$ at each age; convert it to a central rate with (3.8) and apply it to the exposure:

$$
E = \sum_x \mathcal{E}_x\; m^{\text{table}}_x, \qquad \frac{A}{E} = \frac{\mathcal{D}}{E}, \qquad \text{interval:}\ \ \frac{\lambda_L(\mathcal{D})}{E},\ \frac{\lambda_U(\mathcal{D})}{E}. \tag{3.18}
$$

Here $`A`$ is the actual number of deaths and $`E`$ the number the table predicts. A ratio of 3 means the population dies three times as fast as the table says. The project reports it by five-year band for ages 25 to 84 (the range every benchmark table covers) and for the total of those bands, against CNSF 2013 and nine SOA tables for Mexico. Mexico's rate is also divided, band by band, by that of each country in the Human Mortality Database (a plain ratio of crude rates, with no interval).

The intervals here are extremely narrow, because the counts are in the hundreds of thousands. They describe random variation only. They say nothing about whether the table fits an *insured* book, which is selected and healthier than the population: that question needs company experience, and it is the subject of [chapter 7](07-experience-study.md).

## 3.9 When is a rate credible?

How many deaths does a rate need before it can be trusted on its own? The classical (limited-fluctuation) answer asks for a count that lands within a fraction $`k`$ of its mean with probability $`p`$. For a Poisson count with mean $`\lambda`$ (approximately normal with variance $`\lambda`$), $`\lvert N - \lambda\rvert \le k\lambda`$ holds with probability $`p`$ when $`k\lambda = z_{(1+p)/2}\sqrt{\lambda}`$, so

$$
\lambda \ \ge\ n_F = \left(\frac{z_{(1+p)/2}}{k}\right)^{2}. \tag{3.19}
$$

For $`p = 90\%`$ and $`k = 5\%`$ this is $`(1.645/0.05)^2 = 1{,}082`$ deaths, the **full credibility standard** (a Poisson count of 1,082 really does land within 5% of its mean about 90% of the time). The project flags a cell as **thin** when it has fewer than 30 deaths, a floor below which a rate is noise, not a claim of credibility: 1,082 is the bar for a rate to stand on its own, and everything in between is the work of [credibility weighting in chapter 7](07-experience-study.md#73-how-far-to-trust-a-ratio-credibility).

## 3.10 Examples you can check by hand

**A rate and its interval.** 12 deaths in 1,000 person-years: $`\hat m = 0.012`$. By (3.4), $`\lambda_L = \tfrac12\chi^2_{24,\,0.025} = 6.20`$ and $`\lambda_U = \tfrac12\chi^2_{26,\,0.975} = 20.96`$, so the 95% interval is **0.00620 to 0.02096**. The normal shortcut (3.6) would give $`12 \pm 1.96\sqrt{12} = 5.21`$ to $`18.79`$, that is 0.0052 to 0.0188: too low at both ends, because with only 12 deaths the distribution is skewed to the right.

**A probability from a rate.** For the infant rate $`m_0 = 0.0082`$ of a girl, (3.9) gives $`\phi_0 = 0.053 + 2.8 \times 0.0082 = 0.076`$, and (3.7) with that $`\phi_0`$ gives $`q_0 = 0.0082/(1 + 0.924 \times 0.0082) = 0.00814`$.

**Standardization.** Two populations share the same age-specific death rates, $`0.001`$ for the young and $`0.02`$ for the old, but differ in their mix.

| | Young | Old | Deaths | Crude rate | ASR with weights $`(\tfrac12, \tfrac12)`$ |
|---|--:|--:|--:|--:|--:|
| Young-heavy | 80,000 | 20,000 | $`80 + 400 = 480`$ | 0.0048 | $`\tfrac12(0.001) + \tfrac12(0.02) = 0.0105`$ |
| Old-heavy | 20,000 | 80,000 | $`20 + 1600 = 1620`$ | 0.0162 | 0.0105 |

The crude rates differ by a factor of 3.4 and the standardized rates are identical: the entire gap is age mix, none of it is risk.

**An SMR.** Two regions, two age bands. Exposures (person-years) and deaths:

| | Young exposure | Old exposure | Young deaths | Old deaths | Observed |
|---|--:|--:|--:|--:|--:|
| Region X | 10,000 | 2,000 | 12 | 60 | 72 |
| Region Y | 30,000 | 8,000 | 30 | 200 | 230 |
| Pooled | 40,000 | 10,000 | 42 | 260 | 302 |

The pooled rates are $`42/40\,000 = 0.00105`$ (young) and $`260/10\,000 = 0.026`$ (old). Then $`E_X = 10\,000 \times 0.00105 + 2\,000 \times 0.026 = 10.5 + 52 = 62.5`$ and $`E_Y = 31.5 + 208 = 239.5`$, which add to 302, the observed total. The SMRs are $`72/62.5 = 1.152`$ for X and $`230/239.5 = 0.960`$ for Y: region X has 15% more deaths than its age mix predicts, region Y 4% fewer.

## 3.11 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_crude_rates.py`: the mid-year approximation error, the tail equations (3.3) and the chi-square form (3.4), the exact coverage (3.5), the normal limit (3.6), the infant regression (3.9), conservation under pooling and under the allocation of unknowns, the Segi total, the equal-rates property of direct standardization, the **reduction of the Fay-Feuer interval to Garwood's**, the conservation of expected deaths in the SMR, and the 1,082 standard by simulation.
2. **Published values.** `tests/test_rates.py` checks the Poisson limits against published Garwood tables.
3. **The data.** The quantities quoted below are tested against the shipped database.

| | Men | Women |
|---|--:|--:|
| Age-standardized rate (Segi), 2014 to 2019, per 100,000 | 615 to 637 | 415 to 425 |
| 2019 | 637 | 417 |
| Peak year | 2020: **960** (+51%) | 2021: **588** (+41%) |
| 2024 | 614 | 402 |
| Actual-to-expected against CNSF 2013, ages 25 to 84, 2019 | **3.03** | **1.85** |

The age-standardized rates sit nearly flat from 2014 to 2019, jump in the pandemic, and by 2024 are back at the pre-pandemic level (for 2023 and 2024 on CONAPO's projected population, section 3.13). Men aged 25 to 29 were at 4.30 times the CNSF 2013 table in 2019, falling to 1.98 times at 80 to 84: the table is too light for the young adults most.

*Registered versus occurred deaths.* From 2020 the rates use deaths by year of **occurrence**; before that only the INEGI tables by year of **registration** exist. The two bases are close: the ratio of registered to occurred deaths is 0.994 to 1.007 in every year from 2020 to 2024, so 2014 to 2019 is a fair baseline. (The registered count includes the 0.1% to 0.2% of deaths of known residents abroad, which the occurrence series leaves out; restricted to residents of Mexico the difference runs from -0.7% in 2020 to +0.5% in 2024.)

*States.* In 2023 the 32 states range from an SMR of 0.81 (Sinaloa; Guerrero 0.85) to 1.19 (Chihuahua; Colima 1.18). These compare registered deaths with a projected population, so registration coverage and migration move them along with true risk: they are a rating-factor starting point, not a causal finding.

## 3.12 Code map

| Formula | Function (`src/mortality/rates.py`) | Checked by (`tests/test_handbook_crude_rates.py`) |
|---|---|---|
| (3.1), (3.2) | `crude_single`, `crude_grouped` | `test_mid_year_population_is_the_person_years_of_a_steady_trend` |
| (3.3), (3.4) | `poisson_interval`, `rate_interval` | `test_garwood_limits_solve_the_tail_equations`, `test_garwood_limits_are_chi_square_quantiles` |
| (3.5), (3.6) | `poisson_interval` | `test_garwood_never_covers_less_than_95_percent`, `test_for_large_counts_garwood_is_the_normal_interval` |
| (3.7), (3.8), (3.9) | `mx_to_qx`, `qx_to_mx`, `infant_ax` | `test_q_from_m_and_back`, `test_the_infant_separation_factor_and_its_two_regimes` |
| (3.10) | `pool_terminal` | `test_pooling_the_open_age_conserves_deaths_and_exposure` |
| (3.11), (3.12) | `allocate_cube_unknowns` | `test_unknown_sex_and_age_are_spread_in_proportion_and_nothing_is_lost` |
| (3.13), (3.14) | `standardise`, `age_standardised` | `test_standardisation_toy_two_populations_one_set_of_rates`, `test_the_standardised_rate_is_a_weighted_mean_of_the_group_rates` |
| (3.15), (3.16) | `standardise` | `test_fay_feuer_with_one_group_is_the_garwood_interval`, `test_fay_feuer_brackets_the_rate_and_matches_the_variance_formula` |
| (3.17) | `smr_table` | `test_smr_toy_example_and_conservation` |
| (3.18) | `expected_deaths`, `actual_versus_expected`, `ae_interval` | `test_ae_with_a_flat_table_and_its_interval` |
| (3.19) | `THIN_CELL_DEATHS` and its derivation | `test_classical_full_credibility_standard_is_1082_deaths` |
| Section 3.11, table | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To reproduce the first example of section 3.10:

```python
from mortality.rates import rate_interval

print(rate_interval(12, 1000))  # (0.0062006, 0.0209616)
```

## 3.13 Limits

- **The denominator is a projection.** From 2020 the exposure is CONAPO's projected mid-year population, and a Census-based rebasing of later releases would change levels slightly. The pandemic spike does not depend on it; the 2023 and 2024 levels, a little below 2019, do.
- **Two bases.** Rates before 2020 use year of registration in five-year bands; from 2020, year of occurrence by single age. They agree within 0.7% in total (section 3.11), but the single-age detail does not exist before 2020.
- **Poisson means luck only.** The intervals ignore registration errors, age misreporting and population-estimate error, which are larger than sampling luck here (chapter 4 measures the excess scatter).
- **Missing at random.** The allocation of unknown sex and age assumes the missing label carries no information; it is a small effect at 0.5% to 0.7% of deaths, but it is an assumption.
- **The infant regression** (3.9) was fitted to other populations. Mexico's infant mortality sits inside its range, but $`\phi_0`$ is not measured from Mexican birth-and-death timing.
- **SMRs are not directly comparable between regions** with very different age structures, since each uses its own weights; they compare each region with the national rate.
- **A/E measures distance, not fit.** It says how far the population is from a table. It does not say how an insured portfolio would behave.
- **Crude $`q`$ is noisy at old ages.** It is a bridge to the life table, never the table itself.

## References

- Garwood, F. (1936). Fiducial limits for the Poisson distribution. *Biometrika* 28(3-4), 437-442.
- Fay, M. P. and Feuer, E. J. (1997). Confidence intervals for directly standardized rates: a method based on the gamma distribution. *Statistics in Medicine* 16(7), 791-801.
- Segi, M. (1960). *Cancer Mortality for Selected Sites in 24 Countries (1950-57)*. Tohoku University School of Medicine, Sendai. (The world standard population.)
- Breslow, N. E. and Day, N. E. (1987). *Statistical Methods in Cancer Research, Volume II: The Design and Analysis of Cohort Studies*. IARC Scientific Publications No. 82. (Indirect standardization and the SMR.)
- Preston, S. H., Heuveline, P. and Guillot, M. (2001). *Demography: Measuring and Modeling Population Processes*. Blackwell. (The relation between $`\phi_0`$ and infant mortality.)
- Longley-Cook, L. H. (1962). An introduction to credibility theory. *Proceedings of the Casualty Actuarial Society* 49, 194-221. (Limited-fluctuation credibility.)
