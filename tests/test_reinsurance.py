"""Reinsurance: concentration, simulated claims, treaty structures, rating, longevity swap."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import reinsurance as re
from mortality import stress


def block(n=3000, seed=3):
    rng = np.random.default_rng(seed)
    sa = rng.lognormal(13.3, 0.9, n)
    q = rng.uniform(0.0005, 0.004, n)
    return sa, q


def small_terms(**kw) -> re.Terms:
    return re.Terms(sims=3000, **kw)


def test_concentration_adds_up():
    sa, q = block()
    inforce = pd.DataFrame({"sum_assured": sa})
    table = re.concentration(inforce, q)
    assert table["policies"].sum() == len(sa)
    assert table["share_of_sum_at_risk"].sum() == pytest.approx(1.0)
    assert table["share_of_expected_claims"].sum() == pytest.approx(1.0)
    assert table["expected_claims"].sum() == pytest.approx((sa * q).sum())


def test_simulated_mean_matches_the_expected_claims():
    sa, q = block()
    terms = small_terms()
    sim = re.simulate_claims(sa, q, q, terms, level=False, pandemic=False)
    expected = float((sa * q).sum())
    assert sim.totals.mean() == pytest.approx(expected, rel=0.03)
    assert len(sim.totals) == terms.sims


def test_level_and_pandemic_widen_the_distribution():
    sa, q = block()
    q_event = np.minimum(q * 1.5, 1.0)
    terms = small_terms(pandemic_probability=0.2, level_sigma=0.3)
    plain = re.simulate_claims(sa, q, q_event, terms, level=False, pandemic=False)
    level = re.simulate_claims(sa, q, q_event, terms, level=True, pandemic=False)
    both = re.simulate_claims(sa, q, q_event, terms, level=True, pandemic=True)
    assert plain.totals.std() < level.totals.std() < both.totals.std()
    assert both.pandemic.mean() == pytest.approx(0.2, abs=0.04)
    assert both.totals.mean() > plain.totals.mean()


def test_recoveries_never_exceed_claims_and_respect_limits():
    sa, q = block()
    sim = re.simulate_claims(sa, q, q, small_terms())
    totals = sim.totals
    xl = re.per_life_xl(sim, 1_000_000.0, 2_000_000.0)
    assert (xl >= 0).all() and (xl <= totals + 1e-6).all()
    counts = np.bincount(sim.year, minlength=sim.n)
    assert (xl <= counts * 2_000_000.0 + 1e-6).all()
    assert re.per_life_xl(sim, 1e12).sum() == 0.0
    assert re.quota_share(sim, 0.3) == pytest.approx(0.3 * totals)
    sl = re.stop_loss(totals, totals.mean(), 0.2 * totals.mean())
    assert sl.min() >= 0 and sl.max() <= 0.2 * totals.mean() + 1e-6


def test_surplus_is_the_excess_of_loss_with_a_limit_of_its_lines():
    sa, q = block()
    sim = re.simulate_claims(sa, q, q, small_terms())
    a = re.surplus(sim, 800_000.0, 5)
    b = re.per_life_xl(sim, 800_000.0, 5 * 800_000.0)
    assert a == pytest.approx(b)


def test_distribution_reports_capital_above_the_mean():
    totals = np.arange(1.0, 1001.0)
    d = re.distribution(totals)
    assert d["mean"] == pytest.approx(500.5)
    assert d["capital"] == pytest.approx(d["var_995"] - d["mean"])
    assert d["var_95"] < d["var_99"] < d["var_995"] <= d["tvar_99"] + 1e-9


def test_quota_share_relieves_its_share_of_capital():
    sa, q = block()
    terms = small_terms()
    sim = re.simulate_claims(sa, q, q, terms)
    r = re.quota_share(sim, 0.25)
    row = re.evaluate("qs", "proportional", sim, r, re.proportional_premium(r, terms), terms)
    assert row["relief_share"] == pytest.approx(0.25, abs=1e-9)
    assert row["sd_reduction"] == pytest.approx(0.25, abs=1e-9)
    assert row["cost"] == pytest.approx(row["premium"] - row["expected_recoveries"])
    assert row["price_of_relief"] == pytest.approx(row["cost"] / row["capital_relief"])


def test_a_higher_retention_means_less_cost_and_less_relief():
    sa, q = block()
    terms = small_terms()
    sim = re.simulate_claims(sa, q, q, terms)
    table = re.retention_frontier(sim, terms, points=8)
    xl = table[table["family"] == "excess of loss"].sort_values("parameter")
    assert xl["cost"].is_monotonic_decreasing
    assert xl["expected_recoveries"].is_monotonic_decreasing
    qs = table[table["family"] == "quota share"]
    assert qs.loc[qs["parameter"] == 0.0, "cost"].iloc[0] == 0.0


def test_structure_table_lists_every_cover_with_consistent_columns():
    sa, q = block()
    terms = small_terms(pandemic_probability=0.05)
    sim = re.simulate_claims(sa, q, np.minimum(q * 1.4, 1.0), terms)
    table = re.structure_table(sim, terms)
    assert table["structure"].iloc[0] == "No reinsurance"
    assert (table["capital_relief"].iloc[1:] >= -1e-6).all()
    assert (table["retained_mean"] <= table["retained_mean"].iloc[0] + 1e-6).all()
    assert (table["cost"].iloc[1:] >= -1e-6).all()


def test_claim_size_variability_and_credibility():
    assert re.claim_size_cv2([10], [10 * 100.0], [10 * 100.0**2])[0] == pytest.approx(0.0)
    assert re.claim_size_cv2([2], [3.0], [5.0])[0] == pytest.approx(5 / 2 / 1.5**2 - 1)


def test_yrt_rating_blends_the_experience_with_the_manual_rate():
    ae = pd.DataFrame(
        {
            "dimension": ["channel", "channel"], "level": ["A", "B"],
            "deaths": [20.0, 2000.0],
            "exposure_amount": [1e9, 1e11], "expected_amount": [4e6, 4e8],
            "death_amount": [2e6, 2e8], "death_amount_sq": [20 * 2e10, 2000 * 2e10],
        }
    )  # fmt: skip
    # mean claim 100,000 with a squared coefficient of variation of one; A/E is 0.5 for both
    out = re.yrt_rating(ae)
    z = out["credibility"].to_numpy()
    assert (z >= 0).all() and (z <= 1).all() and z[0] < z[1]
    assert (out["ae_amount"] == 0.5).all()
    assert out["experience_factor"].iloc[0] > out["experience_factor"].iloc[1] > 0.5
    assert out["rated_rate_per_1000"].iloc[0] > out["rated_rate_per_1000"].iloc[1]
    assert out["manual_rate_per_1000"].iloc[0] == pytest.approx(1000 * 4e6 / 1e9 * 1.15)


def test_per_life_annuity_variance_on_a_two_year_life():
    q = np.array([[0.5, 1.0]])
    mean, var = re.per_life_pv_variance(q, 0.04)
    v = 1 / 1.04
    assert mean[0] == pytest.approx(1 + 0.5 * v)
    assert var[0] == pytest.approx(0.25 * v**2)


def test_longevity_swap_prices_a_positive_fee_and_reproduces_the_central_reserve():
    ages = np.arange(111)
    base = np.minimum(0.0005 * np.exp(0.09 * ages), 0.5)
    cube = {s: np.array([base * 0.985**t for t in range(10)]) for s in ("M", "F")}
    blk = stress.AnnuityBlock(lives=2000)
    terms = re.Terms(sims=1000)
    summary, dist = re.longevity_swap(blk, cube, terms, draws=20_000)
    make = {s: (lambda a, s=s: stress.cohort_q_paths(cube[s], a)) for s in cube}
    central = stress.annuity_reserves(blk, make)["reserve_T"]
    assert summary["central_reserve"] == pytest.approx(central)
    assert summary["fee_pv"] > 0 and summary["capital"] > 0
    assert summary["fee_bps_per_year"] == pytest.approx(
        1e4 * terms.reinsurer_coc * summary["capital_ratio"]
    )
    assert dist["reserve"].is_monotonic_increasing
    assert 0.0 < summary["pool_share_of_variance"] < 1.0
