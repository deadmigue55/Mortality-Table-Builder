"""A synthetic life-insurance portfolio with a known truth.

No insurer publishes its policy-level data, so this module builds a fictional one. Its purpose is
**method validation**: effects are planted at known sizes, a realistic administrative extract is
produced (lapses, expiries, a claims-reporting lag, data defects), and ``experience.py`` is then
judged on whether it recovers what was planted.

Every number in ``TRUTH`` is an illustrative assumption, not an estimate for any Mexican company.
What matters is the structure: the force of mortality of each policy is

    mu = mu_basis(attained age) x base x sex x age group x class x amount band x channel
         x product x select(duration, class) x state x trend(calendar year) x COVID(age, year)

and is constant inside each Lexis piece (see ``lexis.py``), so deaths are drawn from the exact
model the study assumes. The basis is the CNSF 2013 table, the usual expected basis of a
Mexican insurer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mortality import experience, lexis

STUDY_START = np.datetime64("2014-01-01")
STUDY_END = np.datetime64("2024-06-30")
EXTRACT_DATE = np.datetime64("2024-08-15")  # deaths notified after this are not in the extract

TRUTH = {
    "base": 0.88,
    "sex": {"M": 1.12, "F": 0.74},  # the CNSF table is unisex
    "age_group": {"18-29": 1.25, "30-39": 1.05, "40-49": 1.00, "50-59": 0.97, "60+": 0.92},
    "uw_class": {"PREFERRED": 0.78, "STANDARD": 1.00, "RATED": 1.55, "SIMPLIFIED": 1.38},
    "amount_band": {"<250k": 1.18, "250k-1M": 1.00, "1M-5M": 0.86, "5M+": 0.74},
    "channel": {"AGENT": 1.00, "BANK": 1.10, "DIGITAL": 1.04},
    "product": {"TERM": 1.00, "WHOLE_LIFE": 0.94, "ENDOWMENT": 0.90},
    # underwriting selection: mortality relative to ultimate in policy years 1 to 6
    "select_full": (0.50, 0.65, 0.78, 0.88, 0.95, 1.00),
    "select_simplified": (0.80, 0.88, 0.94, 0.98, 1.00, 1.00),
    "trend_per_year": -0.01,  # mortality improvement, relative to 2014
    "state_exponent": 0.5,  # state mortality relative = state SMR ** 0.5
    "covid_pass_through": 0.65,  # share of the population's excess that insured lives bear
    "covid_peak_excess": {2020: 0.75, 2021: 0.80, 2022: 0.10},  # population excess at its peak age
}

CHANNEL_CLASS_MIX = {
    "AGENT": {"PREFERRED": 0.20, "STANDARD": 0.62, "RATED": 0.08, "SIMPLIFIED": 0.10},
    "BANK": {"PREFERRED": 0.05, "STANDARD": 0.30, "RATED": 0.03, "SIMPLIFIED": 0.62},
    "DIGITAL": {"PREFERRED": 0.03, "STANDARD": 0.15, "RATED": 0.02, "SIMPLIFIED": 0.80},
}
LAPSE_BY_DURATION = (0.11, 0.08, 0.065, 0.055, 0.04)  # annual lapse rate in years 1 to 5, then 5+
LAPSE_CHANNEL = {"AGENT": 0.9, "BANK": 1.4, "DIGITAL": 1.2}
LAPSE_PRODUCT = {"TERM": 1.0, "WHOLE_LIFE": 0.7, "ENDOWMENT": 0.8}
LAG_MEDIAN_DAYS = 30.0  # median days from death to notification
LAG_SIGMA = 1.1  # a long right tail: some claims take months

COLUMNS = (
    "policy_id", "sex", "birth_date", "issue_date", "product", "term_years", "sum_assured",
    "uw_class", "channel", "state", "status", "exit_date", "notification_date",
)  # fmt: skip


@dataclass
class PortfolioSpec:
    n_policies: int = 600_000
    seed: int = 2024
    defect_rate: float = 0.004
    q_basis: np.ndarray | None = None  # annual q by age 0..110 (the CNSF 2013 base)
    state_codes: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 33))
    state_weights: tuple[float, ...] = field(default_factory=lambda: (1.0,) * 32)
    state_smr: dict[str, float] = field(default_factory=dict)


@dataclass
class Portfolio:
    policies: pd.DataFrame  # what the study sees (the extract, with its defects)
    truth: pd.DataFrame  # what really happened, per policy (hidden from the study)
    defects: pd.DataFrame  # which defects were injected where


# ── The planted force of mortality ──────────────────────────────────────────


def _lookup(values, mapping: dict, default=np.nan) -> np.ndarray:
    """``mapping[v]`` for every value: a hash join, far faster than ``np.vectorize`` on millions."""
    return pd.Series(np.asarray(values)).map(mapping).fillna(default).to_numpy(dtype=float)


def covid_excess(age, year, truth=TRUTH) -> np.ndarray:
    """Share by which the population's mortality exceeded normal at this age in this year.

    Peaks at age 60 and fades above and below, as in the project's pandemic analysis."""
    peak = _lookup(year, truth["covid_peak_excess"], 0.0)
    return peak * np.exp(-(((np.asarray(age, dtype=float) - 60.0) / 22.0) ** 2))


def true_force(
    q_basis,
    attained_age,
    duration,
    calendar_year,
    sex,
    uw_class,
    amount_band_,
    channel,
    product,
    state_smr,
    truth=TRUTH,
) -> np.ndarray:
    """The planted force of mortality of each Lexis piece (all arguments are aligned arrays)."""
    age = np.clip(np.asarray(attained_age, dtype=int), 0, len(q_basis) - 1)
    mu = -np.log1p(-np.clip(np.asarray(q_basis)[age], 0.0, 0.999999))
    uw = np.asarray(uw_class)
    mult = np.full(len(mu), truth["base"])
    mult *= _lookup(sex, truth["sex"])
    mult *= _lookup(experience.age_group(attained_age), truth["age_group"])
    mult *= _lookup(uw, truth["uw_class"])
    mult *= _lookup(amount_band_, truth["amount_band"])
    mult *= _lookup(channel, truth["channel"])
    mult *= _lookup(product, truth["product"])
    step = np.minimum(np.asarray(duration), 6) - 1
    mult *= np.where(
        uw == "SIMPLIFIED",
        np.asarray(truth["select_simplified"])[step],
        np.asarray(truth["select_full"])[step],
    )
    mult *= np.asarray(state_smr, dtype=float) ** truth["state_exponent"]
    year = np.asarray(calendar_year)
    mult *= (1.0 + truth["trend_per_year"]) ** (year - 2014)
    mult *= 1.0 + truth["covid_pass_through"] * covid_excess(attained_age, year, truth)
    return mu * mult


def lapse_force(duration, channel, product) -> np.ndarray:
    """Force of lapse of each piece."""
    step = np.minimum(np.asarray(duration), 5) - 1
    rate = np.asarray(LAPSE_BY_DURATION)[step]
    rate = rate * _lookup(channel, LAPSE_CHANNEL) * _lookup(product, LAPSE_PRODUCT)
    return -np.log1p(-np.clip(rate, 0.0, 0.95))


# ── Generation ──────────────────────────────────────────────────────────────


def _draw_attributes(n: int, rng: np.random.Generator, spec: PortfolioSpec) -> pd.DataFrame:
    sex = rng.choice(["M", "F"], n, p=[0.55, 0.45])
    channel = rng.choice(["AGENT", "BANK", "DIGITAL"], n, p=[0.55, 0.30, 0.15])
    uw = np.empty(n, dtype=object)
    for ch, mix in CHANNEL_CLASS_MIX.items():
        idx = channel == ch
        uw[idx] = rng.choice(list(mix), idx.sum(), p=list(mix.values()))
    product = rng.choice(["TERM", "WHOLE_LIFE", "ENDOWMENT"], n, p=[0.55, 0.30, 0.15])
    issue_age = np.clip(np.round(rng.normal(41.0, 11.0, n)), 18, 68).astype(int)

    term = np.full(n, np.nan)
    is_term, is_end = product == "TERM", product == "ENDOWMENT"
    term[is_term] = rng.choice([10, 15, 20, 25], is_term.sum(), p=[0.35, 0.15, 0.40, 0.10])
    term[is_end] = rng.choice([15, 20], is_end.sum(), p=[0.5, 0.5])
    has_term = ~np.isnan(term)
    term[has_term] = np.maximum(np.minimum(term[has_term], 85 - issue_age[has_term]), 5)

    median = np.where(
        product == "TERM", 900_000, np.where(product == "WHOLE_LIFE", 400_000, 300_000)
    )
    amount = np.clip(median * np.exp(rng.normal(0.0, 1.0, n)), 50_000, 60_000_000)
    amount = np.round(amount, -4)

    weights = np.asarray(spec.state_weights, dtype=float)
    state = rng.choice(spec.state_codes, n, p=weights / weights.sum())

    years = np.arange(2008, 2025)
    year_weights = np.linspace(0.5, 1.6, len(years))
    year_weights[-1] *= 0.5  # 2024 is a half year
    issue_year = rng.choice(years, n, p=year_weights / year_weights.sum())
    last_day = np.where(issue_year == 2024, 180, 365)  # to the end of June in 2024
    issue = lexis.make_date(issue_year, 1, 1) + (rng.random(n) * (last_day - 2)).astype(int).astype(
        "timedelta64[D]"
    )
    # born between issue_age and issue_age + 1 years before the issue date, so that the age last
    # birthday at issue is exactly issue_age
    y, m, d = lexis.split_date(issue)
    exactly = lexis.make_date(y - issue_age, m, d)
    birth = exactly - rng.integers(0, 364, n).astype("timedelta64[D]")
    wrong = lexis.completed_years(birth, issue) != issue_age
    birth = np.where(wrong, exactly, birth).astype("datetime64[D]")
    return pd.DataFrame(
        {
            "sex": sex, "birth_date": birth, "issue_date": issue, "product": product,
            "term_years": term, "sum_assured": amount, "uw_class": uw, "channel": channel,
            "state": state, "issue_age": issue_age,
        }
    )  # fmt: skip


def _simulate_exits(attrs: pd.DataFrame, rng: np.random.Generator, spec: PortfolioSpec):
    """True exit date and reason of every policy up to the end of the study."""
    n = len(attrs)
    issue = attrs["issue_date"].to_numpy("datetime64[D]")
    term = attrs["term_years"].to_numpy()
    term_end = np.where(
        np.isnan(term),
        STUDY_END + np.timedelta64(10_000, "D"),
        lexis.anniversary(issue, np.nan_to_num(term).astype(int)),
    )
    sim_end = np.minimum(term_end, STUDY_END)
    seg = lexis.lexis_split(issue, issue, sim_end)
    pos = seg["pos"].to_numpy()
    seg_start = seg["start"].to_numpy("datetime64[D]")
    seg_end = seg["end"].to_numpy("datetime64[D]")
    expo = seg["exposure"].to_numpy()

    smr = np.asarray([spec.state_smr.get(s, 1.0) for s in attrs["state"].to_numpy()])
    age = attrs["issue_age"].to_numpy()[pos] + seg["duration"].to_numpy() - 1
    mu = true_force(
        spec.q_basis, age, seg["duration"].to_numpy(), seg["calendar_year"].to_numpy(),
        attrs["sex"].to_numpy()[pos], attrs["uw_class"].to_numpy()[pos],
        experience.amount_band(attrs["sum_assured"].to_numpy()[pos]),
        attrs["channel"].to_numpy()[pos], attrs["product"].to_numpy()[pos], smr[pos],
    )  # fmt: skip
    lam = lapse_force(
        seg["duration"].to_numpy(),
        attrs["channel"].to_numpy()[pos],
        attrs["product"].to_numpy()[pos],
    )
    hazard = mu + lam
    cumulative = np.cumsum(hazard * expo)
    first_row = np.flatnonzero(np.r_[True, pos[1:] != pos[:-1]])
    group_len = np.diff(np.r_[first_row, len(pos)])
    offset = np.repeat(np.r_[0.0, cumulative[first_row[1:] - 1]], group_len)
    h_end = cumulative - offset
    h_start = h_end - hazard * expo

    threshold = rng.exponential(size=n)[pos]
    row_id = np.arange(len(pos))
    candidate = np.where(h_end >= threshold, row_id, len(pos))
    first_hit = np.minimum.reduceat(candidate, first_row)
    hit = first_hit < len(pos)
    j = first_hit[hit]
    years_in = (threshold[j] - h_start[j]) / hazard[j]
    exit_ = seg_start[j] + np.ceil(years_in * lexis.DAYS_PER_YEAR).astype(int).astype(
        "timedelta64[D]"
    )
    exit_ = np.minimum(exit_, seg_end[j])
    is_death = rng.random(len(j)) < mu[j] / hazard[j]

    owners = pos[first_row]  # policy index of each group, in group order
    exit_date = np.full(n, np.datetime64("NaT", "D"))
    status = np.where(term_end <= STUDY_END, "EXPIRED", "IN_FORCE").astype(object)
    exit_date[owners[hit]] = exit_
    status[owners[hit]] = np.where(is_death, "DEATH", "LAPSE")
    expired = status == "EXPIRED"
    exit_date[expired] = term_end[expired]
    return exit_date, status


def generate_portfolio(spec: PortfolioSpec, chunk: int = 50_000) -> Portfolio:
    """Simulate the portfolio and the extract an administrator would hand to the actuary."""
    if spec.q_basis is None:
        raise ValueError("PortfolioSpec.q_basis (annual q by age, 0 to 110) is required.")
    rng = np.random.default_rng(spec.seed)
    parts = []
    made = 0
    while made < spec.n_policies:
        n = min(chunk, spec.n_policies - made)
        attrs = _draw_attributes(n, rng, spec)
        exit_date, status = _simulate_exits(attrs, rng, spec)
        attrs["true_exit"], attrs["true_status"] = exit_date, status
        attrs["policy_id"] = [f"P{made + i + 1:07d}" for i in range(n)]
        in_window = pd.isna(exit_date) | (exit_date > STUDY_START)
        parts.append(attrs[in_window])
        made += n
    full = pd.concat(parts, ignore_index=True)

    died = full["true_status"] == "DEATH"
    lag = np.clip(np.exp(rng.normal(np.log(LAG_MEDIAN_DAYS), LAG_SIGMA, len(full))), 1, 1500)
    notified = full["true_exit"] + pd.to_timedelta(np.ceil(lag).astype(int), unit="D")
    unreported = died & (notified > EXTRACT_DATE)

    view = full.copy()
    view["status"] = full["true_status"].where(~unreported, "IN_FORCE")
    view["exit_date"] = full["true_exit"].where(~unreported, pd.NaT)
    view["notification_date"] = notified.where(died & ~unreported, pd.NaT)
    policies = view[list(COLUMNS)].copy()
    policies["birth_date"] = pd.to_datetime(policies["birth_date"])
    truth = pd.DataFrame(
        {
            "policy_id": full["policy_id"], "true_status": full["true_status"],
            "true_exit": full["true_exit"], "unreported_death": unreported,
            "notification_lag_days": np.where(died, np.ceil(lag), np.nan),
        }
    )  # fmt: skip
    policies, defects = inject_defects(policies, rng, spec.defect_rate)
    return Portfolio(policies, truth, defects)


def inject_defects(policies: pd.DataFrame, rng: np.random.Generator, rate: float):
    """Add the kinds of defects found in real extracts; returns the damaged copy and a log."""
    p = policies.copy()
    n = len(p)
    log = []

    def pick(share, mask=None):
        """A random share of the rows (of the rows in ``mask`` if given)."""
        pool = np.flatnonzero(mask) if mask is not None else np.arange(n)
        k = round(share * len(pool)) if len(pool) else 0
        return rng.choice(pool, min(max(k, 1), len(pool)), replace=False) if len(pool) else pool

    sex_bad = pick(rate * 0.12)
    p.loc[p.index[sex_bad], "sex"] = rng.choice(["X", "", "U"], len(sex_bad))
    log += [(p["policy_id"].iloc[i], "invalid_sex") for i in sex_bad]
    age_bad = pick(rate * 0.12)
    p.loc[p.index[age_bad], "birth_date"] = p["issue_date"].iloc[
        age_bad
    ].to_numpy() + np.timedelta64(400, "D")
    log += [(p["policy_id"].iloc[i], "birth_after_issue") for i in age_bad]
    sa_bad = pick(rate * 0.12)
    p.loc[p.index[sa_bad], "sum_assured"] = rng.choice([0.0, -50_000.0], len(sa_bad))
    log += [(p["policy_id"].iloc[i], "non_positive_sum_assured") for i in sa_bad]
    state_bad = pick(rate * 0.12)
    p.loc[p.index[state_bad], "state"] = rng.choice(["99", "ZZ", ""], len(state_bad))
    log += [(p["policy_id"].iloc[i], "invalid_state") for i in state_bad]
    exited = (p["status"] != "IN_FORCE") & p["exit_date"].notna()
    exit_bad = pick(rate * 0.5, exited.to_numpy())
    p.loc[p.index[exit_bad], "exit_date"] = p["issue_date"].iloc[exit_bad] - pd.Timedelta(days=30)
    log += [(p["policy_id"].iloc[i], "exit_before_issue") for i in exit_bad]
    future_bad = pick(rate * 0.05)
    p.loc[p.index[future_bad], "issue_date"] = pd.Timestamp(EXTRACT_DATE) + pd.Timedelta(days=45)
    log += [(p["policy_id"].iloc[i], "issue_after_extract") for i in future_bad]
    deaths = (p["status"] == "DEATH").to_numpy()
    note_bad = pick(0.01, deaths)
    p.loc[p.index[note_bad], "notification_date"] = pd.NaT
    log += [(p["policy_id"].iloc[i], "death_without_notification") for i in note_bad]
    dup = pick(rate * 0.25)
    p = pd.concat([p, p.iloc[dup]], ignore_index=True)
    log += [(p["policy_id"].iloc[i], "duplicate_record") for i in dup]
    return p, pd.DataFrame(log, columns=["policy_id", "defect"])
