import numpy as np
import pandas as pd
import pytest

from mortality import quality


def smooth_deaths(lo=0, hi=110):
    """Deaths that rise smoothly with age (like a real death distribution)."""
    ages = np.arange(lo, hi + 1)
    return pd.Series(100 + 10 * ages, index=ages, dtype=float)


def heaped(series, digits=(0, 5), factor=3.0):
    out = series.copy()
    for age in out.index:
        if age % 10 in digits:
            out[age] *= factor
    return out


# ── heaping indices ─────────────────────────────────────────────────────────


def test_whipple_is_100_for_flat_data():
    flat = pd.Series(50.0, index=range(0, 111))
    assert quality.whipple_index(flat) == pytest.approx(100.0)


def test_whipple_is_500_when_everything_is_on_zero_or_five():
    only = pd.Series({a: (10.0 if a % 5 == 0 else 0.0) for a in range(23, 63)})
    assert quality.whipple_index(only) == pytest.approx(500.0)


def test_whipple_rises_with_heaping_and_is_close_to_100_for_smooth_trends():
    smooth = smooth_deaths()
    assert 98 < quality.whipple_index(smooth) < 104
    assert quality.whipple_index(heaped(smooth)) > 150


def test_whipple_handles_empty_data():
    assert np.isnan(quality.whipple_index(pd.Series(dtype=float)))


def test_whipple_classes_follow_the_un_scale():
    assert quality.whipple_class(101) == "highly accurate"
    assert quality.whipple_class(107) == "fairly accurate"
    assert quality.whipple_class(120) == "approximate"
    assert quality.whipple_class(150) == "rough"
    assert quality.whipple_class(200) == "very rough"
    assert quality.whipple_class(float("nan")) == "n/a"


def test_myers_is_zero_for_flat_data_and_large_for_heaped_data():
    flat = pd.Series(100.0, index=range(0, 111))
    assert quality.myers_index(flat) == pytest.approx(0.0, abs=1e-9)
    assert quality.myers_index(smooth_deaths()) < 1.0
    assert quality.myers_index(heaped(smooth_deaths(), digits=(0,), factor=5.0)) > 10


def test_myers_maximum_is_90_when_all_records_share_one_digit():
    only_zero = pd.Series({a: (100.0 if a % 10 == 0 else 0.0) for a in range(0, 111)})
    assert quality.myers_index(only_zero) > 60


def test_noumbissi_ignores_smooth_trends_but_sees_spikes():
    smooth = smooth_deaths()
    assert quality.noumbissi_index(smooth, 0) == pytest.approx(1.0, abs=0.01)
    assert quality.noumbissi_index(smooth, 5) == pytest.approx(1.0, abs=0.01)
    spiky = heaped(smooth, digits=(0,), factor=2.0)
    assert quality.noumbissi_index(spiky, 0) > 1.3
    assert quality.noumbissi_index(spiky, 5) == pytest.approx(1.0, abs=0.05)


def test_noumbissi_rejects_impossible_digit_ranges():
    with pytest.raises(ValueError):
        quality.noumbissi_index(smooth_deaths(), 0, lo=21, hi=29)


def test_heaping_table_groups_by_dataset_year_and_sex():
    rows = []
    for year in (2020, 2021):
        for sex in ("M", "F"):
            rows += [(year, sex, a, v) for a, v in smooth_deaths().items()]
    frame = pd.DataFrame(rows, columns=["year", "sex", "age", "value"])
    table = quality.heaping_table({"demo": frame})
    assert len(table) == 4
    assert set(table["dataset"]) == {"demo"}
    assert (table["whipple_class"] == "highly accurate").all()


# ── allocation of unknowns ──────────────────────────────────────────────────


def cells(rows):
    return pd.DataFrame(rows, columns=["year", "sex", "key", "deaths"])


def test_unknown_sex_is_split_like_the_known_deaths_at_that_age():
    c = cells(
        [
            (2020, "M", 10, 60), (2020, "F", 10, 30), (2020, "M", 20, 40), (2020, "F", 20, 70),
            (2020, None, 10, 9),
        ]
    )  # fmt: skip
    out = quality.allocate_unknowns(c)
    row = out[(out.key == 10)].set_index("sex")
    assert row.loc["M", "added_unknown_sex"] == pytest.approx(6.0)  # 60 / 90 of 9
    assert row.loc["F", "added_unknown_sex"] == pytest.approx(3.0)


def test_unknown_age_is_spread_like_that_sexs_known_deaths():
    c = cells(
        [
            (2020, "M", 10, 60), (2020, "M", 20, 40), (2020, "F", 10, 50), (2020, "F", 20, 50),
            (2020, "M", None, 10),
        ]
    )  # fmt: skip
    out = quality.allocate_unknowns(c)
    male = out[out.sex == "M"].set_index("key")
    assert male.loc[10, "added_unknown_age"] == pytest.approx(6.0)
    assert male.loc[20, "added_unknown_age"] == pytest.approx(4.0)
    assert out[out.sex == "F"]["added_unknown_age"].sum() == 0


def test_unknown_sex_and_age_is_spread_over_the_whole_table():
    c = cells(
        [(2020, "M", 10, 60), (2020, "F", 10, 20), (2020, "M", 20, 10), (2020, "F", 20, 10),
         (2020, None, None, 10)]
    )  # fmt: skip
    out = quality.allocate_unknowns(c)
    assert out["added_unknown_both"].sum() == pytest.approx(10.0)
    top = out[(out.sex == "M") & (out.key == 10)].iloc[0]
    assert top["added_unknown_both"] == pytest.approx(10 * 60 / 100)


def test_no_death_is_created_or_lost():
    rng = np.random.default_rng(1)
    rows = []
    for year in (2020, 2021):
        for sex in ("M", "F"):
            for age in range(0, 60):
                rows.append((year, sex, age, int(rng.integers(0, 50))))
        rows += [
            (year, None, 30, 7),
            (year, "M", None, 11),
            (year, "F", None, 5),
            (year, None, None, 3),
        ]
    c = cells(rows)
    out = quality.allocate_unknowns(c)
    assert out.groupby("year")["adjusted"].sum().tolist() == pytest.approx(
        c.groupby("year")["deaths"].sum().tolist()
    )
    assert (out["adjusted"] >= out["recorded"]).all()
    assert (out[["added_unknown_sex", "added_unknown_age", "added_unknown_both"]] >= 0).all().all()


def test_years_are_allocated_independently():
    c = cells([(2020, "M", 1, 10), (2020, "F", 1, 10), (2021, "M", 1, 100), (2021, "F", 1, 300),
               (2020, None, 1, 4), (2021, None, 1, 4)])  # fmt: skip
    out = quality.allocate_unknowns(c)
    m = out[(out.sex == "M") & (out.key == 1)].set_index("year")["added_unknown_sex"]
    assert m[2020] == pytest.approx(2.0) and m[2021] == pytest.approx(1.0)


def test_unknown_sex_at_an_age_with_no_known_deaths_uses_the_year_split():
    c = cells([(2020, "M", 10, 30), (2020, "F", 10, 10), (2020, None, 99, 8)])
    out = quality.allocate_unknowns(c)
    at99 = out[out.key == 99].set_index("sex")
    assert at99.loc["M", "added_unknown_sex"] == pytest.approx(6.0)  # year split is 75% male
    assert at99.loc["F", "added_unknown_sex"] == pytest.approx(2.0)


def test_a_sex_with_no_known_deaths_still_gets_unknown_age_deaths_allocated():
    c = cells([(2020, "M", 10, 50), (2020, "M", 20, 50), (2020, "F", None, 10)])
    out = quality.allocate_unknowns(c)
    assert out["adjusted"].sum() == pytest.approx(110)
    assert out[out.sex == "F"]["added_unknown_age"].sum() == pytest.approx(10)
