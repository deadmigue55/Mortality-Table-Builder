"""Pricing, profit testing and reserves of a level-term life product.

A profit test follows one policy through its years and records every cash flow: premium in,
commission and expenses out, claims out, interest earned, and the change in the reserve the
insurer must hold. What is left is the profit of each year. The present value of those profits at
the insurer's hurdle rate, and the rate that makes it zero (the IRR), say whether the product is
worth selling at its premium.

For one policy that is in force at the start of policy year ``t``::

    profit(t) = (V(t-1) + P - E(t)) (1 + i) - q(t) (S + claim expense) - (1 - q(t)) (1 - w(t)) V(t)

with premium ``P`` (paid at the start of the year), expenses ``E``, interest ``i``, probability
of death ``q`` (benefit ``S`` at the end of the year), lapse rate ``w`` (no surrender value, so
the reserve is released) and statutory reserve ``V`` at the end of the year. The year's profit
per policy *issued* is this times the probability of being in force at the start of the year.

The module is deliberately free of the warehouse: every function takes arrays, so the same
code prices any table. ``build_tables`` connects it to the project's tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

# ── Assumptions ─────────────────────────────────────────────────────────────

LAPSE_BASE = (0.11, 0.08, 0.065, 0.055, 0.04)  # annual lapse in policy years 1 to 5, then 5+


@dataclass(frozen=True)
class Assumptions:
    """Everything a profit test needs besides mortality. All values are illustrative."""

    sum_assured: float = 1_000_000.0  # MXN
    acquisition_pct: float = 0.35  # of the first-year premium
    acquisition_fixed: float = 600.0  # MXN per policy issued
    maintenance: float = 250.0  # MXN per policy per year, in year-1 money
    expense_inflation: float = 0.04
    commission_first: float = 0.40  # of the first-year premium
    commission_renewal: float = 0.05  # of later premiums
    claim_expense: float = 1_500.0  # MXN per claim
    investment_return: float = 0.05  # earned on reserves and cash
    valuation_interest: float = 0.04  # statutory reserve basis
    hurdle: float = 0.10  # required return
    lapse: tuple[float, ...] = field(default=LAPSE_BASE)

    def lapse_path(self, n: int, scale: float = 1.0) -> np.ndarray:
        """Lapse rate in each of ``n`` policy years (the last given rate repeats)."""
        base = np.asarray(self.lapse, dtype=float)
        idx = np.minimum(np.arange(n), len(base) - 1)
        return np.clip(base[idx] * scale, 0.0, 0.95)


# ── Reserves ────────────────────────────────────────────────────────────────


def net_premium(q: np.ndarray, interest: float, sum_assured: float = 1.0) -> float:
    """Level net annual premium for term insurance paid at the start of each year while alive."""
    n = len(q)
    surv = np.concatenate([[1.0], np.cumprod(1.0 - q[:-1])])
    v = (1.0 + interest) ** -np.arange(n)
    claims = (surv * q * v / (1.0 + interest)).sum()
    return float(sum_assured * claims / (surv * v).sum())


def net_premium_reserves(q: np.ndarray, interest: float, sum_assured: float) -> np.ndarray:
    """Statutory net premium reserve at the end of each policy year, by the recursion
    ``V(t) = ((V(t-1) + P) (1 + i) - q S) / (1 - q)``; it starts and ends at zero.

    Negative values are not floored: for level term cover they do not arise except through
    rounding, and a floor would hide an error."""
    p = net_premium(q, interest, sum_assured)
    reserve = np.zeros(len(q))
    previous = 0.0
    for t in range(len(q)):
        previous = ((previous + p) * (1.0 + interest) - q[t] * sum_assured) / (1.0 - q[t])
        reserve[t] = previous
    reserve[-1] = 0.0  # the policy has expired
    return reserve


# ── The profit test ─────────────────────────────────────────────────────────


def profit_test(
    q_best: np.ndarray,
    premium: float,
    a: Assumptions,
    q_valuation: np.ndarray | None = None,
    lapse_scale: float = 1.0,
    interest: float | None = None,
    expense_scale: float = 1.0,
    shock: dict[int, float] | None = None,
) -> pd.DataFrame:
    """Year-by-year cash flows and profit of one policy, per policy issued.

    ``q_best``: best-estimate probabilities of death by policy year. ``q_valuation``: the
    probabilities the statutory reserve is computed on (defaults to ``q_best``). ``shock``:
    ``{policy year (1-based): multiplier}`` applied to the best-estimate mortality of that year
    only, for a one-off event such as a pandemic.
    """
    n = len(q_best)
    q_val = np.asarray(q_best if q_valuation is None else q_valuation, dtype=float)
    q = np.asarray(q_best, dtype=float).copy()
    for year, mult in (shock or {}).items():
        if 1 <= year <= n:
            q[year - 1] = min(q[year - 1] * mult, 1.0)
    i = a.investment_return if interest is None else interest
    w = a.lapse_path(n, lapse_scale)
    reserve = net_premium_reserves(q_val, a.valuation_interest, a.sum_assured)
    t = np.arange(n)
    in_force = np.concatenate([[1.0], np.cumprod((1.0 - q) * (1.0 - w))[:-1]])
    prem = np.full(n, premium)
    commission = prem * np.where(t == 0, a.commission_first, a.commission_renewal)
    expenses = expense_scale * (
        a.maintenance * (1.0 + a.expense_inflation) ** t
        + np.where(t == 0, a.acquisition_pct * premium + a.acquisition_fixed, 0.0)
    )
    claims = q * (a.sum_assured + a.claim_expense)
    reserve_start = np.concatenate([[0.0], reserve[:-1]])
    reserve_kept = (1.0 - q) * (1.0 - w) * reserve  # released for those who lapse or die
    interest_earned = (reserve_start + prem - commission - expenses) * i
    profit = (
        (reserve_start + prem - commission - expenses) + interest_earned - claims - reserve_kept
    )
    return pd.DataFrame(
        {
            "policy_year": t + 1, "in_force_start": in_force, "premium": prem,
            "commission": commission, "expenses": expenses, "claims": claims,
            "interest": interest_earned, "reserve_end": reserve, "reserve_kept": reserve_kept,
            "profit_per_policy": profit, "profit_issued": profit * in_force,
            "premium_issued": prem * in_force,
        }
    )  # fmt: skip


def irr(cash: np.ndarray, near: float = 0.10) -> float:
    """Internal rate of return of annual cash flows at times 0, 1, 2...: a rate where the present
    value is zero. Returns NaN when there is no sign change (no meaningful rate).

    A profit stream can change sign more than once (a small loss in the last year, say), so the
    present value is scanned over a grid of rates and every sign change refined by bisection;
    when there are several roots the one nearest ``near`` is reported."""
    c = np.asarray(cash, dtype=float)
    if not (c.min() < 0 < c.max()):
        return float("nan")
    t = np.arange(len(c))

    def pv(rate: float) -> float:
        return float((c * (1.0 + rate) ** -t).sum())

    grid = np.linspace(-0.9, 3.0, 1561)
    values = np.array([pv(r) for r in grid])
    flips = np.flatnonzero(np.sign(values[:-1]) * np.sign(values[1:]) < 0)
    roots = []
    for k in flips:
        lo, hi, f_lo = grid[k], grid[k + 1], values[k]
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            f_mid = pv(mid)
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        roots.append(0.5 * (lo + hi))
    return float(min(roots, key=lambda r: abs(r - near))) if roots else float("nan")


def summarise(test: pd.DataFrame, hurdle: float) -> dict[str, float]:
    """NPV at the hurdle, IRR, profit margin (NPV over the PV of premiums) and the payback year.

    The first profit arrives at the end of policy year 1, so cash-flow times are 1, 2, ...;
    the IRR is computed on the profit vector shifted to start at time 0, which does not change
    its zero."""
    cash = test["profit_issued"].to_numpy()
    t = np.arange(1, len(cash) + 1)
    disc = (1.0 + hurdle) ** -t
    npv = float((cash * disc).sum())
    pv_premium = float((test["premium_issued"].to_numpy() * (1.0 + hurdle) ** -(t - 1)).sum())
    cumulative = np.cumsum(cash * disc)
    paid_back = np.flatnonzero(cumulative >= 0)
    payback = int(paid_back[paid_back > 0][0] + 1) if (paid_back > 0).any() else 0
    # a policy that loses money in year 1 and gains later has a sign change; otherwise no IRR
    return {
        "npv": npv, "irr": irr(cash), "margin": npv / pv_premium if pv_premium else float("nan"),
        "pv_premium": pv_premium, "payback_year": payback,
        "year_1_profit": float(cash[0]), "total_profit": float(cash.sum()),
    }  # fmt: skip


def solve_premium(q_best: np.ndarray, a: Assumptions, target_irr: float | None = None,
                  q_valuation: np.ndarray | None = None, **kwargs) -> float:  # fmt: skip
    """The smallest annual premium whose profit test earns ``target_irr`` (default the hurdle).

    The NPV at the target rate rises with the premium, so bisection finds it."""
    r = a.hurdle if target_irr is None else target_irr

    def npv(prem: float) -> float:
        return summarise(profit_test(q_best, prem, a, q_valuation, **kwargs), r)["npv"]

    lo, hi = 0.0, a.sum_assured * 0.5
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if npv(mid) < 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── Mortality paths ─────────────────────────────────────────────────────────


def q_path(q_by_age: np.ndarray, issue_age: int, n: int, multiplier: np.ndarray | None = None
           ) -> np.ndarray:  # fmt: skip
    """Probabilities of death over the ``n`` years of a policy from a table by attained age,
    optionally times a multiplier per policy year (a select factor, a stress, an improvement)."""
    ages = np.clip(issue_age + np.arange(n), 0, len(q_by_age) - 1)
    q = np.asarray(q_by_age, dtype=float)[ages]
    if multiplier is not None:
        q = q * np.asarray(multiplier, dtype=float)
    return np.clip(q, 0.0, 0.999999)


def scenario_grid(q_best: np.ndarray, base: Assumptions, premium: float) -> pd.DataFrame:
    """The sensitivity of one priced policy to each assumption, one at a time.

    Each row reports the IRR and NPV when a single assumption moves, against the base case: the
    data behind a tornado chart. Mortality moves are multiplicative on every year."""
    cases = {
        "base case": {},
        "mortality +20%": {"q": 1.2}, "mortality -20%": {"q": 0.8},
        "mortality +10%": {"q": 1.1}, "mortality -10%": {"q": 0.9},
        "lapse +25%": {"lapse_scale": 1.25}, "lapse -25%": {"lapse_scale": 0.75},
        "investment return -1 pt": {"interest": base.investment_return - 0.01},
        "investment return +1 pt": {"interest": base.investment_return + 0.01},
        "expenses +10%": {"expense_scale": 1.1}, "expenses -10%": {"expense_scale": 0.9},
        "pandemic: year 2 mortality x1.5": {"shock": {2: 1.5}},
        "pandemic: year 2 mortality x2": {"shock": {2: 2.0}},
    }  # fmt: skip
    rows = []
    for name, spec in cases.items():
        spec = dict(spec)
        qb = np.clip(q_best * spec.pop("q", 1.0), 0, 0.999999)
        test = profit_test(qb, premium, base, q_valuation=q_best, **spec)
        rows.append({"scenario": name, **summarise(test, base.hurdle)})
    out = pd.DataFrame(rows)
    ref = out.iloc[0]
    out["irr_change"] = out["irr"] - ref["irr"]
    out["npv_change"] = out["npv"] - ref["npv"]
    return out


def with_assumptions(a: Assumptions, **changes) -> Assumptions:
    return replace(a, **changes)


# ── Best-estimate liability ─────────────────────────────────────────────────


def best_estimate_liability(
    q: np.ndarray, premium: float, a: Assumptions, lapse_scale=1.0
) -> np.ndarray:
    """The present value of all future outgo less premiums, at the start of each policy year
    (before that year's premium), for a policy still in force, at the investment return.

    This is the reserve a best-estimate valuation holds. Unlike the statutory net premium reserve
    it uses the real expenses, the real lapses and the real return, so it can be negative: the
    product is expected to earn more in future premiums than it will cost."""
    n = len(q)
    w = a.lapse_path(n, lapse_scale)
    t = np.arange(n)
    commission = premium * np.where(t == 0, a.commission_first, a.commission_renewal)
    expenses = a.maintenance * (1.0 + a.expense_inflation) ** t + np.where(
        t == 0, a.acquisition_pct * premium + a.acquisition_fixed, 0.0
    )
    v = 1.0 / (1.0 + a.investment_return)
    bel = np.zeros(n + 1)
    for k in range(n - 1, -1, -1):
        outgo = commission[k] + expenses[k] - premium
        bel[k] = outgo + v * (
            q[k] * (a.sum_assured + a.claim_expense) + (1 - q[k]) * (1 - w[k]) * bel[k + 1]
        )
    return bel[:n]


def mortality_cushion(q: np.ndarray, premium: float, a: Assumptions, q_valuation=None) -> float:
    """The multiplier on best-estimate mortality at which the policy just breaks even over its
    life (undiscounted profit zero): how heavy mortality can become before the product loses money.
    Above 1 means there is a cushion; it is found by bisection."""

    qv = q if q_valuation is None else q_valuation

    def total(mult: float) -> float:
        qb = np.clip(q * mult, 0.0, 0.999999)
        return float(profit_test(qb, premium, a, q_valuation=qv)["profit_issued"].sum())

    lo, hi = 0.2, 6.0
    if total(lo) < 0:
        return float("nan")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if total(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── Warehouse tables ────────────────────────────────────────────────────────

ISSUE_AGES = (25, 30, 35, 40, 45, 50, 55, 60)
TERMS = (10, 20)
BASES = {
    "cnsf": "CNSF 2013 (the pricing basis)",
    "cnsf_p995": "CNSF 2013, 99.5th percentile variant",
    "experience": "Company experience (the synthetic book of step 8)",
    "population": "Mexican population 2023",
    "improving": "CNSF 2013 with projected improvement",
}
DESCRIPTIONS = {
    "pricing_premiums": (
        "Net and gross annual premium per 1,000 of a level term product by sex, issue age and "
        "term, the gross premium solved for a 10% return on the CNSF 2013 basis"
    ),
    "pricing_adequacy": (
        "What the CNSF-priced premium earns if mortality follows another basis: IRR, NPV margin "
        "and the mortality cushion, by sex, issue age and basis"
    ),
    "pricing_profit_test": (
        "Year-by-year cash flows of the reference policy (man, 40, 20-year term): premium, "
        "commission, expenses, claims, interest, reserve, profit"
    ),
    "pricing_sensitivity": (
        "Sensitivity of the reference policies' return to mortality, lapses, interest, expenses "
        "and a one-year pandemic shock, one assumption at a time"
    ),
    "pricing_reserves": (
        "Statutory net premium reserve against best-estimate liability by policy year for the "
        "reference policies"
    ),
}


def _bases(con) -> dict | None:
    """The mortality bases as callables ``(sex, issue_age, n) -> q per policy year``."""
    from mortality import experience as ex

    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "cnsf_rates" not in names or "graduated_qx" not in names:
        return None
    cnsf = pd.read_sql(
        "SELECT variant, age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' ORDER BY age", con
    )
    base = (
        cnsf[cnsf["variant"] == "base"]
        .set_index("age")["qx"]
        .reindex(range(111))
        .ffill()
        .to_numpy()
    )
    heavy = (
        cnsf[cnsf["variant"] == "p99.5"]
        .set_index("age")["qx"]
        .reindex(range(111))
        .ffill()
        .to_numpy()
    )
    pop = {
        s: pd.read_sql(
            f"SELECT age, qx FROM graduated_qx WHERE year = 2023 AND sex = '{s}' ORDER BY age", con
        )
        .set_index("age")["qx"]
        .reindex(range(111))
        .ffill()
        .to_numpy()
        for s in ("M", "F")
    }
    out = {
        "cnsf": lambda s, x, n: q_path(base, x, n),
        "cnsf_p995": lambda s, x, n: q_path(heavy, x, n),
        "population": lambda s, x, n: q_path(pop[s], x, n),
    }
    if "experience_basis" in names:
        table = pd.read_sql(
            "SELECT sex, age, duration_group, multiplier FROM experience_basis", con
        )
        look = ex._multiplier_lookup(table.assign(multiplier_upper=table["multiplier"]))

        def experience(s, x, n):
            dur = 1 + np.arange(n)
            label = np.where(dur <= 5, dur.astype(str), np.where(dur <= 10, "6-10", "11+"))
            ages = np.clip(x + np.arange(n), 0, 110)
            m = np.ones(n)
            for lab in ex.DURATION_LABELS:
                key = (s, lab)
                if key in look:
                    m = np.where(label == lab, look[key][ages], m)
            return q_path(base, x, n, m)

        out["experience"] = experience
    if "projected_qx" in names:
        proj = pd.read_sql("SELECT year, sex, age, qx FROM projected_qx", con)
        cube = {
            s: p.pivot_table(index="year", columns="age", values="qx")
            for s, p in proj.groupby("sex")
        }

        def improving(s, x, n):
            ages = np.clip(x + np.arange(n), 0, 110)
            years = np.minimum(2025 + np.arange(n), int(cube[s].index.max()))
            factor = (
                cube[s].to_numpy()[years - int(cube[s].index.min()), ages]
                / cube[s].to_numpy()[0, ages]
            )
            return q_path(base, x, n, factor)

        out["improving"] = improving
    return out


def build_tables(con, assumptions: Assumptions | None = None) -> list[tuple[str, str]]:
    """Price the reference product on the warehouse's tables and store the results."""
    a = assumptions or Assumptions()
    bases = _bases(con)
    if bases is None:
        return []
    rows_prem, rows_adequacy, rows_pt, rows_sens, rows_res = [], [], [], [], []
    for sex in ("M", "F"):
        for term in TERMS:
            for age in ISSUE_AGES:
                q = bases["cnsf"](sex, age, term)
                prem = solve_premium(q, a)
                test = profit_test(q, prem, a)
                s = summarise(test, a.hurdle)
                net = net_premium(q, a.valuation_interest, a.sum_assured)
                rows_prem.append(
                    {"sex": sex, "issue_age": age, "term": term,
                     "net_premium_per_1000": 1000 * net / a.sum_assured,
                     "gross_premium_per_1000": 1000 * prem / a.sum_assured, "gross_premium": prem,
                     "loading_over_net": prem / net - 1.0, "irr": s["irr"], "npv": s["npv"],
                     "year_1_profit": s["year_1_profit"], "payback_year": s["payback_year"]}
                )  # fmt: skip
                if term == 20:
                    for key, make in bases.items():
                        qb = make(sex, age, term)
                        t = profit_test(qb, prem, a, q_valuation=q)
                        r = summarise(t, a.hurdle)
                        rows_adequacy.append(
                            {"sex": sex, "issue_age": age, "basis": key, "basis_label": BASES[key],
                             "irr": r["irr"], "npv": r["npv"], "margin": r["margin"],
                             "total_profit": r["total_profit"],
                             "mortality_cushion": mortality_cushion(qb, prem, a, q_valuation=q)}
                        )  # fmt: skip
    for sex in ("M", "F"):
        q = bases["cnsf"](sex, 40, 20)
        prem = solve_premium(q, a)
        test = profit_test(q, prem, a)
        rows_pt.append(test.assign(sex=sex, issue_age=40, term=20))
        sens = scenario_grid(q, a, prem)
        rows_sens.append(sens.assign(sex=sex, issue_age=40, term=20))
        bel = best_estimate_liability(q, prem, a)
        res = pd.DataFrame(
            {"policy_year": np.arange(1, 21), "statutory_reserve_end": test["reserve_end"],
             # the liability at the start of the next year, before its premium, is the liability
             # at the end of this one: the date the statutory reserve is held at
             "best_estimate_end": np.append(bel[1:], 0.0), "sex": sex, "issue_age": 40, "term": 20}
        )  # fmt: skip
        rows_res.append(res)
    frames = {
        "pricing_premiums": pd.DataFrame(rows_prem),
        "pricing_adequacy": pd.DataFrame(rows_adequacy),
        "pricing_profit_test": pd.concat(rows_pt, ignore_index=True),
        "pricing_sensitivity": pd.concat(rows_sens, ignore_index=True),
        "pricing_reserves": pd.concat(rows_res, ignore_index=True),
    }
    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
