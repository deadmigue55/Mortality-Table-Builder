import numpy as np
import pandas as pd
import pytest

from mortality import insured


def claims_frame():
    rows = [
        # year, age, sex, coverage, claims, claimed
        (2024, 40, "M", "Fallecimiento", 10, 1000.0),
        (2024, 40, "M", "Fallecimiento", 2, -200.0),  # cancelled
        (2024, 41, "F", "Fallecimiento", 5, 500.0),
        (2024, 41, "F", "Muerte accidental (Doble indemnizacion)", 9, 900.0),  # rider
        (2024, 41, "F", "Gastos funerarios", 7, 70.0),  # not a death
        (2024, pd.NA, pd.NA, "Fallecimiento", 4, 400.0),  # no-detail, positive
        (2024, pd.NA, pd.NA, "Fallecimiento", 3, -300.0),  # no-detail, cancelled
        (2023, 40, "M", "Fallecimiento", 6, 600.0),
        (2023, pd.NA, pd.NA, "Fallecimiento", 2, 0.0),  # no-detail, zero
    ]
    frame = pd.DataFrame(
        rows, columns=["year", "age", "sex", "coverage", "claims", "amount_claimed"]
    )
    frame["cause"] = "INFARTO AGUDO DEL MIOCARDIO"
    # an endowment maturity booked as a death with a placeholder cause: not a death
    maturity = pd.DataFrame(
        {
            "year": [2024],
            "age": [62],
            "sex": ["M"],
            "coverage": ["Fallecimiento"],
            "claims": [3],
            "amount_claimed": [3_000_000.0],
            "cause": ["LUXACION, ESGUINCE Y TORCEDURA DE ARTICULACIONES Y LIGAMENTOS DEL TOBILLO"],
        }
    )
    frame = pd.concat([frame, maturity], ignore_index=True)
    frame["age"] = frame["age"].astype("Int16")
    frame["sex"] = frame["sex"].astype("string")
    return frame


def total(frame, year):
    return frame.loc[frame["year"] == year, "deaths"].sum()


def test_base_rule_counts_only_known_positive_death_claims():
    d = insured.death_cells(claims_frame(), "base")
    assert total(d, 2024) == 15  # 10 + 5; rider, funeral cover, cancelled and no-detail rows out
    assert total(d, 2023) == 6
    assert set(d["sex"]) == {"M", "F"}


def test_maturity_payments_coded_as_sprains_are_not_deaths_unless_asked_for():
    base = insured.death_cells(claims_frame(), "base")
    kept = insured.death_cells(claims_frame(), "with_maturities")
    assert total(base, 2024) == 15
    assert total(kept, 2024) == 18  # the 3 maturity payments come back
    assert 62 not in set(base["age"]) and 62 in set(kept["age"])


def test_the_rules_refuse_claims_without_a_cause_instead_of_skipping_the_filter():
    no_cause = claims_frame().drop(columns="cause")
    with pytest.raises(ValueError, match="cause column"):
        insured.death_cells(no_cause, "base")
    assert total(insured.death_cells(no_cause, "with_maturities"), 2024) == 18


def test_net_rule_removes_known_cancellations():
    d = insured.death_cells(claims_frame(), "net")
    assert total(d, 2024) == 13  # 15 - 2
    assert total(d, 2023) == 6


def test_plus_positive_adds_exactly_the_positive_no_detail_claims():
    d = insured.death_cells(claims_frame(), "plus_positive")
    assert total(d, 2024) == pytest.approx(15 + 4)
    assert total(d, 2023) == pytest.approx(6)  # its only no-detail row has a zero amount


def test_plus_all_adds_every_no_detail_claim_and_keeps_the_shape():
    base = insured.death_cells(claims_frame(), "base")
    d = insured.death_cells(claims_frame(), "plus_all")
    assert total(d, 2024) == pytest.approx(15 + 4 + 3)
    assert total(d, 2023) == pytest.approx(6 + 2)
    # every cell grows by the same factor within a year
    ratio = d["deaths"] / base["deaths"]
    same_year = ratio[d["year"] == 2024].to_numpy()
    assert np.allclose(same_year, same_year[0])


def test_unknown_rule_is_refused():
    with pytest.raises(ValueError, match="unknown rule"):
        insured.death_cells(claims_frame(), "everything")


def test_spread_pro_rata_preserves_cells_and_adds_the_total():
    deaths = pd.DataFrame(
        {
            "year": [2024, 2024, 2023],
            "age": [40, 41, 40],
            "sex": ["M", "F", "M"],
            "deaths": [3.0, 1.0, 5.0],
        }
    )
    out = insured.spread_pro_rata(deaths, pd.Series({2024: 2.0}))
    assert out["deaths"].tolist() == pytest.approx([4.5, 1.5, 5.0])
    assert len(out) == len(deaths)


def test_exposure_cells_drop_unknown_age_or_sex_and_filter_plans():
    exposure = pd.DataFrame(
        {
            "year": [2024] * 4,
            "age": pd.array([40, 40, pd.NA, 41], dtype="Int16"),
            "sex": pd.array(["M", "M", "F", None], dtype="string"),
            "plan": ["Temporal", "Vitalicio", "Temporal", "Temporal"],
            "modality": ["Tradicional"] * 4,
            "insured": [10.0, 5.0, 7.0, 3.0],
        }
    )
    assert insured.exposure_cells(exposure)["exposure"].tolist() == [15.0]
    assert insured.exposure_cells(exposure, "term")["exposure"].tolist() == [10.0]
    assert insured.exposure_cells(exposure, "permanent")["exposure"].tolist() == [5.0]


def test_central_exposure_shortens_by_half_the_turnover():
    cells = pd.DataFrame({"year": [2024], "age": [40], "sex": ["M"], "exposure": [100.0]})
    assert insured.central_exposure(cells, 0.2)["exposure"].iloc[0] == pytest.approx(90.0)
    assert insured.central_exposure(cells, 0.0)["exposure"].iloc[0] == 100.0
    with pytest.raises(ValueError):
        insured.central_exposure(cells, 1.5)


def test_crude_cells_keep_cells_without_deaths_as_zero():
    exposure = pd.DataFrame(
        {"year": [2024, 2024], "age": [40, 41], "sex": ["M", "M"], "exposure": [100.0, 50.0]}
    )
    deaths = pd.DataFrame({"year": [2024], "age": [40], "sex": ["M"], "deaths": [2.0]})
    crude = insured.crude_cells(deaths, exposure)
    assert crude["rate"].tolist() == pytest.approx([0.02, 0.0])
    assert not np.isnan(crude["rate"]).any()
