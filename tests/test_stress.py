"""Stress tests: pandemic replay on a book, longevity on an annuity block."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import stress

LABELS = ["0", "1-4", "5-9"] + [f"{a}-{a + 4}" for a in range(10, 85, 5)] + ["85+"]


def excess_frame(score=0.5, young=-0.2) -> pd.DataFrame:
    rows = []
    for sex in ("M", "F"):
        for band, label in enumerate(LABELS):
            rows.append(
                {"year": 2021, "sex": sex, "band": band, "age_group": label,
                 "p_score": young if band < 5 else score}
            )  # fmt: skip
    return pd.DataFrame(rows)


def make_book(n=200, seed=1) -> stress.Book:
    rng = np.random.default_rng(seed)
    inforce = pd.DataFrame(
        {
            "sex": rng.choice(["M", "F"], n),
            "attained_age": rng.integers(20, 80, n),
            "duration": rng.integers(1, 12, n),
            "sum_assured": rng.uniform(1e5, 2e6, n),
            "product": "TERM",
        }
    )
    q_all = 0.0005 * np.exp(0.085 * np.arange(111))
    return stress.Book(inforce, stress.first_year_q(inforce, np.minimum(q_all, 1.0), None))


def cube(years=8) -> np.ndarray:
    ages = np.arange(111)
    base = np.minimum(0.0005 * np.exp(0.09 * ages), 0.5)
    return np.array([base * 0.985**t for t in range(years)])


def test_pscore_spreads_bands_over_ages_and_floors_at_zero():
    p = stress.pscore_by_age(excess_frame(score=0.5, young=-0.2), 2021)
    assert p["M"].shape == (111,)
    assert p["M"][10] == 0.0  # negative excess is not a credit
    assert p["M"][19] == 0.0 and p["M"][20] == 0.5
    assert p["F"][65] == 0.5 and p["F"][110] == 0.5  # the open band covers older ages


def test_first_year_q_applies_the_multiplier_by_sex_and_duration():
    inforce = pd.DataFrame({"sex": ["M", "F"], "attained_age": [40, 40], "duration": [1, 1]})
    q_all = np.full(111, 0.01)
    lookup = {("M", "1"): np.full(111, 0.5)}
    q = stress.first_year_q(inforce, q_all, lookup)
    assert q[0] == pytest.approx(0.005)
    assert q[1] == pytest.approx(0.01)


def test_stress_is_linear_in_severity_and_dampening():
    book = make_book()
    scores = stress.pscore_by_age(excess_frame(), 2021)
    base = book.claims
    one = stress.stressed_claims(book, scores, 1.0, 1.0).sum() - base
    half = stress.stressed_claims(book, scores, 0.5, 1.0).sum() - base
    double = stress.stressed_claims(book, scores, 1.0, 2.0).sum() - base
    none = stress.stressed_claims(book, scores, 0.0, 1.0).sum() - base
    assert one > 0
    assert half == pytest.approx(one / 2)
    assert double == pytest.approx(2 * one)
    assert none == pytest.approx(0.0)


def test_replay_uplift_lies_between_the_smallest_and_largest_p_score():
    book = make_book()
    table = stress.pandemic_scenarios(
        book, excess_frame(0.5), years=(2021,), dampenings=(1.0,), severities=(2.0,)
    )
    replay = table[table["kind"] == "replay"].iloc[0]
    assert 0.0 < replay["extra_pct"] <= 0.5
    severe = table[table["kind"] == "severity"].iloc[0]
    assert severe["extra_pct"] == pytest.approx(2 * replay["extra_pct"])


def test_regulatory_row_reports_the_heavier_table():
    book = make_book()
    table = stress.pandemic_scenarios(
        book, excess_frame(), q_regulatory=np.minimum(book.q * 1.4, 1.0), years=(2021,),
        dampenings=(1.0,), severities=(),
    )  # fmt: skip
    reg = table[table["kind"] == "regulatory"].iloc[0]
    assert reg["extra_pct"] == pytest.approx(0.4)


def insured_frame(index=2.0) -> pd.DataFrame:
    rows = []
    for sex in ("M", "F"):
        for band, value in (("25-44", index), ("45-64", index + 0.5), ("65-79", 0.9)):
            rows.append(
                {
                    "source": "insured",
                    "year": 2021,
                    "sex": sex,
                    "band": band,
                    "index_vs_2023": value,
                }
            )
    rows.append(
        {"source": "population", "year": 2021, "sex": "M", "band": "25-44", "index_vs_2023": 9.0}
    )
    return pd.DataFrame(rows)


def test_insured_pscores_come_from_the_insured_rates_and_never_go_below_zero():
    p = stress.insured_pscores(insured_frame(2.0), 2021)
    assert p["M"][30] == pytest.approx(1.0)  # twice its 2023 rate: a P-score of 1
    assert p["M"][50] == pytest.approx(1.5)
    assert p["M"][70] == 0.0  # 0.9 of 2023 is not a credit
    assert p["M"][18] == pytest.approx(1.0) and p["M"][20] == pytest.approx(1.0)  # below the bands
    assert p["F"][100] == 0.0  # above the bands: the last band's value
    assert p["M"][30] != 9.0 - 1.0  # the population row is ignored


def test_the_observed_insured_scenario_adds_claims_beyond_the_dampened_replays():
    book = make_book()
    scores = {2021: stress.insured_pscores(insured_frame(), 2021)}
    table = stress.pandemic_scenarios(
        book, excess_frame(0.3), years=(2021,), dampenings=(1.0,), severities=(),
        insured_scores=scores,
    )  # fmt: skip
    observed = table[table["kind"] == "observed"].iloc[0]
    replay = table[table["kind"] == "replay"].iloc[0]
    assert observed["scenario"] == "2021 as insured lives lived it"
    assert observed["extra_pct"] > replay["extra_pct"]  # insured lives were not shielded
    # without insured scores the table is unchanged
    plain = stress.pandemic_scenarios(
        book, excess_frame(0.3), years=(2021,), dampenings=(1.0,), severities=()
    )
    assert set(plain["kind"]) == {"replay"}


def test_by_age_table_adds_up_to_the_scenario():
    book = make_book()
    excess = excess_frame()
    by_age = stress.pandemic_by_age(book, excess, 2021)
    total = stress.pandemic_scenarios(
        book, excess, years=(2021,), dampenings=(1.0,), severities=()
    )["extra_claims"].iloc[0]
    assert by_age["extra_claims"].sum() == pytest.approx(total)
    assert by_age["share_of_extra"].sum() == pytest.approx(1.0)


def test_annuity_due_with_constant_q_matches_the_geometric_series():
    q = np.full((1, 400), 0.05)
    v = 1 / 1.04
    expected = 1 / (1 - v * 0.95)
    assert stress.annuity_due_from_q(q, 0.04)[0] == pytest.approx(expected, rel=1e-6)


def test_cohort_paths_follow_the_diagonal_and_scale_the_improvement():
    c = cube()
    ages = np.array([60, 70])
    q1 = stress.cohort_q_paths(c, ages, 1.0)
    q0 = stress.cohort_q_paths(c, ages, 0.0)
    q2 = stress.cohort_q_paths(c, ages, 2.0)
    assert q1[0, 3] == pytest.approx(c[3, 63])
    assert q0[0, 3] == pytest.approx(c[0, 63])
    assert q2[0, 3] == pytest.approx(c[0, 63] * (c[3, 63] / c[0, 63]) ** 2)
    assert q1[0, -1] == 1.0  # everyone dies by the end of the table
    low = stress.cohort_q_paths(c, ages, 1.0, level=0.8)
    assert low[0, 3] == pytest.approx(0.8 * q1[0, 3])


def test_reserves_rise_with_improvement_and_with_lower_interest():
    c = cube()
    block = stress.AnnuityBlock(lives=1000)

    def make(scale=1.0, level=1.0):
        return {s: (lambda ages: stress.cohort_q_paths(c, ages, scale, level)) for s in "MF"}

    none = stress.annuity_reserves(block, make(0.0))["reserve_T"]
    central = stress.annuity_reserves(block, make(1.0))["reserve_T"]
    double = stress.annuity_reserves(block, make(2.0))["reserve_T"]
    light = stress.annuity_reserves(block, make(1.0, 0.8))["reserve_T"]
    cheap = stress.annuity_reserves(block, make(1.0), interest=0.03)["reserve_T"]
    assert none < central < double
    assert central < light
    assert central < cheap


def test_block_weights_sum_to_one_and_reserve_scales_with_lives():
    c = cube()
    q_all = c[0]
    block = stress.AnnuityBlock(lives=1000)
    assert block.weights(q_all).sum() == pytest.approx(1.0)
    make = {s: (lambda ages: stress.period_q_paths(q_all, ages)) for s in "MF"}
    small = stress.annuity_reserves(block, make)["reserve_T"]
    big = stress.annuity_reserves(stress.AnnuityBlock(lives=2000), make)["reserve_T"]
    assert big == pytest.approx(2 * small)


def test_pandemic_releases_annuity_reserve_in_proportion_to_the_excess():
    c = cube()
    block = stress.AnnuityBlock(lives=1000)
    make = {s: (lambda ages: stress.cohort_q_paths(c, ages)) for s in "MF"}
    scores = stress.pscore_by_age(excess_frame(), 2021)
    release = stress.annuity_release(block, make, scores)
    assert release < 0
    assert stress.annuity_release(block, make, scores, dampening=0.5) == pytest.approx(release / 2)
    assert stress.annuity_release(block, make, scores, dampening=0.0) == 0.0
