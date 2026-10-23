# 6. Projection

> [!NOTE]
> **In one minute.** A life table describes the past. A 30-year policy or a pension that starts in 20 years needs the *future* mortality, which is uncertain and, in most countries, has been improving. This chapter fits two standard stochastic models to the history of Mexican mortality, tests them by pretending to stand in the past and forecasting what is now known (a **backtest**), and projects to 2070 with honest bands. The key idea is that the future is a *random walk with drift* in a single index of mortality level, so the forecast is a trend plus a spread that widens with the horizon.
>
> **What this chapter does:** it turns the history of rates into projected rates, closes them to age 110 as in [chapter 4](04-graduation.md#48-closing-the-table-at-the-oldest-ages), measures them with the life-table functions of [chapter 5](05-life-tables.md), and shows why a pension priced on today's table is too cheap.
>
> **The number to remember.** A man who turns 65 in 2025 can expect **18.43** more years if mortality keeps improving along the long-run trend, against **17.61** on today's period table: 0.8 years longer, so an annuity priced on the period table understates its cost by **2.6%**.

Code: `src/mortality/projection.py` and `r/projection_stmomo.R` · Tests: `tests/test_projection.py` and `tests/test_handbook_projection.py` · Results: [projection.md](../projection.md)

**Local symbols** (everything else is in the [notation](01-notation.md)). $`\alpha_x,\ \beta_x,\ \kappa_t`$ are the Lee-Carter age level, age sensitivity and period index; $`\delta`$ and $`\sigma^2`$ the drift and innovation variance of a random walk; $`T`$ the number of years of history; $`h`$ the forecast horizon in years; $`\kappa^1_t,\ \kappa^2_t`$ the two Cairns-Blake-Dowd factors, $`\bar x`$ the mean age 79.5.

**Contents.** [6.1](#61-the-data-problem) data · [6.2](#62-the-lee-carter-model) Lee-Carter · [6.3](#63-forecasting-the-index-a-random-walk-with-drift) random walk · [6.4](#64-the-cairns-blake-dowd-model) CBD · [6.5](#65-closing-the-table-and-measuring-it) closing and measuring · [6.6](#66-cohort-versus-period) cohort vs period · [6.7](#67-the-backtest-and-its-calibration) backtest · [6.8](#68-examples-you-can-check-by-hand) examples · [6.9](#69-validation) validation · [6.10](#610-code-map) code map · [6.11](#611-limits) limits

---

## 6.1 The data problem

A trend needs a long series. This project's own graduated rates cover only 2020 to 2024, and the 2014 to 2019 INEGI tables are five-year groups. The only long single-age series is **CONAPO's**: deaths and mid-year population from 1950 to 2019, national, by sex and age. It is a demographic *reconstruction* (smooth, model-based) rather than raw registration, so the models are fitted to **CONAPO 1970 to 2019**, this project's graduated rates for 2020 to 2024 serve as *observed* out-of-sample years and as the **restart point** of the projection, and CONAPO's official projection (2020 to 2070) is a benchmark, never an input.

The two sources disagree about who dies. For men aged 15 to 39 in 2023, INEGI-based rates imply **34% fewer deaths** than CONAPO models (62,267 against 94,421), while at 60 and over they imply 10% to 16% **more**; the totals agree within 1%. Which source is closer to the truth is open (young adult male deaths are where unregistered or reclassified deaths would matter most), so the projection carries both explicitly: it is fitted to the CONAPO history and restarted at the INEGI-based 2024 rates.

## 6.2 The Lee-Carter model

Lee and Carter (1992) describe the whole surface of log death rates, over age $`x`$ and year $`t`$, with one age profile level and one time index:

$$
\ln m_{x,t} = \alpha_x + \beta_x\,\kappa_t. \tag{6.1}
$$

$`\alpha_x`$ is the average log rate at age $`x`$; $`\kappa_t`$ is the **period index**, one number per year that says how high mortality is overall that year (lower is better); and $`\beta_x`$ says how strongly age $`x`$ responds when the index moves: a large $`\beta_x`$ means that age's mortality improves fast when $`\kappa`$ falls. The model has the rank-one structure of a single factor: all ages follow the same index, at their own speeds.

**Identification.** The three sets of parameters are not unique: shifting $`\kappa`$ by a constant $`s`$ and compensating in $`\alpha`$, or rescaling $`\beta`$ by $`c`$ and $`\kappa`$ by $`1/c`$, gives the same surface,

$$
\left(\alpha_x + \beta_x s,\ \ \kappa_t - s\right) \quad\text{and}\quad \left(\beta_x/c,\ \ c\,\kappa_t\right) \quad\text{give the same } \ln m_{x,t}, \qquad\text{so impose}\quad \sum_x \beta_x = 1, \ \ \sum_t \kappa_t = 0. \tag{6.2}
$$

(The shift is used to make $`\kappa`$ average to zero and the scale to make the $`\beta`$ add to one; with those two constraints $`\alpha_x`$ is the model's log rate at age $`x`$ when the index is at its average level.)

**Fitting.** Lee and Carter's original fit used a singular-value decomposition of the log rates, which gives every age the same weight, although old ages with few deaths are far noisier. Brouhns, Denuit and Vermunt (2002) fit the model by **Poisson maximum likelihood**, so every cell counts in proportion to its exposure. Take $`\mathcal{D}_{x,t} \sim \mathrm{Poisson}(\mu_{x,t})`$ with $`\mu_{x,t} = \mathcal{E}_{x,t}\exp(\alpha_x + \beta_x\kappa_t)`$:

$$
\ell(\alpha, \beta, \kappa) = \sum_{x,t}\left[\mathcal{D}_{x,t}\,(\alpha_x + \beta_x\kappa_t) - \mu_{x,t}\right] + \text{const}. \tag{6.3}
$$

Setting each derivative to zero gives three families of **score equations**:

$$
\sum_t \left(\mathcal{D}_{x,t} - \mu_{x,t}\right) = 0, \qquad \sum_x \beta_x\left(\mathcal{D}_{x,t} - \mu_{x,t}\right) = 0, \qquad \sum_t \kappa_t\left(\mathcal{D}_{x,t} - \mu_{x,t}\right) = 0. \tag{6.4}
$$

The first says something worth remembering: **the fitted model reproduces the total deaths at every age**, as the P-spline of chapter 4 reproduces the total deaths of a year (4.14). Smoothing over time moves deaths between years; it does not create them.

The equations are not linear in the parameters, but each is a one-parameter problem when the others are held fixed, and the score of a Poisson log-likelihood has a simple second derivative ($`-\sum \beta_x^2\mu_{x,t}`$ for $`\kappa_t`$). One Newton step per parameter gives the **one-step updates** of Brouhns et al.:

$$
\kappa_t \leftarrow \kappa_t + \frac{\sum_x \beta_x\,(\mathcal{D}_{x,t} - \mu_{x,t})}{\sum_x \beta_x^2\,\mu_{x,t}}, \quad \alpha_x \leftarrow \alpha_x + \frac{\sum_t (\mathcal{D}_{x,t} - \mu_{x,t})}{\sum_t \mu_{x,t}}, \quad \beta_x \leftarrow \beta_x + \frac{\sum_t \kappa_t\,(\mathcal{D}_{x,t} - \mu_{x,t})}{\sum_t \kappa_t^2\,\mu_{x,t}}. \tag{6.5}
$$

The code cycles through the three updates, re-imposes (6.2) after each cycle without changing the fit, and stops when the deviance (4.3) stops falling (the synthetic example of the tests converges in four cycles); it starts from the first singular vectors of the log rates.

## 6.3 Forecasting the index: a random walk with drift

Everything about the future of mortality has now been reduced to the future of one series, $`\kappa_t`$. Lee and Carter model it as a **random walk with drift**: each year the index moves by a steady amount $`\delta`$ (the trend) plus a random shock,

$$
\kappa_{t+1} = \kappa_t + \delta + \sigma\,\varepsilon_t, \qquad \varepsilon_t \sim N(0, 1). \tag{6.6}
$$

The estimates are the simplest imaginable. The drift is the average yearly change, and because consecutive differences telescope it needs only the two ends of the series; the noise variance is the sample variance of the differences:

$$
\hat\delta = \frac{1}{T-1}\sum_{t=1}^{T-1}(\kappa_{t+1} - \kappa_t) = \frac{\kappa_T - \kappa_1}{T-1}, \qquad \hat\sigma^2 = \frac{1}{T-2}\sum_{t=1}^{T-1}\left(\kappa_{t+1} - \kappa_t - \hat\delta\right)^2. \tag{6.7}
$$

**The forecast.** After $`h`$ years, $`\kappa_{T+h} = \kappa_T + h\delta + \sigma\sum \varepsilon`$, with mean $`\kappa_T + h\delta`$ and variance $`h\sigma^2`$: noise accumulates, so the spread grows with $`\sqrt{h}`$. But the drift itself is *estimated*, from a short and trending series, and a forecast that ignores that makes long-run bands too narrow. $`\hat\delta`$ is the mean of $`T-1`$ differences, so its variance is $`\sigma^2/(T-1)`$, and a drift that is wrong by a little accumulates over $`h`$ years into $`h`$ times that error. The code simulates paths in which **each path draws its own drift**. The total variance of the index $`h`$ years ahead is then

$$
\mathrm{Var}\left(\kappa_{T+h}\right) = \underbrace{h\,\sigma^2}_{\text{noise}} + \underbrace{h^{2}\,\frac{\sigma^2}{T-1}}_{\text{uncertain drift}}. \tag{6.8}
$$

The second term grows like $`h^2`$ and overtakes the first once $`h > T - 1`$: with the 50 years (1970 to 2019) of history used here the two are equal at 49 years, so by 2070 (46 years after 2024) the uncertainty in the trend contributes almost as much variance as the shocks. This is why the project insists on simulating both.

**Where the forecast starts.** The model's fitted rate for the last year, $`\exp(\alpha_x + \beta_x\kappa_T)`$, is a smoothed value; the observed rate is different. The **jump-off** restart carries the observed rates forward by the change in the index alone, so that the forecast begins exactly where the data are:

$$
m_{x,T+h} = m^{\mathrm{obs}}_x\,\exp\!\left(\beta_x\left[\kappa_{T+h} - \kappa_T\right]\right). \tag{6.9}
$$

The project restarts at the INEGI-based graduated 2024 rates while fitting the index on the CONAPO history, which is also how it absorbs the level difference between the two sources of section 6.1. The **central path** switches the shocks off (the index moves by $`h\hat\delta`$). The **long-run** scenario estimates the drift from all 50 years of history; the **recent** scenario from the last 20 years only, which matters because Mexican men's improvement slowed (section 6.9).

## 6.4 The Cairns-Blake-Dowd model

Pensions care about ages 60 to 99, where the age profile is close to straight on a **logit** scale. The Cairns-Blake-Dowd model (2006, "M5") describes the probability of dying with two factors per year and no age-specific parameters at all:

$$
\operatorname{logit} q_{x,t} = \kappa^1_t + \kappa^2_t\,(x - \bar x), \qquad x = 60, \dots, 99, \quad \bar x = 79.5, \tag{6.10}
$$

where $`\operatorname{logit} q = \ln\frac{q}{1-q}`$. $`\kappa^1_t`$ is the level of mortality at the central age; $`\kappa^2_t`$ is the **slope**, how fast mortality rises with age. Each year is fitted by an ordinary regression of $`\operatorname{logit} q_{x,t}`$ on $`x - \bar x`$ over the forty ages (with $`q = m/(1 + m/2)`$), whose solution is

$$
\kappa^1_t = \frac{1}{40}\sum_x \operatorname{logit} q_{x,t}, \qquad \kappa^2_t = \frac{\sum_x (x - \bar x)\operatorname{logit} q_{x,t}}{\sum_x (x - \bar x)^2}. \tag{6.11}
$$

Because the centered ages add to zero, the intercept is just the average. The pair $`(\kappa^1_t, \kappa^2_t)`$ is forecast as a **bivariate random walk with drift**: the same estimates as (6.7), with the drift a vector and $`\sigma^2`$ a $`2 \times 2`$ covariance matrix, simulated by multiplying independent standard normal shocks by its Cholesky factor so that the two factors move together as they did historically. The jump-off restart is the same idea as (6.9): the logit of the observed rate moves by the change in $`\kappa^1`$ plus the change in $`\kappa^2`$ times $`(x - \bar x)`$. StMoMo in R fits the same model by a binomial likelihood rather than least squares, which is why the factors differ slightly (section 6.9).

## 6.5 Closing the table and measuring it

The models cover ages up to 99, and above about 88 the data cannot be trusted ([chapter 4](04-graduation.md#48-closing-the-table-at-the-oldest-ages)). Every projected table is therefore closed to 110 the same way as the graduated one, but in a form that can close thousands of simulated paths at once. Fit a straight line to the logit of the rate at ages 75 to 89 by least squares, with slope $`s`$ and intercept $`\bar y`$ (the mean logit, since the ages are centered at 82), and carry it forward:

$$
m_x = \operatorname{expit}\!\left(\bar y + s\,(x - 82)\right), \qquad x \ge 90, \tag{6.12}
$$

with $`\operatorname{expit}(y) = 1/(1 + e^{-y})`$. This is the Kannisto logistic (4.21) with $`b = s`$ and $`a = e^{\bar y - 2s}`$ (since $`\bar y + s(x - 82) = (\bar y - 2s) + s(x - 80)`$), fitted by least squares on the logit instead of by Poisson deviance; it is exact in closed form. Between ages 84 and 90 the projected rates fade into it on the log scale with the weights of (4.23), the rate at 110 closes the table with $`q_{110} = 1`$, and the ages 90 to 99 of the input are not used at all. A table that is *already* logistic is left unchanged.

**Measuring a table.** Life expectancy at birth and at 65 ($`\mathring{e}_0`$, $`\mathring{e}_{65}`$) and the annuity-due at 65 ($`\ddot{a}_{65}`$, at 4%) are computed for every simulated path and year by exactly the recursions of chapter 5, vectorized: $`q = m/(1+m/2)`$ above infancy and the infant factor of [section 3.3](03-crude-rates.md#33-from-a-rate-to-a-probability) at age 0, $`\ell_{x+1} = \ell_x(1 - q_x)`$, $`L_x = \ell_{x+1} + \phi_x d_x`$, the open last interval $`L_{110} = \ell_{110}/m_{110}`$ of (5.8), and $`\ddot{a}_{65} = N_{65}/D_{65}`$:

$$
\mathring{e}_{x} = \frac{T_x}{\ell_x}, \qquad \ddot{a}_{65} = \frac{\sum_{j \ge 0} v^{j}\,\ell_{65+j}}{\ell_{65}}. \tag{6.13}
$$

The two paths to the same number (this vectorized code and chapter 5's `build_life_table` plus `Commutation`) agree to better than one part in $`10^{9}`$.

## 6.6 Cohort versus period

A **period** table applies the rates of one calendar year $`Y`$ to every age. But a person who turns 65 in year $`Y`$ lives through the rates of $`Y`$ at age 65, of $`Y+1`$ at 66, of $`Y+2`$ at 67 and so on: their own **cohort** path. When mortality is improving, later years have lower rates, so the cohort lives longer than the period table says:

$$
\ddot{a}^{\text{period}}_{65}(Y) = \sum_{j \ge 0} v^{j} \prod_{i=0}^{j-1}\left(1 - q_{65+i,\,Y}\right), \qquad \ddot{a}^{\text{cohort}}_{65}(Y) = \sum_{j \ge 0} v^{j} \prod_{i=0}^{j-1}\left(1 - q_{65+i,\,Y+i}\right). \tag{6.14}
$$

The two coincide exactly when mortality does not change. The ratio $`\ddot{a}^{\text{cohort}}/\ddot{a}^{\text{period}} - 1`$ is how much an annuity priced on the period table **understates** its cost. For a man turning 65 in 2025 on the long-run projection, $`\mathring{e}_{65}`$ is 17.61 on the period table and 18.43 along the cohort path, and the annuity is understated by 2.6% (the same for women turning 65 in 2025).

## 6.7 The backtest and its calibration

A model that fits history may still forecast badly. The **backtest** stands at an *origin* year in the past, fits the model to the data up to then, forecasts 10 and 20 years ahead, and compares with what the series later did (the reconstruction, measured with the same code). The origins are 1979, 1989, 1999 and 2009, the fitting windows start in 1950, 1970 or 1990, and the horizons are those that fit before 2019: 78 forecasts in all. For each, the error is the median forecast minus the actual of $`\mathring{e}_0`$, $`\mathring{e}_{65}`$ and the annuity value, and the check is whether the actual $`\mathring{e}_{65}`$ fell inside the model's own 90% band.

**Calibration.** The backtest shows the model's own band is too narrow: the structural slowdown in Mexican men's mortality after 1999 is not noise. A random walk's forecast error should grow like $`\sqrt{h}`$, so write $`\mathrm{error} = c\sqrt{h}\,Z`$ with $`Z`$ a standard normal and estimate the scale $`c`$ from the backtest errors $`e_i`$ at horizons $`h_i`$. Since $`E[e_i^2] = c^2 h_i`$,

$$
\hat c = \sqrt{\frac{1}{n}\sum_i \frac{e_i^{2}}{h_i}}, \qquad \text{90\% band:}\quad \text{median} \pm 1.645\,\hat c\,\sqrt{h}. \tag{6.15, 6.16}
$$

where $`h`$ is now the years since 2024. For men's life expectancy at birth, $`\hat c = 0.57`$ years, so the band 26 years out (2050) is $`\pm 1.645 \times 0.57 \times \sqrt{26} = \pm 4.8`$ years, against the model's own 75.6 to 78.3.

## 6.8 Examples you can check by hand

**A drift and its spread.** The index of a short history, $`\kappa = 0,\ -1.2,\ -2.1,\ -3.5,\ -4.4`$ ($`T = 5`$). The differences are $`-1.2,\ -0.9,\ -1.4,\ -0.9`$, so by (6.7) $`\hat\delta = -4.4/4 = -1.1`$ and the deviations from it are $`-0.1,\ 0.2,\ -0.3,\ 0.2`$, so $`\hat\sigma^2 = 0.18/3 = 0.06`$. Ten years ahead the mean is $`-4.4 + 10(-1.1) = -15.4`$ and, by (6.8), the variance is $`10 \times 0.06 + 10^2 \times 0.06/4 = 0.6 + 1.5 = 2.1`$: with so little history the **uncertain drift contributes 71% of the variance**, not the shocks.

**Cohort versus period.** Probabilities of dying $`q_{65} = 0.1`$ and $`q_{66} = 0.2`$ today, with the table closing at 67 and everything improving 10% a year, no interest. The period annuity-due uses today's rates at every age: $`1 + 0.9 + 0.9 \times 0.8 = 2.62`$. The cohort faces the improved rate at 66, one year on: $`q_{66} = 0.2 \times 0.9 = 0.18`$, so $`1 + 0.9 + 0.9 \times 0.82 = 2.638`$. The period table understates the annuity by $`2.638/2.62 - 1 = 0.69\%`$.

**A calibration.** Two backtest errors in life expectancy at birth: 1.0 years at a 10-year horizon and 2.0 years at 20 years. By (6.15), $`\hat c^2 = \tfrac12(1/10 + 4/20) = 0.15`$, so $`\hat c = 0.387`$ and the 90% band 25 years out is $`\pm 1.645 \times 0.387 \times 5 = \pm 3.2`$ years.

## 6.9 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_projection.py`: the invariance of the surface under the shifts of (6.2); the score equations (6.4) at the fitted model, including the reproduction of every age's total deaths; the recovery of a known surface from simulated Poisson data; the drift as a telescoping mean and the variance (6.8) by simulation at three horizons; the jump-off formula (6.9) against a manual computation; the CBD regression (6.11); the closure (6.12) leaving an exact logistic unchanged; the agreement of the vectorized measures with chapter 5's life table; the cohort and period annuities against an independent loop; the calibration (6.15) recovering a known $`c`$ from simulated errors; and the three hand examples above.
2. **An independent implementation.** The same Lee-Carter and CBD models are fitted with **StMoMo** in R (a different fitting routine) and compared on every build (`projection_r_crosscheck`):

| | Python against StMoMo |
|---|---|
| Lee-Carter $`\kappa_t`$ | largest difference 0.0001 |
| Lee-Carter $`\beta_x`$ | identical |
| Lee-Carter $`\mathring{e}_0`$ and $`\mathring{e}_{65}`$ forecasts | differ by less than 0.00002 years |
| CBD $`\kappa^1`$ / $`\kappa^2`$ | differ by up to 0.053 / 0.004 (least squares here, binomial likelihood in StMoMo) |
| CBD $`\mathring{e}_{65}`$ forecasts | differ by 0.013 to 0.038 years |

3. **The data.** The quantities below are tested against the shipped database.

*The slowdown of men's improvement.* Least-squares trends in the Lee-Carter index $`\kappa_t`$ (fitted to CONAPO 1970 to 2019): men's index fell **1.86 a year** over 1970 to 1999 and **0.28 a year** over 2000 to 2019, **15%** of the earlier pace; women's fell 2.61 and 0.48, 18%. A model fitted to 1970 to 1999 and restarted at the 1999 rates overshoots men's 2019 life expectancy at birth by **3.9 years** (women 2.3), the cost of extrapolating a trend that stopped.

*Backtest results,* Lee-Carter fitted from 1970 and restarted at the last observed rates:

| | Men | Women |
|---|--:|--:|
| Mean absolute error in $`\mathring{e}_{65}`$ (years) | 0.52 | 0.35 |
| Mean absolute error in the annuity at 65 | 1.8% | 1.5% |
| Same, fitted from 1950 instead of 1970 ($`\mathring{e}_{65}`$) | 0.66 | 0.83 |
| CBD, fitted from 1970 ($`\mathring{e}_{65}`$) | 0.56 | 0.58 |
| Share of five backtests where the actual $`\mathring{e}_{65}`$ fell inside the model's 90% band | 40% | 60% |
| Calibration constant $`\hat c`$: $`\mathring{e}_0`$, $`\mathring{e}_{65}`$, annuity | 0.57, 0.20, 0.64% | 0.44, 0.12, 0.54% |

Life expectancy at 65 is forecast far better than at birth (the error in $`\mathring{e}_0`$ comes from ages under 65, which the pensions do not care about), the 1970 window beats 1950 (the 1950s were a different regime), and the model's own fan is too narrow, which is why the projection carries a second, calibrated band. Five backtests per sex is a small sample: read the coverage and the constants as indicative.

*Scenarios* (medians; all restart at the observed 2024 rates). Life expectancy at birth for men: **74.1** (2030), **77.0** (2050), **79.5** (2070) on the long-run trend; **73.4, 74.3, 75.1** on the recent trend; 73.6, 77.3, 80.2 in CONAPO's official projection. The annuity-due at 65 (4% interest) for men is 12.30 in 2024; by 2050 it is **13.09 (+6%)** on the long-run trend and **12.52 (+2%)** on the recent one. The gap between those two scenarios, not the width of either band, is the main uncertainty about the future of men's mortality.

## 6.10 Code map

| Formula | Function (`src/mortality/projection.py`) | Checked by (`tests/test_handbook_projection.py`) |
|---|---|---|
| (6.1), (6.2), (6.3) | `fit_lee_carter`, `LeeCarter` | `test_lee_carter_identification`, `test_shifting_and_rescaling_leave_the_fitted_rates_unchanged`, `test_lee_carter_recovers_a_known_surface` |
| (6.4), (6.5) | `fit_lee_carter` | `test_lee_carter_solves_the_poisson_score_equations` |
| (6.6), (6.7) | `fit_random_walk` | `test_the_drift_is_the_mean_first_difference_which_telescopes`, `test_drift_example_by_hand` |
| (6.8) | `simulate_walk` | `test_the_forecast_spread_grows_with_the_square_root_of_the_horizon_plus_the_drift_term` |
| (6.9) | `forecast_lee_carter`, `central_lee_carter` | `test_jump_off_restarts_from_the_observed_rates`, `test_the_central_path_moves_by_the_drift_alone` |
| (6.10), (6.11) | `fit_cbd`, `forecast_cbd` | `test_cbd_factors_are_the_intercept_and_slope_of_logit_q_on_age`, `test_cbd_forecast_with_jump_off_starts_from_the_observed_logit` |
| (6.12) | `close_old_ages` | `test_the_closure_of_an_exact_logistic_is_that_logistic_at_every_age` |
| (6.13) | `period_measures` | `test_period_measures_agree_with_the_life_table_of_chapter_5` |
| (6.14) | `_cohort_rows` | `test_cohort_annuity_uses_the_rates_of_the_year_each_age_is_reached`, `test_cohort_toy_example_by_arithmetic` |
| (6.15), (6.16) | `backtest`, `backtest_calibration` | `test_calibration_constant_is_the_root_mean_square_of_error_over_root_horizon` |
| Section 6.9, tables | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To reproduce the drift example of section 6.8:

```python
import numpy as np
from mortality.projection import fit_random_walk

walk = fit_random_walk(np.array([0.0, -1.2, -2.1, -3.5, -4.4]))
print(walk.drift, walk.cov)  # [-1.1] [[0.06]]
```

## 6.11 Limits

- **The history is a reconstruction.** CONAPO's 1970 to 2019 rates are smooth and model-based, so the fitted uncertainty is understated; the backtest and the calibrated band partly correct for it.
- **The source break at 2020.** The observed series is not one consistent measurement: the two sources disagree by age (section 6.1). Scenarios restart at the INEGI-based 2024 rates, which is right for this project but not the level CONAPO itself projects from.
- **Five backtests per sex** is a small sample; the coverage figures and the calibration constants are indicative.
- **COVID is excluded from the fit** (2020 to 2022 are not in the 1970 to 2019 window) and treated as a level shock that the restart absorbs. The scenarios do not model repeat shocks.
- **A linear trend in log mortality cannot slow down by itself.** The long-run scenario will eventually overstate improvement at the youngest ages; that is why the recent-trend scenario is shown next to it.
- **One index for every age.** Lee-Carter has one period index, so all ages are driven by the same shocks; it cannot represent the quite different recent histories of young and old adults. The CBD model, built for ages 60 and over, partly addresses this for pensions.
- **No cause-of-death structure.** Violence, diabetes and COVID are not modeled separately: the stagnation of men is observed, not explained.
- **Drift uncertainty is a normal approximation** with the variance (6.8); it assumes the shocks are independent from year to year and ignores uncertainty in $`\beta`$ and $`\alpha`$.
- **The old ages** rest on the closure (6.12) and, above 90, on assumptions rather than credible data.

## References

- Lee, R. D. and Carter, L. R. (1992). Modeling and forecasting U.S. mortality. *Journal of the American Statistical Association* 87(419), 659-671.
- Brouhns, N., Denuit, M. and Vermunt, J. K. (2002). A Poisson log-bilinear regression approach to the construction of projected lifetables. *Insurance: Mathematics and Economics* 31(3), 373-393.
- Cairns, A. J. G., Blake, D. and Dowd, K. (2006). A two-factor model for stochastic mortality with parameter uncertainty: theory and calibration. *Journal of Risk and Insurance* 73(4), 687-718.
- Booth, H. and Tickle, L. (2008). Mortality modelling and forecasting: a review of methods. *Annals of Actuarial Science* 3(1-2), 3-43.
- Villegas, A. M., Kaishev, V. K. and Millossovich, P. (2018). StMoMo: an R package for stochastic mortality modeling. *Journal of Statistical Software* 84(3), 1-38.
- Thatcher, A. R., Kannisto, V. and Vaupel, J. W. (1998). *The Force of Mortality at Ages 80 to 120*. Odense University Press.
