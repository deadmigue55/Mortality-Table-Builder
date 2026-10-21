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


def _headline(fig, title: str, subtitle: str) -> None:
    """Left-aligned headline that states the finding, a muted line beneath, a source footer."""
    fig.text(0.015, 0.965, title, fontsize=15.5, fontweight="bold", va="top", ha="left")
    wrapped = textwrap.fill(subtitle, width=125)
    fig.text(
        0.015, 0.905, wrapped, fontsize=10.5, color=INK_2, va="top", ha="left", linespacing=1.4
    )
    fig.text(0.015, 0.012, SOURCE, fontsize=8, color=INK_2, va="bottom", ha="left")


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
)


def build_all(out: Path) -> list[Path]:
    """Draw every figure into ``out``; returns the written paths."""
    _style()
    con = warehouse.connect()
    try:
        return [figure(con, out) for figure in FIGURES]
    finally:
        con.close()
