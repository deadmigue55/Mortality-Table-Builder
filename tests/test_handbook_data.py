"""Numerical proof of the formulas in docs/handbook/02-data-exposure-quality.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import optimize

from mortality import lexis, quality

ROOT = Path(__file__).resolve().parents[1]
AGES = np.arange(0, 120)


def profile(values) -> pd.Series:
    return pd.Series(values, index=AGES, dtype=float)


# ── 2.2: age heaping ─────────────────────────────────────────────────────────


def test_whipple_counts_the_fifth_of_ages_that_end_in_0_or_5():
    """(2.1): eight of the forty ages from 23 to 62 end in 0 or 5, so a flat profile scores 100."""
    assert [a for a in range(23, 63) if a % 5 == 0] == [25, 30, 35, 40, 45, 50, 55, 60]
    assert quality.whipple_index(profile(np.ones(120))) == pytest.approx(100.0)
    only_round = profile(np.where(AGES % 5 == 0, 1.0, 0.0))
    assert quality.whipple_index(only_round) == pytest.approx(500.0)
    heaped = profile(np.where(AGES % 5 == 0, 3.0, 1.0))  # three times as many records on 0 and 5
    assert quality.whipple_index(heaped) == pytest.approx(500 * 24 / (24 + 32))


def test_whipple_is_exactly_100_for_any_straight_line_profile():
    """Section 2.2: heaped ages have the same mean age (42.5) as all forty, so a trend cancels."""
    for slope in (-5.0, 0.0, 3.0, 40.0):
        assert quality.whipple_index(profile(1000 + slope * AGES)) == pytest.approx(100.0)
    # a smooth curve moves it by less than a point: deaths rising 9% a year of age, as in adults
    assert abs(quality.whipple_index(profile(np.exp(0.09 * AGES))) - 100) < 1.0


def test_whipple_scale_classes():
    """The UN scale: below 105 highly accurate, 110 fairly, 125 approximate, 175 rough."""
    assert [quality.whipple_class(v) for v in (99, 104.9, 105, 118, 140, 175, 300)] == [
        "highly accurate",
        "highly accurate",
        "fairly accurate",
        "approximate",
        "rough",
        "very rough",
        "very rough",
    ]


def test_myers_blend_is_zero_for_any_straight_line_and_ninety_at_the_extreme():
    """(2.2): the weights (d + 1) and (9 - d) make a linear change in the age profile cancel."""
    assert quality.myers_index(profile(np.ones(120))) == pytest.approx(0.0)
    for slope in (-5.0, 3.0, 40.0):
        assert quality.myers_index(profile(1000 + slope * AGES)) == pytest.approx(0.0, abs=1e-9)
    all_on_three = profile(np.where(AGES % 10 == 3, 1.0, 0.0))
    assert quality.myers_index(all_on_three) == pytest.approx(90.0)
    heaped = profile(np.where(AGES % 5 == 0, 3.0, 1.0))
    assert quality.myers_index(heaped) == pytest.approx(160 / 7)  # 22.857: 0 and 5 take 21.4% each


def test_myers_blended_tallies_by_hand_for_one_digit():
    """(2.2): digit d is counted from age 10 with weight d + 1 and from age 20 with weight 9 - d."""
    counts = profile(np.arange(120, dtype=float))
    d = 4
    first = sum(counts[10 * k + d] for k in range(1, 9))  # 14, 24, ..., 84
    second = sum(counts[10 * k + d] for k in range(2, 10))  # 24, 34, ..., 94
    assert (first, second) == (392.0, 472.0)
    assert (d + 1) * first + (9 - d) * second == 5 * 392 + 5 * 472  # 4,320


def test_noumbissi_compares_a_digit_with_its_neighbours():
    """(2.3): exactly 1 for a straight line; 3 times heaping on 0 and 5 reads as 1.8."""
    for slope in (-5.0, 3.0):
        line = profile(1000 + slope * AGES)
        assert quality.noumbissi_index(line, 0) == pytest.approx(1.0)
        assert quality.noumbissi_index(line, 5) == pytest.approx(1.0)
    heaped = profile(np.where(AGES % 5 == 0, 3.0, 1.0))
    assert quality.noumbissi_index(heaped, 0) == pytest.approx(3 / ((1 + 3 + 1) / 3))
    with pytest.raises(ValueError):
        quality.noumbissi_index(heaped, 0, lo=21, hi=29)  # no age ending in 0 in the range


# ── 2.3: unknown sex and age ─────────────────────────────────────────────────

UNKNOWNS = pd.DataFrame(
    {
        "year": 2020,
        "sex": ["M", "F", "M", "F", np.nan, "M", np.nan],
        "key": [30, 30, 40, 40, 30, np.nan, np.nan],
        "deaths": [60.0, 20.0, 90.0, 30.0, 20.0, 12.0, 8.0],
    }
)


def test_allocation_toy_example_step_by_step():
    """(2.4) to (2.6): the worked example of section 2.7, 200 recorded and 40 unknown deaths."""
    out = quality.allocate_unknowns(UNKNOWNS).set_index(["sex", "key"])
    assert out.loc[("M", 30), "added_unknown_sex"] == pytest.approx(15.0)  # 20 x 60/80
    assert out.loc[("F", 30), "added_unknown_sex"] == pytest.approx(5.0)
    assert out.loc[("M", 30), "added_unknown_age"] == pytest.approx(12 * 75 / 165)
    assert out.loc[("M", 40), "added_unknown_age"] == pytest.approx(12 * 90 / 165)
    assert out.loc[("F", 30), "added_unknown_age"] == 0.0
    final_m30 = (75 + 12 * 75 / 165) * (1 + 8 / 232)
    assert out.loc[("M", 30), "adjusted"] == pytest.approx(final_m30)
    assert round(final_m30, 3) == 83.229
    adjusted = {k: round(out.loc[k, "adjusted"], 3) for k in [("F", 30), ("M", 40), ("F", 40)]}
    assert adjusted == {("F", 30): 25.862, ("M", 40): 99.875, ("F", 40): 31.034}


def test_allocation_conserves_every_death_and_adds_up_column_by_column():
    """(2.7): adjusted = recorded + the three additions, and the total is 240 in, 240 out."""
    out = quality.allocate_unknowns(UNKNOWNS)
    assert out["adjusted"].sum() == pytest.approx(UNKNOWNS["deaths"].sum())
    parts = out[["recorded", "added_unknown_sex", "added_unknown_age", "added_unknown_both"]]
    assert parts.sum(axis=1).to_numpy() == pytest.approx(out["adjusted"].to_numpy())
    assert out["recorded"].sum() == pytest.approx(200.0)
    assert out["added_unknown_sex"].sum() == pytest.approx(20.0)
    assert out["added_unknown_age"].sum() == pytest.approx(12.0)
    assert out["added_unknown_both"].sum() == pytest.approx(8.0)


def test_allocation_without_known_deaths_at_an_age_uses_the_whole_year_split():
    """(2.4): where no one of known sex died at that age, the yearly male share is used."""
    cells = pd.DataFrame(
        {
            "year": 2020,
            "sex": ["M", "F", np.nan],
            "key": [30, 30, 50],
            "deaths": [60.0, 20.0, 40.0],
        }
    )
    out = quality.allocate_unknowns(cells).set_index(["sex", "key"])
    assert out.loc[("M", 50), "added_unknown_sex"] == pytest.approx(40 * 0.75)
    assert out["adjusted"].sum() == pytest.approx(120.0)


# ── 2.4: late registration, the chain ladder ─────────────────────────────────

# Deaths at age 40 by year of occurrence and the file that registered them (section 2.7)
TRIANGLE_CELLS = pd.DataFrame(
    {
        "occ_year": [2020, 2020, 2020, 2021, 2021, 2022],
        "file_year": [2020, 2021, 2022, 2021, 2022, 2022],
        "age": 40,
        "deaths": [1000.0, 50.0, 10.0, 2000.0, 100.0, 1500.0],
    }
)


def test_chain_ladder_toy_example():
    """(2.8) to (2.10): factors 1.05 and 1.0095, completion 1.06 for the latest year."""
    triangle = quality.build_triangle(TRIANGLE_CELLS)
    cumulative = triangle.pivot_table(index="occ_year", columns="lag", values="cumulative")
    assert cumulative.loc[2020].tolist() == [1000, 1050, 1060]
    assert cumulative.loc[2021, [0, 1]].tolist() == [2000, 2100]
    factors = quality.chain_ladder_factors(triangle).set_index("lag")["factor"]
    assert factors[0] == pytest.approx((1050 + 2100) / (1000 + 2000))  # 1.05
    assert factors[1] == pytest.approx(1060 / 1050)
    comp = quality.completion_factors(triangle, quality.chain_ladder_factors(triangle))
    comp = comp.set_index("occ_year")["factor"]
    assert comp[2022] == pytest.approx(1.05 * 1060 / 1050) == pytest.approx(1.06)
    assert comp[2021] == pytest.approx(1060 / 1050)
    assert comp[2020] == pytest.approx(1.0)
    assert 1500 * comp[2022] == pytest.approx(1590)


def test_the_tail_factor_multiplies_every_completion_factor():
    """(2.11): tail = 1 + late / base, and it scales every year, including the oldest."""
    assert quality.tail_factor(60, 80_000) == pytest.approx(1.00075)
    assert quality.tail_factor(5, 0) == 1.0
    triangle = quality.build_triangle(TRIANGLE_CELLS)
    factors = quality.chain_ladder_factors(triangle)
    comp = quality.completion_factors(triangle, factors, tail=1.01).set_index("occ_year")["factor"]
    assert comp[2020] == pytest.approx(1.01)
    assert comp[2022] == pytest.approx(1.06 * 1.01)


def test_the_volume_weighted_factor_is_the_weighted_least_squares_slope():
    """(2.9): sum(C1) / sum(C0) minimises sum((C1 - f C0)^2 / C0), the proportional-growth model."""
    c0 = np.array([1000.0, 2000.0, 700.0, 1300.0])
    c1 = np.array([1050.0, 2100.0, 760.0, 1330.0])
    f = optimize.minimize_scalar(lambda x: np.sum((c1 - x * c0) ** 2 / c0)).x
    assert f == pytest.approx(c1.sum() / c0.sum(), rel=1e-6)


def test_complete_cells_scales_reported_deaths_by_the_age_band_factor():
    """(2.10): completed = reported x factor of the cell's age band and year."""
    triangle = quality.build_triangle(TRIANGLE_CELLS)
    comp = quality.completion_factors(triangle, quality.chain_ladder_factors(triangle))
    cells = pd.DataFrame(
        {"year": [2022, 2021], "sex": ["M", "F"], "key": [40, 40], "deaths": [1500.0, 2100.0]}
    )
    out = quality.complete_cells(cells, comp)
    assert out["completed"].tolist() == pytest.approx([1590.0, 2120.0])
    assert out["reported"].tolist() == [1500.0, 2100.0]


def test_age_bands_cover_every_age_once():
    """Section 2.4: seven bands plus 'unknown', so every record falls in exactly one triangle."""
    assert [quality.age_band(a) for a in (0, 1, 14, 15, 44, 45, 79, 80, 109)] == [
        "0", "1-14", "1-14", "15-29", "30-44", "45-64", "65-79", "80+", "80+",
    ]  # fmt: skip
    assert quality.age_band(np.nan) == "unknown"


# ── 2.5: the pandemic flag ───────────────────────────────────────────────────


def test_a_year_is_a_covid_year_from_one_percent_coded_deaths():
    """(2.12): share = COVID-coded deaths / all deaths, flagged at 1%."""
    assert quality.COVID_SHARE_THRESHOLD == 0.01


# ── 2.6: exposure from dates ─────────────────────────────────────────────────


def d64(*dates: str) -> np.ndarray:
    return np.array(dates, dtype="datetime64[D]")


def test_lexis_toy_example_pieces_and_days():
    """(2.13): issued 15 June 2018, observed to 1 March 2020: pieces of 200, 165, 200, 60 days."""
    pieces = lexis.lexis_split(d64("2018-06-15"), d64("2018-06-15"), d64("2020-03-01"))
    assert (pieces["exposure"] * lexis.DAYS_PER_YEAR).round().tolist() == [200, 165, 200, 60]
    assert pieces["duration"].tolist() == [1, 1, 2, 2]
    assert pieces["calendar_year"].tolist() == [2018, 2019, 2019, 2020]
    assert pieces["last"].tolist() == [False, False, False, True]
    assert pieces["exposure"].sum() == pytest.approx(625 / 365.25)  # (2.14)


def test_pieces_add_up_to_the_observation_time_for_random_policies():
    """(2.14): the cuts never create or destroy time, whatever the dates."""
    rng = np.random.default_rng(4)
    n = 300
    base = np.datetime64("2010-01-01")
    issue = base + rng.integers(0, 3000, n).astype("timedelta64[D]")
    entry = issue + rng.integers(0, 800, n).astype("timedelta64[D]")
    exit_ = entry + rng.integers(1, 2500, n).astype("timedelta64[D]")
    pieces = lexis.lexis_split(issue, entry, exit_)
    per_policy = pieces.groupby("pos")["exposure"].sum().to_numpy()
    assert per_policy == pytest.approx((exit_ - entry).astype(int) / lexis.DAYS_PER_YEAR)
    assert pieces["last"].sum() == n  # one exit event per policy


def test_each_piece_sits_inside_one_duration_and_one_calendar_year():
    """Section 2.6: nothing changes inside a piece, so the force of mortality is constant there."""
    rng = np.random.default_rng(8)
    n = 100
    issue = np.datetime64("2012-03-01") + rng.integers(0, 2500, n).astype("timedelta64[D]")
    exit_ = issue + rng.integers(30, 3000, n).astype("timedelta64[D]")
    pieces = lexis.lexis_split(issue, issue, exit_)
    last_day = pieces["end"] - np.timedelta64(1, "D")
    year_of_last_day, _, _ = lexis.split_date(last_day)
    assert (year_of_last_day == pieces["calendar_year"]).all()
    duration_last = lexis.completed_years(issue[pieces["pos"]], last_day) + 1
    assert (duration_last == pieces["duration"]).all()


def test_the_number_of_pieces_is_one_plus_the_cut_dates_inside():
    """Section 2.6: cuts are policy anniversaries and 1 January, counted once when they coincide."""
    rng = np.random.default_rng(2)
    for _ in range(40):
        issue = date(2015, 1, 1) + timedelta(days=int(rng.integers(0, 1500)))
        entry = issue + timedelta(days=int(rng.integers(0, 400)))
        exit_ = entry + timedelta(days=int(rng.integers(1, 1800)))
        cuts = set()
        for k in range(1, 12):
            try:
                cuts.add(issue.replace(year=issue.year + k))
            except ValueError:  # 29 February: the code moves it to 28 February
                cuts.add(date(issue.year + k, 2, 28))
        cuts |= {date(y, 1, 1) for y in range(entry.year + 1, exit_.year + 2)}
        inside = {c for c in cuts if entry < c < exit_}
        pieces = lexis.lexis_split(d64(str(issue)), d64(str(entry)), d64(str(exit_)))
        assert len(pieces) == 1 + len(inside)


def test_the_central_rate_is_the_maximum_likelihood_estimate():
    """(2.15): with a constant force in each piece, deaths / exposure maximises the likelihood."""
    exposure = np.array([0.55, 0.45, 0.55, 0.16, 1.0, 0.3])
    died = np.array([0, 0, 0, 1, 0, 1])

    def negative_log_likelihood(mu: float) -> float:
        return -np.sum(died * np.log(mu) - mu * exposure)  # piece likelihood: mu^delta e^(-mu t)

    best = optimize.minimize_scalar(negative_log_likelihood, bounds=(1e-6, 5), method="bounded")
    assert best.x == pytest.approx(died.sum() / exposure.sum(), rel=1e-4)
    assert died.sum() / exposure.sum() == pytest.approx(2 / 3.01)


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
    """Section 2.8: the corrections, the triangle, the factors, the heaping indices, the flags."""
    adj = pd.read_sql("SELECT * FROM deaths_adjusted", demo)
    add_cols = [c for c in adj.columns if c.startswith("added_")]
    assert (adj[["reported", *add_cols]].sum(axis=1) - adj["adjusted"]).abs().max() < 1e-6
    by_year = adj.groupby("year")[["reported", "adjusted", *add_cols]].sum()
    assert by_year["adjusted"].round().astype(int).tolist() == [
        1093073, 1117650, 843757, 798055, 814221,
    ]  # fmt: skip
    assert by_year["added_late_registration"].round().tolist() == [802, 1372, 1553, 2334, 17301]
    unknown = by_year[["added_unknown_sex", "added_unknown_age", "added_unknown_both"]].sum(axis=1)
    share = unknown / by_year["adjusted"] * 100
    assert (round(share.min(), 2), round(share.max(), 2)) == (0.45, 0.61)

    tri = pd.read_sql("SELECT * FROM registration_triangle", demo)
    lag = tri.pivot_table(index="occ_year", columns="lag", values="deaths", aggfunc="sum")
    assert lag[0].round().astype(int).tolist() == [1068865, 1096676, 824214, 777593, 796123]
    assert (lag[1] / lag[0] * 100).dropna().round(2).tolist() == [1.93, 1.62, 2.04, 2.31]
    factors = pd.read_sql("SELECT * FROM registration_factors WHERE lag = 0", demo)
    first = factors.set_index("band")["factor"].round(3).to_dict()
    assert first == {
        "0": 1.002, "1-14": 1.012, "15-29": 1.015, "30-44": 1.016,
        "45-64": 1.016, "65-79": 1.019, "80+": 1.024, "unknown": 1.181,
    }  # fmt: skip
    tail = pd.read_sql("SELECT tail_factor FROM registration_tail", demo).iloc[0, 0]
    assert tail == pytest.approx(1.00074, abs=1e-5)
    comp = pd.read_sql("SELECT * FROM registration_completion", demo)
    by = comp.groupby("occ_year")[["reported", "missing_deaths"]].sum()
    assert (by["missing_deaths"] / by["reported"] * 100).round(2).tolist() == [
        0.07, 0.13, 0.2, 0.32, 2.27,
    ]  # fmt: skip

    heaping = pd.read_sql("SELECT * FROM quality_age_heaping WHERE dataset = 'INEGI deaths'", demo)
    assert heaping["whipple"].between(98.2, 101.5).all()
    assert heaping["myers"].between(0.4, 0.9).all()
    assert heaping[["noumbissi_0", "noumbissi_5"]].to_numpy().min() > 0.975
    assert heaping[["noumbissi_0", "noumbissi_5"]].to_numpy().max() < 1.025
    assert set(heaping["whipple_class"]) == {"highly accurate"}

    flags = pd.read_sql("SELECT * FROM year_flags ORDER BY year", demo)
    assert flags["covid_year"].tolist() == [1, 1, 1, 0, 0]
    assert (flags["covid_share"] * 100).round(1).tolist() == [18.4, 21.3, 4.5, 0.6, 0.2]
    assert flags["covid_deaths"].round().astype(int).tolist() == [201280, 238093, 38189, 4625, 1353]
