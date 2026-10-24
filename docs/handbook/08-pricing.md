# 8. Pricing, profit and reserves

> [!NOTE]
> **In one minute.** A mortality table says how many people die. An insurer needs to know what a **policy** earns: the premium that covers the claims *and* the costs *and* a return for the capital at risk, whether that premium really earns its target return, which assumption puts the return in danger, and how much money the regulator makes the company hold in reserve. This chapter follows one policy year by year (a **profit test**), derives the **net premium** and the **reserve** that the regulation prescribes, and shows two identities that make the whole machinery checkable: a policy priced with no costs earns exactly zero, and the value of a policy's profits does not depend on how the reserve is set.
>
> **What this chapter does:** it uses the life-table functions of [chapter 5](05-life-tables.md) to price a level term product, then extends them to a profit test with expenses, commissions, lapses and a hurdle rate, and measures how the premium reacts when mortality, lapses, interest or expenses move.
>
> **The number to remember.** A 20-year term for a man of 40 needs a gross premium of **2.32 per 1,000** of sum assured to earn a 10% return on the regulator's CNSF 2013 table (the net, claims-only premium is 1.74). Priced instead on the table of insured lives, with a 15% margin for error, it is **1.57**: 32% cheaper, with the same return.

Code: `src/mortality/pricing.py` · Tests: `tests/test_pricing.py` and `tests/test_handbook_pricing.py` · Results: [pricing.md](../pricing.md)

> [!IMPORTANT]
> The **mortality** in this chapter is real or derived from real data. The **product** (a level term policy), its expenses, commissions, lapses and the 10% hurdle are **illustrative assumptions**, chosen to be typical of an individual term product; a company would replace them with its own. Nothing here describes any insurer.

**Local symbols** (everything else is in the [notation](01-notation.md)). $`S`$ is the sum assured, $`P`$ the annual premium (paid at the start of each policy year), $`q_t`$ the probability of death in policy year $`t`$, $`w_t`$ the lapse rate, $`V_t`$ the statutory reserve at the end of year $`t`$, $`c_t`$ the commission, $`E_t`$ the expenses, $`\kappa`$ the expense per claim, $`i`$ the interest earned and $`h`$ the hurdle rate.

**Contents.** [8.1](#81-the-net-premium-and-the-reserve) net premium and reserve · [8.2](#82-the-profit-test) profit test · [8.3](#83-two-identities-that-check-the-machinery) two identities · [8.4](#84-the-best-estimate-liability) best-estimate liability · [8.5](#85-the-mortality-cushion) cushion · [8.6](#86-which-assumption-matters) scenarios · [8.7](#87-pricing-on-the-insured-lives-table) insured table · [8.8](#88-examples-you-can-check-by-hand) examples · [8.9](#89-validation) validation · [8.10](#810-code-map) code map · [8.11](#811-limits) limits

---

## 8.1 The net premium and the reserve

The **net premium** covers the expected claims and nothing else (no expenses, no profit). For an $`n`$-year term insurance paying $`S`$ at the end of the year of death, with the premium paid at the start of each year while alive, interest $`i`$ and the probabilities of death $`q_0, \dots, q_{n-1}`$ in successive policy years (here indexed from year 0 for the first), the equivalence principle (the present value of premiums equals that of claims) gives

$$
P = S\ \frac{\sum_{t=0}^{n-1} v^{t+1}\ {}_tp\ q_t}{\sum_{t=0}^{n-1} v^{t}\ {}_tp}, \qquad {}_tp = \prod_{k<t}(1 - q_k), \quad v = \frac{1}{1+i}. \tag{8.1}
$$

This is the ratio $`A^{1}_{x:\overline{n}\vert}/\ddot{a}_{x:\overline{n}\vert}`$ of chapter 5 with $`S`$ as the unit.

The **statutory reserve** $`V_t`$ is the money the regulator makes the company hold for a policy still in force at the end of year $`t`$ (the net premium reserve on the valuation table at the valuation interest, 4%). It follows a one-line recursion: the reserve at the start, plus the premium, earns interest; claims are paid for those who die; what remains must be the reserve for the survivors:

$$
V_t = \frac{\left(V_{t-1} + P\right)(1+i) - q_t S}{1 - q_t}, \qquad V_0 = 0, \qquad V_n = 0. \tag{8.2}
$$

The recursion is the same as Fackler's (5.22), written for level term cover, and it closes at zero *only because* $`P`$ is the net premium (8.1). It also equals the **prospective** reserve, the present value of future claims less future premiums:

$$
V_t = S\,A^{1}_{x+t:\overline{n-t}\vert} - P\,\ddot{a}_{x+t:\overline{n-t}\vert}. \tag{8.3}
$$

For level term cover the reserve is positive after year 0 and falls back to zero at expiry. It starts and ends at zero, so a policy never carries a reserve it did not earn, and a lapsing policy (no surrender value) releases its reserve.

## 8.2 The profit test

A **profit test** follows one policy through its years and records every cash flow. In policy year $`t`$, for a policy in force at the start of the year, the insurer receives the premium $`P`$, pays the commission $`c_t`$ and the expenses $`E_t`$ at the start, holds and invests the result, earns interest at the **investment return** $`i`$ (best estimate, not the valuation interest), pays $`S + \kappa`$ for each death at the end of the year, and sets up the reserve $`V_t`$ for the survivors who do not lapse. What is left is the profit:

$$
\mathrm{profit}_t = \left(V_{t-1} + P - c_t - E_t\right)(1 + i) \;-\; q_t\,(S + \kappa) \;-\; (1 - q_t)(1 - w_t)\,V_t. \tag{8.4}
$$

Weighting by the probability that the policy is still in force at the start of the year gives the profit per policy **issued**:

$$
\ell_t = \prod_{k < t}(1 - q_k)(1 - w_k), \qquad \mathrm{profit}^{\text{issued}}_t = \ell_t\ \mathrm{profit}_t. \tag{8.5}
$$

The **net present value** at the hurdle rate $`h`$ discounts each year's profit from the end of that year; the **margin** divides it by the present value of the premiums (paid at the start of the year, so one year less of discounting):

$$
\mathrm{NPV} = \sum_{t=1}^{n}\frac{\mathrm{profit}^{\text{issued}}_t}{(1+h)^{t}}, \qquad \text{margin} = \frac{\mathrm{NPV}}{\sum_t \ell_t P\,(1+h)^{-(t-1)}}. \tag{8.6}
$$

A margin of 0 means the policy earns exactly its hurdle. The **internal rate of return** is the rate $`r`$ at which the present value is zero:

$$
\sum_{t} \frac{\mathrm{profit}^{\text{issued}}_t}{(1 + r)^{t}} = 0. \tag{8.7}
$$

A term policy loses money at first (acquisition cost and commission are paid before any premium has earned a profit) and makes it back later, so the profits change sign once and (8.7) has one sensible root; but a small loss in the last year can create two. The code scans the present value over a grid of rates, refines every sign change by bisection and reports the root nearest the hurdle; when the cash flows never turn positive there is no rate, and the IRR is reported as undefined, never as zero.

**The gross premium is solved, not assumed.** Every term in (8.4) is *linear in the premium*: the premium itself, the commission and the acquisition cost are percentages of it, and the reserve is computed from the *net* premium on the valuation table, so it does not depend on the gross one. The NPV is therefore a straight line in $`P`$:

$$
\mathrm{NPV}(P) = a + b\,P, \qquad P^{*} = -\frac{a}{b}\quad\text{earns exactly the hurdle.} \tag{8.8}
$$

The code finds $`P^{*}`$ by bisection (a closed form would do as well, and the two agree), and at $`P^{*}`$ the NPV is zero and the IRR is the hurdle.

## 8.3 Two identities that check the machinery

**1. A policy with no costs earns nothing.** Suppose there are no expenses, commissions or lapses, the interest earned is the valuation interest, and the premium is the net premium. Then (8.4) is

$$
\mathrm{profit}_t = \left(V_{t-1} + P\right)(1+i) - q_t S - (1 - q_t)V_t = 0 \quad\text{for every } t, \tag{8.9}
$$

which is the reserve recursion (8.2) rearranged. If a profit test does not return exactly zero here, the reserve or the cash flow is wired wrongly; this is the first test of the code.

**2. The value of the profits does not depend on the reserve.** Take the investment return $`i`$ as the discount rate and multiply (8.4) by $`\ell_t\,(1+i)^{-t}`$. Using $`\ell_{t+1} = \ell_t(1 - q_t)(1 - w_t)`$, the reserve terms are $`+\ell_t V_{t-1}(1+i)^{-(t-1)}`$ and $`-\ell_{t+1}V_t (1+i)^{-t}`$: the second, one year on, is the negative of the first, so **they cancel in the sum** (the reserve starts and ends at zero). What remains is the present value of premiums less commissions, expenses and claims at the rate $`i`$, which is *minus the best-estimate liability* (section 8.4) at issue:

$$
\sum_{t=1}^{n} \frac{\ell_t\,\mathrm{profit}_t}{(1+i)^{t}} = -\mathrm{BEL}_0. \tag{8.10}
$$

The statutory reserve **moves profit through time** (strain early, release later) but, when valued at the rate it earns, cannot create or destroy any. The reserve basis decides *when* the money arrives, not *how much*.

## 8.4 The best-estimate liability

The **best-estimate liability** (BEL) is what a valuation without statutory prudence holds: the present value of the real expected outgo (commission, expenses, claims) less the real premiums, with the real lapses and the real investment return, for a policy still in force at the start of year $`k`$ (before that year's premium):

$$
\mathrm{BEL}_k = \bigl(c_k + E_k - P\bigr) + v\left[\,q_k\,(S + \kappa) + (1 - q_k)(1 - w_k)\,\mathrm{BEL}_{k+1}\right], \qquad \mathrm{BEL}_n = 0, \tag{8.11}
$$

with $`v = 1/(1+i)`$, solved backwards from the last year. Unlike the statutory reserve it can be **negative**: when expected future premiums are worth more than expected claims and expenses, the policy is an asset. It is negative for a term policy early on, because the premium is level while the first-year cost is high and the risk is low; it meets the statutory reserve near expiry, where little is left to be uncertain about. The gap between them, held for prudence early and released over the life of the policy, is the reason the regulator's requirement is conservative and the economic one is not.

## 8.5 The mortality cushion

How heavy can mortality become before the product stops covering its cost? Multiply the best-estimate mortality of every year by a factor $`m`$ and ask for the factor at which the undiscounted lifetime profit is zero:

$$
m^{*} = \max\left\{m :\ \sum_{t=1}^{n}\mathrm{profit}^{\text{issued}}_t\ (m\,q) \ \ge 0\right\}, \tag{8.12}
$$

found by bisection (the profit falls as $`m`$ rises). A value above 1 is a **cushion**: mortality can run $`(m^* - 1)`$ above the pricing basis and the policy still breaks even over its life. A cushion is *not* a capital requirement: solvency capital under the regulator's rules is beyond the scope of the project.

## 8.6 Which assumption matters

The **sensitivity** of one priced policy changes one assumption at a time, with the premium held fixed, and reports the NPV margin and IRR: mortality $`\pm 10\%`$ and $`\pm 20\%`$ (a multiplier on every year), lapses $`\pm 25\%`$, the investment return $`\pm 1`$ point, expenses $`\pm 10\%`$, and a **one-year pandemic**: the best-estimate mortality of policy year 2 multiplied by 1.5 or 2, with the reserve basis unchanged. The results for a man of 40 with a 20-year term are in section 8.9; three points follow from the structure of the profit test.

- **Mortality dominates.** Claims are by far the largest outgo, so a 20% change moves the margin about five times as much as a 10% change in expenses.
- **A single bad year costs a lot.** In year 2 the most policies are in force and the least reserve has been built, so doubling that year's mortality takes 6.5 points off an IRR that targets 10%.
- **Lapses barely matter** for a policy with no surrender value: a lapse removes both a premium and the liability to pay a claim, and the two offset.

## 8.7 Pricing on the insured-lives table

Everything above prices on the regulator's table, the way an insurer without its own experience would. Version 2 of the project adds what the industry's own statistics say about the people who buy the product (chapter 11): the premium is solved on the **insured traditional-term table**, rolled forward from the middle of its base years (2024) to the pricing year (2026) at the table's age-specific improvement $`r_x`$, and loaded with a **margin for adverse deviation** of 15%:

$$
q^{\text{priced}}_x = q^{\text{insured}}_x\ \bigl(1 - r_x\bigr)^{2}\ (1 + 0.15), \qquad V_t \text{ still on CNSF 2013.} \tag{8.13}
$$

The statutory reserve stays on the CNSF table, as the regulation requires, so it is *larger* than the insured basis needs: a strain in the early years, which the premium has to pay for. The expenses, commission, lapses and hurdle are unchanged, so the only thing that moves is the mortality. If mortality then turns out to be the best estimate (without the margin) the same premium earns more than the hurdle: the margin is real.

## 8.8 Examples you can check by hand

**The zero-profit identity.** A two-year policy with $`S = 100`$, $`q = (0.1, 0.2)`$ and no interest, costs or lapses. By (8.1) $`P = 100\,(0.1 + 0.9 \times 0.2)/(1 + 0.9) = 28/1.9 = 14.737`$. The reserve recursion (8.2) gives $`V_1 = (0 + 14.737 - 10)/0.9 = 5.263`$ and $`V_2 = (5.263 + 14.737 - 20)/0.8 = 0`$. The profit of year 1 by (8.4) is $`14.737 - 10 - 0.9 \times 5.263 = 0`$ and that of year 2 is $`(5.263 + 14.737) - 0.2 \times 100 - 0.8 \times 0 = 0`$: both zero, as (8.9) says.

**An IRR by hand.** Cash flows $`-100, +60, +60`$ at times 0, 1, 2. With $`x = 1/(1+r)`$ the equation is $`60x^2 + 60x - 100 = 0`$, so $`x = (-60 + \sqrt{27\,600})/120 = 0.8844`$ and $`r = 13.07\%`$. A stream with two sign changes, $`-100, +230, -132`$, has **two** roots, $`r = 10\%`$ and $`r = 20\%`$ (since $`-132x^2 + 230x - 100 = 0`$ gives $`x = 0.9091`$ or $`0.8333`$): the code returns the one nearest the hurdle, and which one that is matters.

**The best-estimate liability.** Two years, $`S = 1000`$, premium 20, $`q = (0.01, 0.02)`$, lapses $`(0.1, 0.05)`$, no costs, $`i = 5\%`$. The last year first: $`\mathrm{BEL}_1 = -20 + 0.02 \times 1000/1.05 = -0.952`$. Then $`\mathrm{BEL}_0 = -20 + \bigl[0.01 \times 1000 + 0.99 \times 0.9 \times (-0.952)\bigr]/1.05 = -11.284`$: negative, because the premiums are worth more than the claims.

**The first year of a real policy.** A man of 40, 20-year term, solved gross premium $`P = 2{,}316.41`$ MXN per 1,000,000 of sum assured:

| Item | Calculation (from unrounded values) | MXN |
|---|---|--:|
| Commission | $`40\%`$ of the premium | 926.56 |
| Expenses | $`35\%`$ of the premium $`+ 600 + 250`$ (acquisition, fixed cost, maintenance) | 1,660.74 |
| Money held and invested | $`2316.41 - 926.56 - 1660.74`$ | -270.90 |
| Interest at 5% | $`-270.90 \times 0.05`$ | -13.54 |
| Claims | $`q_{40} \times (1{,}000{,}000 + 1{,}500)`$, $`q_{40} = 0.001033`$ | 1,034.55 |
| Reserve for the survivors who do not lapse | $`0.99897 \times 0.89 \times 776.05`$ | 689.97 |
| **Profit** | $`-270.90 - 13.54 - 1034.55 - 689.97`$ | **-2,008.97** |

Every term policy starts in the red: the loss is 87% of the first premium. It takes nine years for the undiscounted profit to turn positive and nineteen at the 10% hurdle, which is the real cost of selling term business.

## 8.9 Validation

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_pricing.py`: the net premium against chapter 5's term premium to twelve digits; the reserve recursion against the prospective reserve and against its own closure at zero; the zero-profit identity (8.9); the value-of-profits identity (8.10) for three different valuation bases; the linearity of the NPV in the premium and the closed-form premium of (8.8); the IRR by hand, including the two-root stream; the margin; the best-estimate liability by hand; the cushion; the pandemic shock; and the paths of mortality.
2. **The data.** The quantities below are tested against the shipped database.

*The premium.* Gross premium for a 20-year term on CNSF 2013 per 1,000 of sum assured (the table is unisex in this model, so men and women are priced alike), solved for the 10% hurdle:

| Issue age | Net | Gross | Loading over net | Year-1 profit (MXN) |
|--:|--:|--:|--:|--:|
| 30 | 0.97 | 1.54 | 58% | -1,463 |
| 40 | 1.74 | 2.32 | 33% | -2,009 |
| 50 | 3.72 | 4.30 | 16% | -3,412 |
| 60 | 9.44 | 9.93 | 5% | -7,460 |

The loading shrinks with age because expenses are a fixed amount plus a percentage, so they weigh most on small premiums. In policy year 5 a man of 40's premium is spent on claims (55%), expenses (13%), commission (5%), additions to the reserve net of interest (11%) and profit (16%).

*Adequacy.* The premium is fixed on CNSF 2013 and the policy is then run on another mortality basis; the NPV margin is the NPV at the hurdle as a share of the present value of premiums.

| Basis | Men 30 | Men 40 | Men 50 | Women 30 | Women 40 | Women 50 |
|---|--:|--:|--:|--:|--:|--:|
| CNSF 2013 (pricing basis) | 0% | 0% | 0% | 0% | 0% | 0% |
| CNSF with projected improvement | +3.9% | +4.6% | +4.3% | +7.0% | +6.3% | +5.4% |
| Company experience (synthetic) | -2.2% | +0.4% | +4.4% | +15.0% | +18.8% | +23.1% |
| CNSF 99.5th percentile | -26% | -29% | -32% | -26% | -29% | -32% |
| Mexican population 2023 | -154% | -171% | -157% | -21% | -44% | -66% |

The synthetic book splits by sex (women's IRR 31% to 41% at the same premium, men's 6% to 16%): a unisex premium subsidizes men with women's profit, which is what the experience study of chapter 7 finds. A policy on the **population's** mortality never recovers its first-year loss (the IRR is undefined, the mortality cushion is 0.28 for men of 40): an insured population is not the population, and the underwriting that makes the difference is not free. On CNSF 2013 the cushion is 1.08 to 1.09 at the typical ages: mortality can run 8% to 9% above the pricing basis before the policy stops covering its cost.

*Sensitivity,* man of 40, 20-year term, premium held fixed:

| Scenario | NPV margin | IRR |
|---|--:|--:|
| Mortality -20% / +20% | +11.6% / -11.6% | 25.7% / undefined |
| Mortality -10% / +10% | +5.8% / -5.8% | 18.1% / undefined |
| Expenses -10% / +10% | +2.2% / -2.2% | 13.6% / 6.7% |
| Investment return +1 pt / -1 pt | +1.7% / -1.7% | 12.6% / 7.0% |
| Lapses +25% / -25% | +0.3% / -0.4% | 10.5% / 9.2% |
| Pandemic in year 2, mortality $`\times 1.5`$ / $`\times 2`$ | -2.7% / -5.4% | 6.3% / 3.5% |

*Reserves,* man of 40, 20-year term (MXN per 1,000,000):

| End of year | Statutory reserve | Best-estimate liability |
|--:|--:|--:|
| 1 | 776 | **-2,230** |
| 4 | 2,951 | 6 |
| 10 | 5,957 | 4,034 |
| 15 | 5,623 | 5,015 |
| 20 | 0 | 0 |

*The insured basis (8.13).* Gross premium per 1,000 for a 20-year term, against CNSF 2013:

| Policy | Insured table | CNSF 2013 | Saving |
|---|--:|--:|--:|
| Man of 30 | 1.13 | 1.54 | 27% |
| Man of 40 | 1.57 | 2.32 | 32% |
| Man of 50 | 2.86 | 4.30 | 33% |
| Woman of 30 | 0.77 | 1.54 | 50% |
| Woman of 40 | 1.04 | 2.32 | 55% |
| Woman of 50 | 1.83 | 4.30 | 57% |

The women's saving is larger because the regulator's table is unisex: it prices a woman as the average of both sexes. If mortality is the best estimate the same premium earns 14.6% (man of 40) and 11.7% (woman of 40) instead of 10%.

## 8.10 Code map

| Formula | Function (`src/mortality/pricing.py`) | Checked by (`tests/test_handbook_pricing.py`) |
|---|---|---|
| (8.1) | `net_premium` | `test_net_premium_is_the_term_premium_of_chapter_5` |
| (8.2), (8.3) | `net_premium_reserves` | `test_the_reserve_recursion_equals_the_prospective_reserve` |
| (8.4), (8.5) | `profit_test` | `test_margin_is_npv_over_the_value_of_the_premiums_paid_at_the_start_of_each_year` |
| (8.6) | `summarise` | the same test |
| (8.7) | `irr` | `test_irr_by_hand_including_a_stream_with_two_roots` |
| (8.8) | `solve_premium` | `test_npv_is_affine_in_the_premium_so_the_solved_premium_has_a_closed_form` |
| (8.9) | `profit_test` | `test_a_bare_policy_priced_at_the_net_premium_earns_exactly_nothing` |
| (8.10) | `profit_test`, `best_estimate_liability` | `test_the_value_of_the_profits_at_the_earned_rate_is_minus_the_best_estimate_liability` |
| (8.11) | `best_estimate_liability` | `test_best_estimate_liability_toy_example_by_hand` |
| (8.12) | `mortality_cushion` | `test_the_mortality_cushion_is_the_multiplier_that_zeroes_the_lifetime_profit` |
| Section 8.6 | `scenario_grid`, `profit_test(shock=...)` | `test_a_pandemic_shock_touches_one_year_of_claims_and_nothing_else` |
| (8.13) | `q_path`, `_insured_bases` | `test_mortality_paths_scale_by_a_margin_and_are_clipped_to_probabilities` |
| Section 8.9, tables | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

To reproduce the net premium and the profit test of a policy:

```python
import numpy as np
from mortality.pricing import Assumptions, profit_test, solve_premium, summarise

a = Assumptions()
q = np.array([0.001033, 0.001102, 0.00118])  # probabilities of death by policy year
premium = solve_premium(q, a)
print(summarise(profit_test(q, premium, a), a.hurdle)["irr"])  # 0.10
```

## 8.11 Limits

- **Only level term is priced:** no whole life, no savings component, no policyholder options.
- **One interest rate and one expense scale** for all scenarios, flat in time: there is no stochastic interest or inflation.
- **Reserves are per policy in force** and net of reinsurance; reinsurance is the subject of [chapter 10](10-reinsurance.md).
- **A mortality cushion is not a capital requirement.** Solvency capital under the regulator's rules is beyond the scope of the project.
- **No surrender value.** The lapse-supported product makes lapses nearly neutral; a product that pays a surrender value would not behave this way.
- **The assumptions are illustrative.** The expense, commission, lapse and hurdle values are not those of any company, and the company-experience basis comes from a synthetic portfolio.
- **The IRR can be ambiguous.** A stream with several sign changes has several roots (section 8.8); the margin is always defined and is the measure the sensitivity analysis uses.

## References

- Bowers, N. L., Gerber, H. U., Hickman, J. C., Jones, D. A. and Nesbitt, C. J. (1997). *Actuarial Mathematics*, 2nd ed. Society of Actuaries. The chapters on net premiums and net premium reserves.
- Dickson, D. C. M., Hardy, M. R. and Waters, H. R. (2020). *Actuarial Mathematics for Life Contingent Risks*, 3rd ed. Cambridge University Press. The chapters on premiums and policy values and on emerging costs (profit testing).
