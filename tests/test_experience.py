"""Tests for the experience study: validation, exposure, A/E, credibility, GLM, lag, basis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import experience as ex

START, END, EXTRACT = "2020-01-01", "2021-12-31", "2022-02-15"
NOTE_JUNE, NOTE_SEPT = pd.Timestamp("2021-06-20"), pd.Timestamp("2020-09-01")
NOTE_LATE = pd.Timestamp("2022-01-20")


def policy(pid, issue, status="IN_FORCE", exit_=None, **kw):
    row = {
        "policy_id": pid, "sex": "M", "birth_date": pd.Timestamp("1980-01-01"),
        "issue_date": pd.Timestamp(issue), "product": "TERM", "term_years": 20.0,
        "sum_assured": 500_000.0, "uw_class": "STANDARD", "channel": "AGENT", "state": "09",
        "status": status, "exit_date": pd.Timestamp(exit_) if exit_ else pd.NaT,
        "notification_date": pd.NaT,
    }  # fmt: skip
    row.update(kw)
    return row


def flat_q(value=0.01, top=110):
    q = pd.Series(value, index=range(0, top + 1))
    q.iloc[-1] = 1.0
    return q


def test_groupings_use_the_documented_edges():
    assert ex.age_group([18, 29, 30, 39, 40, 59, 60, 90]).tolist() == [
        "18-29", "18-29", "30-39", "30-39", "40-49", "50-59", "60+", "60+"
    ]  # fmt: skip
    assert ex.duration_group([1, 5, 6, 10, 11, 30]).tolist() == [
        "1",
        "5",
        "6-10",
        "6-10",
        "11+",
        "11+",
    ]
    assert ex.amount_band([100_000, 250_000, 999_999, 1_000_000, 5_000_000, 9e9]).tolist() == [
        "<250k", "250k-1M", "250k-1M", "1M-5M", "5M+", "5M+"
    ]  # fmt: skip


def test_validation_flags_each_defect_once_and_reconciles():
    rows = [
        policy("A", "2019-06-01"),
        policy("B", "2019-06-01", sex="X"),
        policy("C", "2019-06-01", birth_date=pd.Timestamp("2020-01-01")),
        policy("D", "2019-06-01", sum_assured=-5.0),
        policy("E", "2019-06-01", status="LAPSE", exit_="2019-01-01"),
        policy("F", "2030-01-01"),
        policy("G", "2019-06-01", state="ZZ"),
        policy("H", "2019-06-01", status="DEATH", exit_="2020-05-01"),
        policy("I", "2019-06-01", status="LAPSE"),  # a lapse with no exit date
        policy("J", "2019-06-01", status="IN_FORCE", exit_="2020-05-01"),  # in force with an exit
    ]
    rows.append(rows[0].copy())  # a duplicate of A
    clean, checks, recon = ex.validate_extract(pd.DataFrame(rows), END, EXTRACT)
    by = checks.set_index("check")["records"]
    assert by["duplicate_record"] == 1
    assert by["invalid_sex"] == 1
    assert by["birth_missing_or_after_issue"] == 1
    assert by["non_positive_sum_assured"] == 1
    assert by["exit_before_issue"] == 1
    assert by["issue_after_extract"] == 1
    assert by["invalid_state"] == 1
    assert by["death_without_notification"] == 1
    assert by["status_and_exit_date_disagree"] == 2
    assert set(clean["policy_id"]) == {"A", "G", "H"}  # G is repaired, H is kept
    assert clean.loc[clean["policy_id"] == "G", "state"].iloc[0] == "UNKNOWN"
    assert recon["records"].tolist() == [11, 1, 7, 3]  # one duplicate, seven other exclusions
    assert recon["deaths"].tolist() == [1, 0, 0, 1]
    assert (clean["issue_age"] == 39).all()


def test_validation_demands_the_required_columns():
    with pytest.raises(ValueError, match="lacks required columns"):
        ex.validate_extract(pd.DataFrame({"policy_id": ["A"]}), END, EXTRACT)


def test_exposure_by_hand():
    clean, _, _ = ex.validate_extract(
        pd.DataFrame(
            [
                policy("full", "2019-06-01"),
                policy("dies", "2019-06-01", "DEATH", "2021-06-01", notification_date=NOTE_JUNE),
                policy("lapses", "2020-07-01", "LAPSE", "2020-12-31"),
                policy("late", "2022-03-01"),
                policy("expired", "2019-01-01", "EXPIRED", "2020-02-01"),
            ]
        ),
        END, EXTRACT,
    )  # fmt: skip
    seg = ex.build_exposure(clean, START, END)
    days = lambda a, b: (np.datetime64(b) - np.datetime64(a)).astype(int)  # noqa: E731
    expected_total = (
        days("2020-01-01", "2021-12-31")  # full
        + days("2020-01-01", "2021-06-01")  # dies, left-truncated at the study start
        + days("2020-07-01", "2020-12-31")  # lapses
        + days("2020-01-01", "2020-02-01")  # expired
    ) / 365.25
    assert seg["exposure"].sum() == pytest.approx(expected_total)
    assert seg["deaths"].sum() == 1
    died = seg[seg["deaths"] == 1].iloc[0]
    assert died["end"] == np.datetime64("2021-06-01")
    assert died["attained_age"] == 39 + died["duration"] - 1  # issue age 39
    assert (seg["calendar_year"].between(2020, 2021)).all()
    assert seg["sum_assured"].eq(500_000.0).all()


def test_a_death_after_the_study_ends_is_exposure_not_a_death():
    clean, _, _ = ex.validate_extract(
        pd.DataFrame(
            [policy("late", "2019-06-01", "DEATH", "2022-01-10", notification_date=NOTE_LATE)]
        ),
        END,
        EXTRACT,
    )
    seg = ex.build_exposure(clean, START, END)
    assert seg["deaths"].sum() == 0
    assert seg["exposure"].sum() == pytest.approx(365 * 2 / 365.25, abs=0.01)


def test_expected_deaths_use_the_constant_force_of_the_table():
    seg = pd.DataFrame({"attained_age": [30, 40, 150], "exposure": [2.0, 0.5, 1.0]})
    q = pd.Series([0.01] * 31 + [0.02] * 10, index=range(0, 41))
    out = ex.add_expected(seg, q)
    assert out["expected"].tolist() == pytest.approx(
        [2.0 * -np.log(0.99), 0.5 * -np.log(0.98), 1.0 * -np.log(0.98)]  # age 150 uses the last q
    )


def test_actual_to_expected_intervals_and_credibility():
    cells = pd.DataFrame(
        {"g": ["a"], "exposure": [1000.0], "deaths": [10.0], "expected": [10.0],
         "exposure_amount": [1e9], "expected_amount": [1e7], "death_amount": [8e6],
         "death_amount_sq": [4e12]}
    )  # fmt: skip
    out = ex.actual_to_expected(cells, ["g"]).iloc[0]
    assert out["ae"] == 1.0
    assert out["ae_lower"] == pytest.approx(4.795 / 10, abs=1e-3)  # exact Poisson, 10 deaths
    assert out["ae_upper"] == pytest.approx(18.390 / 10, abs=1e-3)
    assert out["ae_amount"] == pytest.approx(0.8)
    assert out["ae_amount_upper"] - out["ae_amount"] == pytest.approx(1.959964 * 2e6 / 1e7)
    assert out["credibility"] == pytest.approx(np.sqrt(10 / 1082))
    z = out["credibility"]
    assert out["ae_credible"] == pytest.approx(z * 1.0 + (1 - z) * 1.0)


def test_limited_fluctuation_credibility_caps_at_one():
    assert ex.credibility_z([0, 270.5, 1082, 5000]).tolist() == pytest.approx([0.0, 0.5, 1.0, 1.0])


def simulate_classes(n_classes, n_periods, sd_true, expected_per_cell, seed):
    rng = np.random.default_rng(seed)
    theta = 1.0 + rng.normal(0.0, sd_true, n_classes)
    expected = np.full((n_classes, n_periods), float(expected_per_cell))
    deaths = rng.poisson(theta[:, None] * expected)
    return deaths / expected, expected, theta


def test_buhlmann_straub_recovers_the_variance_of_the_true_classes():
    ratios, weights, _ = simulate_classes(200, 8, 0.2, 100.0, 1)
    bs = ex.buhlmann_straub(ratios, weights)
    assert bs["grand_mean"] == pytest.approx(1.0, abs=0.03)
    assert bs["s2"] == pytest.approx(1.0, rel=0.1)  # Poisson ratios: variance = theta / expected
    assert bs["v"] == pytest.approx(0.04, rel=0.25)
    assert bs["k"] == pytest.approx(25.0, rel=0.3)
    assert ((bs["z"] > 0) & (bs["z"] < 1)).all()
    assert bs["z"].mean() == pytest.approx(800 / (800 + 25), abs=0.02)


def test_buhlmann_straub_gives_no_weight_to_classes_that_do_not_differ():
    ratios, weights, _ = simulate_classes(100, 6, 0.0, 100.0, 2)
    bs = ex.buhlmann_straub(ratios, weights)
    assert (bs["z"] <= 0.2).all()  # the classes do not differ by more than chance
    # shrinkage pulls every class toward the grand mean
    assert np.ptp(bs["credible_mean"]) < np.ptp(bs["class_mean"])


def test_buhlmann_straub_ignores_unobserved_cells():
    ratios, weights, _ = simulate_classes(30, 5, 0.2, 80.0, 3)
    ratios[:, 0] = np.nan
    bs = ex.buhlmann_straub(ratios, weights)
    assert np.isfinite(bs["k"]) and len(bs["z"]) == 30


def test_pool_adjacent_violators():
    assert ex.pool_adjacent_violators([1, 2, 3], [1, 1, 1]).tolist() == [1, 2, 3]
    assert ex.pool_adjacent_violators([3, 1], [1, 1]).tolist() == [2, 2]
    assert ex.pool_adjacent_violators([1, 3, 2, 4], [1, 1, 3, 1]).tolist() == pytest.approx(
        [1, 2.25, 2.25, 4]
    )
    out = ex.pool_adjacent_violators([0.5, 0.7, 0.65, 0.9, 0.8, 1.0], np.ones(6))
    assert (np.diff(out) >= -1e-12).all()


def test_binned_dispersion_is_one_for_poisson_and_large_when_overdispersed():
    rng = np.random.default_rng(0)
    # mostly cells that expect a small fraction of a death; 400,000 cells give about 1,600 bins,
    # so the estimate is accurate to about 0.035 (it is unbiased, but noisy with few bins)
    fitted = rng.gamma(0.5, 0.08, 400_000)
    poisson = rng.poisson(fitted)
    assert ex.binned_dispersion(poisson, fitted, 5) == pytest.approx(1.0, abs=0.12)
    big = rng.gamma(2.0, 2.0, 100_000)  # cells expecting about 4 deaths
    mixed = rng.poisson(big * rng.gamma(2.0, 0.5, len(big)))  # variance = mean x (1 + mean / 2)
    assert ex.binned_dispersion(mixed, big, 5) > 1.6


def synthetic_cells(seed=0, scale=4000.0):
    """Cells whose deaths follow an exact multiplicative model, with expected deaths as offset."""
    rng = np.random.default_rng(seed)
    levels = {
        "sex": ["M", "F"], "uw_class": ["STANDARD", "PREFERRED", "RATED"],
        "amount_band": ["250k-1M", "<250k"], "channel": ["AGENT", "BANK"], "product": ["TERM"],
        "duration_group": ["6-10", "1", "2"], "age_group": ["40-49", "30-39"],
        "calendar_year": [2019, 2018], "region": ["LOW", "HIGH"],
    }  # fmt: skip
    grid = pd.MultiIndex.from_product(list(levels.values()), names=list(levels)).to_frame(
        index=False
    )
    truth = {
        ("sex", "F"): 0.7, ("uw_class", "PREFERRED"): 0.8, ("uw_class", "RATED"): 1.5,
        ("amount_band", "<250k"): 1.2, ("channel", "BANK"): 1.1, ("duration_group", "1"): 0.55,
        ("duration_group", "2"): 0.75, ("age_group", "30-39"): 0.9, ("region", "HIGH"): 1.15,
    }  # fmt: skip
    mult = np.full(len(grid), 0.9)
    for (factor, level), value in truth.items():
        mult *= np.where(grid[factor] == level, value, 1.0)
    grid["expected"] = rng.gamma(4.0, scale / 4.0 / 100, len(grid))
    grid["deaths"] = rng.poisson(mult * grid["expected"]).astype(float)
    return grid, truth


def test_the_glm_recovers_a_known_multiplicative_model():
    cells, truth = synthetic_cells()
    fit = ex.fit_relativities(cells, list(ex.GLM_REFERENCE) if False else [
        "sex", "uw_class", "amount_band", "channel", "product", "duration_group", "age_group",
        "calendar_year", "region",
    ])  # fmt: skip
    t = fit["table"].set_index(["factor", "level"])
    inside = 0
    for (factor, level), value in truth.items():
        row = t.loc[(factor, str(level))]
        inside += int(row["lower"] <= value <= row["upper"])
        assert row["relativity"] == pytest.approx(value, rel=0.15)
    assert inside >= len(truth) - 1  # a 95% interval misses about one effect in twenty
    assert t.loc[("(intercept)", "")]["relativity"] == pytest.approx(0.9, rel=0.1)
    assert fit["dispersion"] == pytest.approx(1.0, abs=0.35)
    assert fit["n_deaths"] == cells["deaths"].sum()


def test_recovery_marks_whether_the_truth_is_inside_the_interval():
    est = pd.DataFrame({"factor": ["sex", "sex2"], "level": ["F", "F"], "relativity": [0.7, 1.0],
                        "lower": [0.6, 1.2], "upper": [0.8, 1.5]})  # fmt: skip
    planted = pd.DataFrame({"factor": ["sex", "sex2"], "level": ["F", "F"], "planted": [0.66, 1.0]})
    out = ex.recovery(est, planted)
    assert out["inside_interval"].tolist() == [True, False]
    assert out["error_pct"].iloc[0] == pytest.approx(0.7 / 0.66 - 1)


def test_planted_relativities_are_relative_to_the_reference_level():
    truth = {"sex": {"M": 1.2, "F": 0.6}, "uw_class": {"STANDARD": 1.0, "RATED": 1.5},
             "amount_band": {"250k-1M": 1.0}, "channel": {"AGENT": 1.0}, "product": {"TERM": 1.0},
             "age_group": {"40-49": 0.8, "60+": 0.4}}  # fmt: skip
    out = ex.planted_relativities(truth).set_index(["factor", "level"])["planted"]
    assert out[("sex", "F")] == pytest.approx(0.5)
    assert out[("age_group", "60+")] == pytest.approx(0.5)
    assert ("sex", "M") not in out.index


def test_the_select_table_finds_a_known_select_period():
    cells, _ = synthetic_cells(seed=4, scale=40_000.0)
    factors = list(ex.MAIN_FACTORS)
    sel = ex.select_table(cells, "duration_group", factors)
    assert sel["duration"].tolist() == [1, 2, 3, 4, 5]
    assert sel["relativity"].iloc[0] == pytest.approx(0.55, rel=0.15)
    assert sel["relativity"].iloc[1] == pytest.approx(0.75, rel=0.15)
    assert sel["select_period"].iloc[0] == 2
    finite = sel["smoothed"].dropna()
    assert len(finite) == 2 and (np.diff(finite) >= -1e-12).all()  # only durations 1 and 2 exist
    assert finite.max() <= 1.0


def lag_frame(n=3000, seed=0, extract="2024-08-15", median=30.0, sigma=1.1):
    rng = np.random.default_rng(seed)
    exit_ = np.datetime64("2021-01-01") + rng.integers(0, 365 * 3, n).astype("timedelta64[D]")
    lag = np.ceil(np.exp(rng.normal(np.log(median), sigma, n))).astype(int)
    return pd.DataFrame(
        {
            "status": "DEATH",
            "exit_date": exit_,
            "notification_date": exit_ + lag.astype("timedelta64[D]"),
        }
    ), lag


def test_lag_distribution_and_completion():
    frame, lag = lag_frame()
    grid, cdf = ex.estimate_lag_distribution(frame, "2024-08-15")
    assert (np.diff(cdf) >= 0).all() and cdf[-1] == pytest.approx(1.0)
    assert grid[np.searchsorted(cdf, 0.5)] == pytest.approx(np.median(lag), abs=3)
    quarters = [(2023, 4), (2024, 1), (2024, 2)]
    comp = ex.completion_by_quarter(grid, cdf, "2024-08-15", quarters)
    assert comp[(2023, 4)] > comp[(2024, 1)] > comp[(2024, 2)]
    assert comp[(2023, 4)] > 0.95
    assert 0.6 < comp[(2024, 2)] < 0.95


def test_too_few_mature_deaths_cannot_give_a_lag():
    frame, _ = lag_frame(n=10)
    with pytest.raises(ValueError, match="Too few"):
        ex.estimate_lag_distribution(frame, "2024-08-15")


def test_quarterly_experience_shares_exposure_and_places_deaths():
    clean, _, _ = ex.validate_extract(
        pd.DataFrame(
            [policy("a", "2019-06-01"),
             policy("b", "2019-06-01", "DEATH", "2020-08-10", notification_date=NOTE_SEPT)]
        ), END, EXTRACT)  # fmt: skip
    seg = ex.add_expected(ex.build_exposure(clean, START, END), flat_q())
    q = ex.quarterly_experience(seg)
    assert q["exposure"].sum() == pytest.approx(seg["exposure"].sum())
    assert q["expected"].sum() == pytest.approx(seg["expected"].sum())
    assert q["deaths"].sum() == 1
    assert q.loc[q["deaths"] == 1, ["year", "quarter"]].iloc[0].tolist() == [2020, 3]
    done = ex.quarterly_experience(seg, pd.Series({(2020, 3): 0.5}))
    assert (
        done.loc[(done["year"] == 2020) & (done["quarter"] == 3), "deaths_completed"].iloc[0] == 2.0
    )


def test_term_net_premium_by_hand():
    q = np.array([[0.1, 0.1]])
    # claims 0.1/1 + 0.9 * 0.1 / 1 = 0.19 ; annuity 1 + 0.9 = 1.9 ; premium 0.1
    assert ex.term_net_premium(q, 0.0)[0] == pytest.approx(0.1)
    discounted = ex.term_net_premium(q, 0.25)[0]
    assert discounted == pytest.approx((0.1 / 1.25 + 0.9 * 0.1 / 1.25**2) / (1 + 0.9 / 1.25))


def test_present_value_of_death_benefits_by_hand():
    block = pd.DataFrame({"sex": ["M"], "attained_age": [40], "duration": [7], "years_left": [2],
                          "sum_assured": [1000.0]})  # fmt: skip
    q = flat_q(0.1)
    out = ex.pv_death_benefits(block, q, None, interest=0.0)
    assert out["pv_cnsf"].iloc[0] == pytest.approx(1000 * (0.1 + 0.9 * 0.1))
    assert out["claims_next_12m_cnsf"].iloc[0] == pytest.approx(100.0)
    assert out["pv_experience"].iloc[0] == out["pv_cnsf"].iloc[0]  # no basis: nothing changes
    basis = pd.DataFrame(
        [{"sex": s, "age": a, "duration_group": d, "multiplier": 0.5, "multiplier_upper": 0.6}
         for s in "MF" for a in range(18, 101) for d in ex.DURATION_LABELS]
    )  # fmt: skip
    half = ex.pv_death_benefits(block, q, basis, interest=0.0)
    assert half["pv_experience"].iloc[0] == pytest.approx(1000 * (0.05 + 0.95 * 0.05))
    assert half["claims_next_12m_experience"].iloc[0] == pytest.approx(50.0)


def test_the_inforce_block_has_age_duration_and_years_left():
    clean, _, _ = ex.validate_extract(
        pd.DataFrame(
            [policy("t", "2015-03-01", term_years=10.0),
             policy("w", "2015-03-01", term_years=np.nan),
             policy("x", "2015-03-01", "LAPSE", "2018-01-01")]
        ), END, EXTRACT)  # fmt: skip
    block = ex.inforce_block(clean, "2021-12-31")
    assert set(block["policy_id"]) == {"t", "w"}
    t = block[block["policy_id"] == "t"].iloc[0]
    assert (t["attained_age"], t["duration"], t["years_left"]) == (35 + 6, 7, 4)
    w = block[block["policy_id"] == "w"].iloc[0]
    assert w["years_left"] == 111 - 41
