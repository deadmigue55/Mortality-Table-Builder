"""Reinsurance: what a cedant buys, what it costs, and what a reinsurer sees.

Built on the synthetic in-force block of step 8 and the annuity block of step 9c, so every number
is illustrative of the method, not of a real treaty. The pieces:

* **Concentration.** How much of the sum at risk, and of the expected claims, sits in large
  policies.
* **Aggregate claims.** The next twelve months' claims simulated with three sources of
  uncertainty, added one at a time: random fluctuation (who dies), the level of mortality
  (a lognormal factor) and a pandemic (the 2021 excess profile, with an annual probability).
* **Structures.** Quota share, surplus, per-life excess of loss and stop loss, applied to the same
  simulated years: retained claims, capital relief (99.5% value-at-risk over the mean), the cost of
  the cover and the price of the capital it relieves. Proportional treaties are priced from a
  premium proxy and a ceding commission; non-proportional ones on the reinsurer's cost of capital.
* **Retention.** The retention of a per-life excess of loss swept from small to large, against the
  quota share line: where the cover stops being worth it.
* **Experience rating.** A yearly renewable term treaty rated by cedant segment from the
  experience study, with credibility that allows for the variability of claim sizes.
* **Longevity swap.** The annuity block's reserve under uncertain improvement and a finite pool,
  and the fee a reinsurer needs to take the risk.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mortality import stress

# ── Assumptions ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Terms:
    """Market assumptions of the reinsurance analysis (all illustrative)."""

    sims: int = 10_000
    seed: int = 2026
    level_sigma: float = 0.05  # standard deviation of the log of the mortality level
    pandemic_probability: float = 1 / 30  # chance a year carries a pandemic like 2021
    pandemic_dampening: float = 0.5  # insureds die at half the population's excess
    reinsurer_coc: float = 0.06  # return a reinsurer asks on its risk capital
    cedant_coc: float = 0.10  # what capital costs the cedant
    expense_margin: float = 0.01  # reinsurer expenses as a share of expected recoveries
    loss_ratio: float = 0.65  # expected claims over original premium
    ceding_commission: float = 0.30  # paid by the reinsurer on proportional premium
    quantile: float = 0.995  # the capital level


DEFAULT_TERMS = Terms()
SWAP_GRID = np.arange(-0.5, 3.01, 0.25)

# ── Concentration ───────────────────────────────────────────────────────────

BAND_EDGES = (0.0, 250_000.0, 500_000.0, 1_000_000.0, 2_000_000.0, 5_000_000.0, np.inf)
BAND_LABELS = ("<250k", "250k-500k", "500k-1M", "1M-2M", "2M-5M", "5M+")


def concentration(inforce: pd.DataFrame, q: np.ndarray) -> pd.DataFrame:
    """Policies, sum at risk and expected claims by sum-assured band."""
    sa = inforce["sum_assured"].to_numpy(float)
    band = pd.cut(sa, BAND_EDGES, labels=BAND_LABELS, right=False)
    frame = pd.DataFrame({"band": band, "sum_assured": sa, "expected": sa * q})
    out = frame.groupby("band", observed=False).agg(
        policies=("sum_assured", "size"),
        sum_at_risk=("sum_assured", "sum"),
        expected_claims=("expected", "sum"),
    )
    out["share_of_policies"] = out["policies"] / out["policies"].sum()
    out["share_of_sum_at_risk"] = out["sum_at_risk"] / out["sum_at_risk"].sum()
    out["share_of_expected_claims"] = out["expected_claims"] / out["expected_claims"].sum()
    return out.reset_index()


# ── Aggregate claims ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Simulation:
    """Simulated years of claims: each death is one amount, tagged with its simulated year."""

    year: np.ndarray  # simulated year of each claim
    amount: np.ndarray  # sum assured of each claim
    n: int  # number of simulated years
    pandemic: np.ndarray  # whether each simulated year carried a pandemic

    @property
    def totals(self) -> np.ndarray:
        return np.bincount(self.year, weights=self.amount, minlength=self.n)


def _draw(sa, cdf, lam, rng, offset):
    """Claims of the simulated years with mean ``lam`` deaths: Poisson counts, then lives chosen
    in proportion to their probability of dying."""
    counts = rng.poisson(lam)
    year = np.repeat(np.arange(len(lam)) + offset, counts)
    idx = np.minimum(np.searchsorted(cdf, rng.random(year.size), side="right"), len(sa) - 1)
    return year, sa[idx]


def simulate_claims(
    sa: np.ndarray,
    q: np.ndarray,
    q_pandemic: np.ndarray,
    terms: Terms = DEFAULT_TERMS,
    level: bool = True,
    pandemic: bool = True,
) -> Simulation:
    """Simulate ``terms.sims`` years of claims on the block.

    Deaths in a year are Poisson with the expected number; which lives die is drawn in proportion
    to their probability. The level of mortality gets a lognormal factor of mean one; a pandemic
    year (probability ``pandemic_probability``) draws from ``q_pandemic`` instead of ``q``. A life
    could in theory die twice in one simulated year: with probabilities this small the effect
    is negligible."""
    rng = np.random.default_rng(terms.seed)
    n = terms.sims
    s = terms.level_sigma
    factor = np.exp(s * rng.standard_normal(n) - 0.5 * s * s) if level else np.ones(n)
    event = (rng.random(n) < terms.pandemic_probability) if pandemic else np.zeros(n, dtype=bool)
    cdf_normal = np.cumsum(q) / q.sum()
    cdf_event = np.cumsum(q_pandemic) / q_pandemic.sum()
    years, amounts = [], []
    for mask, cdf, total in ((~event, cdf_normal, q.sum()), (event, cdf_event, q_pandemic.sum())):
        ids = np.flatnonzero(mask)
        if not len(ids):
            continue
        y, a = _draw(sa, cdf, factor[ids] * total, rng, 0)
        years.append(ids[y])
        amounts.append(a)
    return Simulation(
        np.concatenate(years), np.concatenate(amounts), n, event
    )  # fmt: skip


def distribution(totals: np.ndarray, quantile: float = 0.995) -> dict[str, float]:
    """Mean, spread and tail of annual claims; ``capital`` is the tail value over the mean."""
    mean = float(totals.mean())
    var = float(np.quantile(totals, quantile))
    tail = totals[totals >= np.quantile(totals, 0.99)]
    return {
        "mean": mean, "sd": float(totals.std()),
        "cv": float(totals.std() / mean) if mean else float("nan"),
        "var_95": float(np.quantile(totals, 0.95)), "var_99": float(np.quantile(totals, 0.99)),
        "var_995": var, "tvar_99": float(tail.mean()), "capital": var - mean,
    }  # fmt: skip


def aggregate_table(
    sa: np.ndarray, q: np.ndarray, q_pandemic: np.ndarray, terms: Terms = DEFAULT_TERMS
) -> pd.DataFrame:
    """The distribution of annual claims with each source of uncertainty added in turn."""
    rows = []
    for label, level, pandemic in (
        ("random fluctuation only", False, False),
        ("+ uncertain mortality level", True, False),
        ("+ pandemic risk", True, True),
    ):
        sim = simulate_claims(sa, q, q_pandemic, terms, level, pandemic)
        rows.append({"source": label, **distribution(sim.totals, terms.quantile)})
    return pd.DataFrame(rows)


# ── Treaty structures ───────────────────────────────────────────────────────


def quota_share(sim: Simulation, share: float) -> np.ndarray:
    """Recoveries of a quota share: the same proportion of every claim."""
    return share * sim.totals


def surplus(sim: Simulation, retention: float, lines: float) -> np.ndarray:
    """Recoveries of a surplus treaty: each policy cedes the part of its sum assured above the
    retention, up to ``lines`` times the retention, and the reinsurer pays that share of any
    claim on it."""
    ceded = np.clip(sim.amount - retention, 0.0, lines * retention)
    return np.bincount(sim.year, weights=ceded, minlength=sim.n)


def per_life_xl(sim: Simulation, retention: float, limit: float = np.inf) -> np.ndarray:
    """Recoveries of an excess of loss per life: claims above the retention, up to the limit."""
    ceded = np.clip(sim.amount - retention, 0.0, limit)
    return np.bincount(sim.year, weights=ceded, minlength=sim.n)


def stop_loss(totals: np.ndarray, attachment: float, limit: float) -> np.ndarray:
    """Recoveries of an aggregate cover: annual claims above the attachment, up to the limit."""
    return np.clip(totals - attachment, 0.0, limit)


def non_proportional_premium(recoveries: np.ndarray, terms: Terms) -> float:
    """The reinsurer's price of a cover: expected recoveries and expenses, plus its cost of
    capital on the tail of the recoveries (99.5% value-at-risk over the mean)."""
    mean = float(recoveries.mean())
    capital = max(float(np.quantile(recoveries, terms.quantile)) - mean, 0.0)
    return mean * (1.0 + terms.expense_margin) + terms.reinsurer_coc * capital


def proportional_premium(recoveries: np.ndarray, terms: Terms) -> float:
    """Premium net of commission of a proportional treaty: the ceded share of original premium
    (expected claims over the loss ratio), less the ceding commission."""
    return float(recoveries.mean()) / terms.loss_ratio * (1.0 - terms.ceding_commission)


def evaluate(
    name: str, family: str, sim: Simulation, recoveries: np.ndarray, premium: float, terms: Terms
) -> dict:
    """What a cover does to the cedant's annual claims, and what it costs."""
    gross = distribution(sim.totals, terms.quantile)
    net = distribution(sim.totals - recoveries, terms.quantile)
    relief = gross["capital"] - net["capital"]
    cost = premium - float(recoveries.mean())
    return {
        "structure": name, "family": family,
        "expected_recoveries": float(recoveries.mean()), "premium": premium, "cost": cost,
        "retained_mean": net["mean"], "retained_sd": net["sd"], "retained_var_995": net["var_995"],
        "sd_reduction": 1.0 - net["sd"] / gross["sd"],
        "capital": net["capital"], "capital_relief": relief,
        "relief_share": relief / gross["capital"] if gross["capital"] else np.nan,
        "price_of_relief": cost / relief if relief > 1e-9 else np.nan,
        "worth_buying": bool(relief > 1e-9 and cost / relief < terms.cedant_coc),
    }  # fmt: skip


def structure_table(sim: Simulation, terms: Terms = DEFAULT_TERMS) -> pd.DataFrame:
    """The standard covers on the simulated years, each evaluated alone, and one combination."""
    totals = sim.totals
    mean = float(totals.mean())
    rows = [evaluate("No reinsurance", "none", sim, np.zeros(sim.n), 0.0, terms)]

    def add(name: str, family: str, recoveries: np.ndarray, premium: float | None = None) -> None:
        if premium is None:
            price = proportional_premium if family == "proportional" else non_proportional_premium
            premium = price(recoveries, terms)
        rows.append(evaluate(name, family, sim, recoveries, premium, terms))

    for share in (0.2, 0.4):
        add(f"Quota share {share:.0%}", "proportional", quota_share(sim, share))
    for retention in (500_000.0, 1_000_000.0, 2_000_000.0):
        add(f"Surplus, retention {retention / 1e6:g}M, 9 lines", "proportional",
            surplus(sim, retention, 9))  # fmt: skip
    for retention in (1_000_000.0, 2_000_000.0):
        add(f"Per-life XL {8 * retention / 1e6:g}M xs {retention / 1e6:g}M", "excess of loss",
            per_life_xl(sim, retention, 8 * retention))  # fmt: skip
    for attach in (1.15, 1.25):
        add(f"Stop loss, 100% xs {attach:.0%} of expected claims", "excess of loss",
            stop_loss(totals, attach * mean, mean))  # fmt: skip
    # a per-life cover, then a stop loss on what is left
    xl = per_life_xl(sim, 1_000_000.0, 8_000_000.0)
    left = totals - xl
    sl = stop_loss(left, 1.25 * left.mean(), left.mean())
    premium = non_proportional_premium(xl, terms) + non_proportional_premium(sl, terms)
    add("Per-life XL 8M xs 1M + stop loss on what is left", "combined", xl + sl, premium)
    return pd.DataFrame(rows)


def retention_frontier(
    sim: Simulation, terms: Terms = DEFAULT_TERMS, points: int = 25
) -> pd.DataFrame:
    """Cost against capital relief for a per-life excess of loss (unlimited) across retentions,
    and for a quota share across shares: the frontier a cedant chooses its retention on."""
    rows = []
    for retention in np.geomspace(100_000, 10_000_000, points):
        r = per_life_xl(sim, retention)
        e = evaluate("xl", "excess of loss", sim, r, non_proportional_premium(r, terms), terms)
        rows.append({"family": "excess of loss", "parameter": float(retention),
                     "cost": e["cost"], "capital_relief": e["capital_relief"],
                     "expected_recoveries": e["expected_recoveries"],
                     "sd_reduction": e["sd_reduction"]})  # fmt: skip
    for share in np.linspace(0.0, 1.0, 11):
        r = quota_share(sim, share)
        e = evaluate("qs", "proportional", sim, r, proportional_premium(r, terms), terms)
        rows.append({"family": "quota share", "parameter": float(share),
                     "cost": e["cost"], "capital_relief": e["capital_relief"],
                     "expected_recoveries": e["expected_recoveries"],
                     "sd_reduction": e["sd_reduction"]})  # fmt: skip
    return pd.DataFrame(rows)


# ── Experience rating of a yearly renewable term treaty ─────────────────────


def claim_size_cv2(deaths, death_amount, death_amount_sq) -> np.ndarray:
    """Squared coefficient of variation of the claim size, from the sums of claims and of their
    squares: the factor by which amounts need more experience than counts to be credible."""
    n = np.maximum(np.asarray(deaths, dtype=float), 1.0)
    mean = np.asarray(death_amount, dtype=float) / n
    second = np.asarray(death_amount_sq, dtype=float) / n
    return np.maximum(second / np.maximum(mean**2, 1e-12) - 1.0, 0.0)


def yrt_rating(ae: pd.DataFrame, loading: float = 0.15, full_deaths: float = 1082.0):
    """Experience-rated YRT rate by cedant segment.

    ``ae`` is the experience study's one-way table (``experience_ae``) with exposure, expected and
    actual claim amounts. The manual rate is the expected cost per 1,000 of sum at risk loaded for
    the reinsurer's expenses and margin; the experience factor is the amount A/E weighted with
    credibility ``Z = min(1, sqrt(deaths / (full_deaths * (1 + cv2))))``: the full-credibility
    standard is raised by the variability of claim sizes."""
    df = ae.copy()
    cv2 = claim_size_cv2(df["deaths"], df["death_amount"], df["death_amount_sq"])
    df["claim_size_cv2"] = cv2
    df["credibility"] = np.minimum(1.0, np.sqrt(df["deaths"] / (full_deaths * (1.0 + cv2))))
    df["ae_amount"] = df["death_amount"] / df["expected_amount"]
    df["experience_factor"] = df["credibility"] * df["ae_amount"] + (1.0 - df["credibility"])
    df["manual_rate_per_1000"] = (
        1000.0 * df["expected_amount"] / df["exposure_amount"] * (1 + loading)
    )
    df["rated_rate_per_1000"] = df["manual_rate_per_1000"] * df["experience_factor"]
    df["rate_change"] = df["experience_factor"] - 1.0
    df["burning_cost_per_1000"] = 1000.0 * df["death_amount"] / df["exposure_amount"]
    df["loss_ratio_at_manual"] = df["burning_cost_per_1000"] / df["manual_rate_per_1000"]
    return df


# ── Longevity swap ──────────────────────────────────────────────────────────


def per_life_pv_variance(q_paths: np.ndarray, interest: float) -> tuple[np.ndarray, np.ndarray]:
    """Mean and variance of the present value of an annuity-due on a single life, from the paths
    of probabilities of death (first column the year about to start)."""
    n, horizon = q_paths.shape
    surv = np.concatenate([np.ones((n, 1)), np.cumprod(1.0 - q_paths[:, :-1], axis=1)], axis=1)
    p_death_in = surv * q_paths  # alive at the start of year j and dying in it
    v = 1.0 / (1.0 + interest)
    pv_if_dying_in = (1.0 - v ** (np.arange(horizon) + 1.0)) / (1.0 - v)  # payments at 0..j
    mean = (p_death_in * pv_if_dying_in).sum(axis=1)
    second = (p_death_in * pv_if_dying_in**2).sum(axis=1)
    return mean, second - mean**2


def reserve_run_off(block: stress.AnnuityBlock, make_central: dict, interest: float):
    """Present value at time 0 of the expected reserve at each future date, summed: the
    "reserve-years" a capital charge applies to. For a life on a cohort path, the reserve at
    time t is the pensions still to come, in expectation, valued at t."""
    ages = np.arange(block.youngest, block.oldest + 1)
    v = 1.0 / (1.0 + interest)
    total = 0.0
    for sex, share in (("M", block.male_share), ("F", 1.0 - block.male_share)):
        make = make_central[sex]
        q = make(ages)
        surv = np.concatenate(
            [np.ones((len(ages), 1)), np.cumprod(1.0 - q[:, :-1], axis=1)], axis=1
        )
        j = np.arange(q.shape[1])
        reserve_years = (surv * v**j * (j + 1)).sum(axis=1)
        w = block.weights(stress._first_year(make))
        total += float(block.lives * share * block.pension * (w * reserve_years).sum())
    return total


def longevity_swap(
    block: stress.AnnuityBlock,
    cube: dict[str, np.ndarray],
    terms: Terms = DEFAULT_TERMS,
    scale_mean: float = 1.0,
    scale_sd: float = 0.5,
    draws: int = 100_000,
    grid: np.ndarray = SWAP_GRID,
) -> tuple[dict, pd.DataFrame]:
    """Price a longevity swap on the annuity block.

    The cedant pays a fixed schedule of pensions on the swap basis and the reinsurer pays the
    pensions actually due. Two risks sit with the reinsurer: **trend**, the improvement of
    mortality (a multiple ``s`` of the central log improvement, normal around 1 with standard
    deviation 0.5, so that ``none`` and ``double`` are about the 2-sigma range, truncated to
    -0.5 to 3), and **pool risk**, the chance variation of a finite block. The reserve is valued
    for each ``s`` on a grid and interpolated. The fee is the cost of capital on the risk capital
    (99.5% value-at-risk over the mean), held in proportion to the run-off of the reserve.

    Returns the summary and the distribution of the reserve (quantiles)."""
    rng = np.random.default_rng(terms.seed)
    interest = block.interest

    def maker(scale):
        return {s: (lambda ages, s=s, scale=scale: stress.cohort_q_paths(cube[s], ages, scale))
                for s in cube}  # fmt: skip

    reserves = np.array(
        [stress.annuity_reserves(block, maker(float(s)))["reserve_T"] for s in grid]
    )
    central = stress.annuity_reserves(block, maker(1.0))["reserve_T"]
    s_draw = np.clip(rng.normal(scale_mean, scale_sd, draws), grid[0], grid[-1])
    trend_reserve = np.interp(s_draw, grid, reserves)
    # pool risk: the variance of the present value of pensions of the block's own lives
    ages = np.arange(block.youngest, block.oldest + 1)
    central_make = maker(1.0)
    variance = 0.0
    for sex, share in (("M", block.male_share), ("F", 1.0 - block.male_share)):
        make = central_make[sex]
        _, var = per_life_pv_variance(make(ages), interest)
        w = block.weights(stress._first_year(make))
        n = block.lives * share
        variance += n * block.pension**2 * float((w * var).sum())
    pool_sd = float(np.sqrt(variance))
    total = trend_reserve + rng.normal(0.0, pool_sd, draws)
    stats = distribution(total, terms.quantile)
    trend_only = distribution(trend_reserve, terms.quantile)
    run_off = reserve_run_off(block, central_make, interest)
    capital_ratio = stats["capital"] / central
    fee = terms.reinsurer_coc * capital_ratio * run_off
    summary = {
        "central_reserve": central, "mean_reserve": stats["mean"], "sd_reserve": stats["sd"],
        "pool_sd": pool_sd, "trend_capital": trend_only["capital"],
        "capital": stats["capital"], "capital_ratio": capital_ratio,
        "reserve_years": run_off / central, "fee_pv": fee, "fee_share_of_reserve": fee / central,
        "fee_bps_per_year": 1e4 * terms.reinsurer_coc * capital_ratio,
        "pool_share_of_variance": pool_sd**2 / (pool_sd**2 + float(trend_reserve.var())),
    }  # fmt: skip
    levels = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.995)
    dist = pd.DataFrame(
        {"level": levels, "reserve": [float(np.quantile(total, x)) for x in levels]}
    )
    dist["change_vs_central"] = dist["reserve"] / central - 1.0
    return summary, dist


# ── Warehouse tables ────────────────────────────────────────────────────────

DESCRIPTIONS = {
    "reinsurance_concentration": (
        "Policies, sum at risk and expected claims of the in-force block by sum-assured band: "
        "how concentrated the large-claim risk is"
    ),
    "reinsurance_aggregate": (
        "Distribution of next year's claims on the in-force block with each source of "
        "uncertainty added in turn: random fluctuation, mortality level, pandemic"
    ),
    "reinsurance_structures": (
        "Quota share, surplus, per-life excess of loss and stop loss on the simulated years: "
        "retained claims, capital relief, cost of the cover and price of the capital relieved"
    ),
    "reinsurance_frontier": (
        "Cost against capital relief for a per-life excess of loss across retentions and for a "
        "quota share across shares"
    ),
    "reinsurance_yrt_rating": (
        "Experience rating of a yearly renewable term treaty by cedant segment: claim-size "
        "variability, credibility, experience factor and rated rate per 1,000"
    ),
    "reinsurance_longevity_swap": (
        "Longevity swap on the illustrative annuity block: reserve under uncertain improvement "
        "and a finite pool, risk capital and the fee a reinsurer needs"
    ),
    "reinsurance_longevity_distribution": (
        "Quantiles of the annuity block's reserve under trend and pool uncertainty"
    ),
}


def build_tables(con, terms: Terms = DEFAULT_TERMS) -> list[tuple[str, str]]:
    """Run the reinsurance analysis on the synthetic block and the annuity block."""
    from mortality import experience as ex
    from mortality import portfolio as pf
    from mortality.config import get_paths

    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    needed = {"cnsf_rates", "excess_mortality", "projected_qx", "experience_basis", "experience_ae"}
    if not needed <= names:
        return []
    inputs = ex.warehouse_inputs(con)
    if inputs is None:
        return []
    q_cnsf, state_smr, weights = inputs
    portfolio = ex.load_or_generate_portfolio(get_paths(), q_cnsf, state_smr, weights)
    clean = ex.validate_extract(portfolio.policies, pf.STUDY_END, pf.EXTRACT_DATE)[0]
    inforce = ex.inforce_block(clean, pf.STUDY_END)
    base = q_cnsf.reindex(range(stress.MAX_AGE + 1)).ffill().to_numpy()
    table = pd.read_sql("SELECT sex, age, duration_group, multiplier FROM experience_basis", con)
    q = stress.first_year_q(inforce, base, ex._multiplier_lookup(table))
    excess = pd.read_sql("SELECT * FROM excess_mortality", con)
    year = 2021
    scores = stress.pscore_by_age(excess, year)
    sa = inforce["sum_assured"].to_numpy(float)
    age = np.clip(inforce["attained_age"].to_numpy(int), 0, stress.MAX_AGE)
    p = np.zeros(len(age))
    for s, arr in scores.items():
        sel = inforce["sex"].to_numpy() == s
        p[sel] = arr[age[sel]]
    q_pandemic = np.minimum(q * (1.0 + terms.pandemic_dampening * p), 1.0)

    sim = simulate_claims(sa, q, q_pandemic, terms)
    ae = pd.read_sql(
        "SELECT * FROM experience_ae WHERE years = 'all_years' AND dimension IN ('channel',"
        " 'uw_class', 'sex')", con
    )  # fmt: skip
    proj = pd.read_sql("SELECT year, sex, age, qx FROM projected_qx", con)
    cube = {
        s: part.pivot_table(index="year", columns="age", values="qx").sort_index().to_numpy()
        for s, part in proj.groupby("sex")
    }
    swap, swap_dist = longevity_swap(stress.AnnuityBlock(), cube, terms)
    frames = {
        "reinsurance_concentration": concentration(inforce, q),
        "reinsurance_aggregate": aggregate_table(sa, q, q_pandemic, terms),
        "reinsurance_structures": structure_table(sim, terms),
        "reinsurance_frontier": retention_frontier(sim, terms),
        "reinsurance_yrt_rating": yrt_rating(ae),
        "reinsurance_longevity_swap": pd.DataFrame([swap]),
        "reinsurance_longevity_distribution": swap_dist,
    }
    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
