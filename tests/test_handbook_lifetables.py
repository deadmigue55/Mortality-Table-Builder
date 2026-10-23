"""Numerical proof of the formulas in docs/handbook/05-life-tables.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

import numpy as np
import pytest

from mortality.lifetable import (
    Commutation,
    average_years_in_death_year,
    build_life_table,
    lifespan_disparity,
    median_age_at_death,
    summary,
)

AGES = np.arange(0, 111)


def gompertz_makeham(radix: float = 100_000):
    """A smooth table closed at 110, used wherever the handbook says 'a Gompertz-Makeham table'."""
    mu = 0.0005 + 0.00004 * np.exp(0.1 * AGES)
    q = 1 - np.exp(-mu)
    q[-1] = 1.0
    return q, build_life_table(AGES, q, radix=radix)


@pytest.fixture(scope="module")
def gm():
    q, table = gompertz_makeham()
    return q, table, Commutation.from_table(table, 0.04)


# ── 5.1 to 5.3: the table ────────────────────────────────────────────────────


def test_survivors_deaths_and_the_radix(gm):
    q, t, _ = gm
    ell, d = t["lx"].to_numpy(), t["dx"].to_numpy()
    assert np.allclose(ell[1:], ell[:-1] * (1 - q[:-1]))  # (5.1)
    assert np.allclose(d, ell * q)
    assert d.sum() == pytest.approx(ell[0])  # the deaths add up to the radix
    kp = ell[30 + 10] / ell[30]  # (5.2): survive ten years from 30
    assert kp == pytest.approx(np.prod(1 - q[30:40]))


def test_last_age_must_close_the_table():
    with pytest.raises(ValueError):
        build_life_table(np.arange(3), np.array([0.1, 0.2, 0.3]))  # q at omega is not 1


def test_separation_factor_roundtrip():
    rng = np.random.default_rng(7)
    q = rng.uniform(0.001, 0.9, 500)
    phi = rng.uniform(0.05, 0.95, 500)
    m = q / (1 - (1 - phi) * q)  # m in terms of q and phi
    assert np.allclose(average_years_in_death_year(q, m), phi)  # (5.5), second form
    assert np.allclose(m / (1 + (1 - phi) * m), q)  # (5.5), first form
    assert np.allclose(average_years_in_death_year(q, m), 1 - (m / q - 1) / m)


def test_udd_means_half_a_year():
    q = np.array([0.01, 0.2, 0.7])
    m = q / (1 - 0.5 * q)  # UDD: phi = 1/2
    assert np.allclose(average_years_in_death_year(q, m), 0.5)


def test_person_years_and_life_expectancy_recursion(gm):
    q, t, _ = gm
    ell, d, a = t["lx"].to_numpy(), t["dx"].to_numpy(), t["ax"].to_numpy()
    big_l, big_t, e = t["Lx"].to_numpy(), t["Tx"].to_numpy(), t["ex"].to_numpy()
    assert np.allclose(big_l[:-1], ell[1:] + a[:-1] * d[:-1])  # (5.4)
    assert np.allclose(big_t, np.cumsum(big_l[::-1])[::-1])  # (5.6)
    assert np.allclose(e, big_t / ell)
    p = 1 - q
    assert np.allclose(e[:-1], p[:-1] + a[:-1] * q[:-1] + p[:-1] * e[1:])  # (5.7)


def test_open_last_interval_uses_the_central_rate():
    q = np.array([0.1, 0.5, 1.0])
    table = build_life_table(np.arange(3), q, radix=1000, terminal_mx=0.8)
    last = table.iloc[-1]
    assert last["Lx"] == pytest.approx(last["lx"] / 0.8)  # (5.8)
    assert last["ex"] == pytest.approx(1 / 0.8)


# ── 5.4: both sexes ──────────────────────────────────────────────────────────


def test_pooled_central_rate_is_the_exposure_weighted_mix():
    rng = np.random.default_rng(3)
    exp_m, exp_f = rng.uniform(1e4, 9e4, 50), rng.uniform(1e4, 9e4, 50)
    m_m, m_f = rng.uniform(0.001, 0.2, 50), rng.uniform(0.001, 0.2, 50)
    deaths = m_m * exp_m + m_f * exp_f
    pooled = deaths / (exp_m + exp_f)
    w = exp_m / (exp_m + exp_f)
    assert np.allclose(pooled, w * m_m + (1 - w) * m_f)  # (5.9), exact for m


# ── 5.5: summary measures ────────────────────────────────────────────────────


def test_summary_measures_on_the_toy_table():
    toy = build_life_table(np.arange(5), np.array([0.1, 0.2, 0.4, 0.5, 1.0]), radix=1000)
    assert lifespan_disparity(toy) == pytest.approx(
        1.1088, abs=1e-4
    )  # (5.12), by hand: 1108.8/1000
    assert median_age_at_death(toy) == pytest.approx(2 + 0.22 / 0.288)  # (5.11)
    s = summary(build_life_table(AGES, gompertz_makeham()[0]))
    assert s["q5_0"] == pytest.approx(1 - gompertz_makeham()[1]["lx"].iloc[5] / 100_000)  # (5.10)


def test_adult_mortality_and_modal_age(gm):
    _, t, _ = gm
    s = summary(t)
    ell = t.set_index("age")["lx"]
    assert s["q45_15"] == pytest.approx(1 - ell[60] / ell[15])  # (5.10)
    adult = t[t["age"] >= 10]
    assert s["modal_age_at_death"] == adult.loc[adult["dx"].idxmax(), "age"]


# ── 5.6: commutation functions ───────────────────────────────────────────────


def direct_sums(t, i, x):
    """Present values by summing over future years, with no commutation columns at all."""
    v = 1 / (1 + i)
    ell = t["lx"].to_numpy()
    q = t["qx"].to_numpy()
    ks = np.arange(0, len(ell) - x)
    kp = ell[x + ks] / ell[x]
    a_due = np.sum(v**ks * kp)
    ins = np.sum(v ** (ks + 1) * kp * q[x + ks])
    inc = np.sum((ks + 1) * v ** (ks + 1) * kp * q[x + ks])
    return a_due, ins, inc


@pytest.mark.parametrize("x", [0, 20, 40, 65, 90, 109])
def test_commutation_matches_direct_sums(gm, x):
    _, t, c = gm
    a_due, ins, inc = direct_sums(t, 0.04, x)
    assert float(c.annuity_due(x)) == pytest.approx(a_due, rel=1e-12)  # (5.16)
    assert float(c.whole_life_insurance(x)) == pytest.approx(ins, rel=1e-12)  # (5.15)
    assert float(c.increasing_whole_life(x)) == pytest.approx(inc, rel=1e-12)  # (IA)_x = R/D
    v, ell = 1 / 1.04, t["lx"].to_numpy()
    n = min(10, 110 - x)
    assert float(c.pure_endowment(x, n)) == pytest.approx(v**n * ell[x + n] / ell[x])  # (5.13)
    # term, deferred and endowment assembled from the same sums
    q = t["qx"].to_numpy()
    ks = np.arange(0, n)
    term = np.sum(v ** (ks + 1) * (ell[x + ks] / ell[x]) * q[x + ks])
    assert float(c.term_insurance(x, n)) == pytest.approx(term)
    assert float(c.deferred_insurance(x, n)) == pytest.approx(ins - term)
    assert float(c.endowment_insurance(x, n)) == pytest.approx(term + v**n * ell[x + n] / ell[x])
    temp = np.sum(v**ks * (ell[x + ks] / ell[x]))
    assert float(c.temporary_annuity_due(x, n)) == pytest.approx(temp)
    assert float(c.annuity_immediate(x)) == pytest.approx(a_due - 1)
    assert float(c.deferred_annuity_due(x, n)) == pytest.approx(a_due - temp)


def test_columns_are_running_sums(gm):
    _, t, c = gm
    v = 1 / 1.04
    assert np.allclose(c.D, v ** t["age"].to_numpy() * t["lx"].to_numpy())  # (5.14)
    assert np.allclose(c.C, v ** (t["age"].to_numpy() + 1) * t["dx"].to_numpy())
    assert np.allclose(c.N, np.cumsum(c.D[::-1])[::-1])
    assert np.allclose(c.M, np.cumsum(c.C[::-1])[::-1])
    assert np.allclose(c.S, np.cumsum(c.N[::-1])[::-1])
    assert np.allclose(c.R, np.cumsum(c.M[::-1])[::-1])
    # R counts each C_z once for every y from x to z, so R_x = sum (z - x + 1) C_z
    x = 30
    z = np.arange(x, 111)
    assert c.R[x] == pytest.approx(np.sum((z - x + 1) * c.C[z]))


def test_outside_the_table():
    t = build_life_table(np.arange(12, 16), np.array([0.1, 0.2, 0.5, 1.0]), radix=1000)
    c = Commutation.from_table(t, 0.04)
    assert np.isnan(c.annuity_due(5))  # below the first age: undefined
    assert float(c.pure_endowment(14, 3)) == 0.0  # a benefit payable beyond omega is worth nothing
    with np.errstate(invalid="ignore"):
        assert np.isnan(c.annuity_due(40))  # a life already older than omega: 0/0, undefined


def test_recursions_and_the_insurance_annuity_identity(gm):
    q, _, c = gm
    v, d = c.v, c.discount_rate
    p = 1 - q[:-1]
    a, big_a = c.annuity_due(AGES), c.whole_life_insurance(AGES)
    assert np.allclose(a[:-1], 1 + v * p * a[1:])  # (5.17)
    assert np.allclose(big_a[:-1], v * q[:-1] + v * p * big_a[1:])  # (5.17)
    assert np.allclose(big_a, 1 - d * a)  # (5.18), at every age
    assert d == pytest.approx(1 - v) and d == pytest.approx(0.04 / 1.04)


# ── 5.7: premiums and reserves ───────────────────────────────────────────────


@pytest.mark.parametrize(("x", "t"), [(30, 5), (40, 20), (65, 10)])
def test_reserves_prospective_retrospective_and_fackler(gm, x, t):
    q, _, c = gm
    p_x = float(c.whole_life_premium(x))
    assert p_x == pytest.approx(1 / float(c.annuity_due(x)) - c.discount_rate)  # (5.19)
    pro = float(c.whole_life_reserve(x, t))
    assert pro == pytest.approx(1 - float(c.annuity_due(x + t)) / float(c.annuity_due(x)))  # (5.20)
    n, m, d_col = c.N, c.M, c.D
    retro = (p_x * (n[x] - n[x + t]) - (m[x] - m[x + t])) / d_col[x + t]  # (5.21)
    assert pro == pytest.approx(retro, abs=1e-12)
    # Fackler (5.22): (tV + P)(1 + i) = q_{x+t} + p_{x+t} * (t+1)V
    nxt = float(c.whole_life_reserve(x, t + 1))
    assert (pro + p_x) * 1.04 == pytest.approx(q[x + t] + (1 - q[x + t]) * nxt)


def test_term_premium_is_the_equivalence_premium(gm):
    _, _, c = gm
    x, n = 40, 20
    prem = float(c.term_premium(x, n))
    assert prem * float(c.temporary_annuity_due(x, n)) == pytest.approx(
        float(c.term_insurance(x, n))
    )
    end = float(c.endowment_premium(x, n))
    assert end * float(c.temporary_annuity_due(x, n)) == pytest.approx(
        float(c.endowment_insurance(x, n))
    )


# ── 5.8: payments more often than yearly ─────────────────────────────────────


@pytest.mark.parametrize("m", [2, 4, 12])
def test_monthly_payments(gm, m):
    _, t, c = gm
    i, v, d = 0.04, 1 / 1.04, 0.04 / 1.04
    im, dm = m * ((1 + i) ** (1 / m) - 1), m * (1 - v ** (1 / m))
    alpha, beta = i * d / (im * dm), (i - im) / (im * dm)  # (5.23)
    for x in (30, 50, 65, 80):
        exact = alpha * float(c.annuity_due(x)) - beta
        wool = float(c.annuity_due_monthly(x, m))  # (5.24)
        assert wool == pytest.approx(float(c.annuity_due(x)) - (m - 1) / (2 * m))
        assert abs(wool - exact) < 0.006  # the bound quoted in 5.8
    # (5.25): the UDD factor equals the direct monthly sum of discount factors
    direct = (1 / m) * sum(v ** (j / m) for j in range(1, m + 1))
    assert c.udd_factor(m) * v == pytest.approx(direct)
    x = 40
    ell, q = t["lx"].to_numpy(), t["qx"].to_numpy()
    ks = np.arange(0, 111 - x)
    a_m = np.sum(v**ks * (ell[x + ks] / ell[x]) * q[x + ks] * direct)
    assert float(c.whole_life_insurance(x)) * c.udd_factor(m) == pytest.approx(a_m)


# ── 5.9: the worked example ──────────────────────────────────────────────────


def test_toy_table_matches_the_handbook():
    t = build_life_table(np.arange(5), np.array([0.1, 0.2, 0.4, 0.5, 1.0]), radix=1000)
    assert t["lx"].tolist() == [1000, 900, 720, 432, 216]
    assert t["dx"].tolist() == [100, 180, 288, 216, 216]
    assert t["Lx"].tolist() == [950, 810, 576, 324, 108]
    assert t["Tx"].tolist() == [2768, 1818, 1008, 432, 108]
    assert t["ex"].round(3).tolist() == [2.768, 2.020, 1.400, 1.000, 0.500]
    c = Commutation.from_table(t, 0.05)
    assert c.D.round(4).tolist() == [1000.0, 857.1429, 653.0612, 373.1778, 177.7037]
    assert c.C.round(4).tolist() == [95.2381, 163.2653, 248.7852, 177.7037, 169.2417]
    assert c.N.round(4).tolist() == [3061.0857, 2061.0857, 1203.9428, 550.8816, 177.7037]
    assert c.M.round(4).tolist() == [854.2340, 758.9959, 595.7306, 346.9454, 169.2417]
    assert round(float(c.whole_life_insurance(0)), 5) == 0.85423
    assert round(float(c.annuity_due(0)), 5) == 3.06109
    assert round(1 - c.discount_rate * float(c.annuity_due(0)), 5) == 0.85423
    assert round(float(c.pure_endowment(0, 3)), 5) == 0.37318
    assert round(float(c.term_insurance(0, 3)), 5) == 0.50729
    assert round(float(c.temporary_annuity_due(0, 3)), 5) == 2.51020
    assert round(float(c.term_premium(0, 3)), 5) == 0.20209
    assert round(float(c.whole_life_premium(0)), 5) == 0.27906
    assert round(float(c.whole_life_reserve(0, 1)), 5) == 0.21446


# ── 5.10: the closed-form benchmark ──────────────────────────────────────────


def test_constant_force_benchmark():
    mu, i = 0.05, 0.04
    omega = 400
    age = np.arange(omega + 1)
    p = np.exp(-mu)
    q = np.full(omega + 1, 1 - p)
    q[-1] = 1.0
    phi = 1 / mu - 1 / np.expm1(mu)  # average time lived by those who die within a year
    table = build_life_table(age, q, ax=np.full(omega + 1, phi), terminal_mx=mu)
    # m = mu exactly, and the table's phi and q reproduce the central rate
    m = q[:-1] / (1 - (1 - phi) * q[:-1])
    assert np.allclose(m, mu)
    assert np.allclose(average_years_in_death_year(q[:-1], np.full(omega, mu)), phi)
    assert np.allclose(table["ex"].to_numpy()[:100], 1 / mu)  # e_x = 1/mu
    c = Commutation.from_table(table, i)
    v = 1 / (1 + i)
    for x in (0, 30, 100):
        assert float(c.annuity_due(x)) == pytest.approx(1 / (1 - v * p), rel=1e-9)
        assert float(c.whole_life_insurance(x)) == pytest.approx(
            v * (1 - p) / (1 - v * p), rel=1e-9
        )
    assert lifespan_disparity(table) == pytest.approx(1 / mu, rel=1e-4)  # e-dagger = e0


def test_every_equation_label_in_the_chapter_is_used_by_a_test():
    """The chapter's code map must not promise a check that does not exist in this file."""
    import re
    from pathlib import Path

    chapter = Path(__file__).parents[1] / "docs" / "handbook" / "05-life-tables.md"
    named = set(
        re.findall(r"test_handbook_lifetables\.py::(test_\w+)", chapter.read_text(encoding="utf-8"))
    )
    here = {name for name in globals() if name.startswith("test_")}
    assert named <= here, named - here
