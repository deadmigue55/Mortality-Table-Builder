"""Exact exposure from dates: the Lexis split behind an experience study.

A policy contributes exposure from the day it enters observation until the day it leaves (death,
lapse, expiry) or the study ends. Mortality depends on three clocks that tick at different
moments: attained age and policy duration change at each policy anniversary, and the calendar
year changes on 1 January. To attribute every day of exposure, and every death, to exactly one
combination of the three, each policy's observation period is cut at every anniversary and every
1 January. Inside a piece nothing changes, so the force of mortality is constant there and
``expected deaths = exposure x rate`` is exact.

This module has no dependency on the rest of the project: it works on arrays of dates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365.25


def _to_day(dates) -> np.ndarray:
    return np.asarray(dates).astype("datetime64[D]")


def split_date(dates) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Year, month and day of month of each date, as integer arrays."""
    d = _to_day(dates)
    months = d.astype("datetime64[M]")
    years = d.astype("datetime64[Y]")
    year = years.astype(int) + 1970
    month = (months - years.astype("datetime64[M]")).astype(int) + 1
    day = (d - months.astype("datetime64[D]")).astype(int) + 1
    return year, month, day


def make_date(year, month, day) -> np.ndarray:
    """Dates from integer parts; a day past the end of the month is moved back to its last day
    (29 February in a non-leap year becomes 28 February)."""
    year, month, day = (np.asarray(a, dtype=int) for a in (year, month, day))
    start = (year - 1970).astype("datetime64[Y]").astype("datetime64[M]")
    start = start + (month - 1).astype("timedelta64[M]")
    days_in_month = (
        (start + np.timedelta64(1, "M")).astype("datetime64[D]") - start.astype("datetime64[D]")
    ).astype(int)
    return start.astype("datetime64[D]") + (np.minimum(day, days_in_month) - 1).astype(
        "timedelta64[D]"
    )


def anniversary(issue, k) -> np.ndarray:
    """The ``k``-th anniversary of the issue dates (``k = 0`` is the issue date itself)."""
    year, month, day = split_date(issue)
    return make_date(year + np.asarray(k, dtype=int), month, day)


def completed_years(start, at) -> np.ndarray:
    """Whole years from ``start`` to ``at``: how many anniversaries of ``start`` are on or before
    ``at``. Used both for policy duration and for age last birthday."""
    y_start, _, _ = split_date(start)
    y_at, _, _ = split_date(at)
    k = y_at - y_start
    return k - (anniversary(start, k) > _to_day(at)).astype(int)


def lexis_split(issue, entry, exit_) -> pd.DataFrame:
    """Cut each observation period ``[entry, exit)`` at policy anniversaries and 1 January.

    The three arrays are aligned, one element per policy. Rows with ``exit <= entry`` give no
    exposure and are skipped. Returns one row per piece with:

    ``pos`` index of the policy in the inputs; ``start``, ``end`` dates; ``duration`` policy year
    (1 for the first); ``calendar_year``; ``exposure`` in years (days / 365.25); ``last`` True
    for the final piece of a policy (where an exit event is recorded).
    """
    issue, entry, exit_ = _to_day(issue), _to_day(entry), _to_day(exit_)
    keep = np.flatnonzero(exit_ > entry)
    if len(keep) == 0:
        return pd.DataFrame(
            {
                c: []
                for c in ("pos", "start", "end", "duration", "calendar_year", "exposure", "last")
            }
        )
    iss, ent, ext = issue[keep], entry[keep], exit_[keep]
    day = np.timedelta64(1, "D")

    first_k = completed_years(iss, ent)
    last_k = completed_years(iss, ext - day)
    n_anniversaries = np.maximum(last_k - first_k, 0)
    y_entry, _, _ = split_date(ent)
    y_last, _, _ = split_date(ext - day)
    n_calendar = np.maximum(y_last - y_entry, 0)

    def expand(counts):
        owner = np.repeat(np.arange(len(counts)), counts)
        starts = np.cumsum(counts) - counts
        within = np.arange(counts.sum()) - np.repeat(starts, counts)
        return owner, within

    own_a, within_a = expand(n_anniversaries)
    date_a = anniversary(iss[own_a], first_k[own_a] + 1 + within_a)
    own_c, within_c = expand(n_calendar)
    date_c = make_date(y_entry[own_c] + 1 + within_c, 1, 1)

    n = len(keep)
    owner = np.concatenate([np.arange(n), np.arange(n), own_a, own_c])
    when = np.concatenate([ent, ext, date_a, date_c])
    order = np.lexsort((when, owner))
    owner, when = owner[order], when[order]
    distinct = np.ones(len(owner), dtype=bool)
    distinct[1:] = (owner[1:] != owner[:-1]) | (when[1:] != when[:-1])  # an anniversary on 1 Jan
    owner, when = owner[distinct], when[distinct]

    same = owner[1:] == owner[:-1]
    start, end, who = when[:-1][same], when[1:][same], owner[:-1][same]
    is_last = np.ones(len(who), dtype=bool)
    is_last[:-1] = who[1:] != who[:-1]
    year, _, _ = split_date(start)
    return pd.DataFrame(
        {
            "pos": keep[who],
            "start": start,
            "end": end,
            "duration": completed_years(iss[who], start) + 1,
            "calendar_year": year,
            "exposure": (end - start).astype(int) / DAYS_PER_YEAR,
            "last": is_last,
        }
    )
