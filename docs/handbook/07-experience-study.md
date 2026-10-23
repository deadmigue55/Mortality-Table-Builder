# 7. The experience study

> [!NOTE]
> **In one minute.** Every life insurer asks each year: *how is our own mortality running against the table we price with, and what should we change?* An **experience study** answers it. It starts from the company's policy records, cleans them, turns dates into exact exposure, compares actual deaths with those a table predicts (the **A/E** ratio), decides how far to trust each ratio (**credibility**), separates overlapping effects with a regression, reads the wearing-off of underwriting (the **select period**), corrects for deaths not yet reported, and ends with a new mortality basis and what it does to prices and reserves.
>
> **What this chapter does:** it derives each of those steps. Because no insurer publishes its policy data, the study runs on a **synthetic** portfolio with effects planted at known sizes, so the question the chapter can answer is *does the method recover what is really there?* The portfolio's own effects are illustrative assumptions and say nothing about any real company.
>
> **The number to remember.** The study recovers **15 of 15** planted effects within their 95% intervals (women 0.65 against 0.66 planted, rated risks 1.53 against 1.55), and it shows that reading the latest quarter raw would be 19.5% short of the true deaths, against 2.0% after the correction.

Code: `src/mortality/experience.py` (with `lexis.py` for exposure and `portfolio.py` for the synthetic portfolio) · Tests: `tests/test_experience.py`, `tests/test_portfolio.py` and `tests/test_handbook_experience.py` · Results: [experience-study.md](../experience-study.md)

**Local symbols** (everything else is in the [notation](01-notation.md)). $`D_i`$ and $`e_i`$ are the actual and expected deaths of cell $`i`$ (a cell is a set of Lexis pieces sharing the same rating factors); $`\mathrm{SA}`$ is the sum assured; $`Z`$ is a credibility weight; $`s^2`$, $`v`$ and $`K`$ are the Bühlmann-Straub variances and their ratio; $`\psi`$ is the dispersion; $`F(l)`$ is the share of deaths reported within $`l`$ days.

**Contents.** [7.1](#71-exposure-and-expected-deaths) expected deaths · [7.2](#72-actual-to-expected-by-count-and-by-amount) A/E · [7.3](#73-how-far-to-trust-a-ratio-credibility) credibility · [7.4](#74-separating-overlapping-effects-a-poisson-glm) GLM · [7.5](#75-the-select-period) select period · [7.6](#76-deaths-not-yet-reported-the-claims-lag) claims lag · [7.7](#77-a-company-basis-and-what-it-is-worth) basis and impact · [7.8](#78-examples-you-can-check-by-hand) examples · [7.9](#79-validation) validation · [7.10](#710-code-map) code map · [7.11](#711-limits) limits

---

## 7.1 Exposure and expected deaths

The study starts with the policy extract: one row per policy with its dates, sum assured, underwriting class, channel, state, and how and when it left observation. Before any rate is computed the extract is **validated**: duplicates, impossible dates, non-positive amounts, exits before issue and the like are found and counted, every record is accounted for from the extract to the clean file, and the number of **deaths** lost to each rule is reported, since an actuary has to be able to say how many deaths a validation step threw away.

The clean policies are cut into **Lexis pieces** ([section 2.6](02-data-exposure-quality.md#26-exposure-from-dates-the-lexis-split)), each with its exact exposure $`t`$, attained age, policy duration and calendar year. Given a table of annual probabilities $`q_x`$, the **expected** deaths of a piece come from the constant force that reproduces $`q`$ over a year, because the force really is constant inside a piece:

$$
\mu_x = -\ln(1 - q_x), \qquad e_{\text{piece}} = t \times \mu_x. \tag{7.1, 7.2}
$$

(A life that survives a year with probability $`1 - q`$ has $`e^{-\mu} = 1 - q`$, so $`\mu`$ is slightly above $`q`$: for $`q = 0.01`$, $`\mu = 0.0100503`$.) Ages past the end of the table use its last value. Summing the pieces of a cell gives its exposure, its expected deaths and its actual deaths.

## 7.2 Actual to expected, by count and by amount

The ratio of actual to expected deaths measures how the portfolio runs against the table:

$$
\frac{A}{E} = \frac{D}{e}, \qquad \text{interval:}\quad \left[\frac{\lambda_L(D)}{e},\ \frac{\lambda_U(D)}{e}\right], \tag{7.3}
$$

with $`\lambda_L`$ and $`\lambda_U`$ the Garwood limits of [section 3.2](03-crude-rates.md#32-how-much-luck-is-in-a-rate-the-poisson-interval): the expected deaths are treated as fixed and the actual as a Poisson count.

**By amount.** An insurer cares more about money than about heads, so the same ratio is formed with each death weighted by its sum assured, and its interval is wider because a few large claims dominate:

$$
\left(\frac{A}{E}\right)_{\text{amount}} = \frac{\sum_i \mathrm{SA}_i\, d_i}{\sum_i \mathrm{SA}_i\, e_i}, \qquad \text{half-width:}\quad 1.96\,\frac{\sqrt{\sum_i \mathrm{SA}_i^{2}\, d_i}}{\sum_i \mathrm{SA}_i\, e_i}, \tag{7.4}
$$

(the lower limit is cut at zero). The half-width comes from the variance of total claims: if the claims of amount $`\mathrm{SA}_i`$ arrive as independent Poisson counts with means $`\lambda_i`$, the total $`S = \sum \mathrm{SA}_i N_i`$ has $`\mathrm{Var}(S) = \sum \lambda_i\,\mathrm{SA}_i^{2}`$ (a *compound Poisson* variance), estimated by replacing $`\lambda_i`$ with the observed $`d_i`$.

## 7.3 How far to trust a ratio: credibility

An A/E from 45 deaths is not a mortality assumption. **Credibility** says how much weight a company's own ratio deserves against a complement (what you would assume without the data).

**Limited-fluctuation (classical) credibility.** From [section 3.9](03-crude-rates.md#39-when-is-a-rate-credible), a count of $`n_F = 1{,}082`$ deaths is within 5% of its mean with probability 90%: full credibility. With fewer deaths $`D`$, the weight $`Z`$ is chosen so that $`Z \times (A/E)`$ fluctuates as little as a fully credible ratio would. Since the relative fluctuation of $`A/E`$ is proportional to $`1/\sqrt{D}`$, that requires $`Z^2 / D = 1/n_F`$:

$$
Z = \min\!\left(1, \sqrt{\frac{D}{1082}}\right), \qquad \left(\frac{A}{E}\right)_{\text{credible}} = Z \times \frac{A}{E} + (1 - Z) \times 1. \tag{7.5, 7.6}
$$

The complement is the table itself (a ratio of 1).

**Bühlmann-Straub credibility** asks the data how much classes really differ. Suppose a class $`i`$ has a true ratio $`\theta_i`$ drawn from a distribution with mean $`m`$ and variance $`v`$ (the **scatter between classes**), and its observed ratio in each period $`j`$ has mean $`\theta_i`$ and variance $`s^2/w_{ij}`$, where $`w_{ij}`$ is the expected deaths (the **scatter inside a class**, which shrinks with volume). The best linear estimate of $`\theta_i`$ from its own mean $`\bar r_i`$ and the portfolio mean $`m`$ is $`Z \bar r_i + (1-Z)m`$ with $`Z`$ chosen to minimize the squared error $`Z^2 s^2/w + (1-Z)^2 v`$. Setting the derivative to zero,

$$
Z_i = \frac{w_i}{w_i + K}, \qquad K = \frac{s^2}{v}, \qquad w_i = \sum_j w_{ij}. \tag{7.7}
$$

More expected deaths give more weight to the class's own experience; a large $`K`$ (classes that barely differ) gives it little. The two variances are estimated from the data, with $`\bar r_i = \sum_j w_{ij}r_{ij}/w_i`$, $`\bar r = \sum_i w_i\bar r_i/w`$, $`n_i`$ the number of periods in which class $`i`$ is observed and $`c`$ the number of classes:

$$
\hat s^{2} = \frac{\sum_{i,j} w_{ij}\left(r_{ij} - \bar r_i\right)^2}{\sum_i (n_i - 1)}, \qquad \hat v = \frac{\sum_i w_i\left(\bar r_i - \bar r\right)^2 - (c-1)\,\hat s^{2}}{w - \sum_i w_i^{2}/w}, \qquad \hat K = \frac{\hat s^{2}}{\hat v}, \tag{7.8, 7.9}
$$

with $`w = \sum_i w_i`$. (When the classes do not differ by more than chance, $`\hat v \le 0`$ and every $`Z`$ is zero.) The credible mean of a class is $`Z_i\bar r_i + (1-Z_i)\bar r`$, pulled toward the **portfolio** mean $`\bar r`$ instead of toward the table.

> [!IMPORTANT]
> The choice of complement matters more than the choice of formula. A segment of 45 deaths and A/E 0.36 is pulled to 0.87 by classical credibility (toward a table that the data say does not fit) and to 0.40 by Bühlmann-Straub (toward the rest of the portfolio, which runs at 0.77). Which is right depends on whether the old table or the rest of the book is the better prior; here the book is.

## 7.4 Separating overlapping effects: a Poisson GLM

One-way tables mislead when factors overlap: a channel that sells mostly simplified-issue business looks bad until the underwriting class is held equal. A regression separates the effects. Let each cell $`i`$ have expected deaths $`e_i`$ on the reference table and a set of rating-factor levels, coded by indicators $`x_{ij}`$. The **Poisson GLM with an offset** says

$$
D_i \sim \mathrm{Poisson}(\mu_i), \qquad \ln \mu_i = \ln e_i + \beta_0 + \sum_j \beta_j\, x_{ij}, \tag{7.10}
$$

so that $`\exp(\beta_j)`$ is a **relativity**: how much more (or less) mortality level $`j`$ has than the reference level, all other factors held equal, and $`\exp(\beta_0)`$ is the model's A/E of the all-reference cell. The expected deaths enter as a known multiplier (an *offset*), so the regression explains only the *departure* of the portfolio from the table.

The log-likelihood is $`\sum_i [D_i \ln\mu_i - \mu_i]`$ and its derivatives with respect to each $`\beta_j`$ give the score equations

$$
\sum_i x_{ij}\left(D_i - \mu_i\right) = 0 \quad\text{for every } j, \qquad\text{so}\qquad \sum_{i \in \text{level } j}\mu_i = \sum_{i \in \text{level } j} D_i. \tag{7.11}
$$

**The fitted model reproduces the actual deaths of every level of every factor**, and of the whole portfolio (the intercept column is all ones): the regression moves deaths between cells; it neither creates nor loses them. It is the same conservation law as (4.14) and (6.4).

**Honest standard errors.** With a variance of $`\psi\,\mu_i`$ instead of $`\mu_i`$ (overdispersion, as in [section 4.5](04-graduation.md#45-how-smooth-is-smooth-enough)), the **quasi-Poisson** fit keeps the same estimates and scales every standard error by $`\sqrt{\psi}`$:

$$
\mathrm{se}_{\log}(\beta_j) = \sqrt{\hat\psi}\ \mathrm{se}_{\text{Poisson}}(\beta_j), \qquad \text{interval:}\quad \exp\!\left(\hat\beta_j \pm 1.96\,\mathrm{se}_{\log}\right). \tag{7.12}
$$

The dispersion is estimated on **bins**: cells are sorted by fitted value and pooled into bins of about 10 expected deaths, and $`\hat\psi = \max\bigl(1,\ \chi^2_{\text{bins}}/(n_{\text{bins}} - p)\bigr)`$ with the Pearson statistic of the bins and $`p`$ the number of parameters. Pooling matters when most cells expect a small fraction of a death: a Poisson count that small is far from normal, so the statistic over single cells is dominated by a few cells and is noisy; bins of 10 expected deaths are large enough for the normal approximation behind a chi-square. On exactly Poisson data both versions are close to 1, and on overdispersed data the binned one is close to the true dispersion (tested, section 7.9). Pandemic years are left out of the regression, because their excess varies by age and would contaminate the age effect.

## 7.5 The select period

Underwriting wears off: mortality in the first policy years is below the ultimate level. The study reads the policy-year effects of the GLM against the ultimate group (years 6 to 10), separately for fully underwritten and simplified-issue business (their select patterns differ). The raw effects zig-zag with sampling noise, so they are smoothed with **isotonic regression**: among all non-decreasing sequences $`u_1 \le u_2 \le \dots \le u_5`$, take the one closest, in weighted least squares, to the raw factors $`v_j`$:

$$
\min_{u_1 \le \dots \le u_5}\ \sum_j w_j\left(u_j - v_j\right)^2, \qquad w_j = \frac{1}{\mathrm{se}_{\log,j}^{2}}. \tag{7.13}
$$

The **pool-adjacent-violators** algorithm solves it exactly: scan left to right and, whenever a value is above its successor, replace both by their weighted mean and repeat. The result is non-decreasing, preserves the weighted total $`\sum w_j v_j`$, leaves a sequence that already rises unchanged, and removes the zig-zag without inventing a shape. The smoothed factor is capped at 1. The **select period** is the last duration whose interval excludes 1: only policy years 1 and 2 in this portfolio, though the planted effect lasts five. **With a few thousand deaths the select period cannot be dated, and the number is a lower bound.** That is why a basis should use the smoothed factors, not the "period".

## 7.6 Deaths not yet reported: the claims lag

The latest months always look too good, because deaths have not been reported yet (**IBNR**, incurred but not reported, in the language of claims reserving). The extract is taken some weeks after the study ends, so recent deaths are missing from the count; and because an unreported death is still treated as in force, its exposure keeps running to the end of the study.

**The lag distribution.** For deaths old enough that nearly all have been reported (at least 540 days before the extract), the empirical distribution of the days from death to notification is

$$
F(l) = \frac{\#\{\text{mature deaths notified within } l \text{ days}\}}{\#\{\text{mature deaths}\}}. \tag{7.14}
$$

**Completion.** A death on day $`d`$ is in the extract only if it was notified by the extract date $`E`$, which has probability $`F(E - d)`$. The share of a quarter $`Q`$'s deaths that are in the extract is the average over its days, and the completed count and A/E follow:

$$
c_Q = \frac{1}{|Q|}\sum_{d \in Q} F(E - d), \qquad \hat D_Q = \frac{D_Q}{c_Q}, \qquad \left(\frac{A}{E}\right)^{\text{completed}}_Q = \frac{1}{c_Q}\left(\frac{A}{E}\right)_Q. \tag{7.15, 7.16}
$$

Each Lexis piece lies inside one calendar year; its exposure and expected deaths are shared among the quarters it overlaps in proportion to days (exact, because the force is constant in a piece), and a death belongs to the quarter of its last day of exposure.

## 7.7 A company basis and what it is worth

The study ends by turning its findings into a **mortality basis**: the expected table times a multiplier by sex, age group and policy-year group, from the GLM on the non-pandemic years. The multiplier is not the raw regression result, which for thin data would be noise: the overall level and each effect are **shrunk toward 1** by the limited-fluctuation weight $`Z`$ of (7.5), computed from the deaths behind it, and the result is interpolated in age between the centers of the age groups (24, 34.5, 44.5, 54.5 and 65) on the log scale, so the basis has no steps:

$$
\ln \mathrm{mult}\,(\text{sex, age group, duration}) = Z_{0}\ln r_0 + Z_{\text{sex}}\ln r_{\text{sex}} + Z_{\text{age}}\ln r_{\text{age}} + Z_{\text{dur}}\ln r_{\text{dur}}, \qquad q^{\text{exp}}_x = \min\!\left(q^{\text{table}}_x \times \mathrm{mult},\ 1\right). \tag{7.17}
$$

A **prudent** basis adds a margin an actuary may need where a prudent assumption is required: the multiplier raised to its one-sided 95% upper bound, from the standard error of the fitted multiplier (the covariance of the regression), interpolated in the same way,

$$
\mathrm{mult}^{\text{prudent}} = \exp\!\left(\ln \mathrm{mult} + 1.645\ \mathrm{se}\right). \tag{7.18}
$$

It is above the best estimate by construction, and the width of the gap is the visible price of thin data.

**What it is worth.** Two measures of the basis's effect use the formulas of [chapter 5](05-life-tables.md). The **net annual premium** of an $`n`$-year term insurance on a path of probabilities $`q_0, \dots, q_{n-1}`$ (one for each policy year), paid at the start of each year while alive, with $`{}_tp = \prod_{k<t}(1 - q_k)`$ and the benefit paid at the end of the year of death, is

$$
P = \frac{\sum_{t=0}^{n-1} v^{t+1}\,{}_tp\ q_t}{\sum_{t=0}^{n-1} v^{t}\,{}_tp}, \tag{7.19}
$$

the ratio $`A^{1}_{x:\overline{n}\vert}/\ddot{a}_{x:\overline{n}\vert}`$ of chapter 5, with the policy-year multiplier folded into each $`q_t`$ so that the select effect enters the price. The **present value of the death benefits** of an in-force block groups the policies by sex, attained age, duration and years left, and sums

$$
\mathrm{PV} = \sum_{\text{groups}} \mathrm{SA}\ \sum_{t=0}^{n-1} v^{t+1}\,{}_tp\ q_t \qquad (\text{no lapses, benefit at the end of the year of death}), \tag{7.20}
$$

computed once on the table and once on the experience basis. Premiums here are **net** (no expenses, profit or lapses), at 4% interest.

## 7.8 Examples you can check by hand

**A regression by hand.** Four cells, two factors, with deaths exactly equal to expected times a relativity (sex F 0.6, class RATED 1.5):

| Sex | Class | Expected | Deaths | $`D/e`$ |
|---|---|--:|--:|--:|
| M | STANDARD | 100 | 100 | 1.00 |
| M | RATED | 80 | 120 | 1.50 |
| F | STANDARD | 100 | 60 | 0.60 |
| F | RATED | 50 | 45 | 0.90 |

The table is exactly multiplicative ($`0.9 = 0.6 \times 1.5`$), so the GLM (7.10) recovers it with no error: intercept 1.00, F 0.60, RATED 1.50.

**Credibility of a thin segment.** 45 deaths and A/E $`0.36`$ (so $`e = 45/0.36 = 125`$). Classical: $`Z = \sqrt{45/1082} = 0.204`$ and the credible ratio is $`0.204 \times 0.36 + 0.796 \times 1 = 0.87`$. Bühlmann-Straub with $`K = 11.5`$ (section 7.9): $`Z = 125/(125 + 11.5) = 0.916`$ and the credible ratio is $`0.916 \times 0.36 + 0.084 \times 0.77 = 0.40`$.

**Bühlmann-Straub by hand.** Two classes, two periods, all expected deaths 10; ratios $`A: 0.8, 1.0`$ and $`B: 1.2, 1.4`$. The class means are $`\bar r_A = 0.9`$ and $`\bar r_B = 1.3`$ and the grand mean is $`1.1`$; each $`w_i = 20`$ and $`w = 40`$. The scatter inside classes is $`\hat s^2 = (0.2 + 0.2)/(1 + 1) = 0.2`$. Between classes, $`\hat v = \dfrac{20 \times 0.04 + 20 \times 0.04 - 1 \times 0.2}{40 - (400 + 400)/40} = \dfrac{1.4}{20} = 0.07`$. So $`\hat K = 0.2/0.07 = 2.857`$, $`Z = 20/22.857 = 0.875`$ and the credible mean of class A is $`0.875 \times 0.9 + 0.125 \times 1.1 = 0.925`$.

**Isotonic smoothing.** Raw policy-year factors $`0.55,\ 0.50,\ 0.88`$ with equal weights: the first two violate the order, so they are pooled to their mean, giving $`0.525,\ 0.525,\ 0.88`$. With weights $`(1, 3, 1)`$ on $`(0.8, 0.5, 0.9)`$ the first two pool to $`(0.8 + 3 \times 0.5)/4 = 0.575`$.

**A quarter's completion.** Suppose every death is reported within 30 days, $`F(l) = (l+1)/30`$ up to $`l = 29`$ and 1 afterwards, and the extract is on the last day of the quarter (90 days). The day with a wait of $`w`$ days (0 to 89) contributes $`F(w)`$: the 29 days with $`w = 0, \dots, 28`$ contribute $`(1 + 2 + \dots + 29)/30 = 14.5`$ and the other 61 days contribute 1 each, so $`c_Q = 75.5/90 = 0.839`$. If the extract shows 84 deaths, the completed count is $`84/0.839 = 100.1`$.

## 7.9 Validation

The method is judged on what it recovers, and the judgment is possible because the truth is known.

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_experience.py`: the expected-deaths convention; the amount interval and the compound-Poisson variance by simulation; the credibility weights and the minimum of the error expression; Bühlmann-Straub by hand and its recovery of known variances from simulated classes; the GLM on an exactly multiplicative table, the conservation law (7.11) and the quasi-Poisson scaling; the dispersion estimator on Poisson and on overdispersed counts; pool-adjacent-violators against a direct constrained optimization; the lag distribution and the completion of a quarter; the conservation of exposure, expected deaths and deaths across quarters; and the net premium and the present value against chapter 5's term insurance, to twelve digits.
2. **Defects found.** Defects of the kinds found in real extracts are injected into the synthetic portfolio and the validation finds them all:

| Check | Injected | Found |
|---|--:|--:|
| Duplicate records | 573 | 573 |
| Invalid sex | 275 | 275 |
| Birth missing or after issue | 275 | 275 |
| Non-positive sum assured | 275 | 276 |
| Exit before issue | 359 | 393 |
| Issue after the extract date | 115 | 115 |
| Invalid state (repaired to UNKNOWN) | 275 | 275 |
| Death with no notification date (kept) | 44 | 45 |

The few extra are duplicates of already-defective rows. Reconciliation: 573,082 records and 4,353 deaths in the extract; 573 duplicate copies (3 deaths) and 1,298 other exclusions (14 deaths) dropped; **571,211 records and 4,336 deaths** in the clean file.

3. **The ratios.** The portfolio has 2.60 million policy-years, 4,336 deaths against 5,184 expected on CNSF 2013 (all years). Excluding the pandemic years (2,523 deaths) it runs at **0.77** of CNSF 2013 by count (95% interval 0.74 to 0.80) and **0.68** by amount: large policies die less. Men run at 0.91 and women at 0.59, which the unisex table cannot distinguish.
4. **Credibility.** The Bühlmann-Straub estimates are $`\hat s^2 = 0.92`$, $`\hat v = 0.080`$ and $`\hat K = 11.5`$ across 24 segments; the portfolio mean is 0.77. The segment of section 7.8 (female, standard class, bancassurance, 45 deaths, A/E 0.36) gets 0.87 from classical credibility and 0.40 from Bühlmann-Straub.
5. **Recovery of planted effects.** The regression recovers **15 of 15** planted rating effects inside their 95% intervals (95% expected), with the dispersion estimated at 1.27: women 0.65 (planted 0.66), rated 1.53 (1.55), large policies 0.73 (0.74).
6. **The select period.** For fully underwritten business the estimated policy-year factors are 0.55, 0.66, 0.88, 0.99, 1.01 against planted 0.50, 0.65, 0.78, 0.88, 0.95; all ten estimates (both underwriting types) fall inside their intervals, and the select period reads 2, not 5.
7. **The claims lag.** The median notification lag in the data is 32 days (49% of deaths within 30 days, 73% within 60, 84% within 90, 95% within 180). For the last quarter only 82% of deaths are in the extract: A/E as reported is 0.72, and **0.88** once completed. Against the truth the generator knows, the completed count is 186 against a true 190, an error of **-2.0%** where the raw count is 19.5% short; the quarter before, the raw error is -8.8% and the completed one -3.8%. The practical rule: **do not read the last two or three quarters raw.**
8. **Price and reserves.** On the experience basis a 20-year term at age 40 costs **34% less for women** (1.15 against 1.74 per 1,000) and 3% less for men (1.69); at 30, men's premium is 3% *higher*. The prudent version raises men's premium at 40 to 1.93 (+11% on CNSF). The present value of future death benefits of the in-force block (392,274 policies, MXN 414 billion of sum assured) is **MXN 27.4 billion** on the experience basis against 31.0 billion on CNSF 2013, 12% lower (term 19%, endowment 19%, whole life 8%), and expected claims in the next twelve months fall 18%.

## 7.10 Code map

| Formula | Function (`src/mortality/experience.py`) | Checked by (`tests/test_handbook_experience.py`) |
|---|---|---|
| (7.1), (7.2) | `add_expected` | `test_expected_deaths_use_the_constant_force_that_reproduces_q` |
| (7.3), (7.4) | `actual_to_expected`, `aggregate` | `test_count_and_amount_actual_to_expected_and_their_intervals`, `test_the_variance_of_total_claims_is_the_sum_of_squared_amounts_times_the_rates` |
| (7.5), (7.6) | `credibility_z`, `actual_to_expected` | `test_limited_fluctuation_credibility_is_the_square_root_rule` |
| (7.7), (7.8), (7.9) | `buhlmann_straub` | `test_buhlmann_straub_toy_example`, `test_buhlmann_straub_weight_minimises_the_error_when_the_variances_are_known`, `test_buhlmann_straub_recovers_known_variances_and_shrinks_the_extremes`, `test_the_credibility_example_of_section_7_8` |
| (7.10) | `fit_relativities` | `test_glm_recovers_an_exactly_multiplicative_table_by_hand` |
| (7.11) | `fit_relativities` | `test_the_fitted_glm_reproduces_the_deaths_of_every_level_of_every_factor` |
| (7.12) | `fit_relativities`, `binned_dispersion` | `test_quasi_poisson_scales_the_standard_errors_by_the_root_of_the_dispersion`, `test_the_binned_dispersion_is_near_one_for_poisson_and_near_psi_when_overdispersed` |
| (7.13) | `pool_adjacent_violators`, `select_table` | `test_pool_adjacent_violators_toy_example_and_properties`, `test_monotone_input_is_returned_unchanged` |
| (7.14) | `estimate_lag_distribution` | `test_the_empirical_lag_distribution_uses_only_mature_deaths` |
| (7.15), (7.16) | `completion_by_quarter`, `quarterly_experience` | `test_lag_distribution_and_quarter_completion_by_hand`, `test_quarterly_experience_conserves_exposure_expected_and_deaths` |
| (7.17), (7.18) | `build_basis` | `test_the_basis_multiplier_is_shrunk_toward_one_and_the_prudent_one_is_above`, `test_the_multiplier_is_interpolated_between_age_group_centres_on_the_log_scale` |
| (7.19) | `term_net_premium`, `term_premium_table` | `test_term_net_premium_matches_the_chapter_5_formula` |
| (7.20) | `pv_death_benefits` | `test_the_present_value_of_death_benefits_is_the_term_insurance_of_chapter_5` |
| Section 7.9 | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To run the same study on a real extract:

```
uv run mortality experience template --out extract.csv
uv run mortality experience run --policies my_extract.csv --study-start 2018-01-01 --study-end 2024-06-30 --extract-date 2024-08-15
```

## 7.11 Limits

- **The portfolio is synthetic and its effects are assumptions.** The method is validated; no claim is made about any real company or about the Mexican insurance market.
- **The generator is multiplicative and the study fits a multiplicative model.** Real portfolios have interactions the study does not model (it handles the select-by-class interaction by fitting underwriting types separately). Recovery on synthetic data proves the machinery, not that real mortality is multiplicative.
- **Exposure treats unreported deaths as in force** until the study ends: the count is corrected for the lag, the exposure is not, and the small bias is documented.
- **State enters as terciles** of the project's state mortality ratios, so the state effect is an average, not a per-state relativity.
- **Pandemic effects are dampened and parametric**, not the real pattern of any insurer; the relativities exclude 2020 to 2022.
- **The classical credibility standard is for counts.** Amounts need a higher one, since a few large claims dominate; the study applies the count standard to both.
- **Select period.** With a few thousand deaths it can only be bounded from below (section 7.5).
- **Not covered:** lapse and anti-selective lapse studies, cause of death, joint lives, riders, multi-decrement analysis, and reinsurance experience (ceded and retained, large-claim analysis, treaty experience rating). The same pipeline applies to a cedant's data by treating the cedant as a segment, which is a natural next step but is not implemented.

## References

- Bühlmann, H. and Straub, E. (1970). Glaubwürdigkeit für Schadensätze. *Mitteilungen der Vereinigung Schweizerischer Versicherungsmathematiker* 70, 111-133.
- Longley-Cook, L. H. (1962). An introduction to credibility theory. *Proceedings of the Casualty Actuarial Society* 49, 194-221.
- McCullagh, P. and Nelder, J. A. (1989). *Generalized Linear Models*, 2nd ed. Chapman and Hall. (The quasi-Poisson fit and the score equations.)
- Barlow, R. E., Bartholomew, D. J., Bremner, J. M. and Brunk, H. D. (1972). *Statistical Inference under Order Restrictions*. Wiley. (Isotonic regression and pool-adjacent-violators.)
- Keiding, N. (1990). Statistical inference in the Lexis diagram. *Philosophical Transactions of the Royal Society A* 332, 487-509.
