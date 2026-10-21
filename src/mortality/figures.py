"""Static figures for the README and reports, drawn from the warehouse.

Run with ``uv run mortality figures``. Each function reads the tables built by
``mortality db build`` and writes one PNG. Colors follow one small palette (blue, orange,
aqua, then muted grey) so the same series always has the same color across figures.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize

from mortality import rates, warehouse

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
BLUE, ORANGE, AQUA, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#9a998f"
SEX_COLOR = {"M": BLUE, "F": ORANGE, "T": INK_2}
SEX_NAME = {"M": "Men", "F": "Women", "T": "Both sexes"}
SOURCE = "Source: INEGI deaths, CONAPO population · Mortality Table Builder"
SYNTHETIC = (
    "Synthetic portfolio with planted effects (illustrative, not a real insurer) · expected basis "
    "CNSF 2013 · Mortality Table Builder"
)


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "xtick.bottom": False,
            "ytick.left": False,
            "text.color": INK,
            "font.size": 10.5,
            "axes.titlesize": 11,
            "legend.frameon": False,
            "lines.solid_capstyle": "round",
        }
    )


def _headline(fig, title: str, subtitle: str, source: str | None = None) -> None:
    """Left-aligned headline that states the finding, a muted line beneath, a source footer."""
    fig.text(0.015, 0.965, title, fontsize=15.5, fontweight="bold", va="top", ha="left")
    wrapped = textwrap.fill(subtitle, width=125)
    fig.text(
        0.015, 0.905, wrapped, fontsize=10.5, color=INK_2, va="top", ha="left", linespacing=1.4
    )
    fig.text(0.015, 0.012, source or SOURCE, fontsize=8, color=INK_2, va="bottom", ha="left")


def _save(fig, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _query(con, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, con)


def _clean_year(con) -> int:
    """Latest complete non-COVID year (the year the state table uses)."""
    return int(con.execute("SELECT MAX(year) FROM state_smr").fetchone()[0])


# ── 1. The mortality curve against the regulatory table ─────────────────────


def mortality_curve(con, out: Path) -> Path:
    year = _clean_year(con)
    df = _query(
        con,
        f"SELECT sex, age, mx, mx_lower, mx_upper FROM crude_rates_single "
        f"WHERE year = {year} AND age < 100",
    )
    cnsf = _query(
        con,
        "SELECT age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' AND variant = 'base' "
        "AND age BETWEEN 0 AND 99",
    )
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.80, bottom=0.10, left=0.08, right=0.93)
    for sex in ("M", "F"):
        d = df[df["sex"] == sex]
        ax.fill_between(
            d["age"], d["mx_lower"], d["mx_upper"], color=SEX_COLOR[sex], alpha=0.18, lw=0
        )
        ax.plot(d["age"], d["mx"], color=SEX_COLOR[sex], lw=2, label=SEX_NAME[sex])
    ax.plot(
        cnsf["age"],
        rates.qx_to_mx(cnsf["qx"]),
        color=INK_2,
        lw=1.8,
        ls=(0, (4, 3)),
        label="CNSF 2013 regulatory table (both sexes)",
    )
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 1.2)
    ax.set_xlim(0, 99)
    ax.set_xlabel("Age")
    ax.set_ylabel("Death rate per person-year (log scale)")
    ax.legend(loc="upper left", fontsize=10)
    m40 = float(df[(df["sex"] == "M") & (df["age"] == 40)]["mx"].iloc[0])
    c40 = float(rates.qx_to_mx(cnsf.set_index("age").loc[40, "qx"]))
    ax.annotate(
        f"Age 40, men:\n{m40 / c40:.1f}x the CNSF table",
        xy=(40, m40),
        xytext=(52, 0.0012),
        fontsize=10,
        color=INK,
        arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 0.9},
    )
    _headline(
        fig,
        "Mexican population mortality runs well above the CNSF 2013 insured-lives table",
        f"Crude death rates by single age, {year}, with 95% intervals. The gap is widest for "
        "men at working ages: the table describes insured lives, the curves describe the "
        "whole country.",
    )
    return _save(fig, out, "mortality_curve.png")


# ── 2. The pandemic shock by age ────────────────────────────────────────────


def covid_shock(con, out: Path) -> Path:
    df = _query(
        con,
        "SELECT year, sex, band, age_group, mx FROM crude_rates_grouped WHERE sex IN ('M','F')",
    )
    base = df[df["year"] == 2019].set_index(["sex", "band"])["mx"]
    df["ratio"] = df["mx"] / df.set_index(["sex", "band"]).index.map(base).to_numpy()
    df = df[df["band"].between(4, 18) & (df["year"] >= 2020)]
    labels = rates.BAND_LABELS[4:]
    shades = {2020: "#9ec5f0", 2021: BLUE, 2022: "#1c4f94", 2023: MUTED, 2024: INK_2}
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.4), sharey=True)
    fig.subplots_adjust(top=0.76, bottom=0.12, left=0.07, right=0.97, wspace=0.08)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for year, color in shades.items():
            d = df[(df["sex"] == sex) & (df["year"] == year)].sort_values("band")
            ax.plot(range(len(d)), d["ratio"], color=color, lw=2.2 if year in (2020, 2021) else 1.6,
                    label=str(year), ls="-" if year <= 2022 else (0, (4, 2)))  # fmt: skip
        ax.axhline(1, color=INK_2, lw=1)
        ax.set_xticks(range(len(labels)), labels, rotation=60, fontsize=9)
        ax.set_title(SEX_NAME[sex], loc="left", fontweight="bold", color=INK)
        ax.set_ylim(0.7, None)
    axes[0].set_ylabel("Death rate relative to 2019")
    axes[0].legend(loc="upper right", ncol=1, fontsize=9.5)
    peak = df[df["sex"] == "M"].sort_values("ratio").iloc[-1]
    _headline(
        fig,
        f"At the peak, men aged {peak['age_group']} died at {peak['ratio']:.1f}x their 2019 rate "
        f"({int(peak['year'])})",
        "Ratio of the death rate in each year to 2019, by age group (2020-2022 were COVID years). "
        "By 2023 almost every age is back at or below the 2019 baseline. 2019 is on a "
        "registration-year basis, 2020 onwards on occurrence-year (they differ by under 1%).",
    )
    return _save(fig, out, "covid_shock.png")


# ── 3. Age-standardised trend ───────────────────────────────────────────────


def standardised_trend(con, out: Path) -> Path:
    df = _query(
        con,
        "SELECT basis, year, sex, asr, asr_lower, asr_upper FROM age_standardised_rates "
        "WHERE sex IN ('M','F')",
    )
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.80, bottom=0.10, left=0.09, right=0.90)
    ax.axvspan(2019.5, 2022.5, color=GRID, alpha=0.55, lw=0)
    ax.text(2021, 1000, "COVID years", ha="center", va="top", fontsize=9.5, color=INK_2)
    ax.axvline(2019.5, color=INK_2, lw=0.8, ls=(0, (2, 3)))
    for sex in ("M", "F"):
        d = df[df["sex"] == sex].sort_values("year")
        for _, part in d.groupby("basis"):
            ax.fill_between(part["year"], part["asr_lower"] * 1e5, part["asr_upper"] * 1e5,
                            color=SEX_COLOR[sex], alpha=0.2, lw=0)  # fmt: skip
        ax.plot(d["year"], d["asr"] * 1e5, color=SEX_COLOR[sex], lw=2.2, marker="o", ms=4.5,
                mec=SURFACE, mew=1.2)  # fmt: skip
        last = d.iloc[-1]
        ax.text(2024.15, last["asr"] * 1e5, SEX_NAME[sex], color=INK, va="center", fontsize=10.5)
    ax.set_xlim(2013.6, 2024.9)
    ax.set_ylim(250, 1050)
    ax.set_xticks(range(2014, 2025))
    ax.set_ylabel("Deaths per 100,000, age-standardised (Segi)")
    ax.text(2016.3, 280, "registration-year basis", fontsize=9, color=INK_2, ha="center")
    ax.text(2022.2, 280, "occurrence-year basis", fontsize=9, color=INK_2, ha="center")
    t = df[df["sex"] == "M"].set_index("year")["asr"]
    _headline(
        fig,
        f"COVID lifted male mortality {t.loc[2020:2021].max() / t[2019] - 1:.0%} above 2019 at "
        f"its peak; by 2024 it was {1 - t[2024] / t[2019]:.0%} below",
        "Age-standardised death rate (Segi world standard) removes the effect of an ageing "
        "population. From 2020 the denominator is CONAPO's projected population, so the "
        "post-2019 level depends on that projection; the pandemic spike does not.",
    )
    return _save(fig, out, "standardised_trend.png")


# ── 4. States ───────────────────────────────────────────────────────────────


def state_forest(con, out: Path) -> Path:
    df = _query(con, "SELECT * FROM state_smr").sort_values("smr").reset_index(drop=True)
    year = int(df["year"].iloc[0])
    fig, ax = plt.subplots(figsize=(11, 8.6))
    fig.subplots_adjust(top=0.81, bottom=0.09, left=0.20, right=0.95)
    for i, row in df.iterrows():
        significant = row["smr_lower"] > 1 or row["smr_upper"] < 1
        color = (ORANGE if row["smr"] > 1 else BLUE) if significant else MUTED
        ax.plot([row["smr_lower"], row["smr_upper"]], [i, i], color=color, lw=2, alpha=0.65)
        ax.plot(row["smr"], i, "o", color=color, ms=7, mec=SURFACE, mew=1.2)
        ax.text(1.265, i, f"{row['smr']:.2f}", va="center", ha="left", fontsize=8.5, color=INK_2)
    ax.axvline(1, color=INK_2, lw=1)
    ax.set_yticks(range(len(df)), df["state_name"], fontsize=9)
    ax.set_xlim(0.76, 1.3)
    ax.set_ylim(-0.8, len(df) - 0.2)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel(
        "Standardised mortality ratio (1.00 = national mortality for the same ages and sexes)"
    )
    hi, lo = df.iloc[-1], df.iloc[0]
    _headline(
        fig,
        f"{hi['state_name']} dies {hi['smr'] - 1:.0%} faster than its age mix predicts; "
        f"{lo['state_name']} {1 - lo['smr']:.0%} slower",
        f"Standardised mortality ratio by state, {year}, with 95% intervals. Orange = "
        "significantly higher than national, blue = significantly lower, grey = not "
        "distinguishable. This compares registered deaths with CONAPO's projected "
        "population, so registration coverage and migration move it as well as true risk.",
    )
    return _save(fig, out, "state_smr.png")


# ── 5. Population versus pricing tables ─────────────────────────────────────

AE_SERIES = {
    "M": (
        ("CNSF M 2013 (non-disabled lives, base)", "CNSF 2013", BLUE),
        ("MEX 2000 male", "MEX 2000 (population)", ORANGE),
        ("EMSSA 97 pension participants (H)", "EMSSA 97 (pensions)", AQUA),
        ("Seguro Popular 2008 males", "Seguro Popular 2008", MUTED),
    ),
    "F": (
        ("CNSF M 2013 (non-disabled lives, base)", "CNSF 2013", BLUE),
        ("MEX 2000 female", "MEX 2000 (population)", ORANGE),
        ("EMSSA 97 pension participants (M)", "EMSSA 97 (pensions)", AQUA),
        ("Seguro Popular 2008 females", "Seguro Popular 2008", MUTED),
    ),
}


def population_vs_tables(con, out: Path) -> Path:
    year = _clean_year(con)
    df = _query(
        con,
        f"SELECT benchmark, sex, band, age_group, ae, ae_lower, ae_upper FROM benchmark_ae "
        f"WHERE year = {year} AND band >= 0",
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.4), sharey=True)
    fig.subplots_adjust(top=0.76, bottom=0.12, left=0.07, right=0.97, wspace=0.08)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for table, label, color in AE_SERIES[sex]:
            d = df[(df["benchmark"] == table) & (df["sex"] == sex)].sort_values("band")
            ax.plot(range(len(d)), d["ae"], color=color, lw=2.2, label=label)
        ax.axhline(1, color=INK_2, lw=1)
        ax.set_yscale("log")
        ax.set_yticks([0.5, 1, 2, 4, 8], ["0.5x", "1x", "2x", "4x", "8x"])
        ax.minorticks_off()
        labels = rates.BAND_LABELS[6:18]
        ax.set_xticks(range(len(labels)), labels, rotation=60, fontsize=9)
        ax.set_title(SEX_NAME[sex], loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Actual deaths / deaths the table predicts")
    axes[0].legend(loc="upper right", fontsize=9)
    m = df[(df["benchmark"] == AE_SERIES["M"][0][0]) & (df["sex"] == "M")]
    peak = m.sort_values("ae").iloc[-1]
    _headline(
        fig,
        f"Mexican men die up to {peak['ae']:.1f}x faster than the CNSF 2013 table assumes",
        f"Actual {year} deaths of the Mexican population divided by the deaths each table predicts "
        "for the same people; 1x means the table fits. An insured book is healthier than the "
        "country, so above 1x is expected: the size of the gap is what gets priced.",
    )
    return _save(fig, out, "population_vs_tables.png")


# ── 6. Countries ────────────────────────────────────────────────────────────

COUNTRY_NAMES = {
    "CAN": "Canada",
    "CHL": "Chile",
    "ESP": "Spain",
    "FRATNP": "France",
    "GBR_NP": "UK",
    "ITA": "Italy",
    "JPN": "Japan",
    "SWE": "Sweden",
    "USA": "USA",
}


def country_heatmap(con, out: Path) -> Path:
    year = 2019
    df = _query(
        con,
        f"SELECT country, band, ratio FROM benchmark_countries "
        f"WHERE year = {year} AND sex = 'M' AND band BETWEEN 2 AND 17",
    )
    wide = df.pivot_table(index="country", columns="band", values="ratio")
    wide = wide.loc[wide.mean(axis=1).sort_values().index]
    fig, ax = plt.subplots(figsize=(11, 6.2))
    fig.subplots_adjust(top=0.80, bottom=0.12, left=0.10, right=0.93)
    values = wide.to_numpy()
    # one hue, light to dark: every ratio here is above 1, so a diverging scale would waste half
    # its range (vmin follows the data in case a ratio ever falls below 1)
    ramp = LinearSegmentedColormap.from_list("ratio", ["#fdf1ea", ORANGE, "#6e1f0b"])
    im = ax.imshow(values, cmap=ramp, aspect="auto",
                   norm=Normalize(vmin=min(1.0, values.min()), vmax=values.max()))  # fmt: skip
    ax.set_xticks(
        range(wide.shape[1]), [rates.BAND_LABELS[b] for b in wide.columns], fontsize=9, rotation=60
    )
    ax.set_yticks(range(wide.shape[0]), [COUNTRY_NAMES.get(c, c) for c in wide.index])
    ax.grid(False)
    for i in range(wide.shape[0]):
        for j in range(wide.shape[1]):
            v = values[i, j]
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8.5,
                    color="white" if v > 3.4 else INK)  # fmt: skip
    cbar = fig.colorbar(im, ax=ax, pad=0.015, fraction=0.03)
    cbar.set_label("Mexico / country")
    cbar.outline.set_visible(False)
    _headline(
        fig,
        "Young Mexican men die at several times the rate of men in Europe and Japan",
        f"Male death rate in Mexico divided by each country's, {year} (pre-COVID); darker = Mexico "
        "higher. Rows run from the country most like Mexico to the least. Country data: Human "
        "Mortality Database.",
    )
    return _save(fig, out, "country_ratios.png")


# ── Graduation ──────────────────────────────────────────────────────────────

SEX_PANELS = (("M", "Men"), ("F", "Women"))


def _two_panels(figsize=(11, 6.4), top=0.76, sharey=True):
    fig, axes = plt.subplots(1, 2, figsize=figsize, sharey=sharey)
    fig.subplots_adjust(top=top, bottom=0.12, left=0.07, right=0.97, wspace=0.08)
    return fig, axes


def graduation_fit(con, out: Path) -> Path:
    year = _clean_year(con)
    crude = _query(
        con,
        f"SELECT sex, age, mx FROM crude_rates_single WHERE year = {year} AND age BETWEEN 1 AND 89",
    )
    fits = _query(
        con,
        f"SELECT sex, method, age, mx, mx_lower, mx_upper FROM graduated_rates WHERE year = {year}",
    )
    tests = _query(
        con,
        f"SELECT sex, method, deviance FROM graduation_fit_tests WHERE year = {year}",
    ).set_index(["sex", "method"])["deviance"]
    fig, axes = _two_panels()
    styles = {
        "pspline": ("Poisson P-spline", BLUE, 2.4, "-"),
        "whittaker_henderson": ("Whittaker-Henderson", AQUA, 1.5, "-"),
        "heligman_pollard": ("Heligman-Pollard", ORANGE, 1.8, (0, (5, 3))),
        "gompertz_makeham": ("Gompertz-Makeham (35+)", INK_2, 1.5, (0, (1.5, 2.5))),
    }
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        c = crude[crude["sex"] == sex]
        ax.scatter(c["age"], c["mx"], s=14, facecolors="none", edgecolors=MUTED, lw=0.9,
                   label="Crude rates", zorder=2)  # fmt: skip
        for method, (label, color, width, ls) in styles.items():
            f = fits[(fits["sex"] == sex) & (fits["method"] == method)]
            if method == "pspline":
                ax.fill_between(
                    f["age"], f["mx_lower"], f["mx_upper"], color=color, alpha=0.2, lw=0
                )
            ax.plot(f["age"], f["mx"], color=color, lw=width, ls=ls, label=label, zorder=3)
        ax.set_yscale("log")
        ax.set_ylim(1.5e-4, 0.6)
        ax.set_xlim(0, 90)
        ax.set_xlabel("Age")
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Death rate per person-year (log scale)")
    axes[0].legend(loc="upper left", fontsize=9)
    ratio = tests[("M", "heligman_pollard")] / tests[("M", "pspline")]
    _headline(
        fig,
        f"Splines follow Mexican mortality; Heligman-Pollard fits {ratio:.0f}x worse",
        f"Crude {year} rates by single age against four graduations, with the P-spline's 95% band. "
        "Men's young-adult plateau (ages 15 to 35) is what a parametric law cannot bend to.",
    )
    return _save(fig, out, "graduation_fit.png")


def graduation_residuals(con, out: Path) -> Path:
    year = _clean_year(con)
    df = _query(
        con,
        f"SELECT c.sex, c.age, c.deaths, c.exposure, g.method, g.mx AS fit "
        f"FROM crude_rates_single c JOIN graduated_rates g "
        f"ON g.year = c.year AND g.sex = c.sex AND g.age = c.age "
        f"WHERE c.year = {year} AND g.method IN ('pspline', 'whittaker_henderson')",
    )
    expected = df["exposure"] * df["fit"]
    df["z"] = (df["deaths"] - expected) / expected**0.5
    tests = _query(
        con,
        f"SELECT sex, method, share_beyond_2, serial_corr FROM graduation_fit_tests "
        f"WHERE year = {year}",
    ).set_index(["sex", "method"])
    fig, axes = _two_panels(sharey=True)
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        ax.axhspan(-2, 2, color=GRID, alpha=0.6, lw=0)
        for method, label, color in (
            ("whittaker_henderson", "Whittaker-Henderson", AQUA),
            ("pspline", "Poisson P-spline", BLUE),
        ):
            d = df[(df["sex"] == sex) & (df["method"] == method)]
            ax.plot(d["age"], d["z"], color=color, lw=1.4, marker="o", ms=3.2, label=label)
        ax.axhline(0, color=INK_2, lw=0.8)
        ax.set_xlim(0, 90)
        ax.set_xlabel("Age")
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Standardised residual (actual - fitted) / sqrt(fitted)")
    axes[0].legend(loc="upper right", fontsize=9)
    corr = tests.loc[("M", "pspline"), "serial_corr"]
    heaping = _query(
        con,
        f"SELECT excess_at_0_5 FROM graduation_digit_preference WHERE year = {year} AND sex = 'M'",
    )["excess_at_0_5"].iloc[0]
    _headline(
        fig,
        f"Biggest misses sit on ages ending in 0 and 5: men's deaths run {heaping:.1%} high there",
        f"Grey band = plus or minus 2. The {year} spikes at 35, 40, 50 and 55 are digit "
        f"preference in the male death records, which a smooth curve rightly ignores "
        f"(serial correlation of residuals {corr:.2f}).",
    )
    return _save(fig, out, "graduation_residuals.png")


def old_age_closure(con, out: Path) -> Path:
    year = _clean_year(con)
    crude = _query(
        con,
        f"SELECT sex, age, mx FROM crude_rates_single "
        f"WHERE year = {year} AND age BETWEEN 60 AND 99",
    )
    final = _query(
        con,
        f"SELECT sex, age, mx, source, sex_floor FROM graduated_qx "
        f"WHERE year = {year} AND age >= 60",
    )
    hmd = _query(
        con,
        "SELECT country, sex, age, mx FROM hmd_life_tables WHERE year = 2019 "
        "AND country IN ('USA', 'JPN') AND age BETWEEN 60 AND 110",
    )
    ratio = crude[crude["age"] == 99]
    fig, axes = _two_panels()
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        for country, label, ls in (("USA", "USA 2019", (0, (4, 2))), ("JPN", "Japan 2019", ":")):
            h = hmd[(hmd["country"] == country) & (hmd["sex"] == sex)]
            ax.plot(h["age"], h["mx"], color=MUTED, lw=1.5, ls=ls, label=label, zorder=1)
        c = crude[crude["sex"] == sex]
        used, held = c[c["age"] <= 89], c[c["age"] > 89]
        ax.scatter(
            used["age"], used["mx"], s=16, color=SEX_COLOR[sex], label="Crude, used", zorder=3
        )
        ax.scatter(held["age"], held["mx"], s=16, facecolors="none", edgecolors=SEX_COLOR[sex],
                   lw=1.1, label="Crude, held out", zorder=3)  # fmt: skip
        f = final[final["sex"] == sex].sort_values("age")
        ax.plot(f["age"], f["mx"], color=SEX_COLOR[sex], lw=2.4, label="Graduated table", zorder=4)
        floor = f[f["sex_floor"] == 1]
        if len(floor):
            ax.plot(floor["age"], floor["mx"], color=INK, lw=2.4, ls=(0, (1, 1.5)),
                    label="Raised to the female rate", zorder=5)  # fmt: skip
        ax.axvline(90, color=INK_2, lw=0.8, ls=(0, (2, 3)))
        ax.text(90.6, 0.006, "closure\nstarts", fontsize=8.5, color=INK_2, va="bottom")
        ax.set_yscale("log")
        ax.set_ylim(0.005, 1.3)
        ax.set_xlim(60, 110)
        ax.set_xlabel("Age")
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Death rate per person-year (log scale)")
    axes[0].legend(loc="upper left", fontsize=8.5)
    f_over_m = float(
        ratio[ratio["sex"] == "F"]["mx"].iloc[0] / ratio[ratio["sex"] == "M"]["mx"].iloc[0]
    )
    _headline(
        fig,
        f"At 99 the crude data say women die {f_over_m:.1f}x as fast as men; the closure does not "
        "believe it",
        "Above about 88 the crude rates for men flatten while women's keep rising, the signature "
        "of overstated age. The smooth fit stops at 89; a Kannisto logistic fitted to ages 75-89 "
        "carries the table to 110, and men are never allowed below women.",
    )
    return _save(fig, out, "old_age_closure.png")


def lambda_selection(con, out: Path) -> Path:
    year = _clean_year(con)
    path = _query(
        con,
        f"SELECT sex, method, log10_lambda, edf, qaic FROM graduation_lambda_path "
        f"WHERE year = {year} AND method = 'pspline'",
    )
    chosen = _query(
        con,
        f'SELECT sex, "lambda" AS lam, edf FROM graduation_selection '
        f"WHERE year = {year} AND method = 'pspline'",
    ).set_index("sex")
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.6))
    fig.subplots_adjust(top=0.76, bottom=0.13, left=0.07, right=0.97, wspace=0.18)
    for sex, title in SEX_PANELS:
        p = path[path["sex"] == sex]
        color = SEX_COLOR[sex]
        axes[0].plot(
            p["log10_lambda"], p["qaic"] - p["qaic"].min(), color=color, lw=2.2, label=title
        )
        axes[1].plot(p["log10_lambda"], p["edf"], color=color, lw=2.2, label=title)
        pick = math.log10(float(chosen.loc[sex, "lam"]))
        for ax, y in ((axes[0], 0.0), (axes[1], float(chosen.loc[sex, "edf"]))):
            ax.plot([pick], [y], "o", color=color, ms=9, mec=SURFACE, mew=1.5, zorder=5)
    axes[0].set_ylim(-5, 120)
    axes[0].set_xlabel("log10 of the smoothing parameter (more smoothing to the right)")
    axes[0].set_ylabel("QAIC above its minimum")
    axes[0].set_title("Selection criterion", loc="left", fontweight="bold")
    axes[1].set_xlabel("log10 of the smoothing parameter (more smoothing to the right)")
    axes[1].set_ylabel("Effective parameters")
    axes[1].set_title("Flexibility of the curve", loc="left", fontweight="bold")
    axes[1].set_yscale("log")
    axes[1].set_yticks([2, 5, 10, 20, 40], ["2", "5", "10", "20", "40"])
    axes[1].minorticks_off()
    axes[0].legend(loc="upper left", fontsize=9.5)
    _headline(
        fig,
        f"Smoothing is chosen by data, not by eye: about {chosen['edf'].mean():.0f} effective "
        "parameters for 89 ages",
        "Quasi-AIC over a grid of 61 smoothing parameters. Dots mark the choice. The crude rates' "
        "own scatter (estimated from their high-order differences, not from any fit) sets how "
        "much deviance one extra parameter must buy.",
    )
    return _save(fig, out, "lambda_selection.png")


def covid_single_age(con, out: Path) -> Path:
    df = _query(
        con,
        "SELECT year, sex, age, mx FROM graduated_qx WHERE age BETWEEN 15 AND 89 "
        "AND year IN (2020, 2021, 2022, 2023)",
    )
    base = df[df["year"] == 2023].set_index(["sex", "age"])["mx"]
    df["ratio"] = df["mx"] / df.set_index(["sex", "age"]).index.map(base).to_numpy()
    fig, axes = _two_panels()
    shades = {2020: "#9ec5f0", 2021: BLUE, 2022: "#1c4f94"}
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        for year, color in shades.items():
            d = df[(df["sex"] == sex) & (df["year"] == year)]
            ax.plot(d["age"], d["ratio"], color=color, lw=2.3, label=str(year))
        ax.axhline(1, color=INK_2, lw=1)
        ax.set_xlim(15, 89)
        ax.set_xlabel("Age")
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Graduated death rate relative to 2023")
    axes[0].legend(loc="upper right", fontsize=9.5)
    peak = df[(df["sex"] == "M") & (df["year"] <= 2021)].sort_values("ratio").iloc[-1]
    _headline(
        fig,
        f"Men aged {int(peak['age'])} died at {peak['ratio']:.1f}x their 2023 rate in "
        f"{int(peak['year'])}",
        "Graduated death rates in each COVID year divided by 2023, the latest clean year. "
        "Smoothing makes the age profile readable at single-year resolution without hiding "
        "its shape.",
    )
    return _save(fig, out, "covid_single_age.png")


# ── Life tables ─────────────────────────────────────────────────────────────


def _cnsf_tables(con) -> dict[str, pd.DataFrame]:
    """CNSF 2013 life tables for the base rates and the two percentile variants."""
    from mortality import lifetable

    df = _query(
        con,
        "SELECT variant, age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' ORDER BY age",
    )
    return {
        variant: lifetable._table_from_q(part["age"], part["qx"])
        for variant, part in df.groupby("variant")
    }


def life_expectancy_trend(con, out: Path) -> Path:
    ours = _query(con, "SELECT year, sex, e0 FROM life_summary WHERE sex IN ('M', 'F')")
    conapo = _query(
        con,
        "SELECT year, sex, e0 FROM conapo_life_expectancy "
        "WHERE state_code = 0 AND sex IN ('M', 'F') AND year BETWEEN 2012 AND 2024",
    )
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.08, right=0.90)
    ax.axvspan(2019.5, 2022.5, color=GRID, alpha=0.55, lw=0)
    ax.text(2021, 80.6, "COVID years", ha="center", fontsize=9.5, color=INK_2)
    for sex in ("M", "F"):
        c = conapo[conapo["sex"] == sex].sort_values("year")
        ax.plot(c["year"], c["e0"], color=SEX_COLOR[sex], lw=1.7, ls=(0, (4, 2)), alpha=0.85)
        o = ours[ours["sex"] == sex].sort_values("year")
        ax.plot(o["year"], o["e0"], color=SEX_COLOR[sex], lw=2.8, marker="o", ms=6.5,
                mec=SURFACE, mew=1.3)  # fmt: skip
        ax.text(2024.15, o["e0"].iloc[-1], f"{SEX_NAME[sex]} {o['e0'].iloc[-1]:.1f}",
                va="center", fontsize=10.5)  # fmt: skip
    from matplotlib.lines import Line2D

    ax.legend(
        handles=[
            Line2D(
                [], [], color=INK_2, lw=2.8, marker="o", ms=6, label="This project (INEGI deaths)"
            ),
            Line2D([], [], color=INK_2, lw=1.7, ls=(0, (4, 2)), label="CONAPO"),
        ],
        loc="lower left",
        fontsize=9.5,
    )
    ax.set_xlim(2012, 2025.4)
    ax.set_ylim(62, 81.5)
    ax.set_xticks(range(2012, 2025, 2))
    ax.set_ylabel("Life expectancy at birth (years)")
    m_ours = ours[ours["sex"] == "M"].set_index("year")["e0"]
    m_conapo = conapo[conapo["sex"] == "M"].set_index("year")["e0"]
    lost_ours = m_ours.loc[2023] - m_ours.loc[2020:2021].min()
    lost_conapo = m_conapo.loc[2019] - m_conapo.loc[2020:2021].min()
    _headline(
        fig,
        f"COVID cost Mexican men {lost_ours:.1f} to {lost_conapo:.1f} years of life expectancy; "
        "most was back by 2022",
        "Life expectancy at birth from the graduated life tables, against CONAPO's. They agree "
        "within 0.7 years in 2022-2024. In 2020-21 CONAPO models 9% more deaths than INEGI "
        "registered, which points the same way as the gap between the two lines (the range in "
        "the headline is the same event seen through the two death counts).",
    )
    return _save(fig, out, "life_expectancy_trend.png")


def survival_curves(con, out: Path) -> Path:
    year = _clean_year(con)
    df = _query(
        con,
        f"SELECT sex, age, lx FROM life_tables WHERE year = {year} AND sex IN ('M', 'F')",
    )
    cnsf = _cnsf_tables(con)
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.08, right=0.95)
    heavy, light, base = cnsf["p99.5"], cnsf["p0.05"], cnsf["base"]
    ax.fill_between(base["age"], heavy["lx"] / 1e5, light["lx"] / 1e5, color=MUTED, alpha=0.22,
                    lw=0, label="CNSF 2013, 0.05th to 99.5th percentile variants")  # fmt: skip
    ax.plot(base["age"], base["lx"] / 1e5, color=INK_2, lw=1.8, ls=(0, (4, 3)),
            label="CNSF 2013 base")  # fmt: skip
    survive = {}
    for sex in ("M", "F"):
        d = df[df["sex"] == sex]
        ax.plot(d["age"], d["lx"] / 1e5, color=SEX_COLOR[sex], lw=2.8, label=SEX_NAME[sex])
        survive[sex] = float(d.loc[d["age"] == 65, "lx"].iloc[0] / 1e5)
    ax.axvline(65, color=INK_2, lw=0.8, ls=(0, (2, 3)))
    ax.text(65.8, 0.97, "age 65", fontsize=9, color=INK_2, va="top")
    cnsf65 = float(base.loc[base["age"] == 65, "lx"].iloc[0] / 1e5)
    heavy65 = float(heavy.loc[heavy["age"] == 65, "lx"].iloc[0] / 1e5)
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_xlabel("Age")
    ax.set_ylabel("Share of a birth cohort still alive")
    ax.legend(loc="lower left", fontsize=9.5)
    _headline(
        fig,
        f"{survive['M']:.0%} of Mexican men reach 65; the CNSF 2013 table expects {cnsf65:.0%}",
        f"Survival curves from the {year} life tables (women: {survive['F']:.0%} reach 65). The "
        f"regulatory table describes insured lives: at 65 even its higher-mortality 99.5th "
        f"percentile variant ({heavy65:.0%}) is above both population curves.",
    )
    return _save(fig, out, "survival_curves.png")


def lifespan_disparity(con, out: Path) -> Path:
    df = _query(
        con,
        'SELECT source, "table" AS name, sex, year, e0, lifespan_disparity AS disparity '
        "FROM life_table_comparison WHERE sex IN ('M', 'F') AND e0 IS NOT NULL "
        "AND source IN ('HMD', 'INEGI/CONAPO')",
    )
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.78, bottom=0.11, left=0.08, right=0.95)
    for sex in ("M", "F"):
        d = df[df["sex"] == sex]
        h = d[d["source"] == "HMD"]
        ax.scatter(h["e0"], h["disparity"], s=70, color=SEX_COLOR[sex], alpha=0.55,
                   edgecolors="none", zorder=2)  # fmt: skip
        for _, row in h.iterrows():
            code = COUNTRY_NAMES.get(row["name"].split(" ")[0], row["name"].split(" ")[0])
            ax.annotate(code, (row["e0"], row["disparity"]), xytext=(6, -3),
                        textcoords="offset points", fontsize=8.5, color=INK_2)  # fmt: skip
        mex = d[d["source"] == "INEGI/CONAPO"].iloc[0]
        ax.scatter([mex["e0"]], [mex["disparity"]], s=190, color=SEX_COLOR[sex], edgecolors=SURFACE,
                   linewidths=1.8, zorder=4)  # fmt: skip
        offset, align = ((16, 4), "left") if sex == "M" else ((-14, 10), "right")
        name = f"Mexico {mex['year']:.0f}, {SEX_NAME[sex].lower()}"
        ax.annotate(name, (mex["e0"], mex["disparity"]), xytext=offset,
                    textcoords="offset points", ha=align, fontsize=10,
                    fontweight="bold", color=INK)  # fmt: skip
    ax.invert_yaxis()
    ax.set_xlabel("Life expectancy at birth (years)")
    ax.set_ylabel("Lifespan disparity, years (axis flipped: more equal at the top)")
    ax.grid(axis="x", visible=True)
    mx = df[(df["source"] == "INEGI/CONAPO") & (df["sex"] == "M")].iloc[0]
    jp = df[(df["name"] == "JPN 2019") & (df["sex"] == "M")].iloc[0]
    _headline(
        fig,
        f"Mexican men live {jp['e0'] - mx['e0']:.0f} years less than Japanese men, "
        "with less equal lifespans",
        f"Each dot is a life table. The top right is best: long lives, evenly spread ages at "
        f"death. Mexican men's years of life lost at death average {mx['disparity']:.1f}, against "
        f"{jp['disparity']:.1f} in Japan. Mexico is 2023; the HMD countries are 2019, pre-COVID.",
    )
    return _save(fig, out, "lifespan_disparity.png")


def annuity_values(con, out: Path) -> Path:
    df = _query(
        con,
        'SELECT source, "table" AS name, sex, e65, a_due_65 FROM life_table_comparison '
        "WHERE source IN ('CNSF', 'SOA', 'INEGI/CONAPO')",
    )
    short = {
        "CNSF M 2013 (non-disabled lives, base)": "CNSF 2013 base",
        "CNSF M 2013 (p0.05 percentile)": "CNSF 2013, 0.05th pct (pensions)",
        "CNSF M 2013 (p99.5 percentile)": "CNSF 2013, 99.5th pct",
        "CNSF 2000-I individual insured lives (1991-1998)": "CNSF 2000-I insured lives",
        "CNSF 2000-G group life (1991-1998)": "CNSF 2000-G group life",
        "Experiencia Mexicana individual (1982-1989)": "Experiencia Mexicana 1982-89",
        "EMSSA 97 pension participants (H)": "EMSSA 97 pensions",
        "EMSSA 97 pension participants (M)": "EMSSA 97 pensions",
        "MEX 2000 male": "MEX 2000 (population)",
        "MEX 2000 female": "MEX 2000 (population)",
        "Seguro Popular 2008 males": "Seguro Popular 2008",
        "Seguro Popular 2008 females": "Seguro Popular 2008",
    }
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.4), sharex=True)
    fig.subplots_adjust(top=0.76, bottom=0.10, left=0.25, right=0.97, wspace=0.62)
    gaps = {}
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        d = df[df["sex"].isin([sex, "T"])].copy()
        d = d[(d["source"] != "INEGI/CONAPO") | (d["sex"] == sex)]  # one Mexico dot per panel
        d["label"] = [
            f"Mexican population {_clean_year(con)}" if s == "INEGI/CONAPO" else short.get(n, n)
            for s, n in zip(d["source"], d["name"], strict=True)
        ]
        d = d.sort_values("a_due_65").reset_index(drop=True)
        mex = d[d["source"] == "INEGI/CONAPO"].iloc[0]
        cnsf = d[d["name"].str.contains("2013 \\(non-disabled")].iloc[0]
        gaps[sex] = cnsf["a_due_65"] / mex["a_due_65"] - 1
        for i, row in d.iterrows():
            color = SEX_COLOR[sex] if row["source"] == "INEGI/CONAPO" else MUTED
            ax.plot(
                [d["a_due_65"].min() - 0.3, row["a_due_65"]], [i, i], color=GRID, lw=1, zorder=1
            )
            ax.plot(row["a_due_65"], i, "o", color=color, ms=9, mec=SURFACE, mew=1.3, zorder=3)
            ax.text(row["a_due_65"] + 0.12, i, f"{row['a_due_65']:.2f}", va="center", fontsize=8.5,
                    color=INK_2)  # fmt: skip
        ax.set_yticks(range(len(d)), d["label"], fontsize=8.8)
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.set_xlabel("Value of 1 a year for life from 65 (4% interest)")
        ax.set_xlim(10.3, 17.6)
    _headline(
        fig,
        f"CNSF 2013 overstates pension cost by {gaps['M']:.0%} (men) and {gaps['F']:.0%} (women)",
        "Annuity-due at 65 on each table, same code, 4% interest. Lighter mortality makes lifetime "
        "payments dearer. Coloured dot = Mexican population; unisex tables appear in both "
        "panels. The 0.05th pct is CNSF's low-mortality variant for private pensions.",
    )
    return _save(fig, out, "annuity_values.png")


def term_premiums(con, out: Path) -> Path:
    from mortality import lifetable

    year = _clean_year(con)
    mex = _query(
        con,
        f"SELECT sex, age, P_term_20 FROM actuarial_values WHERE year = {year} "
        "AND interest = 0.04 AND sex IN ('M', 'F') AND age BETWEEN 25 AND 60",
    )
    cnsf = {
        k: lifetable.Commutation.from_table(t, lifetable.INTEREST).values()
        for k, t in _cnsf_tables(con).items()
    }
    fig, axes = _two_panels()
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        d = mex[mex["sex"] == sex]
        ax.plot(d["age"], d["P_term_20"] * 1000, color=SEX_COLOR[sex], lw=2.8,
                label="Mexican population, 2023")  # fmt: skip
        for variant, label, ls in (
            ("base", "CNSF 2013 base", (0, (4, 3))),
            ("p99.5", "CNSF 2013, 99.5th pct variant", (0, (1, 2))),
        ):
            v = cnsf[variant]
            v = v[v["age"].between(25, 60)]
            ax.plot(v["age"], v["P_term_20"] * 1000, color=INK_2, lw=1.7, ls=ls, label=label)
        ax.set_yscale("log")
        ax.set_yticks([1, 2, 5, 10, 20, 50], ["1", "2", "5", "10", "20", "50"])
        ax.minorticks_off()
        ax.set_xlim(25, 60)
        ax.set_xlabel("Age at issue")
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
    axes[0].set_ylabel("Net annual premium per 1,000 insured (log scale)")
    axes[0].legend(loc="upper left", fontsize=9)
    m40 = float(mex[(mex["sex"] == "M") & (mex["age"] == 40)]["P_term_20"].iloc[0]) * 1000
    c40 = float(cnsf["base"].loc[cnsf["base"]["age"] == 40, "P_term_20"].iloc[0]) * 1000
    _headline(
        fig,
        f"A 20-year term at 40: {m40:.1f} per 1,000 for men on population mortality, "
        f"{c40:.1f} on CNSF 2013",
        "Net premium (no expenses or profit), equivalence principle, 4% interest. Women's "
        "population premium passes CNSF's higher-mortality variant from about age 30; men's is "
        "above it at every age.",
    )
    return _save(fig, out, "term_premiums.png")


# ── Projection ──────────────────────────────────────────────────────────────


def projection_backtest_chart(con, out: Path) -> Path:
    import numpy as np

    from mortality import projection as proj

    history = proj.load_history(con)
    fig, axes = _two_panels()
    fig.subplots_adjust(wspace=0.14)
    errors = {}
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        d, e, years = proj.history_arrays(history, sex)
        actual = proj.period_measures((d / e).T, 0, sex)["e0"]
        keep = (years >= 1970) & (years <= 1999)
        fit = proj.fit_lee_carter(d[:, keep], e[:, keep], years[keep])
        jump_off = d[:, keep][:, -1] / e[:, keep][:, -1]
        paths = proj.forecast_lee_carter(fit, 20, 1000, 0, jump_off=jump_off)
        band = proj.quantiles(proj.period_measures(paths, 0, sex)["e0"])
        future = np.arange(2000, 2020)
        color = SEX_COLOR[sex]
        ax.fill_between(
            future, band[0], band[4], color=color, alpha=0.2, lw=0, label="Forecast, 90% band"
        )
        ax.plot(future, band[2], color=color, lw=2.2, ls=(0, (4, 2)), label="Forecast made in 1999")
        shown = years >= 1970
        ax.plot(years[shown], actual[shown], color=INK, lw=2.6, label="What happened (CONAPO)")
        ax.axvline(1999.5, color=INK_2, lw=0.8, ls=(0, (2, 3)))
        errors[sex] = float(band[2][-1] - actual[years == 2019][0])
        ax.text(2019, band[2][-1] + 0.5, f"+{errors[sex]:.1f} yrs", ha="right", fontsize=10,
                color=INK, fontweight="bold")  # fmt: skip
        ax.set_xlim(1970, 2020)
        ax.set_ylim(55, 84)
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        ax.set_xlabel("Year")
    axes[0].set_ylabel("Life expectancy at birth (years)")
    axes[0].legend(loc="lower right", fontsize=9)
    _headline(
        fig,
        f"A forecast made in 1999 overshot men's 2019 life expectancy by {errors['M']:.1f} years",
        "Lee-Carter fitted to 1970-1999 and restarted at the 1999 rates, against CONAPO's series. "
        "Men's improvement stalled after 1999; the model's 90% band, which covers only the random "
        f"walk, missed it (women: +{errors['F']:.1f} years).",
    )
    return _save(fig, out, "projection_backtest.png")


def period_index(con, out: Path) -> Path:
    import numpy as np

    df = _query(
        con,
        'SELECT sex, "index" AS year, value FROM projection_parameters '
        "WHERE model = 'lee_carter' AND parameter = 'kt'",
    )
    fig, axes = _two_panels(sharey=False)
    slopes = {}
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        d = df[df["sex"] == sex].sort_values("year")
        y, k = d["year"].to_numpy(), d["value"].to_numpy()
        early, late = (y <= 1999), (y >= 2000)
        s_early = np.polyfit(y[early], k[early], 1)
        s_late = np.polyfit(y[late], k[late], 1)
        slopes[sex] = (s_early[0], s_late[0])
        ax.plot(y, k, color=SEX_COLOR[sex], lw=2.6)
        ax.plot(y[early], np.polyval(s_early, y[early]), color=INK_2, lw=1.4, ls=(0, (4, 3)))
        ax.plot(y[late], np.polyval(s_late, y[late]), color=INK, lw=1.8, ls=(0, (4, 3)))
        ax.plot(
            y[late], np.polyval(s_early, y[late]), color=INK_2, lw=1.1, ls=(0, (1, 2)), alpha=0.8
        )
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        ax.set_xlabel("Year")
        ax.text(1972, k.min() + 0.04 * (k.max() - k.min()), f"1970-99: {s_early[0]:.2f} a year",
                fontsize=9.5, color=INK_2)  # fmt: skip
        ax.text(1972, k.min() + 0.14 * (k.max() - k.min()), f"2000-19: {s_late[0]:.2f} a year",
                fontsize=9.5, color=INK)  # fmt: skip
    axes[0].set_ylabel("Lee-Carter period index k(t): lower = lower mortality")
    m_early, m_late = slopes["M"]
    _headline(
        fig,
        f"Men's mortality improvement slowed to {m_late / m_early:.0%} of its earlier pace after "
        "1999",
        "The Lee-Carter index k(t) (fitted to CONAPO 1970-2019) with straight-line trends for each "
        "period. The dotted line is the 1970-99 trend carried on: women kept to it more closely "
        f"(2000-19 pace {slopes['F'][1] / slopes['F'][0]:.0%} of the earlier one).",
    )
    return _save(fig, out, "period_index.png")


def _fan_panels(con, measure: str, ylabel: str, relative: bool):
    import numpy as np

    sc = _query(
        con,
        f"SELECT scenario, sex, year, p05, p25, p50, p75, p95 FROM projection_scenarios "
        f"WHERE measure = '{measure}'",
    )
    cal = _query(
        con,
        f"SELECT sex, c FROM projection_calibration WHERE measure = '{measure}'",
    ).set_index("sex")["c"]
    fig, axes = _two_panels(sharey=False)
    fig.subplots_adjust(wspace=0.16)
    summary = {}
    last_year = int(sc.loc[sc["scenario"] == "observed", "year"].max())
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        s = sc[sc["sex"] == sex]
        color = SEX_COLOR[sex]
        obs = s[(s["scenario"] == "observed") & (s["year"] >= 1990)]
        ax.plot(obs["year"], obs["p50"], color=INK, lw=2.4, label="Observed")
        ax.axvline(2019.5, color=INK_2, lw=0.8, ls=(0, (2, 3)))
        fan = s[s["scenario"] == "rebased_long_run"].sort_values("year")
        h = (fan["year"] - last_year).to_numpy()
        half = 1.645 * cal[sex] * np.sqrt(h)
        if relative:
            lo, hi = fan["p50"] * (1 - half), fan["p50"] * (1 + half)
        else:
            lo, hi = fan["p50"] - half, fan["p50"] + half
        ax.fill_between(fan["year"], lo, hi, color=color, alpha=0.10, lw=0,
                        label="90%, calibrated on the backtest")  # fmt: skip
        ax.fill_between(fan["year"], fan["p05"], fan["p95"], color=color, alpha=0.28, lw=0,
                        label="90%, the model's own")  # fmt: skip
        ax.plot(fan["year"], fan["p50"], color=color, lw=2.4, label="Long-run trend (1970-2019)")
        rec = s[s["scenario"] == "rebased_recent"].sort_values("year")
        ax.plot(rec["year"], rec["p50"], color=color, lw=1.9, ls=(0, (4, 2)),
                label="Recent trend (last 20 years)")  # fmt: skip
        off = s[s["scenario"] == "conapo_official"].sort_values("year")
        ax.plot(
            off["year"], off["p50"], color=INK_2, lw=1.5, ls=(0, (1, 2)), label="CONAPO official"
        )
        if measure == "a65":
            cbd = s[s["scenario"] == "cbd_rebased"].sort_values("year")
            ax.plot(cbd["year"], cbd["p50"], color=AQUA, lw=1.8, label="CBD, restarted at 2024")
        ax.set_xlim(1990, 2070)
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        ax.set_xlabel("Year")
        at = lambda frame, year: float(frame.loc[frame["year"] == year, "p50"].iloc[0])  # noqa: E731
        summary[sex] = (at(fan, 2050), at(rec, 2050), at(off, 2050), float(obs["p50"].iloc[-1]))
    axes[0].set_ylabel(ylabel)
    axes[0].legend(loc="upper left", fontsize=8.5)
    return fig, summary


def projection_fan_e0(con, out: Path) -> Path:
    fig, s = _fan_panels(con, "e0", "Life expectancy at birth (years)", False)
    long_run, recent, official, _ = s["M"]
    _headline(
        fig,
        f"Men's life expectancy reaches {long_run:.0f} by 2050 on the long trend, "
        f"{recent:.0f} on the recent one",
        f"Medians of the rebased projections (women: {s['F'][0]:.0f} or {s['F'][1]:.0f}); CONAPO's "
        f"official projection says {official:.0f} for men. The darker band is the model's own "
        "uncertainty, the lighter one the width the backtest says is realistic. The jump at 2020 "
        "is the change from CONAPO's reconstruction to INEGI-based rates.",
    )
    return _save(fig, out, "projection_fan_e0.png")


def longevity_risk(con, out: Path) -> Path:
    fig, s = _fan_panels(con, "a65", "Value of 1 a year for life from 65 (4%)", True)
    now = {sex: s[sex][3] for sex in s}
    long_m, recent_m = s["M"][0], s["M"][1]
    _headline(
        fig,
        f"By 2050 a pension at 65 costs {long_m / now['M'] - 1:.0%} more (long trend) or "
        f"{recent_m / now['M'] - 1:.0%} more (recent)",
        f"Annuity-due at 65 against 2024 ({now['M']:.2f} for men): {long_m:.2f} or {recent_m:.2f} "
        f"in 2050 (women: {s['F'][0] / now['F'] - 1:.0%} or {s['F'][1] / now['F'] - 1:.0%} more). "
        "The spread between trends is longevity risk. CONAPO's line starts higher because its "
        "older-age mortality is lower than INEGI's (see the source gap).",
    )
    return _save(fig, out, "longevity_risk.png")


def cohort_vs_period(con, out: Path) -> Path:
    import numpy as np

    df = _query(
        con,
        "SELECT sex, year_at_65, period_e65, cohort_e65, annuity_understated_pct "
        "FROM cohort_tables WHERE year_at_65 IN (2025, 2035, 2045, 2055, 2070)",
    )
    fig, axes = _two_panels()
    gains = {}
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        d = df[df["sex"] == sex].sort_values("year_at_65")
        x = np.arange(len(d))
        ax.bar(
            x - 0.19,
            d["period_e65"],
            width=0.36,
            color=MUTED,
            label="Period table (that year's rates)",
        )
        ax.bar(
            x + 0.19,
            d["cohort_e65"],
            width=0.36,
            color=SEX_COLOR[sex],
            label="Cohort (rates improve as they age)",
        )
        for xi, (_, row) in zip(x, d.iterrows(), strict=True):
            extra = f"+{row['cohort_e65'] - row['period_e65']:.1f}y"
            ax.text(xi + 0.19, row["cohort_e65"] + 0.15, extra, ha="center", fontsize=9, color=INK)
        ax.set_xticks(x, [str(int(v)) for v in d["year_at_65"]])
        ax.set_xlabel("Year the cohort turns 65")
        ax.set_ylim(14, 27)
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        gains[sex] = float(d["annuity_understated_pct"].mean())
    axes[0].set_ylabel("Life expectancy at 65 (years)")
    axes[0].legend(loc="upper left", fontsize=9)
    _headline(
        fig,
        f"Pricing an annuity on a period table understates its cost by about {gains['M']:.1%}",
        "People turning 65 in each year, on that year's rates (period) and on the rates they "
        "will actually live through (cohort), long-run scenario. Labels: extra years of life.",
    )
    return _save(fig, out, "cohort_vs_period.png")


def source_gap_chart(con, out: Path) -> Path:
    import numpy as np

    year = _clean_year(con)
    df = _query(
        con,
        f"SELECT sex, age_band, ratio FROM source_gap WHERE year = {year}",
    )
    bands = ["0", "1-14", "15-39", "40-59", "60-74", "75-89", "90-99"]
    fig, ax = plt.subplots(figsize=(11, 6.2))
    fig.subplots_adjust(top=0.78, bottom=0.12, left=0.08, right=0.97)
    x = np.arange(len(bands))
    for offset, (sex, label) in zip((-0.19, 0.19), SEX_PANELS, strict=True):
        d = df[df["sex"] == sex].set_index("age_band").reindex(bands)
        ax.bar(x + offset, d["ratio"], width=0.36, color=SEX_COLOR[sex], label=label)
        for xi, v in zip(x + offset, d["ratio"], strict=True):
            ax.text(xi, v + 0.015, f"{v:.2f}", ha="center", fontsize=8.5, color=INK_2)
    ax.axhline(1, color=INK, lw=1)
    ax.set_xticks(x, bands)
    ax.set_xlabel("Age band")
    ax.set_ylabel("Deaths implied by INEGI rates / deaths CONAPO models")
    ax.set_ylim(0, 1.4)
    ax.legend(loc="upper left", fontsize=10)
    young = float(df[(df["sex"] == "M") & (df["age_band"] == "15-39")]["ratio"].iloc[0])
    old = float(df[(df["sex"] == "M") & (df["age_band"] == "90-99")]["ratio"].iloc[0])
    _headline(
        fig,
        f"For men aged 15 to 39, INEGI shows {1 - young:.0%} fewer deaths than CONAPO models",
        f"{year}, same population in both. Above age 60 the gap reverses (men 90-99: "
        f"{old - 1:+.0%}). The two sources agree on the total but not on who dies: this is why "
        "life expectancy at 65 falls across the 2019/2020 join while that at birth rises.",
    )
    return _save(fig, out, "source_gap.png")


# ── Experience study ────────────────────────────────────────────────────────

DIM_LABEL = {
    "sex": "Sex", "uw_class": "Underwriting class", "channel": "Channel", "product": "Product",
    "amount_band": "Sum assured (MXN)", "age_group": "Attained age",
    "duration_group": "Policy year",
    "region": "State mortality", "calendar_year": "Calendar year",
}  # fmt: skip
LEVEL_ORDER = {
    "sex": ["M", "F"], "uw_class": ["PREFERRED", "STANDARD", "RATED", "SIMPLIFIED"],
    "channel": ["AGENT", "BANK", "DIGITAL"], "product": ["TERM", "WHOLE_LIFE", "ENDOWMENT"],
    "amount_band": ["<250k", "250k-1M", "1M-5M", "5M+"],
    "age_group": ["18-29", "30-39", "40-49", "50-59", "60+"],
    "duration_group": ["1", "2", "3", "4", "5", "6-10", "11+"],
    "region": ["LOW", "MID", "HIGH"],
}  # fmt: skip


def experience_overview_chart(con, out: Path) -> Path:
    df = _query(
        con,
        "SELECT dimension, level, deaths, ae, ae_lower, ae_upper, credibility FROM experience_ae "
        "WHERE years = 'excluding_2020_2022' AND dimension <> 'calendar_year'",
    )
    total = df[df["dimension"] == "all"].iloc[0]
    rows = []
    for dim, levels in LEVEL_ORDER.items():
        for level in levels:
            r = df[(df["dimension"] == dim) & (df["level"] == level)]
            if len(r):
                rows.append((dim, level, r.iloc[0]))
    fig, ax = plt.subplots(figsize=(11, 9.2))
    fig.subplots_adjust(top=0.84, bottom=0.07, left=0.27, right=0.95)
    y = 0.0
    ticks, labels, previous = [], [], None
    for dim, level, r in rows:
        if previous is not None and dim != previous:
            y += 0.8
        previous = dim
        thin = r["credibility"] < 0.5
        ax.plot(
            [r["ae_lower"], r["ae_upper"]], [y, y], color=BLUE, lw=2.2, alpha=0.5 if thin else 0.9
        )
        ax.plot(r["ae"], y, "o", ms=8, mec=BLUE, mew=1.6,
                mfc=SURFACE if thin else BLUE, zorder=3)  # fmt: skip
        ticks.append(y)
        labels.append(f"{DIM_LABEL[dim]}: {level}")
        y += 1.0
    ax.axvline(1.0, color=INK, lw=1)
    ax.axvline(total["ae"], color=ORANGE, lw=1.4, ls=(0, (4, 3)))
    ax.text(total["ae"] + 0.01, -0.9, f"portfolio {total['ae']:.2f}", color=ORANGE, fontsize=9.5)
    ax.text(1.01, -0.9, "CNSF 2013 = 1.00", color=INK, fontsize=9.5)
    ax.set_yticks(ticks, labels, fontsize=9.2)
    ax.set_ylim(y, -1.4)
    ax.set_xlim(0.2, 1.9)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("Actual deaths / deaths expected on CNSF 2013 (count basis, 95% interval)")
    lo, hi = (
        df[df["dimension"] == "uw_class"]["ae"].min(),
        df[df["dimension"] == "uw_class"]["ae"].max(),
    )
    _headline(
        fig,
        f"The portfolio runs at {total['ae']:.0%} of CNSF 2013, but classes range from {lo:.0%} "
        f"to {hi:.0%}",
        "Actual-to-expected by one rating factor at a time, excluding the pandemic years "
        f"({total['deaths']:,.0f} deaths). Hollow dots have less than half credibility: their "
        "intervals are wide and a pricing decision should not rest on them alone. Synthetic "
        "portfolio.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_overview.png")


def experience_recovery_chart(con, out: Path) -> Path:
    import numpy as np

    df = _query(con, "SELECT factor, level, planted, relativity, lower, upper, inside_interval "
                     "FROM experience_recovery")  # fmt: skip
    fig, ax = plt.subplots(figsize=(10, 7.6))
    fig.subplots_adjust(top=0.78, bottom=0.09, left=0.09, right=0.96)
    span = np.array([0.42, 2.1])
    ax.plot(span, span, color=INK_2, lw=1, ls=(0, (4, 3)))
    for _, r in df.iterrows():
        color = BLUE if r["inside_interval"] else ORANGE
        ax.plot([r["planted"]] * 2, [r["lower"], r["upper"]], color=color, lw=2, alpha=0.6)
        ax.plot(
            r["planted"], r["relativity"], "o", color=color, ms=8, mec=SURFACE, mew=1.2, zorder=3
        )
    for _, r in df.iterrows():
        if abs(r["planted"] - 1) > 0.25 and r["level"] != "18-29":
            lift = 10 if r["level"] == "SIMPLIFIED" else -3
            ax.annotate(f"{r['level']}", (r["planted"], r["relativity"]), xytext=(7, lift),
                        textcoords="offset points", fontsize=8.5, color=INK_2)  # fmt: skip
    ax.set_xscale("log")
    ax.set_yscale("log")
    ticks = [0.5, 0.7, 1.0, 1.4, 2.0]
    ax.set_xticks(ticks, [str(t) for t in ticks])
    ax.set_yticks(ticks, [str(t) for t in ticks])
    ax.minorticks_off()
    ax.set_xlim(*span)
    ax.set_ylim(*span)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("Relativity planted in the synthetic portfolio")
    ax.set_ylabel("Relativity estimated by the study (95% interval)")
    n_in, n = int(df["inside_interval"].sum()), len(df)
    _headline(
        fig,
        f"The study recovers {n_in} of {n} planted rating effects within their 95% intervals",
        "A synthetic portfolio is built with known mortality effects; the study never sees them. "
        "Each dot is one level of a rating factor against its reference level, other factors held "
        "equal (Poisson GLM). Dots on the dashed line are exact. This is what makes the method "
        "trustworthy on a real extract.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_recovery.png")


def experience_select_chart(con, out: Path) -> Path:
    df = _query(con, "SELECT * FROM experience_select")
    fig, axes = _two_panels(sharey=True)
    for ax, kind in zip(axes, ("fully underwritten", "simplified issue"), strict=True):
        d = df[df["underwriting"] == kind].sort_values("duration")
        ax.axhline(1, color=INK_2, lw=1)
        ax.plot(d["duration"], d["planted"], color=INK, lw=2, ls=(0, (4, 3)), label="Planted")
        ax.step(
            d["duration"], d["smoothed"], where="mid", color=BLUE, lw=2.2, label="Smoothed estimate"
        )
        err = [d["relativity"] - d["lower"], d["upper"] - d["relativity"]]
        ax.errorbar(d["duration"], d["relativity"], yerr=err,
                    fmt="o", color=BLUE, ms=7, mec=SURFACE, mew=1.2, capsize=3, lw=1.4,
                    alpha=0.8, label="Estimate, 95% interval")  # fmt: skip
        ax.set_xticks([1, 2, 3, 4, 5], ["1", "2", "3", "4", "5"])
        ax.set_xlabel("Policy year")
        found = int(d["select_period"].iloc[0])
        ax.set_title(f"{kind.capitalize()}: select period found {found} years", loc="left",
                     fontweight="bold", color=INK, fontsize=10.5)  # fmt: skip
        ax.set_ylim(0.3, 1.45)
        ax.set_xlim(0.6, 5.4)
    axes[0].set_ylabel("Mortality relative to the ultimate level (policy years 6-10)")
    axes[0].legend(loc="lower right", fontsize=9)
    full = df[df["underwriting"] == "fully underwritten"]
    _headline(
        fig,
        "Underwriting selection is real, but a few thousand deaths cannot date its end",
        f"Mortality by policy year relative to years 6 to 10. The planted effect fades over five "
        f"years; only years 1 to {int(full['select_period'].iloc[0])} are statistically "
        "distinguishable from ultimate, so the 'select period' is a lower bound. Smoothing "
        "(isotonic) removes the zig-zag without inventing a shape.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_select.png")


def experience_quarterly_chart(con, out: Path) -> Path:

    from mortality import rates

    df = _query(con, "SELECT * FROM experience_ae_quarterly WHERE year >= 2020").reset_index(
        drop=True
    )
    x = df["year"] + (df["quarter"] - 1) / 4
    lo, hi = rates.poisson_interval(df["deaths_completed"].to_numpy(), 0.05)
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.08, right=0.95)
    ax.axvspan(2020, 2023, color=GRID, alpha=0.55, lw=0)
    ax.text(2021.5, 0.34, "pandemic years", ha="center", fontsize=9.5, color=INK_2)
    ax.fill_between(x, lo / df["expected"], hi / df["expected"], color=BLUE, alpha=0.15, lw=0)
    ax.plot(x, df["ae_completed"], color=BLUE, lw=2.4, marker="o", ms=5, mec=SURFACE, mew=1.1,
            label="Completed for the claims lag")  # fmt: skip
    ax.plot(x, df["ae"], color=ORANGE, lw=2.0, ls=(0, (4, 2)), marker="o", ms=5,
            mec=SURFACE, mew=1.1,
            label="As reported")  # fmt: skip
    ax.axhline(1, color=INK_2, lw=1)
    last = df.iloc[-1]
    ax.annotate(f"{last['ae']:.2f} reported\n{last['ae_completed']:.2f} completed",
                (x.iloc[-1], last["ae"]), xytext=(-110, -42), textcoords="offset points",
                fontsize=9.5,
                arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 0.9})  # fmt: skip
    ax.set_xlim(2020, 2024.8)
    ax.set_ylim(0.3, 1.5)
    ax.set_xlabel("Calendar quarter")
    ax.set_ylabel("Actual-to-expected on CNSF 2013 (count)")
    ax.legend(loc="upper left", fontsize=10)
    shortfall = 1 - last["ae"] / last["ae_completed"]
    _headline(
        fig,
        f"Unreported claims make the latest quarter look {shortfall:.0%} healthier than it is",
        f"Quarterly A/E, 95% band on the completed series. The extract was taken 46 days after "
        f"the study ended; deaths take a median 30 days to be notified, so the last quarters are "
        f"incomplete ({last['completion']:.0%} of the final quarter's deaths are in). Completion "
        "factors come from the portfolio's own notification lags.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_quarterly.png")


def experience_credibility_chart(con, out: Path) -> Path:
    df = (
        _query(con, "SELECT * FROM experience_credibility")
        .sort_values("deaths")
        .reset_index(drop=True)
    )
    fig, ax = plt.subplots(figsize=(11, 8.2))
    fig.subplots_adjust(top=0.84, bottom=0.08, left=0.25, right=0.95)
    for i, r in df.iterrows():
        ax.plot([r["ae"], r["bs_credible_ae"]], [i, i], color=GRID, lw=2, zorder=1)
        ax.plot(r["ae"], i, "o", ms=8, mfc=SURFACE, mec=INK_2, mew=1.4, zorder=2)
        ax.plot(r["ae_credible"], i, "s", ms=6, color=MUTED, zorder=3)
        ax.plot(r["bs_credible_ae"], i, "o", ms=8, color=BLUE, mec=SURFACE, mew=1.0, zorder=4)
    ax.axvline(1.0, color=INK, lw=1)
    ax.axvline(float(df["grand_mean"].iloc[0]), color=ORANGE, lw=1.3, ls=(0, (4, 3)))
    from matplotlib.lines import Line2D

    ax.legend(
        handles=[
            Line2D([], [], marker="o", ls="", mfc=SURFACE, mec=INK_2, mew=1.4, ms=8, label="Raw"),
            Line2D([], [], marker="s", ls="", color=MUTED, ms=6, label="Pulled toward CNSF (1.00)"),
            Line2D([], [], marker="o", ls="", color=BLUE, ms=8, label="Pulled toward the mean"),
        ],
        loc="lower right", fontsize=9,
    )  # fmt: skip
    names = [
        f"{c}  ({int(d)} death{'s' if d != 1 else ''})"
        for c, d in zip(df["class"], df["deaths"], strict=True)
    ]
    ax.set_yticks(range(len(df)), names, fontsize=8.6)
    ax.set_xlim(-0.05, 1.75)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("Actual-to-expected on CNSF 2013")
    candidates = df[df["deaths"] >= 30]
    gap = (candidates["ae_credible"] - candidates["bs_credible_ae"]).abs()
    thin = candidates.iloc[gap.to_numpy().argmax()]
    mean = float(df["grand_mean"].iloc[0])
    _headline(
        fig,
        "Thin segments should borrow strength from the portfolio, not from the old table",
        f"{thin['class']}: {int(thin['deaths'])} deaths, raw A/E {thin['ae']:.2f}. "
        f"Limited-fluctuation credibility pulls it to {thin['ae_credible']:.2f} (toward the "
        f"pricing basis, 1.00); Bühlmann-Straub to {thin['bs_credible_ae']:.2f} (toward the "
        f"portfolio mean, dashed orange, {mean:.2f}). Sex, class and channel, no pandemic years.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_credibility.png")


def experience_impact_chart(con, out: Path) -> Path:
    import numpy as np

    price = _query(con, "SELECT * FROM experience_pricing")
    impact = _query(con, "SELECT * FROM experience_impact")
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.4), gridspec_kw={"width_ratios": [1.25, 1]})
    fig.subplots_adjust(top=0.76, bottom=0.12, left=0.08, right=0.97, wspace=0.28)
    ax = axes[0]
    labels, x = [], np.arange(len(price))
    for i, r in price.iterrows():
        color = SEX_COLOR[r["sex"]]
        ax.bar(i - 0.2, r["change_pct"] * 100, width=0.36, color=color, label=None)
        prudent = r["premium_prudent_per_1000"] / r["premium_cnsf_per_1000"] - 1
        ax.bar(i + 0.2, prudent * 100, width=0.36, color=color, alpha=0.4)
        labels.append(f"{SEX_NAME[r['sex']]}\nage {int(r['issue_age'])}")
        ax.text(i - 0.2, r["change_pct"] * 100 + (2 if r["change_pct"] >= 0 else -5),
                f"{r['change_pct']:+.0%}", ha="center", fontsize=9, color=INK)  # fmt: skip
    ax.axhline(0, color=INK, lw=1)
    ax.set_ylim(-46, 26)
    ax.set_xticks(x, labels, fontsize=9)
    ax.set_ylabel("Change in the net premium against CNSF 2013 (%)")
    ax.set_title("20-year term premium", loc="left", fontweight="bold", color=INK)
    ax.text(
        0.02,
        0.04,
        "solid: best estimate    faded: prudent",
        transform=ax.transAxes,
        fontsize=9,
        color=INK_2,
    )
    ax2 = axes[1]
    order = ["ALL", "TERM", "WHOLE_LIFE", "ENDOWMENT"]
    d = impact.set_index("product").loc[order].reset_index()
    names = {
        "ALL": "All business",
        "TERM": "Term",
        "WHOLE_LIFE": "Whole life",
        "ENDOWMENT": "Endowment",
    }
    for i, r in d.iterrows():
        ax2.barh(
            i, r["pv_change_pct"] * 100, color=BLUE if r["product"] != "ALL" else INK_2, height=0.6
        )
        ax2.text(
            r["pv_change_pct"] * 100 - 0.6,
            i,
            f"{r['pv_change_pct']:+.0%}",
            ha="right",
            va="center",
            fontsize=9.5,
        )
    ax2.set_yticks(range(len(d)), [names[p] for p in d["product"]])
    ax2.set_xlim(-26, 2)
    ax2.axvline(0, color=INK, lw=1)
    ax2.invert_yaxis()
    ax2.grid(axis="y", visible=False)
    ax2.grid(axis="x", visible=True)
    ax2.set_xlabel("Change in the PV of future death claims (%)")
    ax2.set_title("In-force block", loc="left", fontweight="bold", color=INK)
    total = impact[impact["product"] == "ALL"].iloc[0]
    saved = (total["pv_cnsf"] - total["pv_experience"]) / 1e6
    f40 = price[(price["sex"] == "F") & (price["issue_age"] == 40)].iloc[0]
    m40 = price[(price["sex"] == "M") & (price["issue_age"] == 40)].iloc[0]
    _headline(
        fig,
        f"CNSF 2013 overprices women's term cover by {-f40['change_pct']:.0%}; "
        f"the block's claims run {-total['pv_change_pct']:.0%} lower",
        f"Net 20-year term premium: women at 40 {f40['change_pct']:+.0%}, men "
        f"{m40['change_pct']:+.0%} (a unisex table cross-subsidises). PV of future death "
        f"benefits of the in-force block falls MXN {saved:,.0f} million at 4% interest. The "
        "prudent margin (95% upper bound) is the price of the data's thinness.",
        source=SYNTHETIC,
    )
    return _save(fig, out, "experience_impact.png")


# ── Excess mortality ────────────────────────────────────────────────────────


def excess_waves(con, out: Path) -> Path:
    m = _query(con, "SELECT * FROM excess_monthly ORDER BY year, month")
    summary = _query(
        con, "SELECT * FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2022"
    )
    x = m["year"] + (m["month"] - 0.5) / 12
    fig, ax = plt.subplots(figsize=(11, 6.4))
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.09, right=0.95)
    ax.fill_between(x, m["baseline"] / 1000, m["deaths"] / 1000, where=m["deaths"] > m["baseline"],
                    color=ORANGE, alpha=0.30, lw=0, label="Excess deaths")  # fmt: skip
    ax.fill_between(x, 0, m["covid_deaths"] / 1000, color=BLUE, alpha=0.30, lw=0,
                    label="Certified as COVID-19")  # fmt: skip
    ax.plot(x, m["deaths"] / 1000, color=INK, lw=2.2, label="All deaths")
    ax.plot(
        x, m["baseline"] / 1000, color=INK_2, lw=1.6, ls=(0, (4, 3)), label="Expected (baseline)"
    )
    ax.set_xlim(2020, 2025)
    ax.set_ylim(0, 185)
    ax.set_xticks(range(2020, 2025))
    ax.set_ylabel("Deaths per month (thousands)")
    total = summary["excess"].sum()
    coded = summary["covid_coded"].sum()
    low, high = summary["excess_low"].sum(), summary["excess_high"].sum()
    ax.legend(loc="upper right", fontsize=9.5)
    _headline(
        fig,
        f"About {total / 1000:,.0f},000 excess deaths in 2020-2022: "
        f"{total / coded:.1f} per certified COVID-19 death",
        f"Monthly deaths against a baseline that keeps the normal seasonal shape. The central "
        f"estimate comes from four baselines (range {low / 1000:,.0f},000 to "
        f"{high / 1000:,.0f},000). Certified COVID-19 deaths: {coded / 1000:,.0f},000. Waves peak "
        f"in July 2020, January 2021 "
        "and August 2021.",
    )
    return _save(fig, out, "excess_waves.png")


def excess_age_profile(con, out: Path) -> Path:
    df = _query(con, "SELECT * FROM excess_mortality WHERE year IN (2020, 2021, 2022)")
    labels = list(rates.BAND_LABELS)
    shades = {2020: "#9ec5f0", 2021: BLUE, 2022: "#1c4f94"}
    fig, axes = _two_panels()
    peak = None
    for ax, (sex, title) in zip(axes, SEX_PANELS, strict=True):
        for year, color in shades.items():
            d = df[(df["sex"] == sex) & (df["year"] == year)].sort_values("band")
            if year == 2021:
                low = (d["observed"] / d["expected_high"] - 1) * 100
                high = (d["observed"] / d["expected_low"] - 1) * 100
                ax.fill_between(d["band"], low, high, color=color, alpha=0.18, lw=0)
            ax.plot(d["band"], d["p_score"] * 100, color=color, lw=2.3, label=str(year))
            if sex == "M" and year == 2021:
                peak = d.sort_values("p_score").iloc[-1]
        ax.axhline(0, color=INK_2, lw=1)
        ax.set_xticks(range(0, len(labels), 2), labels[::2], rotation=60, fontsize=9)
        ax.set_title(title, loc="left", fontweight="bold", color=INK)
        ax.set_xlim(0, len(labels) - 1)
    for ax in axes:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    axes[0].set_ylabel("Excess deaths as a share of expected (P-score)")
    axes[0].legend(loc="upper left", fontsize=9.5)
    _headline(
        fig,
        f"Men aged {peak['age_group']} died at {1 + peak['p_score']:.2f}x the expected rate "
        "in 2021",
        "P-score by age: excess over the central baseline. The shaded band for 2021 spans the "
        "four baselines. Excess rises steeply from the 20s, plateaus between about 45 and 75 at "
        "roughly two thirds above normal, and is smaller at the oldest ages and at young ages, "
        "where infant and child deaths fell below baseline.",
    )
    return _save(fig, out, "excess_age_profile.png")


def excess_causes(con, out: Path) -> Path:
    import numpy as np

    c = _query(con, "SELECT * FROM excess_by_cause")
    s = _query(con, "SELECT year, excess FROM excess_summary WHERE sex = 'T' AND year <= 2022")
    groups = [
        ("U", "Certified COVID-19", BLUE), ("I", "Heart disease and stroke", ORANGE),
        ("E", "Diabetes and endocrine", AQUA), ("J", "Respiratory", "#9085e9"),
    ]  # fmt: skip
    fig, ax = plt.subplots(figsize=(10, 6.6))
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.10, right=0.95)
    years = [2020, 2021, 2022]
    bottom = np.zeros(3)
    totals = s.set_index("year")["excess"].reindex(years).to_numpy()
    for chapter, label, color in groups:
        vals = np.array(
            [
                float(c[(c["year"] == y) & (c["chapter"] == chapter)]["excess"].iloc[0])
                for y in years
            ]
        )
        vals = np.maximum(vals, 0)
        ax.bar(years, vals / 1000, bottom=bottom / 1000, color=color, width=0.62, label=label)
        bottom += vals
    other = np.maximum(totals - bottom, 0)
    ax.bar(
        years, other / 1000, bottom=bottom / 1000, color=MUTED, width=0.62, label="All other causes"
    )
    for y, t in zip(years, totals, strict=True):
        ax.text(
            y, t / 1000 + 6, f"{t / 1000:,.0f},000", ha="center", fontsize=10.5, fontweight="bold"
        )
    ax.set_xticks(years)
    ax.set_ylabel("Excess deaths (thousands)")
    ax.set_ylim(0, 420)
    ax.legend(loc="upper right", fontsize=9.5)
    covid = c[(c["chapter"] == "U") & (c["year"] <= 2022)]["excess"].sum()
    rest = totals.sum() - covid
    _headline(
        fig,
        f"{covid / totals.sum():.0%} of excess deaths were certified as COVID-19; "
        "the rest are in other causes",
        f"Excess by cause chapter against the 2023 level scaled by population. "
        f"{rest / 1000:,.0f},000 "
        "excess deaths carry another certificate: COVID-related deaths certified under other "
        "causes, deaths of people who could not reach care, and causes already rising before 2020. "
        "The baseline for causes is 2023 only, so rising causes are a lower bound.",
    )
    return _save(fig, out, "excess_causes.png")


def excess_states(con, out: Path) -> Path:
    df = _query(con, "SELECT year, state_name, observed, expected, excess FROM excess_state")
    tot = df.groupby("state_name", as_index=False)[["observed", "expected", "excess"]].sum()
    tot["p"] = tot["excess"] / tot["expected"]
    tot["state_name"] = tot["state_name"].replace({"México": "Estado de México"})
    tot = tot.sort_values("p").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10.5, 8.6))
    fig.subplots_adjust(top=0.80, bottom=0.08, left=0.22, right=0.95)
    national = tot["excess"].sum() / tot["expected"].sum()
    for i, r in tot.iterrows():
        color = (
            ORANGE if r["p"] > national + 0.05 else (BLUE if r["p"] < national - 0.05 else MUTED)
        )
        ax.barh(i, r["p"] * 100, color=color, height=0.68)
        ax.text(52, i, f"{r['p']:.0%}  ({r['excess'] / 1000:,.1f}k deaths)", va="center",
                fontsize=8.3, color=INK_2)  # fmt: skip
    ax.axvline(national * 100, color=INK, lw=1.2, ls=(0, (4, 3)))
    ax.set_yticks(range(len(tot)), tot["state_name"], fontsize=8.8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlim(0, 70)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("Excess deaths 2020-2022 as a share of expected (state's own 2023 rates)")
    hi, lo = tot.iloc[-1], tot.iloc[0]
    _headline(
        fig,
        f"{hi['state_name']} lost {hi['p']:.0%} more people than expected; "
        f"{lo['state_name']} {lo['p']:.0%}",
        f"Excess 2020-2022 by state of residence (national {national:.0%}, dashed), against each "
        "state's own age-and-sex death rates of 2023, so age structure and population growth are "
        "removed. Orange: more than 5 points above the nation; blue: more than 5 below. The "
        "baseline is 2023, not a pre-pandemic trend, which the project does not have by state.",
    )
    return _save(fig, out, "excess_states.png")


PRICING_SOURCE = (
    "Illustrative 20-year level term product (sum assured 1,000,000), assumed expenses and "
    "lapses · "
    "CNSF 2013 pricing basis · Mortality Table Builder"
)


def pricing_signature(con, out: Path) -> Path:
    t = _query(con, "SELECT * FROM pricing_profit_test WHERE sex = 'M' ORDER BY policy_year")
    prem = _query(
        con, "SELECT * FROM pricing_premiums WHERE sex = 'M' AND term = 20 AND issue_age = 40"
    ).iloc[0]
    cum = t["profit_issued"].cumsum()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11, 6.0), gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(top=0.76, bottom=0.11, left=0.08, right=0.97, wspace=0.22)
    colors = [ORANGE if v < 0 else BLUE for v in t["profit_issued"]]
    ax.bar(
        t["policy_year"], t["profit_issued"], color=colors, width=0.7, label="Profit in the year"
    )
    ax.plot(t["policy_year"], cum, color=INK, lw=2.2, label="Cumulative profit")
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.set_xlabel("Policy year")
    ax.set_ylabel("Per policy issued (MXN)")
    ax.set_xticks(range(1, 21, 2))
    ax.legend(loc="upper left", fontsize=9.5)
    payback = int(prem["payback_year"])
    ax.annotate(
        f"Year 1: {t['profit_issued'].iloc[0]:,.0f}\nacquisition cost and\nfirst-year commission",
        xy=(1, t["profit_issued"].iloc[0]), xytext=(3.2, t["profit_issued"].iloc[0] * 0.95),
        fontsize=9, color=INK_2, va="center",
        arrowprops={"arrowstyle": "-", "color": MUTED},
    )  # fmt: skip
    break_even = int((cum >= 0).idxmax()) + 1 if (cum >= 0).any() else 0
    if break_even:
        ax.annotate(
            f"Cumulative profit turns positive in year {break_even}",
            xy=(break_even, 0), xytext=(break_even + 1.5, -1300), fontsize=9.5, color=INK,
            arrowprops={"arrowstyle": "->", "color": INK_2},
        )  # fmt: skip
    # Where a renewal-year premium goes (year 5, per policy in force)
    r = t.iloc[4]
    spent = r["claims"] + r["commission"] + r["expenses"] + r["profit_per_policy"]
    parts = {
        "Claims": r["claims"], "Commission": r["commission"], "Expenses": r["expenses"],
        "Added to reserves\n(net of interest)": r["premium"] - spent,
        "Profit": r["profit_per_policy"],
    }  # fmt: skip
    labels = list(parts)
    vals = [parts[k] / r["premium"] * 100 for k in labels]
    bx.barh(labels[::-1], vals[::-1], color=[BLUE, MUTED, AQUA, ORANGE, INK_2])
    for i, v in enumerate(vals[::-1]):
        bx.text(v + 0.8, i, f"{v:.0f}%", va="center", fontsize=9.5, color=INK_2)
    bx.set_xlim(0, max(vals) * 1.25)
    bx.set_xlabel("Share of the year-5 premium (%)")
    bx.grid(axis="y", visible=False)
    bx.grid(axis="x")
    _headline(
        fig,
        f"A term policy loses {abs(t['profit_issued'].iloc[0]):,.0f} on day one and "
        f"is in profit by year {break_even}",
        f"Man aged 40, 20-year term, sum assured 1,000,000, gross premium "
        f"{prem['gross_premium']:,.0f} "
        f"a year ({prem['gross_premium_per_1000']:.2f} per 1,000), solved to earn a "
        f"{prem['irr']:.0%} return, which takes until year {payback} once profit is discounted at "
        f"the hurdle. Net premium on the same table is "
        f"{prem['net_premium_per_1000']:.2f} per 1,000: the loading pays for the expenses.",
        PRICING_SOURCE,
    )
    return _save(fig, out, "pricing_signature.png")


def pricing_adequacy(con, out: Path) -> Path:
    df = _query(con, "SELECT * FROM pricing_adequacy")
    order = ["cnsf", "improving", "experience", "cnsf_p995", "population"]
    names = {
        "cnsf": "CNSF 2013\n(pricing\nbasis)",
        "improving": "CNSF +\nimprove-\nment",
        "experience": "Company\nexperience\n(synthetic)",
        "cnsf_p995": "CNSF\n99.5th\npercentile",
        "population": "Mexican\npopulation\n2023",
    }
    order = [b for b in order if b in set(df["basis"])]
    ages = (30, 40, 50)
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.2), sharey=True)
    fig.subplots_adjust(top=0.76, bottom=0.17, left=0.08, right=0.97, wspace=0.08)
    width = 0.26
    shades = {30: "#8db8ec", 40: BLUE, 50: "#1a4c8a"}
    for ax, (sex, name) in zip(axes, SEX_PANELS, strict=True):
        sub = df[df["sex"] == sex]
        for k, age in enumerate(ages):
            vals = [
                sub[(sub["basis"] == b) & (sub["issue_age"] == age)]["margin"].iloc[0] * 100
                for b in order
            ]
            vals = [max(v, -60) for v in vals]
            x = [i + (k - 1) * width for i in range(len(order))]
            ax.bar(x, vals, width=width, color=shades[age], label=f"Issue age {age}")
        ax.axhline(0, color=INK_2, lw=0.8)
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels([names[b] for b in order], fontsize=8.5)
        ax.set_title(name, loc="left", fontsize=11, fontweight="bold")
        ax.set_ylim(-65, 45)
    axes[0].set_ylabel("NPV margin at the 10% hurdle (% of PV premium)")
    axes[0].legend(loc="lower left", fontsize=9)
    axes[1].text(
        0.98, 0.95, "bars floored at -60%", transform=axes[1].transAxes, ha="right",
        fontsize=8.5, color=MUTED,
    )  # fmt: skip
    pop = df[(df["basis"] == "population") & (df["issue_age"] == 40) & (df["sex"] == "M")]
    cush = df[(df["basis"] == "cnsf") & (df["sex"] == "M")]["mortality_cushion"]
    _headline(
        fig,
        "The premium is safe on the regulatory table and not on the population's mortality",
        f"NPV margin when the CNSF-priced premium meets other mortality. Ages 30 to 50, 20-year "
        f"term. Population mortality would cost a man of 40 {abs(pop['margin'].iloc[0]):.0%} of "
        f"premium; mortality could run {cush.min() - 1:.0%} to {cush.max() - 1:.0%} "
        f"above the CNSF table before the policy stops covering its cost.",
        PRICING_SOURCE,
    )
    return _save(fig, out, "pricing_adequacy.png")


def pricing_tornado(con, out: Path) -> Path:
    s = _query(con, "SELECT * FROM pricing_sensitivity WHERE sex = 'M'").set_index("scenario")
    pairs = [
        ("Mortality ±20%", "mortality -20%", "mortality +20%"),
        ("Pandemic year 2 (x2)", None, "pandemic: year 2 mortality x2"),
        ("Investment return ±1 pt", "investment return +1 pt", "investment return -1 pt"),
        ("Expenses ±10%", "expenses -10%", "expenses +10%"),
        ("Lapses ±25%", "lapse +25%", "lapse -25%"),
    ]
    rows = []
    for label, good, bad in pairs:
        g = s.loc[good, "margin"] * 100 if good else 0.0
        b = s.loc[bad, "margin"] * 100
        rows.append((label, g, b))
    rows.sort(key=lambda r: abs(r[1]) + abs(r[2]))
    fig, ax = plt.subplots(figsize=(11, 5.6))
    fig.subplots_adjust(top=0.76, bottom=0.12, left=0.25, right=0.95)
    for i, (_label, g, b) in enumerate(rows):
        ax.barh(i, g, color=BLUE, height=0.55)
        ax.barh(i, b, color=ORANGE, height=0.55)
        if g:
            ax.text(g + 0.3, i, f"{g:+.1f}%", va="center", fontsize=9.5, color=INK_2)
        ax.text(b - 0.3, i, f"{b:+.1f}%", va="center", ha="right", fontsize=9.5, color=INK_2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.axvline(0, color=INK_2, lw=0.9)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x")
    ax.set_xlim(-16, 16)
    ax.set_xlabel("Change in NPV margin (% of PV premium)")
    top = rows[-1]
    _headline(
        fig,
        "Mortality is the assumption that decides the return",
        f"One assumption moved at a time on a man of 40, 20-year term, premium held fixed. "
        f"Blue favourable, orange adverse. A lapse-supported product is almost indifferent to "
        f"lapses ({rows[0][2]:+.1f}% margin); mortality ±20% moves it by {top[2]:+.1f}%.",
        PRICING_SOURCE,
    )
    return _save(fig, out, "pricing_tornado.png")


def pricing_reserves_chart(con, out: Path) -> Path:
    df = _query(con, "SELECT * FROM pricing_reserves WHERE sex = 'M'")
    fig, ax = plt.subplots(figsize=(11, 6.0))
    fig.subplots_adjust(top=0.78, bottom=0.11, left=0.09, right=0.95)
    ax.plot(df["policy_year"], df["statutory_reserve_end"], color=BLUE, lw=2.4,
            label="Statutory net premium reserve (CNSF, 4%)")  # fmt: skip
    ax.plot(df["policy_year"], df["best_estimate_end"], color=ORANGE, lw=2.4,
            label="Best-estimate liability (real expenses, lapses, 5%)")  # fmt: skip
    ax.fill_between(df["policy_year"], df["best_estimate_end"], df["statutory_reserve_end"],
                    color=MUTED, alpha=0.18, lw=0)  # fmt: skip
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.set_xlabel("End of policy year")
    ax.set_ylabel("Reserve per policy in force (MXN)")
    ax.set_xticks(range(1, 21, 2))
    ax.legend(loc="upper left", fontsize=9.5)
    gap = (df["statutory_reserve_end"] - df["best_estimate_end"]).iloc[0]
    _headline(
        fig,
        "The regulator's reserve holds money the best estimate says is not needed",
        f"Man aged 40, 20-year term. After year 1 the statutory reserve is "
        f"{df['statutory_reserve_end'].iloc[0]:,.0f} while the best-estimate liability is "
        f"{df['best_estimate_end'].iloc[0]:,.0f}: future premiums outweigh future claims. "
        f"The gap, {gap:,.0f}, is margin that releases over the life of the policy.",
        PRICING_SOURCE,
    )
    return _save(fig, out, "pricing_reserves.png")


FIGURES = (
    mortality_curve,
    covid_shock,
    standardised_trend,
    state_forest,
    population_vs_tables,
    country_heatmap,
    graduation_fit,
    graduation_residuals,
    old_age_closure,
    lambda_selection,
    covid_single_age,
    life_expectancy_trend,
    survival_curves,
    lifespan_disparity,
    annuity_values,
    term_premiums,
    projection_backtest_chart,
    period_index,
    projection_fan_e0,
    longevity_risk,
    cohort_vs_period,
    source_gap_chart,
    experience_overview_chart,
    experience_recovery_chart,
    experience_select_chart,
    experience_quarterly_chart,
    experience_credibility_chart,
    experience_impact_chart,
    excess_waves,
    excess_age_profile,
    excess_causes,
    excess_states,
    pricing_signature,
    pricing_adequacy,
    pricing_tornado,
    pricing_reserves_chart,
)


def build_all(out: Path) -> list[Path]:
    """Draw every figure into ``out``; returns the written paths."""
    _style()
    con = warehouse.connect()
    try:
        return [figure(con, out) for figure in FIGURES]
    finally:
        con.close()
