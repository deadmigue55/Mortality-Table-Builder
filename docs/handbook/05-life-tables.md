# 5. Life tables and actuarial functions

> [!NOTE]
> **In one minute.** A life table follows an imaginary group of 100,000 newborns through the mortality rates of one year and sex, and records how many are alive at each age. Everything an insurer prices comes out of that single column of survivors: how long people live, what a promise to pay at death is worth today, what a pension costs. The only mathematics needed is a recursion ($`\ell_{x+1} = \ell_x p_x`$), a discount factor ($`v = 1/(1+i)`$) and sums.
>
> **What this chapter does:** it turns the graduated rates of [chapter 4](../graduation.md) into complete life tables, derives every actuarial function from them, and shows how each formula is checked against the code.
>
> **The number to remember.** In 2023 a Mexican man could expect to live $`\mathring{e}_0 = 72.9`$ years and a woman 78.9. A life annuity of 1 a year at 65 costs 12.21 for men on this table and 14.94 on the regulator's CNSF 2013 table.

Code: `src/mortality/lifetable.py` · Tests: `tests/test_lifetable.py` and `tests/test_handbook_lifetables.py` · Results: [life-tables.md](../life-tables.md)

**Contents.** [5.1](#51-from-rates-to-a-table) rates to a table · [5.2](#52-the-separation-factor) separation factor · [5.3](#53-person-years-and-life-expectancy) person-years · [5.4](#54-both-sexes) both sexes · [5.5](#55-summary-measures) summary measures · [5.6](#56-commutation-functions) commutation · [5.7](#57-premiums-and-reserves) premiums and reserves · [5.8](#58-payments-more-often-than-yearly) monthly payments · [5.9](#59-a-table-you-can-check-by-hand) worked example · [5.10](#510-validation) validation · [5.11](#511-code-map) code map · [5.12](#512-limits) limits

---

## 5.1 From rates to a table

Start with the probability $`q_x`$ that a life aged exactly $`x`$ dies before $`x + 1`$, and $`p_x = 1 - q_x`$ its complement. Following a *radix* of $`\ell_0 = 100\,000`$ lives, the survivors to the next birthday and the deaths in the year are

$$
\ell_{x+1} = \ell_x\, p_x, \qquad d_x = \ell_x\, q_x = \ell_x - \ell_{x+1}. \tag{5.1}
$$

Chaining the first equation gives the probability of surviving $`k`$ more years, and the probability of surviving $`k`$ years and then dying in the next one:

$$
{}_kp_x = \prod_{j=0}^{k-1} p_{x+j} = \frac{\ell_{x+k}}{\ell_x}, \qquad {}_{k\mid}q_x = {}_kp_x\; q_{x+k} = \frac{d_{x+k}}{\ell_x}. \tag{5.2}
$$

The table closes at the oldest age $`\omega`$ (110 here) by setting $`q_\omega = 1`$, so $`\ell_{\omega+1} = 0`$ and the deaths $`d_x`$ add up to the radix. `build_life_table` refuses a table whose last $`q`$ is not 1.

The force of mortality $`\mu_x`$ is the instantaneous rate of dying, and a table that sets $`q_x`$ is equivalent to one that sets $`\mu`$ through

$$
q_x = 1 - \exp\!\left(-\int_0^1 \mu_{x+s}\, ds\right). \tag{5.3}
$$

A graduated table gives $`q_x`$ directly and the integral is never evaluated: (5.3) is only what the word *rate* means.

## 5.2 The separation factor

The graduation of chapter 4 produces **two** rates for each age: the probability $`q_x`$ and the central rate $`m_x`$ (deaths per person-year lived). They are different numbers because the people who die during the year do not live all of it. To keep a table consistent with both, we need the average fraction of the year lived by those who die in it, the **separation factor** $`\phi_x`$.

Let $`L_x`$ be the person-years lived between $`x`$ and $`x+1`$. The $`\ell_{x+1}`$ survivors each contribute a full year and the $`d_x`$ decedents contribute $`\phi_x`$ of a year on average:

$$
L_x = \ell_{x+1} + \phi_x\, d_x, \qquad m_x = \frac{d_x}{L_x}. \tag{5.4}
$$

Dividing numerator and denominator of $`m_x`$ by $`\ell_x`$ and using $`\ell_{x+1}/\ell_x = 1 - q_x`$,

$$
m_x = \frac{q_x}{1 - q_x + \phi_x q_x} = \frac{q_x}{1 - (1-\phi_x)\,q_x},
$$

which can be solved for either rate:

$$
q_x = \frac{m_x}{1 + (1-\phi_x)\,m_x}, \qquad\qquad \phi_x = 1 - \frac{m_x/q_x - 1}{m_x}. \tag{5.5}
$$

**Two cases fix the intuition.** If deaths are spread evenly through the year (the *uniform distribution of deaths*, UDD), decedents live half the year on average, so $`\phi_x = \tfrac12`$ and $`q_x = m_x / (1 + m_x/2)`$. For infants, deaths cluster in the first weeks, so $`\phi_0`$ is small: about $`0.07`$ in the Mexican table.

**What the code does.** Rather than assume $`\phi_x`$, the project *recovers* it from the graduated $`m_x`$ and $`q_x`$ with the second equation of (5.5) (`average_years_in_death_year`), so the finished table reproduces both rates exactly. Where either rate is zero the formula is undefined and $`\phi_x = \tfrac12`$ is used; the value is clipped to $`[0, 1]`$.

## 5.3 Person-years and life expectancy

Equation (5.4) gives the person-years lived in each year of age, and summing from the top gives the person-years lived above age $`x`$ and the **complete life expectancy**:

$$
T_x = \sum_{y \ge x} L_y, \qquad \mathring{e}_x = \frac{T_x}{\ell_x}. \tag{5.6}
$$

Since $`T_x = L_x + T_{x+1}`$, dividing by $`\ell_x`$ yields a recursion that reads as a sentence: a life aged $`x`$ lives the year if it survives, or the fraction $`\phi_x`$ of it if it dies, and then goes on to live $`\mathring{e}_{x+1}`$ more years if it survived:

$$
\mathring{e}_x = \underbrace{p_x + \phi_x q_x}_{L_x / \ell_x} + p_x\, \mathring{e}_{x+1}. \tag{5.7}
$$

**The open last interval.** At age $`\omega`$ every life dies, but not necessarily within the year, so $`L_\omega = \phi_\omega \ell_\omega`$ would be arbitrary. If the force of mortality beyond $`\omega`$ is a constant $`\mu`$ (an exponential tail), the person-years lived by the $`\ell_\omega`$ survivors are

$$
L_\omega = \int_0^\infty \ell_\omega\, e^{-\mu s}\, ds = \frac{\ell_\omega}{\mu} = \frac{\ell_\omega}{m_\omega}, \qquad \text{so} \qquad \mathring{e}_\omega = \frac{1}{m_\omega}, \tag{5.8}
$$

because for a constant force the central rate equals the force. The code uses (5.8) when the final central rate is supplied (`terminal_mx`), and falls back to $`\phi_\omega \ell_\omega`$ otherwise.

## 5.4 Both sexes

The combined table for both sexes ($`T`$) mixes the **rates** of the two sexes, weighting each by its share of the exposed population at that age:

$$
q_x^{T} = w_x\, q_x^{M} + (1 - w_x)\, q_x^{F}, \quad m_x^{T} = w_x\, m_x^{M} + (1 - w_x)\, m_x^{F}, \quad w_x = \frac{\mathcal{E}^{M}_x}{\mathcal{E}^{M}_x + \mathcal{E}^{F}_x}. \tag{5.9}
$$

For the central rate this is exact, not an approximation: the pooled rate is total deaths over total exposure,

$$
m^{T}_x = \frac{\mathcal{D}^{M}_x + \mathcal{D}^{F}_x}{\mathcal{E}^{M}_x + \mathcal{E}^{F}_x} = \frac{m^{M}_x \mathcal{E}^{M}_x + m^{F}_x \mathcal{E}^{F}_x}{\mathcal{E}^{M}_x + \mathcal{E}^{F}_x} = w_x\, m^{M}_x + (1-w_x)\, m^{F}_x .
$$

Averaging the two **tables** instead would be wrong: at age 80 the survivors of a male table and a female table are different mixtures of people than the population alive at 80, because men have been dying faster since birth. Mixing rates at each age, with the population that is actually there, avoids that. The code (`combine_sexes`) mixes $`q`$ and $`m`$ separately and then recovers $`\phi_x`$ from the mixed pair with (5.5), so the combined table is consistent too.

## 5.5 Summary measures

These are the numbers a reader quotes. All are functions of $`\ell_x`$, $`d_x`$ and $`\mathring{e}_x`$.

**Probabilities of dying in an age range.** The probability that a life aged $`x`$ dies within $`n`$ years is $`{}_nq_x = 1 - \ell_{x+n}/\ell_x`$. Two standard cases: the under-five mortality $`{}_5q_0`$ and the WHO adult mortality $`{}_{45}q_{15}`$, the chance that a 15-year-old does not reach 60:

$$
{}_5q_0 = 1 - \frac{\ell_5}{\ell_0}, \qquad {}_{45}q_{15} = 1 - \frac{\ell_{60}}{\ell_{15}}. \tag{5.10}
$$

**Median age at death.** With $`s_k = \ell_k / \ell_0`$ the survival curve, let $`k`$ be the first age with $`s_k \le \tfrac12`$. Interpolating linearly inside the year,

$$
x_{50} = (k-1) + \frac{s_{k-1} - \tfrac12}{s_{k-1} - s_k}. \tag{5.11}
$$

The **modal age at death** is the adult age with the most deaths, $`\arg\max_{x \ge 10} d_x`$ (ages below 10 are excluded so that infant deaths do not hide the adult peak).

**Lifespan disparity.** A person who dies in year $`x`$ dies, on average, at age $`x + \phi_x`$. At that moment they lose the remaining life expectancy of someone that age, which by linear interpolation is $`(1 - \phi_x)\,\mathring{e}_x + \phi_x\,\mathring{e}_{x+1}`$. Averaging over all deaths gives the **average years of life lost at death** (Vaupel and Canudas-Romo, 2003):

$$
e^{\dagger} = \frac{1}{\ell_0} \sum_{x} d_x \Big[(1-\phi_x)\,\mathring{e}_x + \phi_x\, \mathring{e}_{x+1}\Big]. \tag{5.12}
$$

It measures how unequal lifespans are. If everyone died at exactly the same age, nobody would lose anything relative to the expectation, and $`e^{\dagger} = 0`$. If the force of mortality is constant (the most unequal case compatible with a given mean), $`\mathring{e}_x = 1/\mu`$ at every age and $`e^{\dagger} = \mathring{e}_0`$. Mexican men's $`e^\dagger`$ of 14.6 years against 9.9 for Japanese men says that Mexican deaths are spread far more widely across ages.

## 5.6 Commutation functions

An actuary prices a promise as the *expected present value* of its payments. Let $`v = 1/(1+i)`$. A payment of 1 at age $`x + k`$, made only if the life is still alive, has present value $`v^k\,{}_kp_x`$ at age $`x`$. Writing the survival probability with (5.2) and multiplying top and bottom by $`v^x`$,

$$
{}_nE_x = v^{n}\,{}_np_x = \frac{v^{x+n}\,\ell_{x+n}}{v^{x}\,\ell_x} = \frac{D_{x+n}}{D_x}, \qquad \text{where } D_x = v^x\, \ell_x. \tag{5.13}
$$

This is the whole idea: **every present value is a ratio of sums of a few columns**, computed once. The columns are

$$
D_x = v^{x}\,\ell_x, \quad C_x = v^{x+1}\,d_x, \qquad N_x = \sum_{y \ge x} D_y, \quad M_x = \sum_{y \ge x} C_y, \qquad S_x = \sum_{y \ge x} N_y, \quad R_x = \sum_{y \ge x} M_y. \tag{5.14}
$$

**Whole life insurance** pays 1 at the end of the year of death. The present value of the payment if death is in year $`x + k`$ is $`v^{k+1}`$ and its probability is $`{}_{k\mid}q_x = d_{x+k}/\ell_x`$, so

$$
A_x = \sum_{k \ge 0} v^{k+1}\, \frac{d_{x+k}}{\ell_x} = \frac{\sum_{k \ge 0} v^{x+k+1}\, d_{x+k}}{v^{x}\,\ell_x} = \frac{M_x}{D_x}. \tag{5.15}
$$

**The life annuity-due** pays 1 at the start of each year while alive, that is, a pure endowment $`{}_kE_x`$ for every $`k \ge 0`$:

$$
\ddot{a}_x = \sum_{k \ge 0} {}_kE_x = \frac{\sum_{k \ge 0} D_{x+k}}{D_x} = \frac{N_x}{D_x}. \tag{5.16}
$$

Every other value follows by adding or subtracting these:

| Value | Formula | Why |
|---|---|---|
| Pure endowment $`{}_nE_x`$ | $`\dfrac{D_{x+n}}{D_x}`$ | (5.13) |
| Term insurance $`A^{1}_{x:\overline{n}\vert}`$ | $`\dfrac{M_x - M_{x+n}}{D_x}`$ | $`A_x`$ restricted to deaths before $`x+n`$ |
| Deferred insurance $`{}_{n\mid}A_x`$ | $`\dfrac{M_{x+n}}{D_x}`$ | $`A_x`$ restricted to deaths after $`x+n`$ |
| Endowment insurance $`A_{x:\overline{n}\vert}`$ | $`A^{1}_{x:\overline{n}\vert} + {}_nE_x`$ | pays at death or at survival to $`x+n`$ |
| Increasing insurance $`(IA)_x`$ | $`\dfrac{R_x}{D_x}`$ | see below |
| Annuity-immediate $`a_x`$ | $`\ddot{a}_x - 1`$ | the first payment is not made |
| Temporary annuity-due $`\ddot{a}_{x:\overline{n}\vert}`$ | $`\dfrac{N_x - N_{x+n}}{D_x}`$ | at most $`n`$ payments |
| Deferred annuity-due $`{}_{n\mid}\ddot{a}_x`$ | $`\dfrac{N_{x+n}}{D_x}`$ | payments start at $`x+n`$ |

For the increasing insurance, which pays $`k+1`$ if death is in year $`x+k`$, note that $`R_x = \sum_{y \ge x} M_y = \sum_{z \ge x} (z - x + 1)\, C_z`$ (each $`C_z`$ is counted once for every $`y`$ from $`x`$ to $`z`$), hence

$$
(IA)_x = \sum_{k \ge 0} (k+1)\, v^{k+1}\,\frac{d_{x+k}}{\ell_x} = \frac{1}{D_x}\sum_{k \ge 0} (k+1)\, C_{x+k} = \frac{R_x}{D_x}.
$$

**Two relations that tie insurance to annuities.** Conditioning on the first year gives recursions,

$$
\ddot{a}_x = 1 + v\,p_x\, \ddot{a}_{x+1}, \qquad A_x = v\,q_x + v\,p_x\, A_{x+1}, \tag{5.17}
$$

and from them an identity that is used constantly:

$$
A_x = 1 - d\,\ddot{a}_x, \qquad d = \frac{i}{1+i} = 1 - v. \tag{5.18}
$$

*Proof, by backward induction from the last age.* At $`\omega`$, $`q_\omega = 1`$ so $`A_\omega = v`$ and $`\ddot{a}_\omega = 1`$, and $`1 - d = v`$. If it holds at $`x + 1`$, then by (5.17)

$$
A_x = v\,q_x + v\,p_x\bigl(1 - d\,\ddot{a}_{x+1}\bigr) = v - d\,\bigl(v\,p_x\,\ddot{a}_{x+1}\bigr) = v - d\,(\ddot{a}_x - 1) = 1 - d\,\ddot{a}_x. \qquad \blacksquare
$$

The identity is a strong test of any implementation: the insurance column $`M`$ and the annuity column $`N`$ are built from different sums and agree only if both are right.

**Ages outside the table.** Below the first age of a table every value is undefined (`NaN`). Above $`\omega`$ every column is 0, so a benefit that would be payable beyond $`\omega`$ is worth 0 (for example $`{}_nE_x = 0`$ when $`x + n > \omega`$), while a value asked for a life that is *already* older than $`\omega`$ is $`0/0`$ and is returned as `NaN`.

## 5.7 Premiums and reserves

The **equivalence principle** sets the level annual premium so that the expected present value of premiums equals that of benefits. For a whole life policy paid for life, and for an $`n`$-year term policy paid for at most $`n`$ years,

$$
P_x \,\ddot{a}_x = A_x \;\Rightarrow\; P_x = \frac{A_x}{\ddot{a}_x} = \frac{1}{\ddot{a}_x} - d, \qquad\qquad P^{1}_{x:\overline{n}\vert} = \frac{A^{1}_{x:\overline{n}\vert}}{\ddot{a}_{x:\overline{n}\vert}}. \tag{5.19}
$$

The second form of $`P_x`$ follows from (5.18). The **prospective reserve** after $`t`$ years is the expected present value of future benefits minus that of future premiums, for a life then aged $`x + t`$:

$$
{}_tV_x = A_{x+t} - P_x\, \ddot{a}_{x+t} = 1 - \frac{\ddot{a}_{x+t}}{\ddot{a}_x}. \tag{5.20}
$$

The last form comes from substituting $`P_x = 1/\ddot{a}_x - d`$ and using (5.18):

$$
{}_tV_x = \bigl(1 - d\,\ddot{a}_{x+t}\bigr) - \Bigl(\frac{1}{\ddot{a}_x} - d\Bigr)\ddot{a}_{x+t} = 1 - \frac{\ddot{a}_{x+t}}{\ddot{a}_x}.
$$

Looking *back* instead, the reserve is the premiums collected, minus the claims paid, all accumulated with interest and survivorship to age $`x+t`$:

$$
{}_tV_x = \frac{P_x\,(N_x - N_{x+t}) - (M_x - M_{x+t})}{D_{x+t}}. \tag{5.21}
$$

Prospective (5.20) and retrospective (5.21) agree whenever the premium satisfies the equivalence principle, a second independent check of the commutation columns. The reserve also obeys **Fackler's recursion**, which says what happens in one year: the opening reserve plus the premium earns interest, and pays either the sum assured (if death) or the closing reserve (if survival):

$$
({}_tV_x + P_x)(1 + i) = q_{x+t} + p_{x+t}\;{}_{t+1}V_x. \tag{5.22}
$$

## 5.8 Payments more often than yearly

Pensions are paid monthly, not yearly. The exact value depends on how deaths are spread inside the year. Under UDD, with $`i^{(m)} = m\left[(1+i)^{1/m} - 1\right]`$ and $`d^{(m)} = m\left(1 - v^{1/m}\right)`$,

$$
\ddot{a}^{(m)}_x = \alpha(m)\,\ddot{a}_x - \beta(m), \qquad \alpha(m) = \frac{i\,d}{i^{(m)} d^{(m)}}, \qquad \beta(m) = \frac{i - i^{(m)}}{i^{(m)} d^{(m)}}. \tag{5.23}
$$

The code uses the simpler **two-term Woolhouse approximation**, which replaces $`\alpha(m)`$ by 1 and $`\beta(m)`$ by its limit at $`i \to 0`$:

$$
\ddot{a}^{(m)}_x \approx \ddot{a}_x - \frac{m-1}{2m}. \tag{5.24}
$$

At 4% interest the difference between (5.23) and (5.24) is below 0.006 per unit of annuity at every age from 30 to 80 for $`m = 2, 4, 12`$ (0.06% of the value at age 65), which is why the shortcut is acceptable here. The third Woolhouse term would involve $`\mu_x`$ and is omitted.

For an insurance paid at the end of the **month** of death rather than the year, UDD gives a closed factor:

$$
A^{(m)}_x = \frac{i}{i^{(m)}}\, A_x. \tag{5.25}
$$

*Proof.* Death in year $`k`$ happens in month $`j`$ of that year with probability $`1/m`$ each, so the present value in that year is $`v^{k}\,\tfrac{1}{m}\sum_{j=1}^{m} v^{j/m}`$. The geometric sum is $`\sum_{j=1}^m v^{j/m} = v^{1/m}\,\frac{1-v}{1-v^{1/m}}`$. Using $`1 - v = i\,v`$ and $`1 - v^{1/m} = v^{1/m}\, i^{(m)}/m`$,

$$
\frac{1}{m}\sum_{j=1}^{m} v^{j/m} = \frac{i\,v}{i^{(m)}} ,
$$

which is the end-of-year factor $`v`$ multiplied by $`i / i^{(m)}`$. $`\blacksquare`$ The code exposes it as `udd_factor`.

## 5.9 A table you can check by hand

A five-age table with radix 1,000 and $`\phi_x = 0.5`$ at every age, at $`i = 5\%`$ ($`v = 0.952381`$, $`d = 0.047619`$).

| $`x`$ | $`q_x`$ | $`\ell_x`$ | $`d_x`$ | $`L_x`$ | $`T_x`$ | $`\mathring{e}_x`$ |
|:-:|:-:|--:|--:|--:|--:|--:|
| 0 | 0.1 | 1000 | 100 | 950 | 2768 | 2.768 |
| 1 | 0.2 | 900 | 180 | 810 | 1818 | 2.020 |
| 2 | 0.4 | 720 | 288 | 576 | 1008 | 1.400 |
| 3 | 0.5 | 432 | 216 | 324 | 432 | 1.000 |
| 4 | 1.0 | 216 | 216 | 108 | 108 | 0.500 |

Each $`\ell`$ follows (5.1): $`\ell_1 = 1000 \times 0.9 = 900`$, $`\ell_2 = 900 \times 0.8 = 720`$, and so on. Each $`L_x = \ell_{x+1} + 0.5\,d_x`$, for example $`L_0 = 900 + 50 = 950`$. The last row is closed with $`L_4 = 0.5 \times 216 = 108`$. Then $`T_0 = 950 + 810 + 576 + 324 + 108 = 2768`$ and $`\mathring{e}_0 = 2.768`$.

The commutation columns at 5%:

| $`x`$ | $`D_x = v^x \ell_x`$ | $`C_x = v^{x+1} d_x`$ | $`N_x`$ | $`M_x`$ |
|:-:|--:|--:|--:|--:|
| 0 | 1000.0000 | 95.2381 | 3061.0857 | 854.2340 |
| 1 | 857.1429 | 163.2653 | 2061.0857 | 758.9959 |
| 2 | 653.0612 | 248.7852 | 1203.9428 | 595.7306 |
| 3 | 373.1778 | 177.7037 | 550.8816 | 346.9454 |
| 4 | 177.7037 | 169.2417 | 177.7037 | 169.2417 |

For example $`D_1 = 900 / 1.05 = 857.1429`$ and $`C_0 = 100 / 1.05 = 95.2381`$. $`N_x`$ and $`M_x`$ are the running sums from the bottom: $`N_3 = 373.1778 + 177.7037 = 550.8816`$.

| Value | Calculation | Result |
|---|---|--:|
| $`A_0`$ | $`M_0 / D_0 = 854.2340 / 1000`$ | 0.85423 |
| $`\ddot{a}_0`$ | $`N_0 / D_0 = 3061.0857 / 1000`$ | 3.06109 |
| Check (5.18) | $`1 - d\,\ddot{a}_0 = 1 - 0.047619 \times 3.06109`$ | 0.85423 |
| $`{}_3E_0`$ | $`D_3 / D_0`$ | 0.37318 |
| $`A^{1}_{0:\overline{3}\vert}`$ | $`(M_0 - M_3)/D_0 = (854.2340 - 346.9454)/1000`$ | 0.50729 |
| $`\ddot{a}_{0:\overline{3}\vert}`$ | $`(N_0 - N_3)/D_0 = (3061.0857 - 550.8816)/1000`$ | 2.51020 |
| $`P^{1}_{0:\overline{3}\vert}`$ | $`0.50729 / 2.51020`$ | 0.20209 |
| $`P_0`$ | $`0.85423 / 3.06109`$ | 0.27906 |
| $`{}_1V_0`$ by (5.20) | $`1 - \ddot{a}_1/\ddot{a}_0 = 1 - 2.40460 / 3.06109`$ | 0.21446 |

The disparity of this toy table by (5.12) is $`e^{\dagger} = 1108.8 / 1000 = 1.1088`$ years, and its median age at death by (5.11) is $`2 + (0.72 - 0.5)/(0.72 - 0.432) = 2.7639`$.

## 5.10 Validation

Four independent checks stand behind the code; the first two run in the test-suite on every commit.

1. **The identities of this chapter.** (5.1) to (5.22) are tested numerically on a Gompertz-Makeham table and on the toy table above: recursions, $`A_x = 1 - d\ddot{a}_x`$, prospective equals retrospective reserve, Fackler's recursion, the UDD factor against a direct monthly sum, and the Woolhouse error bound.
2. **A closed-form benchmark.** With a constant force of mortality $`\mu`$ and $`p = e^{-\mu}`$, everything has an exact answer, and the table reproduces it:

$$
\phi = \frac{1}{\mu} - \frac{1}{e^{\mu} - 1}, \qquad m = \mu, \qquad \mathring{e}_x = \frac{1}{\mu}, \qquad \ddot{a}_x = \frac{1}{1 - v\,p}, \qquad A_x = \frac{v\,q}{1 - v\,p}, \qquad e^{\dagger} = \frac{1}{\mu} \tag{5.26}
$$

   (the first line is the average time lived by someone who dies within a year under a constant force; the table is run to age 400 so that the open end has no effect).
3. **HMD.** Built from the Human Mortality Database's own $`q_x`$ and $`a_x`$ for nine countries and three sexes, the code gives life expectancy at birth within 0.007 years of the published figure and at 65 within 0.004 (a data check in the warehouse, `hmd_life_expectancy_reproduced`).
4. **CONAPO.** In 2022 to 2024 life expectancy at birth is within 0.7 years of CONAPO's own.

## 5.11 Code map

| Formula | Function (`src/mortality/lifetable.py`) | Checked by |
|---|---|---|
| (5.1), (5.2), (5.4), (5.6), (5.7) | `build_life_table` | `test_lifetable.py`, `test_handbook_lifetables.py` |
| (5.5), second form | `average_years_in_death_year` | `test_handbook_lifetables.py::test_separation_factor_roundtrip` |
| (5.8) | `build_life_table(..., terminal_mx=...)` | `test_handbook_lifetables.py::test_constant_force_benchmark` |
| (5.9) | `combine_sexes` | `test_lifetable.py` |
| (5.10), (5.11), (5.12) | `summary`, `median_age_at_death`, `lifespan_disparity` | `test_handbook_lifetables.py::test_toy_table_matches_the_handbook` |
| (5.13), (5.14), (5.15), (5.16) | `Commutation.from_table`, the insurance and annuity methods | `test_handbook_lifetables.py::test_commutation_matches_direct_sums` |
| (5.17), (5.18) | `whole_life_insurance`, `annuity_due` | `test_handbook_lifetables.py::test_recursions_and_the_insurance_annuity_identity` |
| (5.19) to (5.22) | `*_premium`, `whole_life_reserve` | `test_handbook_lifetables.py::test_reserves_prospective_retrospective_and_fackler` |
| (5.23), (5.24), (5.25) | `annuity_due_monthly`, `udd_factor` | `test_handbook_lifetables.py::test_monthly_payments` |
| (5.26) | the whole module | `test_handbook_lifetables.py::test_constant_force_benchmark` |

To reproduce the toy table of §5.9:

```python
import numpy as np
from mortality.lifetable import build_life_table, Commutation

table = build_life_table(np.arange(5), np.array([0.1, 0.2, 0.4, 0.5, 1.0]), radix=1000)
c = Commutation.from_table(table, interest=0.05)
print(c.whole_life_insurance(0), c.annuity_due(0))  # 0.85423  3.06109
```

## 5.12 Limits

- **Single decrement.** Death is the only way out. Lapses and other exits belong to the experience study (chapter 7), where exposure is cut at the exit.
- **Interest is a constant** $`i`$ in every formula here. Pricing with a yield curve changes $`v^k`$ to a product of forward factors and the commutation shortcut no longer applies.
- **Payments at the end of the year of death** are the base case. The UDD factor (5.25) moves them to the end of the month; a payment at the moment of death needs the force of interest and is not used.
- **The Woolhouse approximation** (5.24) drops a term that grows with $`\mu_x`$ and the interest rate; at very high ages or high rates use (5.23) or sum monthly survival directly.
- **Above the credible age** the table follows the closure of chapter 4 (Kannisto) and not data: every value that depends on those ages, such as $`e^{\dagger}`$ and long annuities, carries that assumption.

## References

- Bowers, N. L., Gerber, H. U., Hickman, J. C., Jones, D. A. and Nesbitt, C. J. (1997). *Actuarial Mathematics*, 2nd ed. Society of Actuaries. Chapters 3 to 8 (life tables, insurance, annuities, premiums, reserves).
- Dickson, D. C. M., Hardy, M. R. and Waters, H. R. (2020). *Actuarial Mathematics for Life Contingent Risks*, 3rd ed. Cambridge University Press.
- Preston, S. H., Heuveline, P. and Guillot, M. (2001). *Demography: Measuring and Modeling Population Processes*. Blackwell. Chapter 3 (life tables and the separation factor).
- Vaupel, J. W. and Canudas-Romo, V. (2003). Decomposing change in life expectancy: a bouquet of formulas in honor of Nathan Keyfitz's 70th birthday. *Demography* 40(2), 201-216.
- Human Mortality Database. *Methods Protocol for the Human Mortality Database*, version 6 (2021). University of California, Berkeley, and Max Planck Institute for Demographic Research.
