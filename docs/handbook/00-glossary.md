# Glossary: the terms in plain words

Actuarial language is precise, and that precision is useful, so this project keeps the real terms. This page says what each one means in everyday words, with the symbol used in the [handbook](README.md) and where to read the mathematics. Terms are grouped in the order they appear in the pipeline.

## Measuring mortality

| Term | In plain words | Symbol | Read more |
|---|---|---|---|
| **Death rate** (central rate) | Deaths in a year divided by the years of life lived by the group. "Out of every 1,000 person-years, how many ended in death?" | $`m_x`$ | [Ch. 3](../crude-rates.md), [Ch. 5](05-life-tables.md) |
| **Probability of dying** | The chance that someone exactly $`x`$ years old does not reach their next birthday. Close to the death rate, but not the same number (see *separation factor*) | $`q_x`$ | [Ch. 5](05-life-tables.md#52-the-separation-factor) |
| **Force of mortality** | The instantaneous risk of dying at an exact age, the rate the probability is built from | $`\mu_x`$ | [Ch. 5](05-life-tables.md#51-from-rates-to-a-table) |
| **Exposure** | The denominator of every rate: person-years actually lived at risk. A person who is alive for 3 months of a year adds 0.25 | $`\mathcal{E}_{x,t}`$ | [Data quality](../data-quality.md), [Ch. 3](../crude-rates.md) |
| **Crude rate** | The raw rate, deaths over exposure, before any smoothing. It wobbles from age to age because deaths are random | $`\hat{m}_{x,t}`$ | [Ch. 3](../crude-rates.md) |
| **Age-standardized rate** | A rate recomputed as if every year (or place) had the same age mix, so that comparing them does not just compare how old each population is | | [Crude rates](../crude-rates.md) |
| **SMR** (standardized mortality ratio) | Deaths that happened divided by the deaths the national rates would predict for that age and sex mix. 1.19 means 19% more deaths than expected | | [Crude rates](../crude-rates.md) |
| **Age heaping / Whipple index** | The habit of reporting ages that end in 0 or 5. The Whipple index is 100 when ages are reported evenly and rises with heaping | | [Data quality](../data-quality.md) |
| **Late registration** | Deaths that occurred in a year but were officially registered in a later one. The latest year is always incomplete until they are added back | | [Data quality](../data-quality.md) |

## Building a table

| Term | In plain words | Symbol | Read more |
|---|---|---|---|
| **Graduation** | Smoothing the wobbly crude rates into a clean curve by age, without erasing real features | | [Ch. 4](../graduation.md) |
| **Life table** | A table that follows 100,000 imaginary newborns through one year's mortality rates and records how many are alive at each age | $`\ell_x`$ | [Ch. 5](05-life-tables.md) |
| **Radix** | The starting size of the imaginary group (100,000) | $`\ell_0`$ | [Ch. 5](05-life-tables.md) |
| **Separation factor** | The average share of a year lived by people who die in it. It is what turns a death *rate* into a death *probability*: $`q = m / (1 + (1 - \phi)\,m)`$ | $`\phi_x`$ | [Ch. 5](05-life-tables.md#52-the-separation-factor) |
| **Life expectancy** | The average number of years a newborn (or a person of a given age) can expect to live, if today's death rates stayed fixed | $`\mathring{e}_x`$ | [Ch. 5](05-life-tables.md#53-person-years-and-life-expectancy) |
| **Lifespan disparity** | The average number of years of life lost at death. High when many people die young as well as old: how *unequal* lifespans are | $`e^{\dagger}`$ | [Ch. 5](05-life-tables.md#55-summary-measures) |
| **Closure** (old-age) | Rates at the oldest ages are unreliable, so they are replaced by a fitted curve (here, a Kannisto logistic) instead of read from the data | | [Ch. 4](../graduation.md) |

## Pricing and reserves

| Term | In plain words | Symbol | Read more |
|---|---|---|---|
| **Interest rate and discount factor** | A peso paid in a year is worth less than a peso today. The discount factor says how much less | $`i`$, $`v`$ | [Ch. 5](05-life-tables.md#56-commutation-functions) |
| **Commutation functions** | Precomputed columns ($`D`$, $`N`$, $`C`$, $`M`$) that turn any price into a division of two numbers | $`D_x`$, $`N_x`$, $`M_x`$ | [Ch. 5](05-life-tables.md#56-commutation-functions) |
| **Term insurance** | Pays the sum assured if death happens within a fixed number of years, and nothing otherwise | $`A^1_{x:\overline{n}\vert}`$ | [Ch. 5](05-life-tables.md) |
| **Whole life / endowment** | Whole life pays at death whenever it happens. An endowment also pays if the person survives to the end of the term | $`A_x`$, $`A_{x:\overline{n}\vert}`$ | [Ch. 5](05-life-tables.md) |
| **Life annuity** | A payment of 1 a year for as long as the person lives (a pension). *Annuity-due* pays at the start of each year | $`\ddot{a}_x`$ | [Ch. 5](05-life-tables.md) |
| **Net premium** | The price of the risk alone: just enough to pay the expected claims, with no expenses and no profit | $`P_x`$ | [Ch. 5](05-life-tables.md#57-premiums-and-reserves) |
| **Gross premium** | What the customer pays: the net premium plus commissions, expenses and the profit the company targets | | [Pricing](../pricing.md) |
| **Reserve** | The money the insurer must hold today against future claims on policies it has already sold | $`{}_tV_x`$ | [Ch. 5](05-life-tables.md#57-premiums-and-reserves) |
| **Best-estimate liability** | The expected present value of future claims and costs minus future premiums, with no safety margin | | [Pricing](../pricing.md) |
| **Profit test** | Projecting a policy's cash flows year by year to see when it breaks even and what return it earns | | [Pricing](../pricing.md) |
| **IRR** | Internal rate of return: the yearly return a policy earns on the money the company puts in | | [Pricing](../pricing.md) |
| **Margin for adverse deviation** | A deliberate cushion added to mortality so that a bad but plausible outcome does not turn the product into a loss | | [Insured lives](../insured-lives.md) |

## Looking back at experience

| Term | In plain words | Symbol | Read more |
|---|---|---|---|
| **A/E** (actual over expected) | Deaths that really happened divided by the deaths a reference table predicted. 1.00 means the table fits; 0.77 means 23% fewer deaths than expected | | [Experience study](../experience-study.md) |
| **Credibility** | How much weight to put on your own data rather than on a reference table. Few deaths, little weight; many deaths, full weight | $`Z`$ | [Experience study](../experience-study.md) |
| **Select period** | The first years after a policy is sold, when mortality is lower because the person has just passed medical underwriting | | [Experience study](../experience-study.md) |
| **Claims lag / IBNR** | Claims for deaths that have already happened but have not been reported yet. Counting only reported claims makes the latest months look too good | | [Experience study](../experience-study.md) |
| **GLM** | A regression that explains deaths by age, sex, policy year and other factors at once, with the right model for counts | | [Experience study](../experience-study.md) |
| **Planted truth** | Known effects deliberately built into synthetic data to check that the method finds them: the test that a method works | | [Experience study](../experience-study.md) |

## Looking forward and sideways

| Term | In plain words | Symbol | Read more |
|---|---|---|---|
| **Mortality improvement** | The long-run fall in death rates as medicine and living conditions get better | | [Projection](../projection.md) |
| **Lee-Carter model** | A projection method that describes every age's mortality with one shared time trend: $`\ln m_{x,t} = \alpha_x + \beta_x \kappa_t`$ | | [Ch. 6](../projection.md) |
| **Period vs cohort table** | A *period* table uses this year's death rates for every age. A *cohort* table follows one generation through the rates it will actually meet. Cohort values are lower when mortality improves | | [Projection](../projection.md) |
| **Excess mortality** | Deaths above what would have been expected without an event such as a pandemic. The *P-score* is that excess as a share of the expected deaths | | [Excess mortality](../excess-mortality.md) |
| **Stress test** | Asking "what if": replaying a past shock, or doubling mortality, on today's book and measuring the damage | | [Stress tests](../stress-tests.md) |

## Reinsurance

| Term | In plain words | Read more |
|---|---|---|
| **Reinsurance** | Insurance for insurers: the company passes part of its risk to a reinsurer in exchange for a premium | [Reinsurance](../reinsurance.md) |
| **Quota share** | The reinsurer takes a fixed percentage of every policy, its premiums and its claims | [Reinsurance](../reinsurance.md) |
| **Surplus** | The company keeps each policy up to a retention limit and the reinsurer takes the rest | [Reinsurance](../reinsurance.md) |
| **Excess of loss / stop loss** | The reinsurer pays claims above a threshold: per life (excess of loss) or on the whole year's total (stop loss) | [Reinsurance](../reinsurance.md) |
| **YRT** (yearly renewable term) | A reinsurance premium charged every year per unit of sum at risk, rather than a share of the original premium | [Reinsurance](../reinsurance.md) |
| **Longevity swap** | A contract in which the company pays a fixed amount and receives the pensions actually due, so that someone else carries the risk of people living longer than expected | [Reinsurance](../reinsurance.md) |

## Sources and institutions

| Name | What it is |
|---|---|
| **INEGI** | Mexico's national statistics office. Source of registered deaths |
| **CONAPO** | Mexico's national population council. Source of the population (the exposure) |
| **CNSF** | Mexico's insurance and surety regulator. Publishes the regulatory mortality tables and the industry's life-insurance statistics |
| **CNSF 2013** | The regulatory mortality table currently in force for pricing and reserving |
| **SOA** | Society of Actuaries (United States). Publishes standard mortality tables such as the 2017 CSO |
| **HMD** | Human Mortality Database: high-quality mortality data for about forty countries, used here as an international yardstick |
