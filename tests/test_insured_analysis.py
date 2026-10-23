import numpy as np
import pandas as pd
import pytest

from mortality import insured_analysis as analysis


def test_improvement_is_the_geometric_average_rate():
    projected = pd.DataFrame(
        {
            "year": [2025, 2045] * 2,
            "sex": ["M", "M", "F", "F"],
            "age": [40, 40, 40, 40],
            "qx": [0.002, 0.002 * 0.98**20, 0.001, 0.001],
        }
    )
    out = analysis.improvement_table(projected).set_index("sex")
    assert out.loc["M", "annual_improvement"] == pytest.approx(0.02)
    assert out.loc["F", "annual_improvement"] == pytest.approx(0.0)


def test_pandemic_table_indexes_each_source_to_its_own_2023():
    def frame(rates):
        rows = []
        for year, rate in rates.items():
            for sex in ("M", "F"):
                rows.append(
                    {"year": year, "sex": sex, "age": 50, "deaths": rate * 1e5, "exposure": 1e5}
                )
        return pd.DataFrame(rows)

    out = analysis.pandemic_table(
        frame({2021: 0.006, 2023: 0.003}), frame({2021: 0.015, 2023: 0.010})
    )
    ins = out[(out["source"] == "insured") & (out["year"] == 2021) & (out["sex"] == "M")]
    pop = out[(out["source"] == "population") & (out["year"] == 2021) & (out["sex"] == "M")]
    assert ins["index_vs_2023"].iloc[0] == pytest.approx(2.0)  # relative to its own 2023
    assert pop["index_vs_2023"].iloc[0] == pytest.approx(1.5)
    assert set(out["band"]) == {"45-64"}  # only the band holding age 50 has data


def test_amount_table_ratio_says_whether_big_policies_die_more():
    claims = pd.DataFrame(
        {
            "year": [2024, 2024, 2024],
            "age": [40, 41, 42],
            "sex": ["M", "M", "M"],
            "plan": ["Temporal"] * 3,
            "modality": ["Tradicional"] * 3,
            "claims": [1.0, 1.0, 0.0],
            "amount_claimed": [3_000_000.0, 1_000_000.0, -5.0],  # the last is a cancellation
        }
    )
    issued = pd.DataFrame(
        {
            "year": [2024] * 3,
            "age": [40, 41, 42],
            "sex": ["M"] * 3,
            "plan": ["Temporal"] * 3,
            "modality": ["Tradicional"] * 3,
            "insured": [500.0, 500.0, 500.0],
            "sum_assured": [500e6, 500e6, 500e6],  # average 1,000,000 per life
        }
    )
    out = analysis.amount_table(claims, issued)
    row = out[(out["segment"] == "term_traditional") & (out["decade"] == 40)].iloc[0]
    assert row["rate_by_count"] == pytest.approx(2 / 1500)
    assert row["rate_by_amount"] == pytest.approx(4e6 / 1.5e9)
    assert row["amount_to_count_ratio"] == pytest.approx(2.0)  # claims average 2x the policy
    assert row["avg_claim"] == pytest.approx(2_000_000)


def test_legacy_table_excludes_rejected_claims_and_reports_the_sex_mix():
    issued = pd.DataFrame(
        {
            "year": [2019, 2019, 2019],
            "age": [40, 40, 41],
            "sex": ["M", "F", "M"],
            "asegurados": [600.0, 300.0, 400.0],
        }
    )
    claims = pd.DataFrame(
        {
            "year": [2019] * 4,
            "age": [40, 40, 41, 40],
            "sex": ["M", "M", "M", "F"],
            "mto_sin_ben_1": [100.0, 100.0, 100.0, 100.0],
            "status_sin": [2, 3, 1, 4],  # the status-3 row is a rejected claim
            "siniestros": [2.0, 5.0, 1.0, 1.0],
        }
    )
    base = pd.DataFrame({"sex": ["M", "F"], "decade": [40, 40], "rate": [0.002, 0.001]})
    out, mix = analysis.legacy_table(issued, claims, base)
    men = out[out["sex"] == "M"].iloc[0]
    assert men["deaths"] == 3.0 and men["lives"] == 1000.0
    assert men["ratio_to_base"] == pytest.approx(0.003 / 0.002)
    assert mix.set_index("sex")["share"].to_dict() == pytest.approx(
        {"M": 1000 / 1300, "F": 300 / 1300}
    )
    assert np.isclose(mix["share"].sum(), 1.0)
