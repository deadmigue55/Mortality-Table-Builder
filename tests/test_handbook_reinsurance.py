"""Numerical proof of the formulas in docs/handbook/10-reinsurance.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mortality import reinsurance as re
from mortality import stress

ROOT = Path(__file__).resolve().parents[1]


def small_block(n: int = 3000, seed: int = 0):
    """A block of policies with sums assured of very different sizes and a flat probability of death."""
    rng = np.random.default_rng(seed)
    sa = rng.choice([2e5, 5e5, 1e6, 2e6, 5e6], n, p=[0.3, 0.3, 0.2, 0.15, 0.05])
    q = np.full(n, 0.004)
    return sa, q


# ── 10.1: concentration ──────────────────────────────────────────────────────


def test_with_a_flat_probability_the_shares_of_sum_and_of_claims_coincide():
    """(10.1): expected claims = sum assured x q, so the two shares are equal when q does not vary."""
    sa, q = small_block()
    out = re.concentration(pd.DataFrame({"sum_assured": sa}), q)
    assert out["policies"].sum() == len(sa)
    assert out["share_of_sum_at_risk"].to_numpy() == pytest.approx(
        out["share_of_expected_claims"].to_numpy()
    )
    assert out["share_of_policies"].sum() == pytest.approx(1.0)
    assert out["sum_at_risk"].sum() == pytest.approx(sa.sum())
    varying = re.concentration(pd.DataFrame({"sum_assured": sa}), np.where(sa > 1e6, 0.008, 0.002))
    assert varying["share_of_expected_claims"].iloc[-1] > varying["share_of_sum_at_risk"].iloc[-1]


# ── 10.2: aggregate claims ───────────────────────────────────────────────────


def test_simulated_claims_have_the_compound_poisson_mean_and_variance():
    """(10.2) to (10.4): E[S] = sum SA q; Var(S) = sum SA^2 q + (exp(s^2) - 1) E[S]^2."""
    sa, q = small_block()
    terms = re.Terms(sims=200_000, seed=1, level_sigma=0.05)
    mean = (sa * q).sum()
    fluctuation = (sa**2 * q).sum()
    only = re.simulate_claims(sa, q, q, terms, level=False, pandemic=False).totals
    assert only.mean() == pytest.approx(mean, rel=0.005)
    assert only.var() == pytest.approx(fluctuation, rel=0.02)
    level = re.simulate_claims(sa, q, q, terms, level=True, pandemic=False).totals
    assert level.mean() == pytest.approx(mean, rel=0.005)  # the level factor has mean one
    assert level.var() == pytest.approx(fluctuation + (np.exp(0.05**2) - 1) * mean**2, rel=0.03)


def test_the_lognormal_level_factor_has_mean_one():
    """(10.2): F = exp(s Z - s^2 / 2) has E[F] = 1 and Var(F) = exp(s^2) - 1."""
    rng = np.random.default_rng(3)
    s = 0.05
    factor = np.exp(s * rng.standard_normal(2_000_000) - 0.5 * s * s)
    assert factor.mean() == pytest.approx(1.0, abs=1e-3)
    assert factor.var() == pytest.approx(np.exp(s * s) - 1, rel=0.03)


def test_a_pandemic_year_mixes_two_distributions():
    """(10.5): Var = p Var_pandemic + (1 - p) Var_normal + p (1 - p) (mean_pandemic - mean_normal)^2."""
    sa, q = small_block()
    q_pandemic = q * 1.6
    p, s = 1 / 10, 0.05
    terms = re.Terms(sims=300_000, seed=2, level_sigma=s, pandemic_probability=p)
    totals = re.simulate_claims(sa, q, q_pandemic, terms).totals
    mu_n, mu_p = (sa * q).sum(), (sa * q_pandemic).sum()
    var_n = (sa**2 * q).sum() + (np.exp(s * s) - 1) * mu_n**2
    var_p = (sa**2 * q_pandemic).sum() + (np.exp(s * s) - 1) * mu_p**2
    mixture_mean = p * mu_p + (1 - p) * mu_n
    mixture_var = p * var_p + (1 - p) * var_n + p * (1 - p) * (mu_p - mu_n) ** 2
    assert totals.mean() == pytest.approx(mixture_mean, rel=0.005)
    assert totals.var() == pytest.approx(mixture_var, rel=0.03)
    # the tail comes from the pandemic years: capital grows far more than the mean
    plain = re.simulate_claims(sa, q, q, terms, level=True, pandemic=False).totals
    dist, base = re.distribution(totals), re.distribution(plain)
    assert dist["capital"] / base["capital"] > 1.05 * dist["mean"] / base["mean"]


def test_the_distribution_summary_defines_capital_as_the_tail_over_the_mean():
    """(10.6): capital = VaR at 99.5% minus the mean."""
    totals = np.arange(1.0, 1001.0)
    d = re.distribution(totals, 0.995)
    assert d["mean"] == pytest.approx(500.5)
    assert d["var_995"] == pytest.approx(np.quantile(totals, 0.995))
    assert d["capital"] == pytest.approx(d["var_995"] - 500.5)
    assert d["cv"] == pytest.approx(totals.std() / 500.5)


# ── 10.3: the covers ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sim():
    sa, q = small_block()
    return re.simulate_claims(sa, q, q * 1.5, re.Terms(sims=20_000, seed=5)), sa


def test_the_surplus_treaty_recovers_exactly_a_limited_excess_of_loss(sim):
    """(10.7), (10.8): min(max(SA - R, 0), lines x R) is an excess of loss of lines x R xs R."""
    simulation, _ = sim
    for retention, lines in ((5e5, 9), (1e6, 4), (2e6, 9)):
        by_surplus = re.surplus(simulation, retention, lines)
        by_xl = re.per_life_xl(simulation, retention, lines * retention)
        assert by_surplus == pytest.approx(by_xl)
    one = re.Simulation(np.array([0, 0, 1]), np.array([3e6, 8e5, 5e5]), 2, np.array([False, False]))
    assert re.per_life_xl(one, 1e6, 1.5e6).tolist() == [
        1.5e6,
        0.0,
    ]  # 3M xs 1M capped at 1.5M; 0.5M ceded nothing


def test_recoveries_are_bounded_and_stop_loss_takes_the_slice_of_the_aggregate(sim):
    """(10.9): stop loss recovers clip(S - A, 0, L); no cover recovers more than the claims."""
    simulation, _ = sim
    totals = simulation.totals
    mean = totals.mean()
    sl = re.stop_loss(totals, 1.1 * mean, 0.4 * mean)
    assert sl == pytest.approx(np.clip(totals - 1.1 * mean, 0, 0.4 * mean))
    assert sl.max() <= 0.4 * mean + 1e-9 and sl.min() == 0.0
    for recoveries in (
        re.quota_share(simulation, 0.3),
        re.surplus(simulation, 1e6, 9),
        re.per_life_xl(simulation, 1e6),
    ):
        assert (recoveries >= 0).all() and (recoveries <= totals + 1e-6).all()
    assert re.quota_share(simulation, 0.3) == pytest.approx(0.3 * totals)


def test_the_two_prices_of_a_cover(sim):
    """(10.10), (10.11): non-proportional = mean (1 + e) + coc x capital; proportional = mean / LR (1 - c)."""
    simulation, _ = sim
    terms = re.Terms()
    r = re.per_life_xl(simulation, 1e6)
    capital = np.quantile(r, 0.995) - r.mean()
    assert re.non_proportional_premium(r, terms) == pytest.approx(r.mean() * 1.01 + 0.06 * capital)
    quota = re.quota_share(simulation, 0.4)
    assert re.proportional_premium(quota, terms) == pytest.approx(quota.mean() / 0.65 * 0.70)


def test_a_quota_share_relieves_its_own_share_of_capital_at_a_price_that_does_not_depend_on_the_share(
    sim,
):
    """(10.12), (10.13): relief = s x capital and cost / relief = mean [(1 - c) / LR - 1] / capital for every s."""
    simulation, _ = sim
    terms = re.Terms()
    gross = re.distribution(simulation.totals, terms.quantile)
    prices = []
    for share in (0.2, 0.4, 0.7):
        r = re.quota_share(simulation, share)
        e = re.evaluate(
            f"QS {share}", "proportional", simulation, r, re.proportional_premium(r, terms), terms
        )
        assert e["capital_relief"] == pytest.approx(share * gross["capital"], rel=1e-9)
        assert e["relief_share"] == pytest.approx(share)
        prices.append(e["price_of_relief"])
    assert prices == pytest.approx([prices[0]] * 3)
    expected = (
        gross["mean"] * ((1 - terms.ceding_commission) / terms.loss_ratio - 1) / gross["capital"]
    )
    assert prices[0] == pytest.approx(expected)


def test_the_price_of_a_non_proportional_cover_is_linear_in_the_reinsurers_return(sim):
    """(10.14): price = (e mean + coc x capital_recoveries) / relief, a straight line in coc."""
    simulation, _ = sim
    prices = []
    for coc in (0.04, 0.06, 0.08, 0.10):
        t = replace(re.Terms(), reinsurer_coc=coc)
        r = re.per_life_xl(simulation, 1e6)
        prices.append(
            re.evaluate(
                "xl", "excess of loss", simulation, r, re.non_proportional_premium(r, t), t
            )["price_of_relief"]
        )
    steps = np.diff(prices)
    assert steps == pytest.approx([steps[0]] * 3)
    r = re.per_life_xl(simulation, 1e6)
    gross = re.distribution(simulation.totals)["capital"]
    net = re.distribution(simulation.totals - r)["capital"]
    capital_rec = np.quantile(r, 0.995) - r.mean()
    assert steps[0] == pytest.approx(0.02 * capital_rec / (gross - net))


def test_worth_buying_compares_the_price_with_the_cedants_cost_of_capital(sim):
    """(10.14): a cover is worth buying when it relieves capital at a price below the cedant's rate."""
    simulation, _ = sim
    terms = re.Terms()
    r = re.per_life_xl(simulation, 1e6)
    cheap = re.evaluate(
        "xl", "excess of loss", simulation, r, re.non_proportional_premium(r, terms), terms
    )
    assert cheap["worth_buying"] == (cheap["price_of_relief"] < 0.10)
    dear = re.evaluate(
        "xl", "excess of loss", simulation, r, re.non_proportional_premium(r, terms) * 3, terms
    )
    assert dear["price_of_relief"] > cheap["price_of_relief"] and not dear["worth_buying"]
    none = re.evaluate("none", "none", simulation, np.zeros(simulation.n), 0.0, terms)
    assert none["capital_relief"] == pytest.approx(0.0) and not none["worth_buying"]


def test_layer_prices_add_up_between_the_extreme_retentions(sim):
    """(10.15): the marginal price of a layer is its extra cost over its extra relief."""
    simulation, _ = sim
    frontier = re.retention_frontier(simulation, re.Terms(), points=9)
    xl = (
        frontier[frontier["family"] == "excess of loss"]
        .sort_values("parameter")
        .reset_index(drop=True)
    )
    d_cost = xl["cost"].iloc[0] - xl["cost"].iloc[1]
    d_relief = xl["capital_relief"].iloc[0] - xl["capital_relief"].iloc[1]
    assert xl["marginal_price"].iloc[0] == pytest.approx(d_cost / d_relief)
    cost_total = xl["cost"].iloc[0] - xl["cost"].iloc[-1]
    relief_total = xl["capital_relief"].iloc[0] - xl["capital_relief"].iloc[-1]
    layers = xl["marginal_price"].iloc[:-1].to_numpy()
    weights = xl["capital_relief"].iloc[:-1].to_numpy() - xl["capital_relief"].iloc[1:].to_numpy()
    assert np.nansum(layers * weights) / weights.sum() == pytest.approx(cost_total / relief_total)
    benefit = 0.10 * xl["capital_relief"] - xl["cost"]
    assert xl["net_benefit"].to_numpy() == pytest.approx(benefit.to_numpy())


# ── 10.5: experience rating of a YRT treaty ──────────────────────────────────


def test_claim_size_variability_and_why_amounts_need_more_deaths():
    """(10.16), (10.17): cv^2 = E[SA^2] / E[SA]^2 - 1, and the standard becomes 1,082 (1 + cv^2)."""
    amounts = np.array([1e6, 3e6])
    cv2 = re.claim_size_cv2([2], [amounts.sum()], [(amounts**2).sum()])[0]
    assert (
        cv2
        == pytest.approx((np.mean(amounts**2) / np.mean(amounts) ** 2) - 1)
        == pytest.approx(0.25)
    )
    # compound Poisson: relative variance of total claims is (1 + cv^2) / lambda, against 1 / lambda for counts
    rng = np.random.default_rng(4)
    sizes = rng.lognormal(0.0, 0.8, 200_000)
    cv2_true = sizes.var() / sizes.mean() ** 2
    lam = 400
    totals = np.array([rng.choice(sizes, rng.poisson(lam)).sum() for _ in range(4000)])
    assert (totals.std() / totals.mean()) ** 2 == pytest.approx((1 + cv2_true) / lam, rel=0.1)
    assert pytest.approx(3138, abs=1) == 1082 * (1 + 1.9)


def test_the_yrt_rating_factor_and_rate():
    """(10.18), (10.19): factor = Z x amount A/E + (1 - Z); rate = manual x factor."""
    deaths = np.array([365.0, 2166.0, 5000.0])
    mean_claim, cv2_planted = 1e6, 1.9  # second moment = mean^2 (1 + cv^2)
    ae = pd.DataFrame(
        {
            "deaths": deaths,
            "exposure_amount": [3.7e11, 1.0e12, 2.0e12],
            "expected_amount": [7.3e8, 2.0e9, 4.0e9],
            "death_amount": deaths * mean_claim,
            "death_amount_sq": deaths * mean_claim**2 * (1 + cv2_planted),
        }
    )
    out = re.yrt_rating(ae, loading=0.15)
    cv2 = out["claim_size_cv2"]
    assert cv2.to_numpy() == pytest.approx([cv2_planted] * 3)
    z = np.minimum(1.0, np.sqrt(ae["deaths"] / (1082 * (1 + cv2))))
    assert out["credibility"].to_numpy() == pytest.approx(z.to_numpy())
    assert out["credibility"].iloc[2] == 1.0  # 5,000 deaths exceed the 3,138 that amounts need
    assert out["credibility"].iloc[1] == pytest.approx(np.sqrt(2166 / (1082 * 2.9)))  # 0.83
    factor = z * (ae["death_amount"] / ae["expected_amount"]) + (1 - z)
    assert out["experience_factor"].to_numpy() == pytest.approx(factor.to_numpy())
    manual = 1000 * ae["expected_amount"] / ae["exposure_amount"] * 1.15
    assert out["manual_rate_per_1000"].to_numpy() == pytest.approx(manual.to_numpy())
    assert out["rated_rate_per_1000"].to_numpy() == pytest.approx((manual * factor).to_numpy())
    low, high = (
        np.minimum(1, ae["death_amount"] / ae["expected_amount"]),
        np.maximum(1, ae["death_amount"] / ae["expected_amount"]),
    )
    assert (
        (out["experience_factor"] >= low - 1e-12) & (out["experience_factor"] <= high + 1e-12)
    ).all()


# ── 10.6: the longevity swap ─────────────────────────────────────────────────


def test_per_life_variance_of_an_annuity_by_hand():
    """(10.20), (10.21): a two-year life: the PV is 1 if death in year 1 and 1 + v if in year 2."""
    i = 0.05
    v = 1 / (1 + i)
    q = np.array([[0.1, 0.2]])
    mean, var = re.per_life_pv_variance(q, i)
    pv1, pv2 = 1.0, 1.0 + v
    p1, p2 = 0.1, 0.9 * 0.2
    m = p1 * pv1 + p2 * pv2
    assert mean[0] == pytest.approx(m)
    assert var[0] == pytest.approx(p1 * pv1**2 + p2 * pv2**2 - m**2)
    # over a long horizon the mean is the annuity-due of chapter 5 and 9
    closed = np.full((1, 60), 0.03)
    closed[0, -1] = 1.0  # the table closes: everyone dies by the last year
    mean_long, _ = re.per_life_pv_variance(closed, 0.04)
    assert mean_long[0] == pytest.approx(stress.annuity_due_from_q(closed, 0.04)[0], rel=1e-12)


def test_closed_two_year_life_example_and_the_other_hand_examples():
    """Section 10.7: q = (0.1, 1): mean 1.857, variance 0.0816; the quota-share and YRT examples."""
    mean, var = re.per_life_pv_variance(np.array([[0.1, 1.0]]), 0.05)
    assert (round(mean[0], 3), round(var[0], 4)) == (1.857, 0.0816)
    assert mean[0] == pytest.approx(0.1 + 0.9 * (1 + 1 / 1.05))
    # the price of a quota share, from the aggregate table of section 10.8: 748.7 x 0.0769 / 293.7
    assert pytest.approx(0.196, abs=1e-3) == 748.7 * ((1 - 0.30) / 0.65 - 1) / 293.7
    # surplus and excess of loss on one policy: 3M and 12M with retention 1M and nine lines
    one = re.Simulation(np.array([0, 0]), np.array([3e6, 12e6]), 1, np.array([False]))
    assert re.surplus(one, 1e6, 9).tolist() == [2e6 + 9e6]
    assert re.per_life_xl(one, 1e6, 9e6).tolist() == [2e6 + 9e6]
    # a stop loss: attachment 115% of 742M, claims of 900M
    assert re.stop_loss(np.array([900e6]), 1.15 * 742e6, 742e6)[0] == pytest.approx(900e6 - 853.3e6)
    # the YRT credibility of the preferred class
    z = np.sqrt(365 / (1082 * 2.84))
    assert (round(z, 3), round(z * 0.465 + (1 - z), 3)) == (0.345, 0.816)


def test_swap_fee_identities_on_a_small_block():
    """(10.22), (10.23): capital ratio = capital / central, fee = coc x ratio x run-off, bps = coc x ratio."""
    ages = np.arange(0, 111)
    base = np.clip(0.0005 * np.exp(0.09 * ages), 0, 1)
    base[-1] = 1.0
    years = np.arange(0, 60)
    cube = base[None, :] * np.exp(-0.015 * years)[:, None]
    cube[:, -1] = 1.0
    block = stress.AnnuityBlock(
        lives=5000, male_share=0.5, pension=100_000.0, youngest=60, oldest=95
    )
    terms = re.Terms(seed=7)
    summary, dist = re.longevity_swap(block, {"M": cube, "F": cube}, terms, draws=20_000)
    assert summary["capital_ratio"] == pytest.approx(
        summary["capital"] / summary["central_reserve"]
    )
    assert summary["fee_pv"] == pytest.approx(
        terms.reinsurer_coc
        * summary["capital_ratio"]
        * summary["reserve_years"]
        * summary["central_reserve"]
    )
    assert summary["fee_share_of_reserve"] == pytest.approx(
        terms.reinsurer_coc * summary["capital_ratio"] * summary["reserve_years"]
    )
    assert summary["fee_bps_per_year"] == pytest.approx(
        1e4 * terms.reinsurer_coc * summary["capital_ratio"]
    )
    assert 0 < summary["pool_share_of_variance"] < 0.5  # a block of thousands: trend dominates
    assert summary["capital"] >= summary["trend_capital"] * 0.95
    assert dist["reserve"].is_monotonic_increasing and dist["change_vs_central"].iloc[
        3
    ] == pytest.approx(0.0, abs=0.01)


# ── The numbers quoted in the chapter come from the shipped database ─────────


@pytest.fixture(scope="module")
def demo():
    path = ROOT / "app" / "data" / "demo.sqlite"
    if not path.exists():
        pytest.skip("demo database not built")
    con = sqlite3.connect(path)
    yield con
    con.close()


def test_chapter_numbers_match_the_database(demo):
    """Section 10.8: concentration, aggregate claims, covers, layers, rating and the swap."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    k = q("SELECT * FROM reinsurance_concentration")
    assert k["policies"].sum() == 392_274 and round(k["sum_at_risk"].sum() / 1e9) == 414
    big = k.iloc[-2:]
    assert (
        round(big["share_of_policies"].sum() * 100),
        round(big["share_of_sum_at_risk"].sum() * 100),
    ) == (13, 49)
    assert k.iloc[-1]["policies"] == 9669 and round(k.iloc[-1]["share_of_sum_at_risk"] * 100) == 19
    assert k["share_of_sum_at_risk"].to_numpy() == pytest.approx(
        k["share_of_expected_claims"].to_numpy(), abs=0.002
    )

    a = q("SELECT * FROM reinsurance_aggregate")
    assert (a["sd"] / 1e6).round().astype(int).tolist() == [49, 62, 74]
    assert (a["var_995"] / 1e6).round().astype(int).tolist() == [877, 915, 1042]
    assert (a["capital"] / 1e6).round().astype(int).tolist() == [136, 174, 294]
    assert round(a["mean"].iloc[1] / 1e6) == 741 and round(a["cv"].iloc[0] * 100, 1) == 6.7
    assert round((a["capital"].iloc[2] - a["capital"].iloc[1]) / a["capital"].iloc[2] * 100) == 41

    s = q("SELECT * FROM reinsurance_structures").set_index("structure")
    assert (
        round(s.loc["Quota share 20%", "price_of_relief"] * 100, 1)
        == round(s.loc["Quota share 40%", "price_of_relief"] * 100, 1)
        == 19.6
    )
    assert round(s.loc["Per-life XL 8M xs 1M", "price_of_relief"] * 100, 1) == 9.1
    assert round(s.loc["Stop loss, 100% xs 115% of expected claims", "relief_share"] * 100) == 60
    assert (
        round(s.loc["Stop loss, 100% xs 115% of expected claims", "price_of_relief"] * 100, 1)
        == 6.0
    )
    assert (
        round(s.loc["Per-life XL 8M xs 1M + stop loss on what is left", "relief_share"] * 100) == 62
    )
    assert [
        round(s.loc[n, "capital_relief"] / 1e6)
        for n in ("Surplus, retention 0.5M, 9 lines", "Per-life XL 16M xs 2M")
    ] == [159, 79]
    assert (
        round(s.loc["Stop loss, 100% xs 115% of expected claims", "expected_recoveries"] / 1e6, 1)
        == 4.6
    )
    worth = s["worth_buying"].astype(bool)
    assert worth[["Per-life XL 8M xs 1M", "Stop loss, 100% xs 115% of expected claims"]].all()
    assert not worth[["Quota share 20%", "Per-life XL 16M xs 2M"]].any()

    sens = q("SELECT * FROM reinsurance_price_sensitivity").set_index("reinsurer_coc")
    a_, b_ = sens.loc[0.06, "xl_price_of_relief"], sens.loc[0.07, "xl_price_of_relief"]
    assert round(a_ * 100, 1) == 9.1
    assert (
        round((0.06 + (0.10 - a_) / (b_ - a_) * 0.01) * 100, 1) == 6.9
    )  # crosses the cedant's 10%
    assert sens.loc[0.06, "cutoff_retention"] == pytest.approx(5.62e6, rel=0.01)
    assert round(sens.loc[0.06, "net_benefit"] / 1e6, 1) == 6.1
    assert sens.loc[0.07:, "cutoff_retention"].isna().all()
    assert sens["stop_loss_price_of_relief"].round(2).tolist() == [round(c, 2) for c in sens.index]

    y = q("SELECT * FROM reinsurance_yrt_rating").set_index(["dimension", "level"])
    assert y["claim_size_cv2"].min() > 1.6 and y["claim_size_cv2"].max() < 2.12
    row = y.loc[("uw_class", "PREFERRED")]
    assert (row["deaths"], round(row["ae_amount"], 3), round(row["experience_factor"], 3)) == (
        365,
        0.465,
        0.816,
    )
    assert round(row["credibility"] * 100) == 34 or round(row["credibility"] * 100) == 35
    agent = y.loc[("channel", "AGENT")]
    assert (round(agent["rate_change"] * 100), round(agent["loss_ratio_at_manual"], 2)) == (
        -29,
        0.56,
    )
    rated = y.loc[("uw_class", "RATED")]
    assert (round(rated["rate_change"] * 100, 1), round(rated["loss_ratio_at_manual"], 2)) == (
        2.5,
        0.93,
    )

    sw = q("SELECT * FROM reinsurance_longevity_swap").iloc[0]
    assert round(sw["central_reserve"] / 1e6) == 24992 and round(sw["sd_reserve"] / 1e6) == 291
    assert round(sw["pool_sd"] / 1e6) == 77 and round(sw["capital"] / 1e6) == 761
    assert round(sw["reserve_years"], 1) == 8.9 and round(sw["fee_pv"] / 1e6) == 405
    assert round(sw["fee_share_of_reserve"] * 100, 1) == 1.6 and round(sw["fee_bps_per_year"]) == 18
    assert round(sw["pool_share_of_variance"] * 100, 1) == 6.9
    assert sw["fee_pv"] == pytest.approx(
        0.06 * sw["capital_ratio"] * sw["reserve_years"] * sw["central_reserve"], rel=1e-9
    )
    dist = q("SELECT * FROM reinsurance_longevity_distribution").set_index("level")
    assert round(dist.loc[0.995, "change_vs_central"] * 100, 1) == 3.1
