"""Stress tests: a pandemic on an insurance book, longevity on an annuity book, and the hedge
between them.

Two risks that look like opposites. A pandemic raises mortality for a year: it costs a life
insurer claims and releases reserves for an annuity writer. Longevity is a permanent fall in
mortality: it costs the annuity writer reserves and gives the life insurer a gain. The stress tests
measure each on its own book and then together.

* **Pandemic.** The age and sex profile of Mexico's 2020 to 2022 excess mortality (step 9a) is
  replayed on the in-force block of the synthetic portfolio (step 8): each policy's chance of
  dying in the next twelve months is raised by the P-score of its age band and sex. Two knobs:
  ``dampening``, because an insured population is healthier than the general one and its excess was
  smaller, and ``severity``, a multiple of the observed profile.
* **Longevity.** An illustrative annuity-in-payment block is valued on the regulatory pensions
  table, the population's own period table, the central projection of step 7, a projection with the
  improvement scaled (none, double) and a permanent 20% fall in mortality. The reserve is a present
  value of pensions: annuity-due at 4%.

The book and the annuity block are illustrative; the shocks are not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mortality import experience as ex

MAX_AGE = 110
PROJECTION_BASE_YEAR = 2025


# ── Pandemic ────────────────────────────────────────────────────────────────


def pscore_by_age(excess: pd.DataFrame, year: int) -> dict[str, np.ndarray]:
    """P-score (excess over expected deaths) by single age 0..110 for each sex in ``year``.

    The five-year bands of ``excess_mortality`` are spread over their ages and the open band
    takes all older ages. A negative P-score is set to zero: a stress test gets no credit for the
    bands where deaths fell below the baseline."""
    out: dict[str, np.ndarray] = {}
    for sex in ("M", "F"):
        part = excess[(excess["year"] == year) & (excess["sex"] == sex)].sort_values("band")
        lows = [int(str(label).split("-")[0].rstrip("+")) for label in part["age_group"]]
        scores = np.clip(part["p_score"].to_numpy(float), 0.0, None)
        idx = np.searchsorted(lows, np.arange(MAX_AGE + 1), side="right") - 1
        out[sex] = scores[np.clip(idx, 0, len(scores) - 1)]
    return out


def first_year_q(inforce: pd.DataFrame, q_all: np.ndarray, lookup: dict | None) -> np.ndarray:
    """Probability of dying in the next twelve months for each policy of an in-force block: the
    expected table, times the company multiplier of its age, sex and duration if one is given."""
    age = np.clip(inforce["attained_age"].to_numpy(int), 0, MAX_AGE)
    q = q_all[age].copy()
    if lookup:
        label = ex.duration_group(inforce["duration"].to_numpy(int))
        sex = inforce["sex"].to_numpy()
        for (s, lab), mult in lookup.items():
            sel = (sex == s) & (label == lab)
            q[sel] = q[sel] * mult[age[sel]]
    return np.minimum(q, 1.0)


@dataclass(frozen=True)
class Book:
    """The in-force block reduced to what a one-year stress needs: per policy sum assured, age,
    sex, product and the base probability of dying in the next twelve months."""

    inforce: pd.DataFrame
    q: np.ndarray

    @property
    def claims(self) -> float:
        return float((self.inforce["sum_assured"].to_numpy(float) * self.q).sum())


def stressed_claims(book: Book, scores: dict[str, np.ndarray], dampening=1.0, severity=1.0):
    """Expected claims of the next twelve months with the excess profile applied.

    Returns the per-policy stressed claims; ``dampening`` scales the P-score to an insured
    population, ``severity`` is a multiple of the observed excess."""
    age = np.clip(book.inforce["attained_age"].to_numpy(int), 0, MAX_AGE)
    sex = book.inforce["sex"].to_numpy()
    p = np.zeros(len(age))
    for s, arr in scores.items():
        sel = sex == s
        p[sel] = arr[age[sel]]
    q = np.minimum(book.q * (1.0 + dampening * severity * p), 1.0)
    return book.inforce["sum_assured"].to_numpy(float) * q


def pandemic_scenarios(
    book: Book,
    excess: pd.DataFrame,
    q_regulatory: np.ndarray | None = None,
    years=(2020, 2021, 2022),
    dampenings=(1.0, 0.5),
    severities=(0.5, 1.5, 2.0),
) -> pd.DataFrame:
    """The book's extra claims under each replay of the pandemic and under the regulator's stress.

    ``q_regulatory`` is a heavier table (the 99.5th percentile CNSF variant): its uplift is the
    shock the regulator expects a company to withstand, the comparison for the replays."""
    base = book.claims
    sa = book.inforce["sum_assured"].to_numpy(float)
    rows = []

    def add(kind, scenario, year, dampening, severity, claims):
        rows.append(
            {"kind": kind, "scenario": scenario, "year": year, "dampening": dampening,
             "severity": severity, "base_claims": base, "stressed_claims": claims,
             "extra_claims": claims - base, "extra_pct": claims / base - 1.0}
        )  # fmt: skip

    for year in years:
        scores = pscore_by_age(excess, year)
        for damp in dampenings:
            add("replay", f"{year} replay", year, damp, 1.0,
                float(stressed_claims(book, scores, damp, 1.0).sum()))  # fmt: skip
    ref = max(years, key=lambda y: pscore_by_age(excess, y)["M"][65])
    scores = pscore_by_age(excess, ref)
    for sev in severities:
        add("severity", f"{ref} profile x{sev:g}", ref, 1.0, sev,
            float(stressed_claims(book, scores, 1.0, sev).sum()))  # fmt: skip
    if q_regulatory is not None:
        heavy = float((sa * np.minimum(q_regulatory, 1.0)).sum())
        add("regulatory", "CNSF 99.5th percentile table", np.nan, np.nan, np.nan, heavy)
    return pd.DataFrame(rows)


def pandemic_by_age(book: Book, excess: pd.DataFrame, year: int, dampening=1.0) -> pd.DataFrame:
    """Where in the age range the replay lands: base and extra claims by age band and sex."""
    scores = pscore_by_age(excess, year)
    claims = stressed_claims(book, scores, dampening, 1.0)
    frame = pd.DataFrame(
        {
            "age_group": ex.age_group(book.inforce["attained_age"].to_numpy(int)),
            "sex": book.inforce["sex"].to_numpy(),
            "base_claims": book.inforce["sum_assured"].to_numpy(float) * book.q,
            "stressed_claims": claims,
        }
    )
    out = frame.groupby(["age_group", "sex"], observed=True).sum().reset_index()
    out["extra_claims"] = out["stressed_claims"] - out["base_claims"]
    out["extra_pct"] = out["stressed_claims"] / out["base_claims"] - 1.0
    out["share_of_extra"] = out["extra_claims"] / out["extra_claims"].sum()
    out.insert(0, "year", year)
    return out


# ── Longevity ───────────────────────────────────────────────────────────────


def annuity_due_from_q(q_paths: np.ndarray, interest: float) -> np.ndarray:
    """Annuity-due (1 a year in advance while alive) for each row of a matrix of probabilities of
    death in each future year. The first column is the year about to start."""
    n, horizon = q_paths.shape
    surv = np.concatenate([np.ones((n, 1)), np.cumprod(1.0 - q_paths[:, :-1], axis=1)], axis=1)
    return (surv * (1.0 + interest) ** -np.arange(horizon)).sum(axis=1)


def cohort_q_paths(cube: np.ndarray, ages: np.ndarray, scale: float = 1.0, level: float = 1.0):
    """Probabilities of death along the diagonal of a projected table for lives of ``ages`` in the
    base year. ``cube`` is ``[year, age]`` with the base year first.

    ``scale`` multiplies the (log) improvement against the base year: 0 means mortality stays at
    its base-year level, 1 the projection, 2 twice the improvement. ``level`` is a permanent
    multiplier on every probability (0.8 is a 20% fall)."""
    n_years, n_ages = cube.shape
    horizon = n_ages - int(ages.min())
    j = np.arange(horizon)
    age_idx = np.clip(ages[:, None] + j[None, :], 0, n_ages - 1)
    year_idx = np.clip(j, 0, n_years - 1)[None, :].repeat(len(ages), axis=0)
    base = cube[0][age_idx]
    ratio = cube[year_idx, age_idx] / base
    q = base * ratio**scale * level
    q[age_idx >= n_ages - 1] = 1.0
    return np.clip(q, 0.0, 1.0)


def period_q_paths(q_all: np.ndarray, ages: np.ndarray, level: float = 1.0) -> np.ndarray:
    """The same, for a period table: mortality does not change with the calendar year."""
    horizon = len(q_all) - int(ages.min())
    idx = np.clip(ages[:, None] + np.arange(horizon)[None, :], 0, len(q_all) - 1)
    q = q_all[idx] * level
    q[idx >= len(q_all) - 1] = 1.0
    return np.clip(q, 0.0, 1.0)


@dataclass(frozen=True)
class AnnuityBlock:
    """An illustrative block of annuities in payment (pensions)."""

    lives: int = 20_000
    male_share: float = 0.6
    pension: float = 120_000.0
    youngest: int = 60
    oldest: int = 95
    interest: float = 0.04

    def weights(self, q_all: np.ndarray) -> np.ndarray:
        """Number of annuitants at each age: the survivors of a cohort from the youngest age."""
        ages = np.arange(self.youngest, self.oldest + 1)
        surv = np.concatenate([[1.0], np.cumprod(1.0 - q_all[ages[:-1]])])
        return surv / surv.sum()


def annuity_reserves(
    block: AnnuityBlock, q_by_sex: dict[str, np.ndarray], interest: float | None = None
) -> dict[str, float]:
    """Reserve of the block for each sex and for both, and the annuity-due at 65.

    ``q_by_sex[sex]`` is a function ``ages -> (n, horizon)`` matrix of probabilities of death
    (period tables ignore the calendar year; projections follow the cohort)."""
    i = block.interest if interest is None else interest
    ages = np.arange(block.youngest, block.oldest + 1)
    out: dict[str, float] = {}
    total = 0.0
    for sex, share in (("M", block.male_share), ("F", 1.0 - block.male_share)):
        make = q_by_sex[sex]
        a_all = annuity_due_from_q(make(ages), i)
        w = block.weights(_first_year(make))
        out[f"reserve_{sex}"] = float(block.lives * share * block.pension * (w * a_all).sum())
        out[f"a65_{sex}"] = float(annuity_due_from_q(make(np.array([65])), i)[0])
        total += out[f"reserve_{sex}"]
    out["reserve_T"] = total
    return out


def _first_year(make) -> np.ndarray:
    """First-year probabilities of death at every age 0..110, for the age weights."""
    ages = np.arange(0, 111)
    return make(ages)[:, 0]


# ── The hedge ───────────────────────────────────────────────────────────────


def annuity_release(
    block: AnnuityBlock, q_by_sex: dict[str, callable], scores: dict[str, np.ndarray], dampening=1.0
) -> float:
    """Reserve released by one year of pandemic excess among the annuitants (a negative change).

    Each extra death at age x frees the present value of the pensions that will not be paid:
    ``pension * v * a_due(x + 1)``, valued on the block's own table."""
    ages = np.arange(block.youngest, block.oldest + 1)
    v = 1.0 / (1.0 + block.interest)
    total = 0.0
    for sex, share in (("M", block.male_share), ("F", 1.0 - block.male_share)):
        make = q_by_sex[sex]
        w = block.weights(_first_year(make))
        q1 = make(ages)[:, 0]
        a_next = annuity_due_from_q(make(np.minimum(ages + 1, MAX_AGE)), block.interest)
        extra = np.minimum(q1 * dampening * scores[sex][ages], 1.0 - q1)
        total += float(block.lives * share * block.pension * (w * extra * v * a_next).sum())
    return -total


# ── Warehouse tables ────────────────────────────────────────────────────────

DESCRIPTIONS = {
    "stress_pandemic_book": (
        "Extra claims of the synthetic in-force book under replays of the 2020-2022 excess "
        "mortality (insured-lives dampening and severity variants) and under the CNSF 99.5th "
        "percentile table, the regulator's own stress"
    ),
    "stress_pandemic_age": (
        "Where the 2021 replay lands: base and extra claims of the in-force book by age band and "
        "sex"
    ),
    "stress_longevity": (
        "Reserve of an illustrative annuity-in-payment block under the regulatory pensions table, "
        "the population table, the central projection, none and double the improvement, a 20% "
        "permanent fall in mortality and interest rates one point away"
    ),
    "stress_hedge": (
        "Pandemic and longevity shocks on the in-force life book and on the annuity block, and "
        "the size of annuity block that would offset the life book's loss"
    ),
}


def build_tables(con, *, interest: float = 0.04) -> list[tuple[str, str]]:
    """Stress the synthetic book and the annuity block on the warehouse's tables."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if (
        not {"cnsf_rates", "excess_mortality", "projected_qx", "graduated_qx", "experience_basis"}
        <= names
    ):
        return []
    from mortality import portfolio as pf
    from mortality.config import get_paths

    inputs = ex.warehouse_inputs(con)
    if inputs is None:
        return []
    q_cnsf, state_smr, weights = inputs
    portfolio = ex.load_or_generate_portfolio(get_paths(), q_cnsf, state_smr, weights)
    clean = ex.validate_extract(portfolio.policies, pf.STUDY_END, pf.EXTRACT_DATE)[0]
    inforce = ex.inforce_block(clean, pf.STUDY_END)

    cnsf = pd.read_sql(
        "SELECT variant, age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' ORDER BY age", con
    )

    def cnsf_q(variant: str) -> np.ndarray:
        s = cnsf[cnsf["variant"] == variant].set_index("age")["qx"]
        return s.reindex(range(MAX_AGE + 1)).ffill().to_numpy()

    base, heavy, light = cnsf_q("base"), cnsf_q("p99.5"), cnsf_q("p0.05")
    table = pd.read_sql("SELECT sex, age, duration_group, multiplier FROM experience_basis", con)
    lookup = ex._multiplier_lookup(table)
    q1 = first_year_q(inforce, base, lookup)
    book = Book(inforce, q1)
    age = np.clip(inforce["attained_age"].to_numpy(int), 0, MAX_AGE)
    q_regulatory = np.minimum(q1 * heavy[age] / base[age], 1.0)
    excess = pd.read_sql("SELECT * FROM excess_mortality", con)
    pandemic = pandemic_scenarios(book, excess, q_regulatory)
    by_age = pandemic_by_age(book, excess, 2021)

    # longevity: the annuity block on each basis
    proj = pd.read_sql("SELECT year, sex, age, qx FROM projected_qx", con)
    cube = {
        s: p.pivot_table(index="year", columns="age", values="qx").sort_index().to_numpy()
        for s, p in proj.groupby("sex")
    }
    pop = {
        s: pd.read_sql(
            f"SELECT age, qx FROM graduated_qx WHERE year = 2023 AND sex = '{s}' ORDER BY age", con
        )
        .set_index("age")["qx"]
        .reindex(range(MAX_AGE + 1))
        .ffill()
        .to_numpy()
        for s in ("M", "F")
    }

    def projected(scale=1.0, level=1.0):
        return {s: (lambda ages, s=s: cohort_q_paths(cube[s], ages, scale, level)) for s in cube}

    def period(table_by_sex, level=1.0):
        return {s: (lambda ages, s=s: period_q_paths(table_by_sex[s], ages, level)) for s in cube}

    block = AnnuityBlock(interest=interest)
    cases = {
        "cnsf_pensions": ("CNSF 2013, pensions variant", period({"M": light, "F": light}), None),
        "cnsf_base": ("CNSF 2013", period({"M": base, "F": base}), None),
        "population_2023": ("Mexican population 2023 (no improvement)", period(pop), None),
        "no_improvement": ("Projection with no improvement after 2025", projected(0.0), None),
        "central": ("Central projection (step 7)", projected(1.0), None),
        "improvement_x2": ("Projection with double the improvement", projected(2.0), None),
        "level_minus_20": ("Central, mortality 20% lower for good", projected(1.0, 0.8), None),
        "interest_minus_1": ("Central, interest 1 point lower", projected(1.0), interest - 0.01),
        "interest_plus_1": ("Central, interest 1 point higher", projected(1.0), interest + 0.01),
    }  # fmt: skip
    rows = []
    for key, (label, make, rate) in cases.items():
        r = annuity_reserves(block, make, rate)
        rows.append({"scenario": key, "label": label, "interest": rate or interest, **r})
    longevity = pd.DataFrame(rows)
    central = float(longevity.loc[longevity["scenario"] == "central", "reserve_T"].iloc[0])
    longevity["change_vs_central"] = longevity["reserve_T"] / central - 1.0
    longevity["change_mxn"] = longevity["reserve_T"] - central

    # the hedge: the same shocks on both books
    central_make = projected(1.0)
    pv_base = float(
        ex.pv_death_benefits(inforce, pd.Series(base), table, interest)["pv_experience"].iloc[0]
    )
    pv_low = float(
        ex.pv_death_benefits(inforce, pd.Series(base * 0.8), table, interest)["pv_experience"].iloc[
            0
        ]
    )
    hedge = []
    for year in (2020, 2021, 2022):
        scores = pscore_by_age(excess, year)
        full = pandemic[(pandemic["kind"] == "replay") & (pandemic["dampening"] == 1.0)]
        extra = float(full.loc[full["year"] == year, "extra_claims"].iloc[0])
        release = annuity_release(block, central_make, scores)
        hedge.append({"shock": f"{year} pandemic replay", "life_book_change": extra,
                      "annuity_change": release})  # fmt: skip
    shock_reserve = float(
        longevity.loc[longevity["scenario"] == "level_minus_20", "reserve_T"].iloc[0]
    )
    hedge.append({"shock": "Mortality 20% lower for good", "life_book_change": pv_low - pv_base,
                  "annuity_change": shock_reserve - central})  # fmt: skip
    hedge = pd.DataFrame(hedge)
    hedge["net_change"] = hedge["life_book_change"] + hedge["annuity_change"]
    hedge["annuity_reserve"] = central
    opposite = np.sign(hedge["life_book_change"]) != np.sign(hedge["annuity_change"])
    hedge["annuity_block_to_offset"] = np.where(
        opposite, -hedge["life_book_change"] / hedge["annuity_change"] * central, np.nan
    )
    hedge["life_book_pv_death_benefits"] = pv_base

    frames = {
        "stress_pandemic_book": pandemic,
        "stress_pandemic_age": by_age,
        "stress_longevity": longevity,
        "stress_hedge": hedge,
    }
    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
