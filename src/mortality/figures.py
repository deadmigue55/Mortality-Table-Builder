"""Static figures for the README and reports, drawn from the warehouse.

Run with ``uv run mortality figures``. Each function reads the tables built by
``mortality db build`` and writes one PNG. Colors follow one small palette (blue, orange,
aqua, then muted grey) so the same series always has the same color across figures.
"""

from __future__ import annotations

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


FIGURES = (
    mortality_curve,
    covid_shock,
    standardised_trend,
    state_forest,
    population_vs_tables,
    country_heatmap,
)


def build_all(out: Path) -> list[Path]:
    """Draw every figure into ``out``; returns the written paths."""
    _style()
    con = warehouse.connect()
    try:
        return [figure(con, out) for figure in FIGURES]
    finally:
        con.close()
