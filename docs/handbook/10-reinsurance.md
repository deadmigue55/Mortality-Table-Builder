# 10. Reinsurance

> [!NOTE]
> **In one minute.** A life insurer can pass part of its risk to a reinsurer, for a price. This chapter asks the four questions a reinsurance desk asks: **where is the risk** (in a few large policies? in a pandemic?), **which cover relieves it most cheaply** (a share of every policy, a slice of the big ones, or a limit on the year's total?), **how should the treaty be priced for each cedant** (in proportion to its own experience, weighted by how much that experience can be trusted), and **what does it cost to take longevity off an annuity book?** The method is a simulation of next year's claims, the four standard covers applied to the same simulated years, and a price expressed as *cost per peso of capital relieved*, to be compared with what the cedant's own capital costs.
>
> **What this chapter does:** it builds on the life book of the [experience study](07-experience-study.md) and the annuity block and pandemic profile of [chapter 9](09-excess-stress.md), and uses the compound-Poisson and credibility ideas of [chapters 3](03-crude-rates.md) and [7](07-experience-study.md).
>
> **The number to remember.** The pandemic tail, not the large policies, drives the capital: random fluctuation needs MXN 136 million of capital on a block expecting 742 million of claims, and adding a one-in-thirty-years pandemic takes it to **MXN 294 million**. A stop loss that attaches at 115% of expected claims relieves **60% of that capital** for MXN 10.7 million a year; a quota share buys capital at about **20 cents per peso**, twice the cedant's own cost.

Code: `src/mortality/reinsurance.py` · Tests: `tests/test_reinsurance.py` and `tests/test_handbook_reinsurance.py` · Results: [reinsurance.md](../reinsurance.md)

> [!IMPORTANT]
> The mortality, the pandemic profile and the improvement scenarios are the project's own, from real data. The **books are synthetic**, and the **market terms are assumptions**, chosen to be plausible and to be changed: a reinsurer's cost of capital of 6% and a cedant's of 10%, a pandemic once in 30 years at half the population's excess, a 65% loss ratio and a 30% ceding commission. Conclusions that depend on them say so.

**Local symbols** (everything else is in the [notation](01-notation.md)). $`S`$ is the annual claims of the block; $`F`$ the level factor; $`\mathrm{SA}_i`$ and $`q_i`$ the sum assured and probability of death of policy $`i`$; $`R`$ a retention and $`L`$ a limit; $`c_{\text{re}}`$ and $`c_{\text{ced}}`$ the reinsurer's and the cedant's cost of capital; $`K`$ capital.

**Contents.** [10.1](#101-where-is-the-risk-concentration) concentration · [10.2](#102-next-years-claims-a-compound-poisson-simulation) claims · [10.3](#103-the-covers-and-their-price) covers · [10.4](#104-what-is-a-layer-worth) layers · [10.5](#105-rating-a-treaty-by-cedant-experience-rating) YRT rating · [10.6](#106-what-a-longevity-swap-costs) longevity swap · [10.7](#107-examples-you-can-check-by-hand) examples · [10.8](#108-validation) validation · [10.9](#109-code-map) code map · [10.10](#1010-limits) limits

---

## 10.1 Where is the risk? Concentration

Group the policies by sum-assured band and compare each band's share of the policies, of the **sum at risk** $`\sum \mathrm{SA}_i`$ and of the expected claims $`\sum \mathrm{SA}_i\,q_i`$. When the probability of dying does not depend on the sum assured the last two shares are identical, since expected claims are the sum assured times a common $`q`$:

$$
\frac{\sum_{i \in \text{band}}\mathrm{SA}_i\,q_i}{\sum_i \mathrm{SA}_i\,q_i} = \frac{\sum_{i \in \text{band}}\mathrm{SA}_i}{\sum_i \mathrm{SA}_i} \quad\text{when } q_i \equiv q. \tag{10.1}
$$

In the block, policies of 2 million or more are 13% of the policies and **49% of the sum at risk**; the 9,669 policies of 5 million or more hold 19% on their own. A few large policies carry a large share of the exposure, which is what a per-life cover addresses.

## 10.2 Next year's claims: a compound-Poisson simulation

The claims of the next twelve months are simulated with three sources of uncertainty, added one at a time. In a year with a level factor $`F`$, the number of deaths is Poisson with mean $`F\sum_i q_i`$, and **each death is one of the lives, drawn with probability proportional to its probability of dying** (so $`P(\text{policy } i) = q_i / \sum_j q_j`$); the claim is that policy's sum assured. The total $`S`$ is the sum of the claims. This is a **compound Poisson** distribution, with these moments, which are the ones the simulation must reproduce:

$$
E[S \mid F] = F\sum_i \mathrm{SA}_i\,q_i, \qquad \mathrm{Var}(S \mid F) = F\sum_i \mathrm{SA}_i^{2}\,q_i. \tag{10.2}
$$

(By thinning, the mean count times the mean claim is $`\sum q \times \sum \mathrm{SA}\,q/\sum q`$; the variance of a compound Poisson is the mean count times the second moment of the claim.)

**The level of mortality is uncertain.** The factor $`F`$ is lognormal with mean 1, so that the expected claims are unchanged and only their spread grows: with $`Z`$ standard normal and a standard deviation $`\sigma`$ of the log,

$$
F = \exp\!\left(\sigma Z - \tfrac12\sigma^{2}\right), \qquad E[F] = 1, \qquad \mathrm{Var}(F) = e^{\sigma^{2}} - 1. \tag{10.3}
$$

Adding the variance of $`F`$ to (10.2) by the law of total variance gives the variance with an uncertain level:

$$
\mathrm{Var}(S) = \underbrace{\sum_i \mathrm{SA}_i^{2}\,q_i}_{\text{who dies}} + \underbrace{\left(e^{\sigma^{2}} - 1\right)\Bigl(\sum_i \mathrm{SA}_i\,q_i\Bigr)^{2}}_{\text{the level}}. \tag{10.4}
$$

**A pandemic year** (probability $`p`$) draws from the probabilities $`q^{\text{pan}}`$ instead of $`q`$ (the profile of [section 9.5](09-excess-stress.md#95-replaying-the-pandemic-on-a-life-book) with its dampening). The year is then a mixture of two distributions, with mean $`\mu = p\mu_{\text{pan}} + (1-p)\mu_0`$ and variance

$$
\mathrm{Var}(S) = p\,V_{\text{pan}} + (1-p)\,V_{0} + p(1-p)\left(\mu_{\text{pan}} - \mu_{0}\right)^{2}, \tag{10.5}
$$

where the last term is the spread *between* the two kinds of year. It is what turns a modest pandemic probability into a heavy tail: the mean barely moves, because the pandemic is rare, but the 99.5th percentile is a pandemic year.

**Capital** is the tail above the mean, the value-at-risk at the 99.5% level:

$$
K = \mathrm{VaR}_{99.5\%}(S) - E[S]. \tag{10.6}
$$

## 10.3 The covers and their price

Four standard covers, each applied to the same simulated years. A **quota share** takes a fixed share $`a`$ of every claim; a **surplus** treaty cedes the part of each policy's sum assured above a retention $`R`$, up to a number of $`\text{lines}`$ times the retention; a **per-life excess of loss** pays each claim above $`R`$ up to a limit $`L`$; a **stop loss** pays the year's total above an attachment $`A`$, up to a limit:

$$
\underbrace{\min\bigl(\max(\mathrm{SA} - R,\,0),\ \mathrm{lines}\times R\bigr)}_{\text{surplus, per claim}} = \underbrace{\min\bigl(\max(\mathrm{SA} - R,\,0),\ L\bigr)}_{\text{excess of loss, } L = \mathrm{lines}\times R}, \tag{10.7, 10.8}
$$

$$
\text{quota share: } a\,S, \qquad \text{stop loss: } \min\bigl(\max(S - A,\,0),\ L\bigr). \tag{10.9}
$$

**A surplus treaty reduces claims exactly like an excess of loss** of $`\mathrm{lines}\times R`$ excess of $`R`$: a claim on a policy of sum assured $`\mathrm{SA}`$ recovers the same amount under both. The two differ only in *price*, because a surplus is a proportional treaty (the reinsurer takes a proportional share of premium, net of a commission) and an excess of loss is priced on risk.

**Price.** A non-proportional cover is priced on the reinsurer's cost: the expected recoveries and expenses plus a return on the capital the recoveries need, with $`K_{\text{rec}}`$ the tail of the recoveries over their mean (as in 10.6). A proportional cover is priced from a premium proxy: the ceded share of original premium, which is expected claims over the loss ratio, less the ceding commission:

$$
\text{non-proportional: } \mathrm{premium} = E[\text{rec}]\,(1 + e) + c_{\text{re}}\,K_{\text{rec}}, \qquad \text{proportional: } \mathrm{premium} = \frac{E[\text{rec}]}{\text{loss ratio}}\,(1 - \text{ceding commission}). \tag{10.10, 10.11}
$$

**What the cedant gets for it.** The *cost* of a cover is its premium less the expected recoveries it pays back, and its *capital relief* is the fall in the capital of the claims the cedant keeps:

$$
\mathrm{cost} = \mathrm{premium} - E[\text{rec}], \qquad \text{relief} = K_{\text{gross}} - K_{\text{net}}, \qquad \text{price of relief} = \frac{\mathrm{cost}}{\text{relief}}. \tag{10.12}
$$

A cover is **worth buying** when it relieves capital at a price below the cedant's own cost of capital, $`\mathrm{cost}/\text{relief} < c_{\text{ced}}`$ (10%).

**A quota share has a price that does not depend on the share.** The tail of $`(1-a)S`$ is $`(1-a)`$ times the tail of $`S`$ (a value-at-risk scales with the loss), so a quota share of $`a`$ relieves exactly the share $`a`$ of the capital, $`aK`$. Its cost is $`aE[S]\bigl[(1-c)/\mathrm{LR} - 1\bigr]`$, so $`a`$ cancels:

$$
\text{price of relief (quota share)} = \frac{E[S]\ \bigl[(1 - c)/\mathrm{LR} - 1\bigr]}{K} \quad\text{for every share.} \tag{10.13}
$$

With the block's figures, $`748.7 \times 0.0769 / 293.7 = 19.6\%`$ for any share. For a **non-proportional** cover the price is a straight line in the reinsurer's return,

$$
\text{price} = \frac{e\,E[\text{rec}] + c_{\text{re}}\,K_{\text{rec}}}{\text{relief}}, \tag{10.14}
$$

rising by $`K_{\text{rec}}/\text{relief}`$ for each unit of $`c_{\text{re}}`$ (1.11 for the 1M-retention excess of loss here, that is 1.1 points of price for each point of the reinsurer's return), which is how a change of a point or two in the reinsurer's required return moves a layer from worth buying to not.

## 10.4 What is a layer worth?

Lowering a per-life retention adds a layer. The **marginal price** of the layer between a retention and the next one up is the extra cost over the extra capital relieved:

$$
\text{marginal price}_k = \frac{\mathrm{cost}(R_k) - \mathrm{cost}(R_{k+1})}{\mathrm{relief}(R_k) - \mathrm{relief}(R_{k+1})}, \qquad \text{net benefit}(R) = c_{\text{ced}}\,\mathrm{relief}(R) - \mathrm{cost}(R). \tag{10.15}
$$

A layer is worth buying while its marginal price is below $`c_{\text{ced}}`$. Layers near the retention of a large policy relieve a great deal of capital per peso; the thin top layers, which pay a handful of times in 10,000 simulated years, relieve little and are noisy. The **cutoff retention** is the lowest retention at which a layer first becomes too dear, found by going up from the smallest retention, and the net benefit is what the worthwhile layers below it earn the cedant. Because the price is linear in $`c_{\text{re}}`$ (10.14), the cutoff moves with the reinsurer's required return: it is where the reinsurer's price, the cedant's cost of capital and the claim distribution meet.

## 10.5 Rating a treaty by cedant: experience rating

A **yearly renewable term (YRT)** treaty charges a rate per 1,000 of sum at risk. The **manual rate** is the expected cost per 1,000, loaded for the reinsurer's expenses and margin; **experience rating** adjusts it by the cedant's own experience, weighted by credibility:

$$
\text{manual} = 1000\ \frac{\text{expected amount}}{\text{exposure amount}}\,(1 + \text{loading}), \qquad \text{factor} = Z\,\left(\frac{A}{E}\right)_{\text{amount}} + (1 - Z), \qquad \text{rated rate} = \text{manual} \times \text{factor}. \tag{10.16}
$$

**Claim amounts need more experience than claim counts to be credible**, because claim sizes vary. By the compound-Poisson variance (10.2), the relative variance of total claims with $`\lambda`$ expected deaths is $`E[\mathrm{SA}^2]/(\lambda E[\mathrm{SA}]^2) = (1 + \mathrm{cv}^2)/\lambda`$, where the **squared coefficient of variation of the claim size** is

$$
\mathrm{cv}^{2} = \frac{E[\mathrm{SA}^{2}]}{E[\mathrm{SA}]^{2}} - 1, \tag{10.17}
$$

against $`1/\lambda`$ for counts alone. To achieve the same relative accuracy the number of deaths must be $`(1 + \mathrm{cv}^2)`$ times larger: the full-credibility standard of [section 3.9](03-crude-rates.md#39-when-is-a-rate-credible) becomes $`1{,}082\,(1 + \mathrm{cv}^2)`$, and the credibility weight is

$$
Z = \min\!\left(1,\ \sqrt{\frac{\text{deaths}}{1082\,(1 + \mathrm{cv}^{2})}}\right). \tag{10.18}
$$

With $`\mathrm{cv}^2`$ between 1.6 and 2.1 in this book the standard is about 3,000 deaths. The experience factor lies between the manual rate (factor 1) and the cedant's own amount A/E, by construction.

## 10.6 What a longevity swap costs

In a **longevity swap** the cedant pays a fixed schedule of pensions (on the swap basis) and the reinsurer pays the pensions actually due: the reinsurer takes the longevity risk, the cedant keeps the investment and credit risk. Two risks sit with the reinsurer.

**Trend.** The improvement of mortality is a multiple $`s`$ of the central log improvement ([equation 9.16](09-excess-stress.md#96-longevity-an-annuity-block)), drawn from a normal distribution around 1 with standard deviation 0.5 and truncated to $`[-0.5,\ 3]`$ (so that "none" and "double" improvement are about the two-sigma range). The block's reserve is valued on a grid of $`s`$ from $`-0.5`$ to 3 in steps of 0.25 and interpolated.

**Pool risk.** The chance variation of a finite block of lives. For one life aged $`x`$, who dies in year $`j`$ with probability $`P_j = {}_jp\,q_j`$ and so receives $`j+1`$ pensions, the present value is $`\ddot a_{\overline{j+1}\vert}`$, and its mean and variance are

$$
\mathrm{PV}_j = \ddot a_{\overline{j+1}\vert} = \frac{1 - v^{\,j+1}}{1 - v}, \qquad \mu_x = \sum_j P_j\,\mathrm{PV}_j, \qquad \sigma^2_x = \sum_j P_j\,\mathrm{PV}_j^{2} - \mu_x^{2}. \tag{10.19, 10.20}
$$

($`\mu_x`$ is the annuity-due of chapter 9 when the table closes.) The lives are independent, so for a block of $`N`$ annuitants with pension $`\pi`$ and age weights $`w_x`$ the variance of the reserve is $`\sigma^2_{\text{pool}} = \sum_{\text{sex}} N\,\text{share}\ \pi^2 \sum_x w_x\sigma^2_x`$ (10.21). The total reserve is the trend reserve plus an independent normal pool error, and capital is its tail over the mean (10.6).

**The fee.** The reinsurer holds capital in proportion to the **run-off** of the reserve, the expected reserve at each future date, valued at issue and summed:

$$
\text{run-off} = \sum_{t \ge 0} v^{t}\,E[R_t] = \pi \sum_{k \ge 0} {}_kp\ v^{k}\,(k + 1), \qquad \text{capital ratio} = \frac{K}{R_0}, \qquad \text{fee} = c_{\text{re}} \times \text{capital ratio} \times \text{run-off}. \tag{10.22, 10.23}
$$

(For a life aged $`x`$ at time 0, summed over the block's lives; $`R_t`$ is the expected value at time $`t`$ of the pensions still to come, and $`\sum_t v^t R_t`$ collects each pension $`k+1`$ times, once in each reserve it is part of.) The fee as a share of the reserve is $`c_{\text{re}} \times \text{capital ratio} \times (\text{run-off}/R_0)`$ and per year it is $`c_{\text{re}} \times \text{capital ratio}`$.

## 10.7 Examples you can check by hand

**A surplus is an excess of loss.** Retention 1 million, nine lines. A claim of 3 million cedes $`\min(3 - 1,\ 9) = 2`$ million under the surplus and $`\min(\max(3-1, 0),\ 9) = 2`$ million under a 9-million excess of loss; a claim of 12 million cedes $`\min(11,\ 9) = 9`$ million under both. A claim of 0.8 million cedes nothing.

**A stop loss.** The block expects claims of 742 million; the cover attaches at 115% (853.3 million) with a limit of 742 million. A year of 900 million recovers $`900 - 853.3 = 46.7`$ million; a year of 800 million recovers nothing; the cover pays only in tail years, which is why its expected recovery is just 4.6 million.

**The price of a quota share.** With $`E[S] = 748.7`$ million and $`K = 293.7`$ million, a 20% or 40% share costs $`a \times 748.7 \times (0.70/0.65 - 1)`$ and relieves $`a \times 293.7`$: in both cases $`748.7 \times 0.0769/293.7 = 19.6`$ cents per peso, double the cedant's 10%.

**A YRT rating.** The preferred class has 365 deaths and a squared coefficient of variation of 1.84, so full credibility on amounts takes $`1{,}082 \times 2.84 = 3{,}073`$ deaths and $`Z = \sqrt{365/3073} = 0.345`$. With an amount A/E of 0.465 the factor is $`0.345 \times 0.465 + 0.655 = 0.816`$, not 0.465: a partial credit.

**An annuity life.** A two-year closed life, $`q = (0.1,\ 1)`$, $`i = 5\%`$, $`v = 1/1.05`$. The pensions are paid at times 0 and 1: if the life dies in year 1 the present value is 1, if in year 2 it is $`1 + v = 1.9524`$, with probabilities 0.1 and 0.9. So $`\mu = 0.1 + 0.9 \times 1.9524 = 1.857`$ and $`\sigma^2 = 0.1 \times 1 + 0.9 \times 1.9524^2 - 1.857^2 = 0.0816`$.

## 10.8 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_reinsurance.py`: the equal shares of sum and claims (10.1); the compound-Poisson mean and variance of the simulation (10.2, 10.4) over 200,000 simulated years; the lognormal factor (10.3); the pandemic mixture (10.5), with the tail growing faster than the mean; the capital definition (10.6); the surplus equal to a limited excess of loss on every simulated year (10.7); the bounds on recoveries; the two price formulas (10.10, 10.11); the quota share's relief of exactly its own share and its share-independent price (10.13); the price's linearity in the reinsurer's return (10.14); the marginal prices (10.15); the compound-Poisson reason for the credibility standard (10.17, by simulation), the rating (10.16, 10.18); the annuity variance by hand (10.19, 10.20); and the swap fee identities (10.22, 10.23).
2. **The data.** The quantities below are tested against the shipped database (10,000 simulated years; the block is the 392,274-policy block of chapter 9, MXN 414 billion of sum assured).

*Aggregate claims* (expected claims MXN 742 million, a coefficient of variation of 6.7% from random fluctuation alone):

| Source | Standard deviation (MXN million) | 99.5% claims | Capital |
|---|--:|--:|--:|
| Who dies | 49 | 877 | 136 |
| + uncertain mortality level | 62 | 915 | 174 |
| + pandemic (1 in 30) | 74 | 1,042 | **294** |

The pandemic accounts for 41% of the capital while adding a hundredth to the mean.

*The covers* (capital relieved in MXN million, with the share of capital; price per peso of relief):

| Cover | Capital relieved | Net cost (MXN million) | Price of relief |
|---|--:|--:|--:|
| Quota share 20% / 40% | 59 (20%) / 117 (40%) | 11.5 / 23.0 | 19.6% / 19.6% |
| Surplus, retention 0.5M, 9 lines | 159 (54%) | 32.1 | 20.2% |
| Surplus, retention 1M, 9 lines | 123 (42%) | 23.7 | 19.2% |
| Surplus, retention 2M, 9 lines | 80 (27%) | 13.6 | 17.0% |
| Per-life XL 8M xs 1M | 122 (41%) | 11.0 | **9.1%** |
| Per-life XL 16M xs 2M | 79 (27%) | 7.9 | 10.1% |
| Stop loss, 100% xs 115% of expected claims | **177 (60%)** | 10.7 | **6.0%** |
| Stop loss, 100% xs 125% of expected claims | 105 (36%) | 6.3 | 6.0% |
| Per-life XL 8M xs 1M + stop loss on what is left | 182 (62%) | 14.7 | 8.1% |

Proportional treaties are the expensive way to buy capital (about 20 cents per peso, double the cedant's own cost); they also finance acquisition costs and share expenses, which this analysis does not value. The stop loss is the cheapest relief by far, because the tail is a pandemic tail and the cover pays rarely, but it is also the one that depends most on the assumed pandemic. The per-life XL is worth buying only at the lower retention.

*Layers and the reinsurer's price.* At a 6% reinsurer return the per-life layers cost 6% to 9% of the capital they relieve up to about 5 million; above that the thin layers are dearer and noisier (the marginal prices above 5 million are not conclusions). The 1M-retention cover costs 9.1% of the capital relieved at 6% and **crosses the cedant's 10% at about 6.9%**; at 6% the layers up to 5.6 million are worth buying (a net benefit of MXN 6.1 million a year), and at 7% or more not even the lowest one is. A stop loss costs about the reinsurer's own return per peso relieved, so it stays worth buying until the reinsurer asks the cedant's 10%.

*Experience rating* (selected segments):

| Segment | Deaths | Amount A/E | Credibility | Rated factor |
|---|--:|--:|--:|--:|
| Underwriting: PREFERRED | 365 | 0.465 | 34% | 0.816 |
| Underwriting: RATED | 331 | 1.075 | 33% | 1.025 |
| Underwriting: STANDARD | 1,687 | 0.605 | 74% | 0.708 |
| Channel: AGENT | 2,166 | 0.644 | 81% | 0.710 |
| Sex: M | 2,812 | 0.879 | 95% | 0.886 |

A cedant with few deaths and a good result gets a partial credit (factor 0.82, not 0.47); one with many deaths gets nearly what its experience says (the agent channel's rated rate is 29% under the manual rate, the rated class's 2.5% over it, with loss ratios at the manual rate of 0.56 and 0.93).

*The longevity swap* (the annuity block of chapter 9, central reserve MXN 24,992 million):

| | MXN million |
|---|--:|
| Standard deviation of the reserve | 291 (1.2%) |
| of which pool risk | 77 (6.9% of the variance) |
| Risk capital (99.5% over the mean) | 761 (about 3% of the reserve) |
| Reserve at the 99.5th percentile | +3.1% over central |
| Run-off | 8.9 reserve-years |
| **Fee, present value** | **405 (1.6% of the reserve, about 18 basis points a year)** |

Most of the risk is trend, which is why the size of the pool matters little and the model of improvement matters a lot. The number is not a market quote: it is what this model's assumptions imply.

## 10.9 Code map

| Formula | Function (`src/mortality/reinsurance.py`) | Checked by (`tests/test_handbook_reinsurance.py`) |
|---|---|---|
| (10.1) | `concentration` | `test_with_a_flat_probability_the_shares_of_sum_and_of_claims_coincide` |
| (10.2), (10.4) | `simulate_claims` | `test_simulated_claims_have_the_compound_poisson_mean_and_variance` |
| (10.3) | `simulate_claims` | `test_the_lognormal_level_factor_has_mean_one` |
| (10.5) | `simulate_claims` | `test_a_pandemic_year_mixes_two_distributions` |
| (10.6) | `distribution`, `aggregate_table` | `test_the_distribution_summary_defines_capital_as_the_tail_over_the_mean` |
| (10.7), (10.8), (10.9) | `surplus`, `per_life_xl`, `quota_share`, `stop_loss` | `test_the_surplus_treaty_recovers_exactly_a_limited_excess_of_loss`, `test_recoveries_are_bounded_and_stop_loss_takes_the_slice_of_the_aggregate` |
| (10.10), (10.11) | `non_proportional_premium`, `proportional_premium` | `test_the_two_prices_of_a_cover` |
| (10.12), (10.13) | `evaluate`, `structure_table` | `test_a_quota_share_relieves_its_own_share_of_capital_at_a_price_that_does_not_depend_on_the_share`, `test_worth_buying_compares_the_price_with_the_cedants_cost_of_capital` |
| (10.14) | `evaluate`, `price_sensitivity` | `test_the_price_of_a_non_proportional_cover_is_linear_in_the_reinsurers_return` |
| (10.15) | `retention_frontier` | `test_layer_prices_add_up_between_the_extreme_retentions` |
| (10.16), (10.18) | `yrt_rating` | `test_the_yrt_rating_factor_and_rate` |
| (10.17) | `claim_size_cv2` | `test_claim_size_variability_and_why_amounts_need_more_deaths` |
| (10.19), (10.20) | `per_life_pv_variance` | `test_per_life_variance_of_an_annuity_by_hand`, `test_closed_two_year_life_example_and_the_other_hand_examples` |
| (10.21) to (10.23) | `longevity_swap`, `reserve_run_off` | `test_swap_fee_identities_on_a_small_block` |
| Section 10.8, tables | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To reproduce the annuity life of section 10.7:

```python
import numpy as np
from mortality.reinsurance import per_life_pv_variance

mean, var = per_life_pv_variance(np.array([[0.1, 1.0]]), 0.05)
print(mean, var)  # [1.857] [0.0816]
```

## 10.10 Limits

- **One-year, static block.** No lapses, no new business, no reinstatements of the cover, no multi-year treaties.
- **Simulation noise.** 10,000 years leave visible noise in the layer prices and much more in the thin top layers: the marginal prices above 5 million are not conclusions.
- **The market terms are assumptions.** Results that hinge on the gap between the reinsurer's and the cedant's cost of capital, or on the pandemic's probability, are shown against them and should be recomputed on real quotes.
- **No credit risk and no basis risk.** The reinsurer always pays, and the recoveries follow the cedant's own claims.
- **Pricing by cost of capital** is the cedant's view of what a reinsurer should ask, not a reinsurer's pricing model, which would also carry its profit margin, the diversification across its other treaties and the cost of uncertainty in the parameters.
- **A life could die twice** in one simulated year: with probabilities this small the effect is negligible.
- **The longevity swap has no basis risk and no default,** and the trend distribution is a normal around the central projection, not the stochastic fan of chapter 6.

## References

- Bühlmann, H. (1970). *Mathematical Methods in Risk Theory*. Springer. (The compound Poisson distribution and its moments.)
- Kaas, R., Goovaerts, M., Dhaene, J. and Denuit, M. (2008). *Modern Actuarial Risk Theory: Using R*, 2nd ed. Springer. (Compound Poisson claims, reinsurance covers and their recoveries.)
- Longley-Cook, L. H. (1962). An introduction to credibility theory. *Proceedings of the Casualty Actuarial Society* 49, 194-221.
- Bühlmann, H. and Straub, E. (1970). Glaubwürdigkeit für Schadensätze. *Mitteilungen der Vereinigung Schweizerischer Versicherungsmathematiker* 70, 111-133.
- Biffis, E. and Blake, D. (2014). Keeping some skin in the game: how to start a capital market in longevity risk transfers. *North American Actuarial Journal* 18(1), 14-21. (Longevity risk transfer.)
