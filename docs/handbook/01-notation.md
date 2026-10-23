# 1. Notation and conventions

> [!NOTE]
> **In one minute.** Actuarial writing reuses a handful of letters for many things ($D$ for deaths *and* for a commutation column, $a$ for an annuity *and* for the average time lived in a year). This chapter fixes one meaning per symbol so that every later chapter can be read without guessing. When a chapter needs a local symbol it says so in its first lines.

## 1.1 How to read the handbook

The handbook follows the pipeline of the project. Each chapter has the same shape:

| Block | What it gives you |
|---|---|
| **In one minute** | The idea in plain words and the one number worth remembering |
| **Definitions and derivations** | Every formula, derived from the one before it, in LaTeX |
| **A worked example** | A table small enough to check by hand |
| **Code map** | For each formula, the function that implements it and the test that checks it |
| **Limits** | What the method assumes and where it stops being right |

A formula in this handbook is never decoration: each one that the software uses is **tested numerically against the code** (`tests/test_handbook_*.py`), and every formula is syntax-checked before publication (`node scripts/mathcheck/check.mjs`).

## 1.2 Ages, years and sexes

| Symbol | Meaning |
|---|---|
| $x$ | Age. In a single-year table, $x$ is the age at last birthday and the table row for $x$ describes the year of life from exact age $x$ to exact age $x+1$ |
| $t$ | Calendar year (or the year of a cohort's life when stated) |
| $\omega$ | The last age of a table, where $q_\omega = 1$. The Mexican tables of this project use $\omega = 110$ |
| $s \in \{M, F, T\}$ | Sex: men, women, both sexes combined. Written as a superscript, $q_x^{M}$ |

## 1.3 Data quantities

Observed quantities come from records and are written in calligraphic type so that they cannot be confused with the commutation columns of §1.5.

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\mathcal{D}_{x,t}$ | Observed deaths at age $x$ in year $t$ | INEGI registered deaths, completed for late registration |
| $\mathcal{E}_{x,t}$ | Central exposure: person-years lived at age $x$ in year $t$ | CONAPO mid-year population, or exact Lexis exposure for a policy book |
| $\hat m_{x,t}$ | Crude central rate, $\mathcal{D}_{x,t} / \mathcal{E}_{x,t}$ | Chapter 3 |

## 1.4 The life table

| Symbol | Meaning | Column in the code |
|---|---|---|
| $\mu_x$ | Force of mortality at exact age $x$ (instantaneous rate of dying) | |
| $q_x$ | Probability that a life aged exactly $x$ dies before $x+1$ | `qx` |
| $p_x$ | $1 - q_x$, the probability of surviving the year | `px` |
| $m_x$ | Central rate of mortality: deaths per person-year lived | `mx` |
| $\phi_x$ | **Separation factor**: the average fraction of the year lived by those who die in it | `ax` |
| $\ell_x$ | Number of survivors to exact age $x$ out of the radix $\ell_0$ (100,000) | `lx` |
| $d_x$ | Deaths between $x$ and $x+1$, $\ell_x q_x$ | `dx` |
| ${}_kp_x$ | Probability that a life aged $x$ survives $k$ more years, $\ell_{x+k}/\ell_x$ | |
| ${}_{k\mid}q_x$ | Probability of surviving $k$ years and then dying within the next one | |
| $L_x$ | Person-years lived between $x$ and $x+1$ | `Lx` |
| $T_x$ | Person-years lived above age $x$, $\sum_{y \ge x} L_y$ | `Tx` |
| $\mathring{e}_x$ | Complete life expectancy at age $x$, $T_x / \ell_x$ | `ex` |
| $e^{\dagger}$ | Lifespan disparity: average years of life lost at death | `lifespan_disparity` |

> [!IMPORTANT]
> The separation factor is called $\phi_x$ here and `ax` in the code and the warehouse. The usual textbook letter, $a_x$, is already taken by the annuity-immediate, so it is not used for two things.

## 1.5 Interest, insurance and annuities

The notation is the International Actuarial Notation, with the symbols below.

| Symbol | Meaning | Method in `Commutation` |
|---|---|---|
| $i$ | Annual effective interest rate (the technical rate) | `interest` |
| $v$ | Annual discount factor, $1/(1+i)$ | `v` |
| $d$ | Annual effective discount rate, $i/(1+i) = iv = 1 - v$ | `discount_rate` |
| $\delta$ | Force of interest, $\ln(1+i)$ | |
| $i^{(m)}$ | Nominal rate convertible $m$ times a year, $m\left[(1+i)^{1/m} - 1\right]$ | |
| $D_x,\ N_x,\ S_x$ | Commutation columns for survival: $D_x = v^x \ell_x$, then running sums | `D`, `N`, `S` |
| $C_x,\ M_x,\ R_x$ | Commutation columns for death: $C_x = v^{x+1} d_x$, then running sums | `C`, `M`, `R` |
| ${}_nE_x$ | Pure endowment: 1 paid at $x+n$ if alive | `pure_endowment` |
| $A_x$ | Whole life insurance: 1 paid at the end of the year of death | `whole_life_insurance` |
| $A^{1}_{x:\overline{n}\vert}$ | $n$-year term insurance | `term_insurance` |
| ${}_{n\mid}A_x$ | Insurance deferred $n$ years | `deferred_insurance` |
| $A_{x:\overline{n}\vert}$ | $n$-year endowment insurance | `endowment_insurance` |
| $(IA)_x$ | Increasing whole life insurance (1, 2, 3, ... for the 1st, 2nd, 3rd year of death) | `increasing_whole_life` |
| $\ddot{a}_x$ | Life annuity-due: 1 at the start of each year while alive | `annuity_due` |
| $a_x$ | Life annuity-immediate, $\ddot{a}_x - 1$ | `annuity_immediate` |
| $\ddot{a}_{x:\overline{n}\vert}$ | Temporary annuity-due, at most $n$ payments | `temporary_annuity_due` |
| ${}_{n\mid}\ddot{a}_x$ | Deferred annuity-due | `deferred_annuity_due` |
| $\ddot{a}^{(m)}_x$ | Annuity-due payable $m$ times a year | `annuity_due_monthly` |
| $P_x,\ P^{1}_{x:\overline{n}\vert}$ | Net annual premiums (whole life, term) | `whole_life_premium`, `term_premium` |
| ${}_tV_x$ | Prospective net premium reserve after $t$ years | `whole_life_reserve` |

## 1.6 Conventions

- **Logarithms** are natural, $\log = \ln$. Vectors and matrices over age are written in bold, $\mathbf{q}$.
- **Estimators** wear a hat, $\hat m_x$. A quantity from a *graduated* (smoothed) table is written without a hat and is explicitly called graduated.
- **Single-year ages**, last birthday, 0 to 110. Tables for other sources keep their own first age (the SOA tables start at 12) and the same formulas apply.
- **Radix** $\ell_0 = 100\,000$ for every table built here.
- **Money** is written MXN (Mexican pesos). Premiums are quoted per 1,000 of sum assured unless stated.
- **Local symbols.** The chapters on graduation, projection and the experience study reuse Greek letters ($\alpha_x$, $\beta_x$, $\kappa_t$ in the Lee-Carter model; $\theta$ for spline coefficients). Each declares its own symbols in its first lines, and none of them uses a symbol of §1.4 or §1.5 for something else.
- **Uncertainty** is stated with 95% intervals unless another level is given.

## 1.7 Where each symbol lives in the code

The mapping from symbol to column or method is in the tables above (last column). The life table is built in `src/mortality/lifetable.py`; the commutation functions are the methods of `Commutation` in the same file. Chapter 5 derives and tests every one of them.
