"""Tests for the Lexis exposure split."""

from __future__ import annotations

import numpy as np
import pytest

from mortality import lexis


def d(*s):
    return np.array(s, dtype="datetime64[D]")


def test_date_parts_roundtrip():
    dates = d("2020-02-29", "1999-12-31", "2024-01-01")
    y, m, day = lexis.split_date(dates)
    assert y.tolist() == [2020, 1999, 2024]
    assert m.tolist() == [2, 12, 1]
    assert day.tolist() == [29, 31, 1]
    assert (lexis.make_date(y, m, day) == dates).all()


def test_make_date_moves_an_impossible_day_to_the_end_of_the_month():
    assert lexis.make_date([2021, 2024], [2, 2], [29, 29]).tolist() == list(
        d("2021-02-28", "2024-02-29")
    )


def test_anniversaries_of_a_leap_day_issue():
    issue = d("2020-02-29")
    assert lexis.anniversary(issue, 0)[0] == np.datetime64("2020-02-29")
    assert lexis.anniversary(issue, 1)[0] == np.datetime64("2021-02-28")
    assert lexis.anniversary(issue, 4)[0] == np.datetime64("2024-02-29")


def test_completed_years_counts_anniversaries_on_or_before():
    issue = d("2015-06-15", "2015-06-15", "2015-06-15")
    at = d("2016-06-14", "2016-06-15", "2020-01-01")
    assert lexis.completed_years(issue, at).tolist() == [0, 1, 4]


def test_a_hand_worked_policy():
    # issued 15 March 2020, observed to 1 March 2022
    seg = lexis.lexis_split(d("2020-03-15"), d("2020-03-15"), d("2022-03-01"))
    assert seg["start"].tolist() == list(d("2020-03-15", "2021-01-01", "2021-03-15", "2022-01-01"))
    assert seg["end"].tolist() == list(d("2021-01-01", "2021-03-15", "2022-01-01", "2022-03-01"))
    assert seg["duration"].tolist() == [1, 1, 2, 2]
    assert seg["calendar_year"].tolist() == [2020, 2021, 2021, 2022]
    assert seg["last"].tolist() == [False, False, False, True]
    assert seg["exposure"].sum() == pytest.approx(
        (np.datetime64("2022-03-01") - np.datetime64("2020-03-15")).astype(int) / 365.25
    )


def test_an_anniversary_on_new_year_makes_one_cut_not_two():
    seg = lexis.lexis_split(d("2019-01-01"), d("2019-01-01"), d("2021-06-30"))
    assert seg["start"].is_unique
    assert seg["duration"].tolist() == [1, 2, 3]
    assert seg["calendar_year"].tolist() == [2019, 2020, 2021]


def test_entry_on_an_anniversary_starts_a_new_duration():
    seg = lexis.lexis_split(d("2010-05-10"), d("2014-05-10"), d("2014-12-31"))
    assert seg["duration"].tolist() == [5]
    assert seg["calendar_year"].tolist() == [2014]


def test_entry_after_issue_is_left_truncated():
    seg = lexis.lexis_split(d("2010-01-01"), d("2014-01-01"), d("2015-06-01"))
    assert seg["start"].iloc[0] == np.datetime64("2014-01-01")
    assert seg["duration"].tolist()[0] == 5
    assert seg["exposure"].sum() == pytest.approx(
        (np.datetime64("2015-06-01") - np.datetime64("2014-01-01")).astype(int) / 365.25
    )


def test_empty_and_reversed_periods_give_no_rows():
    seg = lexis.lexis_split(
        d("2020-01-01", "2020-01-01"), d("2020-06-01", "2020-06-01"), d("2020-06-01", "2020-01-01")
    )
    assert len(seg) == 0
    assert set(seg.columns) >= {"pos", "start", "end", "exposure"}


def test_exposure_and_boundaries_hold_for_random_policies():
    rng = np.random.default_rng(0)
    n = 4000
    issue = np.datetime64("2000-01-01") + rng.integers(0, 365 * 24, n).astype("timedelta64[D]")
    entry = issue + rng.integers(0, 365 * 8, n).astype("timedelta64[D]")
    exit_ = entry + rng.integers(1, 365 * 12, n).astype("timedelta64[D]")
    seg = lexis.lexis_split(issue, entry, exit_)
    # every day of observation is counted exactly once
    total = (exit_ - entry).astype(int) / 365.25
    assert seg.groupby("pos")["exposure"].sum().to_numpy() == pytest.approx(total)
    assert set(seg["pos"]) == set(range(n))
    # pieces are contiguous, non-empty, and never cross an anniversary or 1 January
    assert (seg["end"] > seg["start"]).all()
    year_start, year_end = (
        lexis.split_date(seg["start"])[0],
        lexis.split_date(seg["end"] - np.timedelta64(1, "D"))[0],
    )
    assert (year_start == year_end).all()
    iss = issue[seg["pos"].to_numpy()]
    assert (
        lexis.completed_years(iss, seg["start"])
        == lexis.completed_years(iss, seg["end"] - np.timedelta64(1, "D"))
    ).all()
    # exactly one last piece per policy, and it ends at the exit date
    assert seg["last"].sum() == n
    assert (
        seg.loc[seg["last"], "end"].to_numpy() == exit_[seg.loc[seg["last"], "pos"].to_numpy()]
    ).all()
    # durations never fall along a policy
    assert (seg.groupby("pos")["duration"].diff().dropna() >= 0).all()
