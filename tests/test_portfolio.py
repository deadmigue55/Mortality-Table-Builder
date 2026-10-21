"""Tests for the synthetic portfolio and for the whole study run on it."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import experience as ex
from mortality import lexis
from mortality import portfolio as pf


def basis_q(scale=1.0):
    """A smooth annual q by age 0 to 110, closing at 1 (a stand-in for the CNSF table)."""
    age = np.arange(0, 111)
    q = np.minimum(scale * 0.0004 * np.exp(0.085 * np.maximum(age - 20, 0)) + 0.0004, 1.0)
    q[-1] = 1.0
    return q


@pytest.fixture(scope="module")
def small():
    spec = pf.PortfolioSpec(n_policies=30_000, seed=7, q_basis=basis_q(4.0))
    return pf.generate_portfolio(spec), spec


def test_the_same_seed_gives_the_same_portfolio():
    a = pf.generate_portfolio(pf.PortfolioSpec(n_policies=2_000, seed=3, q_basis=basis_q()))
    b = pf.generate_portfolio(pf.PortfolioSpec(n_policies=2_000, seed=3, q_basis=basis_q()))
    c = pf.generate_portfolio(pf.PortfolioSpec(n_policies=2_000, seed=4, q_basis=basis_q()))
    pd.testing.assert_frame_equal(a.policies, b.policies)
    assert not a.policies.equals(c.policies)


def test_a_basis_is_required():
    with pytest.raises(ValueError, match="q_basis"):
        pf.generate_portfolio(pf.PortfolioSpec(n_policies=10))


def test_the_planted_force_is_the_product_of_its_factors():
    q = basis_q()
    args = dict(
        q_basis=q, attained_age=np.array([45]), duration=np.array([3]),
        calendar_year=np.array([2018]),
        sex=np.array(["F"]), uw_class=np.array(["PREFERRED"]), amount_band_=np.array(["5M+"]),
        channel=np.array(["BANK"]), product=np.array(["ENDOWMENT"]), state_smr=np.array([1.21]),
    )  # fmt: skip
    t = pf.TRUTH
    expected = (
        -np.log1p(-q[45]) * t["base"] * t["sex"]["F"] * t["age_group"]["40-49"]
        * t["uw_class"]["PREFERRED"] * t["amount_band"]["5M+"] * t["channel"]["BANK"]
        * t["product"]["ENDOWMENT"] * t["select_full"][2] * 1.21 ** t["state_exponent"]
        * (1 + t["trend_per_year"]) ** 4
    )  # fmt: skip
    assert pf.true_force(**args)[0] == pytest.approx(expected)
    simplified = pf.true_force(**{**args, "uw_class": np.array(["SIMPLIFIED"])})[0]
    ratio = simplified / pf.true_force(**{**args, "uw_class": np.array(["STANDARD"])})[0]
    assert ratio == pytest.approx(
        t["uw_class"]["SIMPLIFIED"] * t["select_simplified"][2] / t["select_full"][2]
    )


def test_covid_excess_peaks_at_sixty_in_the_pandemic_years_only():
    ages = np.array([20, 60, 90])
    assert (pf.covid_excess(ages, np.full(3, 2019)) == 0).all()
    e = pf.covid_excess(ages, np.full(3, 2021))
    assert e[1] == pytest.approx(0.80) and e[0] < e[1] > e[2]
    assert pf.covid_excess([60], [2022])[0] == pytest.approx(0.10)


def test_lapse_falls_with_duration_and_is_higher_through_banks():
    f = pf.lapse_force(np.array([1, 3, 8]), np.array(["AGENT"] * 3), np.array(["TERM"] * 3))
    assert f[0] > f[1] > f[2]
    bank = pf.lapse_force(np.array([1]), np.array(["BANK"]), np.array(["TERM"]))[0]
    assert bank > f[0]


def test_the_extract_is_internally_consistent(small):
    portfolio, _ = small
    p, truth = portfolio.policies, portfolio.truth
    assert list(p.columns) == list(pf.COLUMNS)
    assert set(p["status"]) <= {"IN_FORCE", "DEATH", "LAPSE", "EXPIRED"}
    # an unreported death looks like a policy still in force, in the extract
    hidden = truth.loc[truth["unreported_death"], "policy_id"]
    assert p[p["policy_id"].isin(hidden)]["status"].eq("IN_FORCE").all()
    assert len(hidden) > 0
    # deaths the extract does know about were notified no later than the extract
    d = p[p["status"] == "DEATH"]
    notified = d["notification_date"].dropna()
    assert (notified <= pd.Timestamp(pf.EXTRACT_DATE)).all()
    # the integer age at issue is the age last birthday (for records without an injected defect)
    ok = p[~p["policy_id"].isin(portfolio.defects["policy_id"])]
    age = lexis.completed_years(
        ok["birth_date"].to_numpy("datetime64[D]"), ok["issue_date"].to_numpy("datetime64[D]")
    )
    assert age.min() >= 18 and age.max() <= 70
    assert ok["sum_assured"].gt(0).all() and ok["sex"].isin(["M", "F"]).all()
    assert (ok["issue_date"] <= pd.Timestamp(pf.STUDY_END)).all()


def test_every_defect_kind_is_injected_and_logged(small):
    portfolio, _ = small
    kinds = set(portfolio.defects["defect"])
    assert kinds == {
        "invalid_sex", "birth_after_issue", "non_positive_sum_assured", "invalid_state",
        "exit_before_issue", "issue_after_extract", "death_without_notification",
        "duplicate_record",
    }  # fmt: skip


def test_validation_finds_every_injected_defect(small):
    portfolio, _ = small
    _, checks, recon = ex.validate_extract(portfolio.policies, pf.STUDY_END, pf.EXTRACT_DATE)
    found = checks.set_index("check")["records"]
    injected = portfolio.defects["defect"].value_counts()
    mapping = {
        "duplicate_record": "duplicate_record", "invalid_sex": "invalid_sex",
        "birth_after_issue": "birth_missing_or_after_issue",
        "non_positive_sum_assured": "non_positive_sum_assured", "invalid_state": "invalid_state",
        "exit_before_issue": "exit_before_issue", "issue_after_extract": "issue_after_extract",
        "death_without_notification": "death_without_notification",
    }  # fmt: skip
    for injected_name, check in mapping.items():
        assert found[check] >= injected[injected_name], injected_name
    r = recon["records"]
    assert r.iloc[0] == r.iloc[1] + r.iloc[2] + r.iloc[3]
    d = recon["deaths"]
    assert d.iloc[0] == d.iloc[1] + d.iloc[2] + d.iloc[3]


def test_deaths_balance_between_truth_extract_and_study(small):
    """Every true death is either studied, unreported at the extract, or lost to validation."""
    portfolio, _ = small
    clean, _, recon = ex.validate_extract(portfolio.policies, pf.STUDY_END, pf.EXTRACT_DATE)
    seg = ex.build_exposure(clean, pf.STUDY_START, pf.STUDY_END)
    true_deaths = int((portfolio.truth["true_status"] == "DEATH").sum())
    unreported = int(portfolio.truth["unreported_death"].sum())
    lost = int(recon["deaths"].iloc[2])  # excluded for a reason other than being a duplicate
    assert int(seg["deaths"].sum()) == true_deaths - unreported - lost


def test_the_whole_study_runs_and_recovers_the_planted_effects(small):
    portfolio, spec = small
    q = pd.Series(spec.q_basis, index=range(0, 111))
    smr = {f"{i:02d}": 1.0 + 0.01 * (i - 16) for i in range(1, 33)}
    out = ex.run_study(
        portfolio.policies, q, smr, pf.STUDY_START, pf.STUDY_END, pf.EXTRACT_DATE, truth=pf.TRUTH
    )
    expected_tables = {
        "dq_checks", "dq_reconciliation", "overview", "ae_one_way", "ae_age_sex", "ae_covid_age",
        "credibility_segments", "relativities", "recovery", "select", "lag_distribution",
        "ae_quarterly", "basis", "pricing", "impact",
    }  # fmt: skip
    assert expected_tables <= set(out)
    rec = out["recovery"]
    assert len(rec) == 15
    assert (
        rec["inside_interval"].mean() >= 0.75
    )  # about 95% in expectation; fewer deaths, wider intervals
    assert out["overview"]["deaths"].iloc[0] > 800
    # the sex effect is strong enough to be recovered tightly
    sex = rec[(rec["factor"] == "sex")].iloc[0]
    assert sex["relativity"] == pytest.approx(sex["planted"], rel=0.12)
    # the select factors of fully underwritten business rise with duration
    full = out["select"][out["select"]["underwriting"] == "fully underwritten"]
    assert full["relativity"].iloc[0] < full["relativity"].iloc[3]
    assert full["inside_interval"].mean() >= 0.6
    # the basis is a proper table: positive multipliers, probabilities, prudent above best estimate
    basis = out["basis"]
    assert (basis["multiplier"] > 0).all() and (basis["q_experience"] <= 1).all()
    assert (basis["multiplier_upper"] >= basis["multiplier"]).all()
    # women are cheaper than the unisex expected basis, men dearer, in the pricing signal
    price = out["pricing"].set_index(["sex", "issue_age"])["change_pct"]
    assert price[("F", 40)] < price[("M", 40)]
    assert (out["impact"]["pv_cnsf"] > 0).all()
    # the quarterly series is completed upwards in the most recent quarters
    q = out["ae_quarterly"].iloc[-1]
    assert q["deaths_completed"] > q["deaths"]
