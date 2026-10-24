# 11. The insured-lives table

> [!NOTE]
> **In one minute.** The people who buy life insurance are not a sample of the population: they are wealthier, underwritten and mostly urban. A table built from the registered deaths of the whole country (chapters 3 to 5) is therefore the wrong table for **pricing a quote**. This chapter builds the right one from the industry's own statistics, the CNSF's individual-life tables for 2021 to 2025. The mathematics is mostly care about *what to count*: which rows of a claims sheet are really deaths, which lives are really exposed, and then how to smooth the rates by comparing them with the population's, where to stop trusting the data, how to extend the table above that, and how large a margin the remaining doubts justify.
>
> **What this chapter does:** it reuses the smoothing of [chapter 4](04-graduation.md), the premium of [chapter 8](08-pricing.md) and the credibility ideas of [chapter 7](07-experience-study.md) on a new kind of data, and states each rule and sensitivity as a formula that is tested.
>
> **The number to remember.** Insured lives die at **14% to 25%** of the population's rate between ages 25 and 65. A 20-year term for a man of 40 has a net premium of **0.85 per 1,000** on the traditional-term table, against 1.74 on the regulator's CNSF 2013 table and **6.62** on the population: which table you quote on moves a price by more than every modeling choice behind the table.

Code: `src/mortality/insured.py`, `insured_analysis.py`, `insured_sensitivity.py`, `insured_compare.py` and `insured_causes.py` · Tests: `tests/test_insured*.py` and `tests/test_handbook_insured.py` · Results: [insured-lives.md](../insured-lives.md)

> [!IMPORTANT]
> The data are **industry statistics**, not a policy-level extract: one row is a cell of age, sex, plan, modality and cover, reported by the insurers to the CNSF, with no policy duration and no dates. What counts as a death and as exposure therefore has to be inferred from the shape of the sheets, which is the first half of this chapter.

**Local symbols** (everything else is in the [notation](01-notation.md)). $`D`$ and $`L`$ are death claims and insured lives of a cell; $`q^{\mathrm{ref}}_x`$ the reference (population) probability of dying; $`a, b`$ the Brass shift and slope; $`k`$ a segment multiplier; $`f`$ the share of lives exposed for part of the year; $`r_x`$ the annual improvement.

**Contents.** [11.1](#111-what-counts-as-a-death-and-as-exposure) deaths and exposure · [11.2](#112-graduating-against-the-population) graduation · [11.3](#113-where-the-data-stop) where data stop · [11.4](#114-products-multipliers-and-the-market-blend) products · [11.5](#115-time-improvement-and-trend) time · [11.6](#116-the-price-the-margin-and-the-law-of-large-numbers) price and margin · [11.7](#117-examples-you-can-check-by-hand) examples · [11.8](#118-validation) validation · [11.9](#119-code-map) code map · [11.10](#1110-limits) limits

---

## 11.1 What counts as a death and as exposure

**Three traps** in the sheets each look harmless and each would have moved the premium by several percent.

**1. One death-claim row in five is not a death.** 20.5% of the 2023 death claims have no age, no sex, no plan and no modality. Dropping them looks like losing a fifth of the deaths; spreading them across the table looks like conservatism; neither is right, because **they are not deaths**: their claimed amounts net to about zero while carrying 0.8 to 1.1 billion pesos of payments a year, cancellations outweigh new claims every year, and their count stays flat at about 7,500 a year while real deaths fell from 51,000 to 27,000. They are the ledger of payments and cancellations of claims reported in earlier years. The rule for a death is therefore *a row of the death cover with a known age and sex, a positive claimed amount and a cause that can cause a death*; the alternative readings are kept as named sensitivities.

When a reading adds rows that cannot be assigned to a product, they are spread over the cells **in proportion to the deaths already there**, year by year, so the year's total grows by exactly the extra and no cell is created or emptied:

$$
d'_{c} = d_c\left(1 + \frac{\mathrm{extra}_y}{\sum_{c' \in y} d_{c'}}\right), \qquad \sum_{c \in y} d'_c = \sum_{c \in y} d_c + \mathrm{extra}_y. \tag{11.1}
$$

**2. 2,300 "sprained ankles" are endowment maturities.** The cause text "LUXACION, ESGUINCE Y TORCEDURA ... DEL TOBILLO" appears on 2,328 death claims from 2022 on. Three quarters of them are at ages 60 to 69 (a spread of 4 years against 14 for all claims), the average claim is 3.6 times a death claim, and they sit on savings-type plans: they are maturities of endowments booked under the death cover with a placeholder cause. They are excluded.

**3. Deaths and exposure must refer to the same cover.** The exposure sheet counts every life with any cover; deaths are counted under the death cover only. A term policy with only a disability cover is exposed but can never produce a death claim. The issue sheet reports lives *by cover*, so the denominator is the lives **holding the death cover**. Since a rate is $`D/L`$, a denominator larger by a factor $`g`$ lowers it by $`1 - 1/g`$: for term business about 10% fewer lives hold the death cover than hold any cover, so using all lives lowers the rates by that much and the premium of a man of 40 by 11.4%.

**Head count, not person-years.** The sheets give the number of lives, not time lived. A life that entered or left during the year counts as one, so the rate is slightly low. If a share $`f`$ of the head count is exposed for only part of the year, on average half of it, the central exposure and the corrected rate are

$$
L^{\mathrm{central}} = L\left(1 - \frac{f}{2}\right), \qquad \text{rate}^{\mathrm{corrected}} = \frac{D}{L(1 - f/2)} = \frac{1}{1 - f/2}\cdot\frac{D}{L}. \tag{11.2, 11.3}
$$

With $`f = 10\%`$ the rate rises by 5.3% ($`1/0.95`$), with $`f = 20\%`$ by 11.1% ($`1/0.9`$). The data give no way to measure $`f`$, so it is a sensitivity, not an adjustment.

## 11.2 Graduating against the population

Four methods are fitted to each product and sex over the ages where the data are credible. Two are those of [chapter 4](04-graduation.md): a **direct Poisson P-spline** of the insured rate and the **Gompertz-Makeham** law. The other two compare the insured rate with a **reference**, the population's $`q^{\mathrm{ref}}_x`$, which lets thin data inherit the population's shape (the young men's hump, the old-age rise).

**The relational P-spline.** Pass the expected deaths *under the reference*, $`L_x\,q^{\mathrm{ref}}_x`$, to the Poisson P-spline as if they were the exposure. The fitted "rate" is then the insured-to-reference **ratio**, smooth in age:

$$
D_x \sim \mathrm{Poisson}\bigl(L_x\,q^{\mathrm{ref}}_x\,\rho_x\bigr), \qquad \hat q^{\mathrm{ins}}_x = \hat\rho_x\,q^{\mathrm{ref}}_x. \tag{11.4}
$$

It keeps every property of the P-spline of chapter 4, including the conservation of total deaths (4.14): the fitted ratio times the reference reproduces the observed deaths.

**The Brass relational model.** Two numbers describe an insured group against the population on the logit scale:

$$
\operatorname{logit} q^{\mathrm{ins}}_x = a + b\,\operatorname{logit} q^{\mathrm{ref}}_x. \tag{11.5}
$$

$`a`$ shifts the whole curve (how much lighter the insured mortality is: with $`b = 1`$ every odds ratio is multiplied by $`e^{a}`$) and $`b`$ tilts it: for small rates the ratio of the insured rate to the reference is about $`e^{a}\,(q^{\mathrm{ref}}_x)^{b-1}`$, so with $`b > 1`$ the ratio *rises* with age and the gap **narrows** as mortality increases (and with $`b < 1`$ it widens). With $`a = 0`$ and $`b = 1`$ the model is the reference itself. It is fitted by binomial maximum likelihood with the lives as weights, and its score equations are

$$
\sum_x L_x\left(\frac{D_x}{L_x} - \hat q_x\right) = 0, \qquad \sum_x L_x\left(\frac{D_x}{L_x} - \hat q_x\right)\operatorname{logit} q^{\mathrm{ref}}_x = 0, \tag{11.6}
$$

so the fitted curve reproduces the total deaths and their logit-weighted total. For the market blend of all products, $`a = -0.10`$ and $`b = 1.32`$ for men: against a population rate of 0.5% the insured rate is $`\operatorname{expit}(-0.10 + 1.32 \times (-5.293)) = 0.0835\%`$, **17% of the population's**.

**Choosing the method.** One dispersion is used for every method, estimated from the crude counts' own high-order differences ([equation 4.18](04-graduation.md#45-how-smooth-is-smooth-enough)): taking it from each fit would let a badly fitting method shrink its own penalty, since the worse the fit the larger its dispersion and the smaller $`\mathrm{Dev}/\hat\psi`$. Each method is scored by the quasi-AIC (4.17) and by a **leave-one-year-out shape error**: fit on two years, predict the third, after rescaling the prediction to the held-out year's total so that a year of lower mortality does not decide the contest,

$$
\mathrm{shape\ error} = \mathrm{Dev}\!\left(D,\ \hat\mu\,\frac{\sum D}{\sum\hat\mu}\right). \tag{11.7}
$$

The rule: **the lowest quasi-AIC among the methods whose out-of-sample shape error is within 5% of the best.** For men's traditional term the quasi-AICs are 47.4 (direct P-spline), 48.8 (relational), 50.4 (Gompertz-Makeham) and 63.6 (Brass), and the direct P-spline is selected; for men's whole life the direct spline's 69.6 (and 73.4 for the relational) is far below 209 and 336 for the parametric methods. With enough data the splines win by a lot; where data are thin (women's traditional term) the four are close and the rule picks the one with the fewest effective parameters.

## 11.3 Where the data stop

Above some age the insured data stop describing insured lives: a term policy ends, so the lives that remain at 60 and over are few and unrepresentative, and lives who died stay in the books with their deaths never reported. The ratio of the insured rate to the population's, which is steady at the working ages, then **collapses**. The rule for the last credible age finds the collapse:

$$
R_x = \frac{D_x/L_x}{q^{\mathrm{ref}}_x}, \qquad \bar R_x = \tfrac13\left(R_{x-1} + R_x + R_{x+1}\right), \qquad x_{\text{last}} = \min\bigl\{x \ge 55 : \bar R_x < 0.85\ \operatorname{median}_{40 \le x' \le 60} R_{x'}\bigr\} - 1. \tag{11.8}
$$

The threshold is 85% of the median ratio at ages 40 to 60 (if no age from 55 to 90 falls below it the range ends at 90); a ratio that *rises* (a product mix moving toward whole life) is not a collapse. Because of the three-age smoothing the rule fires one age *before* a sharp fall: a ratio that drops from 0.20 to 0.10 at age 70 gives $`x_{\text{last}} = 68`$. One range is used for both sexes (the shorter), since letting each sex have its own made women's extension start first and cross men's.

**The extension.** Above $`x_{\text{last}}`$ the table is not read from the data. The ratio to the population rises from its value $`r_{\text{end}}`$ at $`x_{\text{last}}`$ to 1 at age 105 along a smooth S-curve, the **smoothstep**:

$$
w = \frac{x - x_{\text{last}}}{105 - x_{\text{last}}}, \qquad r(x) = r_{\text{end}} + (1 - r_{\text{end}})\left(3w^{2} - 2w^{3}\right), \qquad q^{\mathrm{ins}}_x = r(x)\,q^{\mathrm{ref}}_x. \tag{11.9}
$$

The function $`3w^2 - 2w^3`$ is 0 at $`w = 0`$ and 1 at $`w = 1`$, passes 0.5 at the middle, and has a zero slope at both ends, so the extension joins the data without a kink and meets the population without one. The result is kept non-decreasing in age from $`x_{\text{last}}`$ and equals the population's rate above 105. The pace is of the order of the US's (the US insured advantage closes over about 45 years of age); it is an *assumption*, flagged in every table (`source = extended`) and figure. It moves no standard quote (a 20-year term at 40 uses ages 40 to 59, all inside the data; convergence at 95 or 115 changes the premium by 0.0%) but it does move whole life, annuities and any quote past about age 45.

**The sex floor.** No population and no insured group shows women dying faster than men at these ages, but a thin extension can leave men below women. Men's rate is raised to women's wherever it falls below, and the changed ages are flagged and lose their interval:

$$
q^{M}_x \leftarrow \max\!\left(q^{M}_x,\ q^{F}_x\right), \qquad x \ge 18. \tag{11.10}
$$

## 11.4 Products, multipliers and the market blend

Mortality differs two to three and a half times between products (credit life, traditional term, whole life and endowment), so a table is built for each, and quoting a traditional term on the market blend would overstate it by 40%. Segments too thin to graduate are a multiple of a reference segment's table. The multiplier is the **Poisson maximum-likelihood estimate** of one factor in deaths $`\sim \mathrm{Poisson}(k\,L_x\,q^{\mathrm{ref}}_x)`$: total deaths over total expected deaths,

$$
\hat k = \frac{\sum_x D_x}{\sum_x L_x\,q^{\mathrm{ref}}_x}. \tag{11.11}
$$

(Setting the derivative of $`\sum D\ln(kE) - kE`$ to zero gives this, as for the single factor of (3.1).) Its interval is widened by the dispersion of the age-decade ratios, because the segment's age pattern is never exactly the reference's. A single factor cannot capture a segment that pulls away from the reference as ages rise (whole life against term), so a second parameter is allowed, a straight line in the log of the multiplier, fitted by a Poisson regression with the reference as offset:

$$
\ln k(x) = a + b\,\frac{x - 45}{20}, \qquad x \in [25, 65]. \tag{11.12}
$$

The **market blend** is the exposure-weighted mean of the product tables, so it is always consistent with its parts and carries the mix of business of the base years:

$$
q^{\mathrm{market}}_x = \frac{\sum_s L_{s,x}\,q_{s,x}}{\sum_s L_{s,x}}, \tag{11.13}
$$

and therefore always lies between its smallest and largest component. Against traditional term, credit life dies 1.3 to 1.6 times as fast at 25 to 44 and 1.6 to 2.1 times at 45 to 65; whole life and endowments 1.9 to 2.3 times at 25 to 44 and 2.5 to 3.6 at 45 to 65; other term modalities 1.1 to 1.5 times at 25 to 44.

## 11.5 Time: improvement and trend

The table is the 2023 to 2025 level, centered on 2024. To roll it to the pricing year, the project uses the **population's** projected improvement ([chapter 6](06-projection.md)), the geometric average annual rate over 2025 to 2045, not the insured data's own trend:

$$
r_x = 1 - \left(\frac{q_{x,2045}}{q_{x,2025}}\right)^{1/20}, \qquad q_{x,\ \text{pricing year}} = q_{x,\ \text{table}}\,(1 - r_x)^{\,n}, \tag{11.14}
$$

with $`n = 2`$ years from 2024 to 2026 (the improvement runs from about 0.7% to 2.7% a year at ages 25 to 65). The insured data's own trend is evidence about the direction of change but cannot be used as the improvement assumption: the book grew 20% in two years, new business is freshly underwritten (the select period of [chapter 7](07-experience-study.md#75-the-select-period)), and three years cannot separate that from improvement.

**The trend measures.** To compare years without the effect of a changing age mix, the **standardized rate** applies fixed age weights (the 2024 exposure) at ages 25 to 79, and the **annual change** is the slope of a Poisson regression of deaths on the year with the table as offset:

$$
\text{rate}_y = \frac{\sum_x w_x\,D_{x,y}/L_{x,y}}{\sum_x w_x}, \qquad \ln\frac{D_{x,y}}{L_{x,y}\,q_x} = \gamma_0 + \gamma_1\,(y - \bar y), \qquad \text{annual change} = e^{\gamma_1} - 1. \tag{11.15, 11.16}
$$

(a change of $`-5\%`$ a year in every age gives $`\gamma_1 = \ln 0.95`$). Standard errors are scaled by the Pearson dispersion.

## 11.6 The price, the margin and the law of large numbers

**The premium.** A table is turned into a premium by the net premium of [chapter 8](08-pricing.md#81-the-net-premium-and-the-reserve) at 4%, per 1,000 of a level term cover,

$$
P_{1000} = 1000 \times P\bigl(q_x, \dots, q_{x+n-1};\ i = 4\%\bigr). \tag{11.17}
$$

**The margin for adverse deviation.** The table is the best estimate; a quote needs a margin. The adverse readings that cannot be ruled out (counting the positive no-detail rows as deaths: +11.1%; 10% of lives exposed part of the year: +5.3%) are combined **in quadrature**, because they are different, independent ways of being wrong, and the result is rounded *up* to the next multiple of 5%:

$$
m = \sqrt{\sum_{\text{adverse } j}\ \Delta_j^{2}}, \qquad \text{margin} = 0.05\left\lceil \frac{\max_{\text{policies}} m}{0.05} \right\rceil, \qquad \sqrt{0.111^2 + 0.053^2} = 12.3\% \ \to\ 15\%. \tag{11.18}
$$

The three reference policies give 12.4% (a woman of 40), 12.3% (a man of 40) and 12.0% (a man of 55 with a 10-year term), so the recommended margin is **15%**.

**What a margin buys.** For a book of $`n`$ equal policies with probability of death $`q`$, the one-year claims are binomial and their coefficient of variation is

$$
\mathrm{CV} = \sqrt{\frac{1 - q}{n\,q}}, \qquad n_{15\%} = \frac{1 - q}{q\,(0.15)^{2}}. \tag{11.19}
$$

For a man of 40 ($`q = 0.000533`$), $`\mathrm{CV} = 43\%`$ at 10,000 policies, 14% at 100,000 and 4% at a million; the 15% margin covers one standard deviation from about 83,000 policies. The figure ignores differences in sums assured and the uncertainty in $`q`$ itself (which the margin and the sensitivity table are there for); a pandemic is a systemic risk that a large book does not diversify away.

## 11.7 Examples you can check by hand

**The ledger, the maturities and the riders.** Eight claim rows in one year: four known deaths of the death cover (10 and 4 men aged 40, 6 women aged 40, and 3 cancelled claims of a man), two no-detail ledger rows (5 positive, 7 negative), one maturity coded as a sprain (8 claims at 65) and one funeral rider (9 claims). The base rule counts $`10 + 4 = 14`$ men and 6 women at age 40 and nothing else; "net" subtracts the 3 cancelled ($`14 - 3 = 11`$); "plus positive" adds the 5 positive ledger rows spread pro rata over the 20 known deaths, giving $`14 \times 1.25 = 17.5`$ and $`6 \times 1.25 = 7.5`$; keeping the maturities would add 8 deaths at 65.

**Spreading pro rata.** Cells with 30 and 10 deaths in a year and 8 extra: the factor is $`1 + 8/40 = 1.2`$, giving 36 and 12, a total of 48 $`= 40 + 8`$.

**A turnover allowance.** 1,000 lives and a share $`f = 20\%`$ exposed part of the year: central exposure $`1000 \times 0.9 = 900`$, and the rate rises by $`1000/900 - 1 = 11.1\%`$.

**A Brass curve.** $`a = -0.10`$, $`b = 1.32`$ and a population rate of 0.5%: $`\operatorname{logit}(0.005) = -5.293`$, so the insured logit is $`-0.10 + 1.32 \times (-5.293) = -7.087`$ and the rate is $`0.0835\%`$, or 17% of 0.5%.

**The extension.** $`x_{\text{last}} = 60`$ with an insured-to-population ratio of 0.25 there. At age 82.5, halfway to 105 ($`w = 0.5`$), the smoothstep is 0.5 and the ratio is $`0.25 + 0.75 \times 0.5 = 0.625`$; at 105 and above it is 1.

**A margin.** Adverse readings of 11.1% and 5.3% combine to $`\sqrt{0.0123 + 0.0028} = 12.3\%`$, which rounds up to 15%. A reading of 15.00001% would round up to 20%: the steps are 5% and upward only.

**Improvement.** A population rate that falls from 0.0010 in 2025 to 0.0008 in 2045 improves at $`1 - 0.8^{1/20} = 1.11\%`$ a year; two years of it multiply the rate by $`0.8^{2/20} = 0.978`$.

## 11.8 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_insured.py`: the base rule against the ledger, cancellations, riders and maturities, and the pro-rata spreading; the central exposure and the denominator effect; the Brass fit recovering a planted curve and solving its score equations (11.6); the relational fit and its conservation of deaths; the shape error and the method rule; the last credible age on a planted collapse (found within one age) and on a rising ratio; the smoothstep extension, its middle value and its zero slope at the ends; the sex floor; the multiplier as the Poisson maximum-likelihood estimate; the age-varying multiplier recovered exactly; the blend between its parts; the improvement formula; the standardized trend and the log-slope of the annual change; the premium against chapter 8; the quadrature margin and its rounding; and the binomial coefficient of variation by simulation. Further tests in `tests/test_insured*.py` check the full pipeline on simulated data from a planted insured curve (the intervals cover the truth and the median error is under 5%).
2. **The data.** The quantities below are tested against the shipped database.

*What each choice is worth* for a man of 40 with a 20-year term (the base is the traditional-term table, premium 0.855 per 1,000):

| Choice | Change in the premium |
|---|--:|
| Net of cancelled claims | -2.3% |
| Keeping the maturity payments coded as sprains | 0.0% |
| Plus the no-detail rows with a positive amount | +11.1% |
| Plus every no-detail row (the reading the evidence rejects) | +24.9% |
| 10% / 20% of lives exposed part of the year | +5.3% / +11.1% |
| Every insured life, whatever the cover | -11.4% |
| Pooling 2023-24 only / 2024-25 only | +0.8% / -5.3% |
| Relational P-spline / Gompertz-Makeham / Brass | -0.1% / +0.3% / +2.6% |
| Old ages meeting the population at 95 or at 115 | 0.0% |
| **Quoting on the market blend of all products** | **+40.2%** |
| Quoting on all term | +14.6% |
| Rolled to 2026 at the projected improvement | -2.4% |
| By sum assured (larger policies die more) | +36.9% |

The 15% margin is the quadrature of the two adverse readings (+11.1% and +5.3%), 12.3% for this policy, rounded up. The tornado of this table makes the point: **which table you quote on moves a premium by more than every modeling choice behind the table.**

*The gap and the premiums.* Between ages 25 and 65 the market table is at **14% to 25%** of the population for men and **18% to 23%** for women; traditional term alone is at 11% to 17% for men; the CNSF 2013 table sits at 23% to 31% of the Mexican population for men. Net annual premium per 1,000 of a 20-year term at 4%:

| Issue age | Insured, traditional term | Insured, market | CNSF 2013 | CNSF 99.5th pct | US insured (Unloaded CSO) | Population |
|---|--:|--:|--:|--:|--:|--:|
| **Men 30** | 0.50 | 0.63 | 0.97 | 1.46 | 1.46 | 3.88 |
| **Men 40** | **0.85** | 1.20 | 1.74 | 2.62 | 2.52 | 6.62 |
| **Men 50** | 2.01 | 2.84 | 3.72 | 5.57 | 5.37 | 12.28 |
| **Women 30** | 0.20 | 0.29 | 0.97 | 1.46 | 0.81 | 1.48 |
| **Women 40** | **0.38** | 0.64 | 1.74 | 2.62 | 1.69 | 3.27 |
| **Women 50** | 0.99 | 1.76 | 3.72 | 5.57 | 4.20 | 7.70 |

The regulator's table is unisex, so for a woman of 40 it is 4.6 times the insured premium; the population table overstates a man's by 7.7 times.

*The market and the trend.* Traditional term wrote MXN 43.2 billion of premium in 2023 to 2025 (4.07 per 1,000 of cover) and reported MXN 9.5 billion of death claims: **22%** of premium (14% paid), which is room in a price (premium also pays commissions, expenses and profit), not profit. Age-standardized insured death rates fell 9% (men) and 21% (women) between 2023 and 2025 on the market blend, about $`-4.7\%`$ and $`-11.4\%`$ a year in the fitted model (intervals $`-8.2`$ to $`-1.1\%`$ and $`-15.2`$ to $`-7.5\%`$): not improvement, since the book grew 20% and its new business is freshly underwritten.

## 11.9 Code map

| Formula | Function | Checked by (`tests/test_handbook_insured.py`) |
|---|---|---|
| Section 11.1 | `insured.death_cells`, `exposure_cells` | `test_the_base_rule_counts_only_known_positive_deaths_on_the_death_cover` |
| (11.1) | `insured.spread_pro_rata` | `test_spreading_extra_deaths_pro_rata_adds_exactly_that_many_and_creates_no_cell` |
| (11.2), (11.3) | `insured.central_exposure`, `crude_cells` | `test_the_exposure_keeps_known_ages_...`, `test_using_every_life_instead_of_those_holding_the_death_cover_lowers_the_rate` |
| (11.4) | `insured.relational_fit` | `test_the_relational_fit_smooths_the_ratio_to_the_reference` |
| (11.5), (11.6) | `insured.fit_brass`, `BrassFit` | `test_brass_recovers_a_planted_curve_and_solves_its_score_equations`, `test_brass_with_a_zero_shift_and_unit_slope_is_the_reference_...` |
| (11.7) | `insured.shape_error`, `select_method` | `test_the_shape_error_ignores_the_level_of_a_held_out_year`, `test_the_method_rule_picks_the_cheapest_...` |
| (11.8) | `insured.last_credible_age` | `test_the_credible_range_ends_where_the_ratio_to_the_population_collapses` |
| (11.9) | `insured.extend_to_reference` | `test_the_extension_moves_the_ratio_to_one_along_a_smooth_s_curve` |
| (11.10) | `insured.floor_men_at_women` | `test_men_are_floored_at_women_and_the_changed_ages_are_flagged` |
| (11.11), (11.12) | `insured.relativity`, `fit_relative_curve` | `test_a_segment_multiplier_is_total_deaths_over_total_expected_deaths`, `test_the_age_varying_multiplier_recovers_...` |
| (11.13) | `insured.blend_tables` | `test_the_market_blend_is_the_exposure_weighted_mean_of_the_products` |
| (11.14) | `insured_analysis.improvement_table`, `insured_sensitivity.improvement_factor` | `test_improvement_is_the_geometric_average_rate_of_the_projection` |
| (11.15), (11.16) | `insured.standardised_trend`, `annual_change` | `test_the_standardised_trend_uses_fixed_age_weights_and_the_annual_change_is_a_log_slope` |
| (11.17) | `insured_sensitivity.premium_per_1000` | `test_the_premium_of_a_table_is_the_net_term_premium_of_chapter_8` |
| (11.18) | `insured_sensitivity.margin_table` | `test_the_margin_adds_the_adverse_readings_in_quadrature_and_rounds_up_to_5_percent` |
| (11.19) | the binomial CV | `test_the_law_of_large_numbers_for_a_book_of_equal_policies` |
| Section 11.4, 11.5 tables | `insured_analysis.market_table`, `pandemic_table` | `test_the_market_table_and_the_pandemic_index_by_hand` |
| Section 11.8, tables | `insured.build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To reproduce the Brass example of section 11.7:

```python
from scipy import special

print(special.expit(-0.10 + 1.32 * special.logit(0.005)))  # 0.000835
```

## 11.10 Limits

- **Not a select table.** The statistics have no policy duration. Term business is dominated by recent, freshly underwritten policies, so the term tables mix select and ultimate mortality, and the recent insured trend is contaminated. A select-ultimate table needs an insurer's own policy-level data ([chapter 7](07-experience-study.md) does that).
- **Not a company table.** It is the industry average; a company's A/E against it is what an experience study measures.
- **Not reliable above the credible range.** The extension (11.9) is an assumption, flagged in every table; it does not move a standard quote but it moves whole life, annuities and any quote past about age 45.
- **Not free of reporting differences between insurers.** Some report cause, state and size better than others; the cause field mixes underlying and immediate causes (shock, acidosis, arrest), so it shows a pattern, not an exact statistic.
- **The no-detail rows are an inference.** That they are an adjustment ledger and not deaths rests on four independent observations (they net to zero, cancellations outweigh claims, their count is flat while deaths fell, COVID appears in them years late); a reading that adds them back is shown as a sensitivity, not as a possibility to ignore.
- **Head count, several policies per person, claims booked in the year.** These are documented simplifications. A person with two policies counts twice in the exposure *and* produces two claims, so the rate is not distorted, only its variance; the year of booking stands for the year of death.
- **Not for the youngest ages.** Below 18 to 26 the table is the population curve scaled; those ages are not priced.
- **The 2018 to 2020 statistics** are in an older format with an unstable exposure (women's share of lives goes 46%, 36%, 37%, then 50% to 52% from 2021) and no cause or cover detail: they are read and compared, but not pooled.
- **Products can cross at the oldest ages,** because each is extended independently from its own last credible age.

## References

- Brass, W. (1971). On the scale of mortality. In *Biological Aspects of Demography*, Taylor and Francis, 69-110. (The relational logit model.)
- Eilers, P. H. C. and Marx, B. D. (1996). Flexible smoothing with B-splines and penalties. *Statistical Science* 11(2), 89-121.
- Currie, I. D., Durban, M. and Eilers, P. H. C. (2004). Smoothing and forecasting mortality rates. *Statistical Modelling* 4(4), 279-298.
- Burnham, K. P. and Anderson, D. R. (2002). *Model Selection and Multimodel Inference*, 2nd ed. Springer. (Quasi-AIC.)
- Society of Actuaries (2017). *2017 Commissioners Standard Ordinary (CSO) Mortality Tables*. (The US insured table used for comparison.)
- CNSF (2018 to 2025). *Sistema Estadístico del Subramo de Vida Individual*, and *CUSF Annex 5.3.3-a* (CNSF 2013).
