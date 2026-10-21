"""An insurer-style mortality experience study.

The study takes a policy-level administrative extract (the fields any life insurer holds: dates,
sum assured, underwriting class, channel, exit reason) and turns it into the things a pricing or
valuation actuary needs: validated data, exact exposure, actual-to-expected ratios by count and
amount with confidence intervals, credibility-weighted results, multivariate relativities,
select-period and calendar-year findings, a claims-reporting-lag correction, a derived
mortality basis and its financial impact.

Nothing here knows whether the extract is real. ``portfolio.py`` builds a synthetic extract with
effects planted at known sizes so that the whole method can be tested for what it recovers.

Sections: groupings, data validation, exposure and expected deaths, actual-to-expected,
credibility, relativities (GLM), select period, claims lag, the basis, financial impact.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mortality import lexis

# ── Groupings ───────────────────────────────────────────────────────────────

AGE_EDGES = (0, 30, 40, 50, 60, 200)
AGE_LABELS = ("18-29", "30-39", "40-49", "50-59", "60+")
DURATION_LABELS = ("1", "2", "3", "4", "5", "6-10", "11+")
AMOUNT_EDGES = (0.0, 250_000.0, 1_000_000.0, 5_000_000.0, np.inf)
AMOUNT_LABELS = ("<250k", "250k-1M", "1M-5M", "5M+")


def age_group(age) -> np.ndarray:
    """Attained-age group labels (``AGE_LABELS``) for integer ages."""
    idx = np.digitize(np.asarray(age), AGE_EDGES[1:-1])
    return np.asarray(AGE_LABELS)[idx]


def duration_group(duration) -> np.ndarray:
    """Policy-duration group labels: single years to 5, then 6-10 and 11+ (1 = first year)."""
    d = np.asarray(duration)
    labels = np.asarray(DURATION_LABELS)
    idx = np.where(d <= 5, d - 1, np.where(d <= 10, 5, 6))
    return labels[idx]


def amount_band(sum_assured) -> np.ndarray:
    """Sum-assured band labels (MXN)."""
    idx = np.digitize(np.asarray(sum_assured, dtype=float), AMOUNT_EDGES[1:-1])
    return np.asarray(AMOUNT_LABELS)[idx]


# ── Data validation ─────────────────────────────────────────────────────────

REQUIRED_COLUMNS = (
    "policy_id", "sex", "birth_date", "issue_date", "product", "sum_assured", "uw_class",
    "channel", "state", "status", "exit_date", "notification_date",
)  # fmt: skip
VALID_STATES = frozenset(f"{i:02d}" for i in range(1, 33))
MAX_ISSUE_AGE = 90


def validate_extract(
    policies: pd.DataFrame, study_end, extract_date
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Check an administrative extract before any rate is computed.

    Returns ``(clean, checks, reconciliation)``. ``checks`` lists each test with the number of
    records that fail it, how many of those are deaths, and what was done. ``reconciliation``
    follows the records from the extract to the clean file, because an actuary has to be able to
    say how many deaths a validation step threw away. Records that cannot be used are excluded;
    an unusable state code is repaired to "UNKNOWN" and a death with no notification date is kept.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in policies.columns]
    if missing:
        raise ValueError(f"The extract lacks required columns: {', '.join(missing)}")
    p = policies.reset_index(drop=True).copy()
    issue = p["issue_date"].to_numpy("datetime64[D]")
    birth = p["birth_date"].to_numpy("datetime64[D]")
    exit_ = p["exit_date"].to_numpy("datetime64[D]")
    notified = p["notification_date"].to_numpy("datetime64[D]")
    has_exit = ~np.isnat(exit_)
    is_death = (p["status"] == "DEATH").to_numpy()

    with np.errstate(invalid="ignore"):
        birth_ok = ~np.isnat(birth) & ~np.isnat(issue) & (birth < issue)
        age = np.where(birth_ok, lexis.completed_years(birth, issue), -1)
        masks = {
            "duplicate_record": (
                p.duplicated("policy_id", keep="first").to_numpy(), "error", "second copy dropped"
            ),
            "invalid_sex": (~p["sex"].isin(["M", "F"]).to_numpy(), "error", "excluded"),
            "birth_missing_or_after_issue": (~birth_ok, "error", "excluded"),
            "implausible_issue_age": (
                birth_ok & (age > MAX_ISSUE_AGE), "error", "excluded"
            ),
            "non_positive_sum_assured": (
                ~(p["sum_assured"].to_numpy(float) > 0), "error", "excluded"
            ),
            "exit_before_issue": (has_exit & (exit_ < issue), "error", "excluded"),
            "issue_after_extract": (issue > np.datetime64(extract_date), "error", "excluded"),
            "status_and_exit_date_disagree": (
                (p["status"].eq("IN_FORCE").to_numpy() & has_exit)
                | (~p["status"].eq("IN_FORCE").to_numpy() & ~has_exit),
                "error", "excluded",
            ),
            "invalid_state": (
                ~p["state"].isin(VALID_STATES).to_numpy(), "warning", "set to UNKNOWN"
            ),
            "death_without_notification": (
                is_death & np.isnat(notified), "warning", "kept; left out of the lag estimate"
            ),
            "notified_before_death": (
                is_death & ~np.isnat(notified) & has_exit & (notified < exit_), "warning",
                "kept; left out of the lag estimate",
            ),
        }  # fmt: skip
    rows = [
        {"check": name, "severity": severity, "records": int(mask.sum()),
         "deaths": int((mask & is_death).sum()), "action": action}
        for name, (mask, severity, action) in masks.items()
    ]  # fmt: skip
    exclude = np.zeros(len(p), dtype=bool)
    for mask, severity, _ in masks.values():
        if severity == "error":
            exclude |= mask
    clean = p.loc[~exclude].copy()
    clean["state"] = clean["state"].where(clean["state"].isin(VALID_STATES), "UNKNOWN")
    clean["issue_age"] = lexis.completed_years(
        clean["birth_date"].to_numpy("datetime64[D]"), clean["issue_date"].to_numpy("datetime64[D]")
    )
    duplicate = masks["duplicate_record"][0]
    other = exclude & ~duplicate
    reconciliation = pd.DataFrame(
        [
            ("records in the extract", len(p), int(is_death.sum())),
            ("duplicate copies dropped", int(duplicate.sum()), int((duplicate & is_death).sum())),
            ("records excluded for other reasons", int(other.sum()), int((other & is_death).sum())),
            ("records in the clean file", len(clean), int((clean["status"] == "DEATH").sum())),
        ],
        columns=["step", "records", "deaths"],
    )
    return clean, pd.DataFrame(rows), reconciliation


# ── Exposure and expected deaths ────────────────────────────────────────────


def build_exposure(clean: pd.DataFrame, study_start, study_end) -> pd.DataFrame:
    """Exact exposure by Lexis piece with deaths attached.

    Each policy is observed from the later of its issue and ``study_start`` until it exits or the
    study ends. An unreported death is still "in force": that bias is the claims lag, handled in
    ``completion_by_quarter``. Every piece carries its attained age (issue age plus duration
    minus one), duration, calendar year and the policy's rating factors.
    """
    start, stop = np.datetime64(study_start), np.datetime64(study_end)
    issue = clean["issue_date"].to_numpy("datetime64[D]")
    exit_ = clean["exit_date"].to_numpy("datetime64[D]")
    has_exit = ~np.isnat(exit_)
    entry = np.maximum(issue, start)
    end = np.where(has_exit & (exit_ <= stop), exit_, stop)
    seg = lexis.lexis_split(issue, entry, end)
    pos = seg["pos"].to_numpy()
    died = (clean["status"] == "DEATH").to_numpy() & has_exit & (exit_ <= stop) & (exit_ > entry)
    sa = clean["sum_assured"].to_numpy(float)[pos]
    duration = seg["duration"].to_numpy()
    age = clean["issue_age"].to_numpy()[pos] + duration - 1
    deaths = (seg["last"].to_numpy() & died[pos]).astype(np.int8)
    out = pd.DataFrame(
        {
            "start": seg["start"], "end": seg["end"],
            "calendar_year": seg["calendar_year"].astype(np.int16),
            "duration": duration.astype(np.int16), "attained_age": age.astype(np.int16),
            "exposure": seg["exposure"], "deaths": deaths, "sum_assured": sa,
            "sex": clean["sex"].to_numpy()[pos], "product": clean["product"].to_numpy()[pos],
            "uw_class": clean["uw_class"].to_numpy()[pos],
            "channel": clean["channel"].to_numpy()[pos],
            "state": clean["state"].to_numpy()[pos],
        }
    )  # fmt: skip
    for column in ("sex", "product", "uw_class", "channel", "state"):
        out[column] = out[column].astype("category")
    out["age_group"] = pd.Categorical(age_group(age), categories=AGE_LABELS)
    out["duration_group"] = pd.Categorical(duration_group(duration), categories=DURATION_LABELS)
    out["amount_band"] = pd.Categorical(amount_band(sa), categories=AMOUNT_LABELS)
    return out


def add_expected(seg: pd.DataFrame, q_basis: pd.Series, name: str = "expected") -> pd.DataFrame:
    """Expected deaths on a table of annual q by age: exposure times the constant force
    ``-ln(1 - q)`` that reproduces q over a year. Ages past the table use its last value."""
    q = q_basis.sort_index()
    age = np.clip(seg["attained_age"].to_numpy(), int(q.index.min()), int(q.index.max()))
    mu = -np.log1p(-np.clip(q.reindex(age).to_numpy(), 0.0, 0.999999))
    seg[name] = seg["exposure"].to_numpy() * mu
    return seg


# ── Actual to expected ──────────────────────────────────────────────────────

FULL_CREDIBILITY_DEATHS = 1082  # 90% probability of being within 5% (Mowbray / classical)


def aggregate(seg: pd.DataFrame, by: list[str], expected: str = "expected") -> pd.DataFrame:
    """Sum the pieces into cells: counts and sum-assured-weighted amounts."""
    tmp = pd.DataFrame(
        {
            **{c: seg[c] for c in by},
            "exposure": seg["exposure"],
            "deaths": seg["deaths"].astype(float),
            "expected": seg[expected],
            "exposure_amount": seg["exposure"] * seg["sum_assured"],
            "expected_amount": seg[expected] * seg["sum_assured"],
            "death_amount": seg["deaths"] * seg["sum_assured"],
            "death_amount_sq": seg["deaths"] * seg["sum_assured"] ** 2,
        }
    )
    return tmp.groupby(by, observed=True, sort=True).sum().reset_index()


def credibility_z(deaths, full: float = FULL_CREDIBILITY_DEATHS) -> np.ndarray:
    """Limited-fluctuation credibility: the square root of the share of full credibility."""
    return np.sqrt(np.minimum(np.asarray(deaths, dtype=float) / full, 1.0))


def actual_to_expected(cells: pd.DataFrame, by: list[str], level: float = 0.95) -> pd.DataFrame:
    """Actual over expected by count and by amount, with intervals and credibility.

    Count A/E has an exact Poisson interval (the expected deaths are treated as fixed). Amount
    A/E has a normal interval from the compound-Poisson variance ``sum(SA^2 over claims)``, which
    is much wider than the count interval: a few large claims drive the amount ratio.
    ``ae_credible`` shrinks the count A/E toward 1 (the expected basis) by the limited-
    fluctuation factor.
    """
    from mortality import rates

    g = (
        cells.groupby(by, observed=True, sort=True).sum(numeric_only=True).reset_index()
        if by
        else (cells.sum(numeric_only=True).to_frame().T)
    )
    lower, upper = rates.poisson_interval(g["deaths"].to_numpy(), 1 - level)
    g["ae"] = g["deaths"] / g["expected"]
    g["ae_lower"], g["ae_upper"] = lower / g["expected"], upper / g["expected"]
    g["ae_amount"] = g["death_amount"] / g["expected_amount"]
    half = 1.959964 * np.sqrt(g["death_amount_sq"]) / g["expected_amount"]
    g["ae_amount_lower"] = (g["ae_amount"] - half).clip(lower=0.0)
    g["ae_amount_upper"] = g["ae_amount"] + half
    g["credibility"] = credibility_z(g["deaths"])
    g["ae_credible"] = g["credibility"] * g["ae"] + (1.0 - g["credibility"])
    return g


def buhlmann_straub(ratios: np.ndarray, weights: np.ndarray) -> dict[str, np.ndarray | float]:
    """Bühlmann-Straub credibility across risk classes observed over several periods.

    ``ratios`` and ``weights`` are ``(classes, periods)``; a ratio is a class's A/E in a period
    and its weight is that cell's expected deaths (NaN where a class is not observed). Estimates
    the expected process variance ``s2`` (scatter inside a class), the variance of the true
    class means ``v`` (scatter between them), and ``k = s2 / v``. A class with total weight ``w``
    gets ``z = w / (w + k)``: more expected deaths, more weight on its own experience. When the
    classes do not differ by more than chance ``v`` is not positive and every ``z`` is 0.
    """
    r = np.asarray(ratios, dtype=float)
    w = np.where(np.isnan(r), 0.0, np.asarray(weights, dtype=float))
    r = np.nan_to_num(r)
    wi = w.sum(axis=1)
    keep = wi > 0
    r, w, wi = r[keep], w[keep], wi[keep]
    ri = (w * r).sum(axis=1) / wi
    n_obs = (w > 0).sum(axis=1)
    classes, total = len(wi), wi.sum()
    grand = (wi * ri).sum() / total
    s2 = (w * (r - ri[:, None]) ** 2).sum() / max((n_obs - 1).sum(), 1)
    denom = total - (wi**2).sum() / total
    v = ((wi * (ri - grand) ** 2).sum() - (classes - 1) * s2) / denom if denom > 0 else 0.0
    k = s2 / v if v > 0 else np.inf
    z = wi / (wi + k) if np.isfinite(k) else np.zeros_like(wi)
    return {"class_mean": ri, "grand_mean": float(grand), "s2": float(s2), "v": float(v),
            "k": float(k), "z": z, "credible_mean": z * ri + (1 - z) * grand}  # fmt: skip


# ── Relativities: a Poisson GLM ─────────────────────────────────────────────

GLM_REFERENCE = {
    "sex": "M", "uw_class": "STANDARD", "amount_band": "250k-1M", "channel": "AGENT",
    "product": "TERM", "age_group": "40-49", "duration_group": "6-10", "calendar_year": 2019,
    "region": "LOW",
}  # fmt: skip
COVID_YEARS = (2020, 2021, 2022)


def fit_relativities(
    cells: pd.DataFrame, factors: list[str], reference: dict | None = None
) -> dict[str, pd.DataFrame | float]:
    """Poisson regression of deaths on rating factors with log expected deaths as offset.

    ``exp(coefficient)`` is a relativity: how much more or less mortality a level has than the
    reference level, other factors held equal. The intercept is the A/E ratio of the all-reference
    cell. The model fits all factors at once, so overlapping effects are separated (a channel that
    sells mostly simplified-issue business looks worse in a one-way table and is cleared by the
    class factor). Standard errors are scaled by the dispersion of the fit (quasi-Poisson), the
    honest choice when cells show more scatter than a Poisson count.
    """
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    ref = {**GLM_REFERENCE, **(reference or {})}
    d = cells[cells["expected"] > 0].copy()
    for f in factors:
        d[f] = d[f].astype(str) if f != "calendar_year" else d[f].astype(int).astype(str)
    terms = [f"C({f}, Treatment(reference='{ref[f]}'))" for f in factors]
    model = smf.glm(
        "deaths ~ " + " + ".join(terms),
        data=d,
        family=sm.families.Poisson(),
        offset=np.log(d["expected"].to_numpy()),
    )
    plain = model.fit()
    dispersion = binned_dispersion(d["deaths"].to_numpy(), plain.mu, len(plain.params))
    scaled = model.fit(scale=dispersion)
    z = 1.959964
    rows = [
        {"factor": "(intercept)", "level": "", "relativity": float(np.exp(scaled.params.iloc[0])),
         "lower": float(np.exp(scaled.params.iloc[0] - z * scaled.bse.iloc[0])),
         "upper": float(np.exp(scaled.params.iloc[0] + z * scaled.bse.iloc[0])),
         "se_log": float(scaled.bse.iloc[0]), "p_value": float(scaled.pvalues.iloc[0])}
    ]  # fmt: skip
    import re

    for name, coef in scaled.params.items():
        match = re.match(r"C\((\w+), Treatment\(reference='.*?'\)\)\[T\.(.*)\]", name)
        if not match:
            continue
        se = float(scaled.bse[name])
        rows.append(
            {"factor": match.group(1), "level": match.group(2), "relativity": float(np.exp(coef)),
             "lower": float(np.exp(coef - z * se)), "upper": float(np.exp(coef + z * se)),
             "se_log": se, "p_value": float(scaled.pvalues[name])}
        )  # fmt: skip
    return {
        "table": pd.DataFrame(rows),
        "dispersion": dispersion,
        "deviance": float(plain.deviance),
        "n_cells": len(d),
        "n_deaths": float(d["deaths"].sum()),
        "model": scaled,
    }


def binned_dispersion(observed, fitted, n_params: int, bin_size: float = 10.0) -> float:
    """Overdispersion of a Poisson fit, estimated on bins that have enough expected deaths.

    With 100,000 sparse cells the usual Pearson statistic is dominated by cells that expect a
    fraction of a death, where a Poisson count is far from normal, and it overstates the
    dispersion even for data that are exactly Poisson. Cells are sorted by fitted value and pooled
    into bins of about ``bin_size`` expected deaths; the Pearson statistic of the bins, divided
    by their degrees of freedom, is a stable estimate. Values below 1 are reported as 1.
    """
    o = np.asarray(observed, dtype=float)
    f = np.asarray(fitted, dtype=float)
    order = np.argsort(f)
    bins = np.floor(np.cumsum(f[order]) / bin_size).astype(int)
    pooled = pd.DataFrame({"o": o[order], "f": f[order], "bin": bins}).groupby("bin").sum()
    pooled = pooled[pooled["f"] >= 0.5 * bin_size]
    df = len(pooled) - n_params
    if df <= 0:
        return 1.0
    chi2 = float(((pooled["o"] - pooled["f"]) ** 2 / pooled["f"]).sum())
    return max(1.0, chi2 / df)


def planted_relativities(truth: dict, reference: dict | None = None) -> pd.DataFrame:
    """Relativity of every level of the main factors versus the reference level, as planted."""
    ref = {**GLM_REFERENCE, **(reference or {})}
    rows = []
    for factor in ("sex", "uw_class", "amount_band", "channel", "product", "age_group"):
        values = truth[factor]
        for level, value in values.items():
            if level != ref[factor]:
                rows.append((factor, level, value / values[ref[factor]]))
    return pd.DataFrame(rows, columns=["factor", "level", "planted"])


def recovery(estimated: pd.DataFrame, planted: pd.DataFrame) -> pd.DataFrame:
    """Compare estimated relativities with the planted ones: the validation of the whole study."""
    m = planted.merge(estimated, on=["factor", "level"], how="left")
    m["inside_interval"] = (m["planted"] >= m["lower"]) & (m["planted"] <= m["upper"])
    m["error_pct"] = m["relativity"] / m["planted"] - 1.0
    return m[["factor", "level", "planted", "relativity", "lower", "upper", "error_pct",
              "inside_interval"]]  # fmt: skip


# ── Select period ───────────────────────────────────────────────────────────


def pool_adjacent_violators(values, weights) -> np.ndarray:
    """Weighted isotonic (non-decreasing) regression: the closest non-decreasing sequence.

    Select factors must rise toward the ultimate level as underwriting wears off; sampling noise
    makes the raw factors zig-zag, and pooling adjacent violators removes that without inventing
    a shape."""
    v = [float(x) for x in values]
    w = [float(x) for x in weights]
    blocks: list[list[float]] = []  # [value, weight, count]
    for value, weight in zip(v, w, strict=True):
        blocks.append([value, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            a, b = blocks[-2], blocks[-1]
            total = a[1] + b[1]
            blocks[-2:] = [[(a[0] * a[1] + b[0] * b[1]) / total, total, a[2] + b[2]]]
    out: list[float] = []
    for value, _, count in blocks:
        out += [value] * count
    return np.asarray(out)


def select_table(
    cells: pd.DataFrame, group: str, factors: list[str], reference: dict | None = None
) -> pd.DataFrame:
    """Duration relativities for one subset of the portfolio, smoothed and with a select period.

    Fits the GLM on ``cells`` (already limited to one underwriting type), reads the duration
    effects against the ultimate group "6-10", pools adjacent violators over years 1 to 5, and
    reports the select period: the first duration from which every later one is statistically
    indistinguishable from the ultimate level.
    """
    fit = fit_relativities(cells, factors, reference)
    t = fit["table"]
    t = t[t["factor"] == "duration_group"].set_index("level")
    levels = ["1", "2", "3", "4", "5"]
    deaths = cells.groupby("duration_group", observed=True)["deaths"].sum()
    expected = cells.groupby("duration_group", observed=True)["expected"].sum()
    raw = t.reindex(levels)
    weights = 1.0 / np.maximum(raw["se_log"].to_numpy() ** 2, 1e-9)
    have = raw["relativity"].notna().to_numpy()
    smooth = np.full(len(raw), np.nan)  # durations with no estimate stay empty
    if have.any():
        smooth[have] = pool_adjacent_violators(raw["relativity"].to_numpy()[have], weights[have])
    out = pd.DataFrame(
        {
            "duration": [1, 2, 3, 4, 5],
            "deaths": [float(deaths.get(level, 0.0)) for level in levels],
            "expected": [float(expected.get(level, 0.0)) for level in levels],
            "relativity": raw["relativity"].to_numpy(),
            "lower": raw["lower"].to_numpy(),
            "upper": raw["upper"].to_numpy(),
            "smoothed": np.minimum(smooth, 1.0),
        }
    )
    # the select period is the last duration whose factor is still distinguishable from 1
    # a duration with no estimate (no data) cannot show a select effect
    differs = out["lower"].notna() & ~((out["lower"] <= 1.0) & (out["upper"] >= 1.0))
    out["select_period"] = int(out.loc[differs, "duration"].max()) if differs.any() else 0
    out["dispersion"] = fit["dispersion"]
    return out


# ── Claims reporting lag ────────────────────────────────────────────────────


def estimate_lag_distribution(clean: pd.DataFrame, extract_date, mature_days: int = 540):
    """Empirical distribution of the days from death to notification.

    Uses only deaths old enough that nearly all have been reported (``mature_days`` before the
    extract), so the distribution is not truncated by the extract itself. Returns the lag grid in
    days and the cumulative share reported within each lag.
    """
    extract = np.datetime64(extract_date)
    d = clean[
        (clean["status"] == "DEATH")
        & clean["notification_date"].notna()
        & clean["exit_date"].notna()
    ]
    exit_ = d["exit_date"].to_numpy("datetime64[D]")
    note = d["notification_date"].to_numpy("datetime64[D]")
    ok = (note >= exit_) & (exit_ <= extract - np.timedelta64(mature_days, "D"))
    lags = (note[ok] - exit_[ok]).astype(int)
    if len(lags) < 30:
        raise ValueError("Too few mature deaths to estimate the reporting lag.")
    grid = np.arange(0, int(lags.max()) + 1)
    cdf = np.searchsorted(np.sort(lags), grid, side="right") / len(lags)
    return grid, cdf


def completion_by_quarter(grid, cdf, extract_date, quarters) -> pd.Series:
    """Share of deaths in each calendar quarter that are in the extract, on average.

    ``quarters``: iterable of ``(year, quarter)``. For each day of a quarter the share reported by
    the extract date is ``cdf(extract - day)``; the quarter's value is the mean over its days.
    """
    from mortality import lexis as lx

    extract = np.datetime64(extract_date)
    out = {}
    for year, quarter in quarters:
        first = lx.make_date([year], [3 * quarter - 2], [1])[0]
        nxt = lx.make_date([year + (quarter == 4)], [1 if quarter == 4 else 3 * quarter + 1], [1])[
            0
        ]
        days = np.arange(first, nxt)
        waiting = np.clip((extract - days).astype(int), 0, len(grid) - 1)
        out[(year, quarter)] = float(np.mean(cdf[waiting]))
    return pd.Series(out)


def quarterly_experience(seg: pd.DataFrame, completion: pd.Series | None = None) -> pd.DataFrame:
    """A/E by calendar quarter, as reported and completed for the claims lag.

    Each piece lies inside one calendar year; its exposure and expected deaths are shared among
    the quarters it overlaps in proportion to days (exact, because the force is constant in a
    piece). A death belongs to the quarter of its last day of exposure.
    """
    from mortality import lexis as lx

    start = seg["start"].to_numpy("datetime64[D]")
    end = seg["end"].to_numpy("datetime64[D]")
    year = seg["calendar_year"].to_numpy()
    length = np.maximum((end - start).astype(int), 1)
    rows = []
    expected_all = seg["expected"].to_numpy()
    exposure_all = seg["exposure"].to_numpy()
    for quarter in (1, 2, 3, 4):
        qs = lx.make_date(year, 3 * quarter - 2, 1)
        qe = lx.make_date(year + (quarter == 4), 1 if quarter == 4 else 3 * quarter + 1, 1)
        overlap = np.clip((np.minimum(end, qe) - np.maximum(start, qs)).astype(int), 0, None)
        share = overlap / length
        frame = pd.DataFrame(
            {"year": year, "quarter": quarter, "exposure": exposure_all * share,
             "expected": expected_all * share}
        )  # fmt: skip
        rows.append(frame.groupby(["year", "quarter"]).sum().reset_index())
    base = pd.concat(rows).groupby(["year", "quarter"], as_index=False).sum()
    died = seg["deaths"].to_numpy() > 0
    last_day = end[died] - np.timedelta64(1, "D")
    y, m, _ = lx.split_date(last_day)
    deaths = (
        pd.DataFrame({"year": y, "quarter": (m - 1) // 3 + 1}).groupby(["year", "quarter"]).size()
    )
    base = base.merge(deaths.rename("deaths").reset_index(), on=["year", "quarter"], how="left")
    base["deaths"] = base["deaths"].fillna(0.0)
    base = base[base["exposure"] > 0].reset_index(drop=True)
    base["ae"] = base["deaths"] / base["expected"]
    if completion is not None:
        key = list(zip(base["year"], base["quarter"], strict=True))
        base["completion"] = [completion.get(k, 1.0) for k in key]
        base["deaths_completed"] = base["deaths"] / base["completion"]
        base["ae_completed"] = base["deaths_completed"] / base["expected"]
    return base


# ── A derived mortality basis ───────────────────────────────────────────────

BASIS_FACTORS = ["sex", "age_group", "duration_group"]
AGE_CENTRES = {"18-29": 24.0, "30-39": 34.5, "40-49": 44.5, "50-59": 54.5, "60+": 65.0}


def build_basis(cells: pd.DataFrame, q_basis: pd.Series, ages=range(18, 101)) -> pd.DataFrame:
    """A company mortality basis: the expected table times a credibility-weighted multiplier.

    The multiplier of each (sex, age group, duration group) comes from a GLM on the non-pandemic
    years. The overall level and each factor effect are shrunk toward 1.0 (the expected table) by
    limited-fluctuation credibility on the deaths behind them, then interpolated between age-group
    centres so the table has no steps. ``multiplier_upper`` is the 95% upper bound from the
    model's covariance: a margin an actuary can add where a prudent basis is required.
    """
    fit = fit_relativities(cells, BASIS_FACTORS)
    model, table = fit["model"], fit["table"]
    deaths = {
        (f, str(level)): float(v)
        for f in BASIS_FACTORS
        for level, v in cells.groupby(f, observed=True)["deaths"].sum().items()
    }
    z_total = float(credibility_z(fit["n_deaths"]))
    z_level = {
        (r["factor"], r["level"]): float(credibility_z(deaths.get((r["factor"], r["level"]), 0.0)))
        for _, r in table.iterrows()
        if r["factor"] != "(intercept)"
    }
    log_effect = {
        (r["factor"], r["level"]): np.log(r["relativity"]) * z_level[(r["factor"], r["level"])]
        for _, r in table.iterrows()
        if r["factor"] != "(intercept)"
    }
    intercept = np.log(table.loc[table["factor"] == "(intercept)", "relativity"].iloc[0]) * z_total
    ages = np.asarray(list(ages))
    centres = np.asarray([AGE_CENTRES[g] for g in AGE_LABELS])
    rows = []
    for sex in ("M", "F"):
        for dur in DURATION_LABELS:
            by_group = np.asarray(
                [
                    intercept
                    + log_effect.get(("sex", sex), 0.0)
                    + log_effect.get(("age_group", g), 0.0)
                    + log_effect.get(("duration_group", dur), 0.0)
                    for g in AGE_LABELS
                ]
            )
            log_mult = np.interp(ages, centres, by_group)
            # the parameter covariance gives an interval for the raw (unshrunk) multiplier
            grid = pd.DataFrame({"sex": sex, "age_group": list(AGE_LABELS), "duration_group": dur})
            pred = model.get_prediction(grid, offset=np.zeros(len(grid))).summary_frame()
            se_by_group = np.asarray(
                (np.log(pred["mean_ci_upper"]) - np.log(pred["mean"])) / 1.959964
            )
            se = np.interp(ages, centres, se_by_group)
            mult = np.exp(log_mult)
            upper = np.exp(log_mult + 1.645 * se)
            base_q = q_basis.reindex(
                np.clip(ages, int(q_basis.index.min()), int(q_basis.index.max()))
            )
            rows.append(
                pd.DataFrame(
                    {
                        "sex": sex,
                        "age": ages,
                        "duration_group": dur,
                        "multiplier": mult,
                        "multiplier_upper": upper,
                        "q_expected_basis": base_q.to_numpy(),
                        "q_experience": np.minimum(base_q.to_numpy() * mult, 1.0),
                        "q_experience_prudent": np.minimum(base_q.to_numpy() * upper, 1.0),
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


# ── Financial impact ────────────────────────────────────────────────────────


def _multiplier_lookup(basis: pd.DataFrame) -> dict[tuple, np.ndarray]:
    ages = np.arange(0, 111)
    out = {}
    for (sex, dur), g in basis.groupby(["sex", "duration_group"]):
        g = g.sort_values("age")
        out[(sex, dur)] = np.interp(ages, g["age"].to_numpy(), g["multiplier"].to_numpy())
    return out


def pv_death_benefits(
    inforce: pd.DataFrame, q_basis: pd.Series, basis: pd.DataFrame | None, interest: float = 0.04
) -> pd.DataFrame:
    """Present value of future death benefits of an in-force block, with and without the basis.

    ``inforce`` needs ``sex``, ``attained_age``, ``duration``, ``years_left`` and ``sum_assured``.
    Benefits are paid at the end of the year of death, no lapses are assumed, and policies are
    grouped by (sex, age, duration, years left) so the projection is a matrix operation.
    Returns the block's ``pv_cnsf`` (expected table alone) and ``pv_experience`` and the expected
    claims in the next 12 months under each.
    """
    mult = _multiplier_lookup(basis) if basis is not None else None
    q_all = q_basis.reindex(range(0, 111)).ffill().to_numpy()
    keys = (
        inforce.groupby(["sex", "attained_age", "duration", "years_left"], observed=True)[
            "sum_assured"
        ]
        .sum()
        .reset_index()
    )
    horizon = int(keys["years_left"].max())
    t = np.arange(horizon)
    v = (1.0 + interest) ** -(t + 1.0)
    out_cnsf = np.zeros(len(keys))
    out_exp = np.zeros(len(keys))
    first_cnsf = np.zeros(len(keys))
    first_exp = np.zeros(len(keys))
    age0 = keys["attained_age"].to_numpy()
    dur0 = keys["duration"].to_numpy()
    left = keys["years_left"].to_numpy()
    ages = np.clip(age0[:, None] + t[None, :], 0, 110)
    live = t[None, :] < left[:, None]
    q_c = np.where(live, q_all[ages], 0.0)
    q_e = q_c.copy()
    if mult is not None:
        for sex in ("M", "F"):
            sel = (keys["sex"] == sex).to_numpy()
            if not sel.any():
                continue
            dur_t = dur0[sel][:, None] + t[None, :]
            labels = np.where(dur_t <= 5, dur_t.astype(str), np.where(dur_t <= 10, "6-10", "11+"))
            m = np.ones(dur_t.shape)
            for label in DURATION_LABELS:
                key = (sex, label)
                if key in mult:
                    m = np.where(labels == label, mult[key][ages[sel]], m)
            q_e[sel] = np.minimum(q_c[sel] * m, 1.0)
    for q, out, first in ((q_c, out_cnsf, first_cnsf), (q_e, out_exp, first_exp)):
        surv = np.concatenate(
            [np.ones((len(keys), 1)), np.cumprod(1.0 - q[:, :-1], axis=1)], axis=1
        )
        out[:] = (surv * q * v[None, :]).sum(axis=1)
        first[:] = q[:, 0]
    sa = keys["sum_assured"].to_numpy()
    return pd.DataFrame(
        {"pv_cnsf": [float((out_cnsf * sa).sum())], "pv_experience": [float((out_exp * sa).sum())],
         "claims_next_12m_cnsf": [float((first_cnsf * sa).sum())],
         "claims_next_12m_experience": [float((first_exp * sa).sum())]}
    )  # fmt: skip


def inforce_block(clean: pd.DataFrame, valuation_date) -> pd.DataFrame:
    """The policies in force on the valuation date, with age, duration and years left."""
    val = np.datetime64(valuation_date)
    alive = (clean["status"] == "IN_FORCE") & (clean["issue_date"].to_numpy("datetime64[D]") <= val)
    b = clean[alive].copy()
    issue = b["issue_date"].to_numpy("datetime64[D]")
    done = lexis.completed_years(issue, np.full(len(b), val))
    b["attained_age"] = b["issue_age"].to_numpy() + done
    b["duration"] = done + 1
    term = b["term_years"].to_numpy(float) if "term_years" in b.columns else np.full(len(b), np.nan)
    b["years_left"] = np.where(
        np.isnan(term), 111 - b["attained_age"], np.maximum(term - done, 1)
    ).astype(int)
    return b


def term_net_premium(q_path: np.ndarray, interest: float = 0.04) -> np.ndarray:
    """Net annual premium per unit of term insurance (paid at the start of each year while alive).

    ``q_path``: ``(policies, years)`` probabilities of death in each future policy year."""
    n, years = q_path.shape
    surv = np.concatenate([np.ones((n, 1)), np.cumprod(1.0 - q_path[:, :-1], axis=1)], axis=1)
    t = np.arange(years)
    claims = (surv * q_path * (1.0 + interest) ** -(t + 1.0)).sum(axis=1)
    annuity = (surv * (1.0 + interest) ** -t).sum(axis=1)
    return claims / annuity


# ── Pricing consequences ────────────────────────────────────────────────────


def _q_path(q_all: np.ndarray, ages: np.ndarray, sex: str, table: dict) -> np.ndarray:
    """Probabilities of death over the policy years of a new policy: the expected table times the
    multiplier for the policy year (duration group), age and sex."""
    dur = 1 + np.arange(len(ages))
    label = np.where(dur <= 5, dur.astype(str), np.where(dur <= 10, "6-10", "11+"))
    m = np.ones(len(ages))
    for lab in DURATION_LABELS:
        key = (sex, lab)
        if key in table:
            m = np.where(label == lab, table[key][ages], m)
    return np.minimum(q_all[ages] * m, 1.0)


def term_premium_table(
    basis: pd.DataFrame,
    q_basis: pd.Series,
    ages=(30, 40, 50),
    term: int = 20,
    interest: float = 0.04,
) -> pd.DataFrame:
    """Net annual term premium per 1,000 on the expected basis and on the experience basis.

    For each issue age and sex the 20-year path of q is built on the CNSF table alone, on the
    experience multipliers (which include the select effect by policy year), and on the prudent
    multipliers. The percentage change is the pricing signal of the study."""
    lookup = _multiplier_lookup(basis)
    upper = _multiplier_lookup(basis.assign(multiplier=basis["multiplier_upper"]))
    q_all = q_basis.reindex(range(0, 111)).ffill().to_numpy()
    rows = []
    for sex in ("M", "F"):
        for age in ages:
            years = np.clip(age + np.arange(term), 0, 110)
            base = term_net_premium(q_all[years][None, :], interest)[0]
            exp = term_net_premium(_q_path(q_all, years, sex, lookup)[None, :], interest)[0]
            prudent = term_net_premium(_q_path(q_all, years, sex, upper)[None, :], interest)[0]
            rows.append(
                {"sex": sex, "issue_age": age, "term": term,
                 "premium_cnsf_per_1000": 1000 * base, "premium_experience_per_1000": 1000 * exp,
                 "premium_prudent_per_1000": 1000 * prudent, "change_pct": exp / base - 1.0}
            )  # fmt: skip
    return pd.DataFrame(rows)


# ── The whole study ─────────────────────────────────────────────────────────


def region_groups(state_smr: dict[str, float]) -> dict[str, str]:
    """Group states into LOW, MID and HIGH terciles of standardised mortality ratio."""
    s = pd.Series(state_smr, dtype=float)
    return pd.qcut(s, 3, labels=["LOW", "MID", "HIGH"]).astype(str).to_dict()


MAIN_FACTORS = [
    "sex", "uw_class", "amount_band", "channel", "product", "duration_group", "age_group",
    "calendar_year", "region",
]  # fmt: skip
ONE_WAY = ["sex", "uw_class", "channel", "product", "amount_band", "duration_group", "age_group",
           "region", "calendar_year"]  # fmt: skip


def _stack(frames: dict[str, pd.DataFrame], key: str = "dimension") -> pd.DataFrame:
    parts = []
    for name, f in frames.items():
        g = f.copy()
        g.insert(0, key, name)
        g = g.rename(columns={name: "level"})
        g["level"] = g["level"].astype(str)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def run_study(
    policies: pd.DataFrame,
    q_basis: pd.Series,
    state_smr: dict[str, float],
    study_start,
    study_end,
    extract_date,
    truth: dict | None = None,
    interest: float = 0.04,
) -> dict[str, pd.DataFrame]:
    """Run every stage of the experience study on a policy extract.

    ``q_basis``: the expected table, annual q by age. ``state_smr``: state standardised mortality
    ratios, used only to group states into risk terciles. ``truth``: the planted effects, if the
    extract is synthetic, which adds a recovery table. Returns the result tables by name.
    """
    out: dict[str, pd.DataFrame] = {}
    clean, checks, recon = validate_extract(policies, study_end, extract_date)
    out["dq_checks"], out["dq_reconciliation"] = checks, recon

    seg = add_expected(build_exposure(clean, study_start, study_end), q_basis)
    regions = region_groups(state_smr)
    seg["region"] = pd.Categorical(
        seg["state"].astype(str).map(regions).fillna("MID"), categories=["LOW", "MID", "HIGH"]
    )
    covid = seg["calendar_year"].isin(COVID_YEARS)
    out["overview"] = pd.DataFrame(
        {
            "policies": [clean["policy_id"].nunique()],
            "exposure_years": [seg["exposure"].sum()],
            "deaths": [float(seg["deaths"].sum())],
            "expected_deaths": [seg["expected"].sum()],
            "sum_assured_in_force_mxn": [
                float(clean.loc[clean["status"] == "IN_FORCE", "sum_assured"].sum())
            ],
        }
    )

    # actual to expected: all years and without the pandemic years
    ae = {}
    for label, frame in (("all_years", seg), ("excluding_2020_2022", seg[~covid])):
        one = {f: actual_to_expected(aggregate(frame, [f]), [f]) for f in ONE_WAY}
        stacked = _stack(one)
        stacked.insert(0, "years", label)
        ae[label] = stacked
        total = actual_to_expected(aggregate(frame, ["sex"]), [])
        total.insert(0, "dimension", "all")
        total.insert(1, "level", "all")
        total.insert(0, "years", label)
        ae[label + "_total"] = total
    out["ae_one_way"] = pd.concat(list(ae.values()), ignore_index=True)
    out["ae_age_sex"] = actual_to_expected(
        aggregate(seg[~covid], ["age_group", "sex"]), ["age_group", "sex"]
    )
    out["ae_covid_age"] = actual_to_expected(
        aggregate(seg, ["calendar_year", "age_group"]), ["calendar_year", "age_group"]
    )

    # credibility across segments: Buhlmann-Straub on sex x class x channel, by calendar year
    seg_cells = aggregate(seg[~covid], ["sex", "uw_class", "channel", "calendar_year"])
    seg_cells["class"] = (
        seg_cells["sex"].astype(str)
        + "/"
        + seg_cells["uw_class"].astype(str)
        + "/"
        + seg_cells["channel"].astype(str)
    )
    seg_cells = seg_cells[seg_cells["expected"] > 0]
    ratio = seg_cells.pivot_table(
        index="class", columns="calendar_year", values="deaths", aggfunc="sum"
    )
    expected = seg_cells.pivot_table(
        index="class", columns="calendar_year", values="expected", aggfunc="sum"
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        bs = buhlmann_straub((ratio / expected).to_numpy(), expected.to_numpy())
    kept = expected.index[expected.sum(axis=1) > 0]
    totals = actual_to_expected(
        aggregate(seg[~covid], ["sex", "uw_class", "channel"]), ["sex", "uw_class", "channel"]
    )
    totals["class"] = (
        totals["sex"].astype(str)
        + "/"
        + totals["uw_class"].astype(str)
        + "/"
        + totals["channel"].astype(str)
    )
    cred = pd.DataFrame({"class": kept, "bs_z": bs["z"], "bs_credible_ae": bs["credible_mean"]})
    cred = totals.merge(cred, on="class")
    cred["bs_k"], cred["bs_s2"], cred["bs_v"], cred["grand_mean"] = (
        bs["k"],
        bs["s2"],
        bs["v"],
        bs["grand_mean"],
    )
    out["credibility_segments"] = cred.drop(
        columns=["exposure_amount", "expected_amount", "death_amount", "death_amount_sq"]
    )

    # the multivariate model on the non-pandemic years, and its recovery of the planted truth
    cells = aggregate(seg[~covid], MAIN_FACTORS)
    fit = fit_relativities(cells, MAIN_FACTORS)
    rel = fit["table"].copy()
    rel["dispersion"], rel["n_deaths"], rel["n_cells"] = (
        fit["dispersion"],
        fit["n_deaths"],
        fit["n_cells"],
    )
    out["relativities"] = rel
    if truth is not None:
        out["recovery"] = recovery(fit["table"], planted_relativities(truth))

    # select period by underwriting type, on all years with calendar-year effects
    selects = []
    for kind, mask in (
        ("fully underwritten", seg["uw_class"] != "SIMPLIFIED"),
        ("simplified issue", seg["uw_class"] == "SIMPLIFIED"),
    ):
        factors = [f for f in MAIN_FACTORS if not (kind == "simplified issue" and f == "uw_class")]
        table = select_table(aggregate(seg[mask], factors), "duration_group", factors)
        table.insert(0, "underwriting", kind)
        if truth is not None:
            planted = truth["select_simplified" if kind == "simplified issue" else "select_full"]
            table["planted"] = list(planted[:5])
            table["inside_interval"] = (table["planted"] >= table["lower"]) & (
                table["planted"] <= table["upper"]
            )
        selects.append(table)
    out["select"] = pd.concat(selects, ignore_index=True)

    # claims reporting lag and quarterly monitoring
    grid, cdf = estimate_lag_distribution(clean, extract_date)
    keep = min(len(grid), 400)
    out["lag_distribution"] = pd.DataFrame({"days": grid[:keep], "share_reported": cdf[:keep]})
    first_year = int(np.datetime64(study_end).astype("datetime64[Y]").astype(int) + 1970) - 4
    quarters = [
        (y, q) for y in range(first_year, first_year + 5) for q in (1, 2, 3, 4)
        if np.datetime64(f"{y}-{3 * q - 2:02d}-01") <= np.datetime64(study_end)
    ]  # fmt: skip
    completion = completion_by_quarter(grid, cdf, extract_date, quarters)
    quarterly = quarterly_experience(seg, completion)
    out["ae_quarterly"] = quarterly[quarterly["year"] >= first_year].reset_index(drop=True)

    # the derived basis, its pricing and its effect on the in-force block
    basis = build_basis(cells, q_basis)
    out["basis"] = basis
    out["pricing"] = term_premium_table(basis, q_basis, interest=interest)
    block = inforce_block(clean, study_end)
    rows = []
    for product, part in [("ALL", block), *block.groupby("product")]:
        pv = pv_death_benefits(part, q_basis, basis, interest)
        pv.insert(0, "product", product)
        pv.insert(1, "policies", len(part))
        pv.insert(2, "sum_assured_mxn", float(part["sum_assured"].sum()))
        rows.append(pv)
    impact = pd.concat(rows, ignore_index=True)
    impact["pv_change_pct"] = impact["pv_experience"] / impact["pv_cnsf"] - 1.0
    impact["claims_12m_change_pct"] = (
        impact["claims_next_12m_experience"] / impact["claims_next_12m_cnsf"] - 1.0
    )
    out["impact"] = impact
    return out


# ── Warehouse integration ───────────────────────────────────────────────────

TABLE_NAMES = {
    "overview": "experience_overview",
    "dq_checks": "experience_dq_checks",
    "dq_reconciliation": "experience_dq_reconciliation",
    "ae_one_way": "experience_ae",
    "ae_age_sex": "experience_ae_age_sex",
    "ae_covid_age": "experience_ae_covid",
    "ae_quarterly": "experience_ae_quarterly",
    "credibility_segments": "experience_credibility",
    "relativities": "experience_relativities",
    "recovery": "experience_recovery",
    "select": "experience_select",
    "lag_distribution": "experience_claims_lag",
    "basis": "experience_basis",
    "pricing": "experience_pricing",
    "impact": "experience_impact",
    "lag_validation": "experience_lag_validation",
    "truth": "experience_truth",
    "injected_defects": "experience_injected_defects",
}
DESCRIPTIONS = {
    "experience_overview": (
        "The synthetic portfolio study at a glance: policies, "
        "exposure, deaths, expected deaths, sum assured"
    ),
    "experience_dq_checks": (
        "Data validation of the policy extract: each test, records "
        "failing, deaths affected, action taken"
    ),
    "experience_dq_reconciliation": "Records and deaths from the extract to the clean file",
    "experience_ae": (
        "Actual-to-expected by count and amount, one rating factor at a "
        "time, with intervals and credibility, all years and excluding 2020-2022"
    ),
    "experience_ae_age_sex": "Actual-to-expected by age group and sex, excluding 2020-2022",
    "experience_ae_covid": (
        "Actual-to-expected by calendar year and age group: the pandemic years in the portfolio"
    ),
    "experience_ae_quarterly": (
        "Actual-to-expected by calendar quarter as reported and "
        "completed for the claims reporting lag"
    ),
    "experience_credibility": (
        "Limited-fluctuation and Buhlmann-Straub credibility by segment (sex, class, channel)"
    ),
    "experience_relativities": (
        "Poisson GLM relativities for every rating factor, other "
        "factors held equal, with quasi-Poisson intervals"
    ),
    "experience_recovery": (
        "Estimated relativities against the effects planted in the "
        "synthetic portfolio: the validation of the method"
    ),
    "experience_select": (
        "Duration (select) factors by underwriting type, raw and "
        "smoothed, with the select period and the planted truth"
    ),
    "experience_claims_lag": (
        "Share of deaths notified within each number of days: the claims reporting lag distribution"
    ),
    "experience_basis": (
        "Derived mortality basis: credibility-weighted multiplier on "
        "CNSF 2013 by sex, age and duration, with a prudent upper bound"
    ),
    "experience_pricing": (
        "Net annual 20-year term premium per 1,000 on CNSF 2013, on "
        "the experience basis and on the prudent basis"
    ),
    "experience_impact": (
        "Present value of future death claims and next-12-month claims "
        "of the in-force block, CNSF 2013 against the experience basis"
    ),
    "experience_lag_validation": (
        "Claims-lag completion against the true number of "
        "deaths (known only for a synthetic portfolio)"
    ),
    "experience_truth": (
        "The effects planted in the synthetic portfolio (illustrative "
        "assumptions, not estimates for any company)"
    ),
    "experience_injected_defects": (
        "How many defects of each kind were injected into the synthetic extract"
    ),
}


def _truth_table(truth: dict) -> pd.DataFrame:
    rows = []
    for key, value in truth.items():
        if isinstance(value, dict):
            rows += [(key, str(level), float(v)) for level, v in value.items()]
        elif isinstance(value, (tuple, list)):
            rows += [(key, str(i + 1), float(v)) for i, v in enumerate(value)]
        else:
            rows.append((key, "", float(value)))
    return pd.DataFrame(rows, columns=["effect", "level", "value"])


def load_or_generate_portfolio(
    paths, q_basis: pd.Series, state_smr: dict, weights: dict, force=False
):
    """The synthetic portfolio, cached as Parquet (generating it takes about 15 seconds)."""
    from mortality import portfolio as pf

    folder = paths.processed / "experience"
    files = {n: folder / f"{n}.parquet" for n in ("policies", "truth", "defects")}
    if not force and all(f.exists() for f in files.values()):
        return pf.Portfolio(*(pd.read_parquet(files[n]) for n in ("policies", "truth", "defects")))
    codes = tuple(sorted(weights))
    spec = pf.PortfolioSpec(
        q_basis=q_basis.to_numpy(), state_codes=codes,
        state_weights=tuple(weights[c] for c in codes), state_smr=state_smr,
    )  # fmt: skip
    portfolio = pf.generate_portfolio(spec)
    folder.mkdir(parents=True, exist_ok=True)
    portfolio.policies.to_parquet(files["policies"])
    portfolio.truth.to_parquet(files["truth"])
    portfolio.defects.to_parquet(files["defects"])
    return portfolio


def lag_validation(quarterly: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Completed deaths per quarter against the true deaths: how good the lag correction is."""
    t = truth[truth["true_status"] == "DEATH"].copy()
    when = pd.to_datetime(t["true_exit"]) - pd.Timedelta(days=1)
    actual = (
        pd.DataFrame({"year": when.dt.year, "quarter": when.dt.quarter})
        .groupby(["year", "quarter"])
        .size()
        .rename("true_deaths")
        .reset_index()
    )
    m = quarterly.merge(actual, on=["year", "quarter"], how="left")
    m["raw_error_pct"] = m["deaths"] / m["true_deaths"] - 1.0
    m["completed_error_pct"] = m["deaths_completed"] / m["true_deaths"] - 1.0
    return m[["year", "quarter", "deaths", "completion", "deaths_completed", "true_deaths",
              "raw_error_pct", "completed_error_pct"]]  # fmt: skip


def warehouse_inputs(con):
    """The expected basis (CNSF 2013, annual q by age), the state mortality ratios and the state
    population weights, from the warehouse; ``None`` if the warehouse lacks them."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"cnsf_rates", "state_smr", "conapo_population"} <= names:
        return None
    q = pd.read_sql(
        "SELECT age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' AND variant = 'base' "
        "ORDER BY age",
        con,
    ).set_index("age")["qx"]
    if q.empty:
        return None
    smr_df = pd.read_sql("SELECT state, smr FROM state_smr", con)
    state_smr = {
        f"{int(s):02d}": float(v) for s, v in zip(smr_df["state"], smr_df["smr"], strict=True)
    }
    pop = pd.read_sql(
        "SELECT state_code, SUM(population) AS p FROM conapo_population WHERE year = 2023 "
        "AND state_code BETWEEN 1 AND 32 GROUP BY state_code",
        con,
    )
    total = pop["p"].sum()
    weights = {
        f"{int(c):02d}": float(v / total) for c, v in zip(pop["state_code"], pop["p"], strict=True)
    }
    return q, state_smr, weights


def build_tables(con, *, force_portfolio: bool = False) -> list[tuple[str, str]]:
    """Run the study on the synthetic portfolio and store its results in the warehouse."""
    from mortality import portfolio as pf
    from mortality.config import get_paths

    inputs = warehouse_inputs(con)
    if inputs is None:
        return []
    q, state_smr, weights = inputs
    portfolio = load_or_generate_portfolio(get_paths(), q, state_smr, weights, force_portfolio)
    results = run_study(
        portfolio.policies, q, state_smr, pf.STUDY_START, pf.STUDY_END, pf.EXTRACT_DATE,
        truth=pf.TRUTH,
    )  # fmt: skip
    results["lag_validation"] = lag_validation(results["ae_quarterly"], portfolio.truth)
    results["truth"] = _truth_table(pf.TRUTH)
    results["injected_defects"] = (
        portfolio.defects["defect"].value_counts().rename_axis("defect").reset_index(name="records")
    )
    docs = []
    for key, name in TABLE_NAMES.items():
        if key in results and len(results[key]):
            results[key].to_sql(name, con, if_exists="replace", index=False)
            docs.append((name, DESCRIPTIONS[name]))
    return docs


# ── Running the study on a real extract ─────────────────────────────────────

DATE_COLUMNS = ("birth_date", "issue_date", "exit_date", "notification_date")
TEMPLATE_ROWS = [
    ["P0000001", "M", "1985-04-12", "2019-03-01", "TERM", 20, 1500000, "STANDARD", "AGENT", "09",
     "IN_FORCE", "", ""],
    ["P0000002", "F", "1978-11-30", "2016-07-15", "WHOLE_LIFE", "", 600000, "PREFERRED", "AGENT",
     "14", "LAPSE", "2021-07-15", ""],
    ["P0000003", "M", "1970-02-02", "2015-01-10", "TERM", 15, 800000, "SIMPLIFIED", "BANK", "19",
     "DEATH", "2022-05-20", "2022-06-18"],
]  # fmt: skip


def load_extract(path) -> pd.DataFrame:
    """Read a policy extract from CSV or Parquet; dates are parsed, empty dates become missing."""
    from pathlib import Path

    path = Path(path)
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str)
    for column in DATE_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in ("sum_assured", "term_years"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def write_template(path) -> None:
    """Write a CSV with the columns an extract needs and three example rows."""
    frame = pd.DataFrame(TEMPLATE_ROWS, columns=[
        "policy_id", "sex", "birth_date", "issue_date", "product", "term_years", "sum_assured",
        "uw_class", "channel", "state", "status", "exit_date", "notification_date",
    ])  # fmt: skip
    frame.to_csv(path, index=False)
