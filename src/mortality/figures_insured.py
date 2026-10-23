"""Figures for the insured-lives table (version 2).

They follow the project's figure style (see ``figures.py``): the title states the finding, one
muted line explains how to read it, series are labelled directly or in a legend, one axis per
chart. Colours have a role that never changes: the insured table is green, the population
near-black, the CNSF 2013 regulatory table grey and dashed, the US insured table violet. Where a
figure is split by sex it uses one panel per sex, so the colours are free for the sources. The
palette was checked with the dataviz validator (contrast, colour-blind separation).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import NullFormatter

from mortality.figures import (
    BLUE,
    GRID,
    INK,
    INK_2,
    MUTED,
    ORANGE,
    _headline,
    _query,
    _save,
)
from mortality.insured_compare import MAIN, TERM

plt.rcParams["axes.axisbelow"] = True  # gridlines behind bars and lines

GREEN = "#0b8a5c"  # the insured table
VIOLET = "#7a52c7"  # the US insured table
ORANGE_TEXT = "#b34a1d"  # orange dark enough for text
POPULATION = INK
SOURCE = "Source: CNSF Sistema Estadístico, Vida Individual 2021-2025 · Mortality Table Builder v2"
SEX_TITLE = {"M": "Men", "F": "Women"}
PRODUCT_COLOR = {
    "term_traditional": GREEN,
    "credit": ORANGE,
    "permanent": VIOLET,
    "all": INK,
}


def _panels(n: int = 2, figsize=(11.5, 6.4), top=0.76, sharey=True):
    fig, axes = plt.subplots(1, n, figsize=figsize, sharey=sharey)
    fig.subplots_adjust(top=top, bottom=0.13, left=0.075, right=0.975, wspace=0.07)
    return fig, np.atleast_1d(axes)


def _table(con, segment: str) -> pd.DataFrame:
    return _query(con, f"SELECT * FROM insured_table WHERE segment = '{segment}' ORDER BY sex, age")


def _label(ax, x, y, text, color, ha="left", size=9.5, weight="bold"):
    ax.text(x, y, text, color=color, fontsize=size, ha=ha, va="center", fontweight=weight)


def _sex_title(ax, sex: str) -> None:
    ax.set_title(SEX_TITLE[sex], loc="left", fontsize=12, fontweight="bold")


def _split(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The ages that come from data and the ages the table extends beyond them."""
    solid = table[table["source"] != "extended"]
    dotted = table[table["age"] >= solid["age"].max()]
    return solid, dotted


# ── 1. The hero: two Mexicos ────────────────────────────────────────────────


def insured_hero(con, out: Path) -> Path:
    table = _table(con, "all")
    term = _table(con, "term_traditional")
    pooled = _query(
        con,
        "SELECT sex, age, rate FROM insured_pooled "
        "WHERE segment = 'all' AND age BETWEEN 20 AND 90 AND deaths >= 5",
    )
    fig, axes = _panels(2)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        t = table[(table["sex"] == sex) & table["age"].between(18, 100)]
        tt = term[(term["sex"] == sex) & term["age"].between(18, 100)]
        solid, dotted = _split(t)
        ax.axvspan(solid["age"].max(), 100, color=GRID, alpha=0.5, lw=0, zorder=0)
        ax.plot(t["age"], t["q_population"], color=POPULATION, lw=2, zorder=3)
        ax.plot(t["age"], t["q_cnsf2013"], color=MUTED, lw=1.8, ls=(0, (4, 3)), zorder=2)
        crude = pooled[pooled["sex"] == sex]
        ax.scatter(crude["age"], crude["rate"], s=9, color=GREEN, alpha=0.35, lw=0, zorder=2)
        ax.plot(solid["age"], solid["qx"], color=GREEN, lw=2.6, zorder=4)
        ax.plot(dotted["age"], dotted["qx"], color=GREEN, lw=2.0, ls=(0, (1, 2)), zorder=4)
        t_solid, _ = _split(tt)
        ax.plot(t_solid["age"], t_solid["qx"], color=GREEN, lw=1.2, alpha=0.7, zorder=3)
        ax.set_yscale("log")
        ax.set_ylim(5e-5, 0.8)
        ax.set_xlim(18, 100)
        _sex_title(ax, sex)
        ax.set_xlabel("Age")
        row = t[t["age"] == 40].iloc[0]
        ax.annotate(
            f"Age 40: {row['qx'] * 1000:.2f} per 1,000\nvs {row['q_population'] * 1000:.1f} "
            f"in the population\n({row['q_population'] / row['qx']:.0f} times lower)",
            xy=(40, row["qx"]),
            xytext=(46, 1.0e-4),
            fontsize=9.5,
            color=INK,
            va="bottom",
            arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 0.9},
        )
        ax.text(
            solid["age"].max() + 1.2,
            0.55,
            "extended by assumption",
            fontsize=8.5,
            color=INK_2,
            va="top",
            ha="left",
        )
        if sex == "M":
            ax.set_ylabel("Probability of dying within a year (log scale)")
    handles = [
        Line2D([], [], color=POPULATION, lw=2, label="Population"),
        Line2D([], [], color=MUTED, lw=1.8, ls=(0, (4, 3)), label="CNSF 2013 (regulator)"),
        Line2D([], [], color=GREEN, lw=2.6, label="Insured lives, all products"),
        Line2D([], [], color=GREEN, lw=1.2, alpha=0.7, label="Insured, traditional term"),
    ]
    axes[0].legend(handles=handles, loc="upper left", fontsize=9)
    _headline(
        fig,
        "Mexicans who buy life insurance die at a seventh to a quarter of the population's rate",
        "Probability of dying within a year by age. Green: the insured-lives table built from the "
        "CNSF industry statistics 2023-25 (dots are the raw rates it was fitted to). Grey band: "
        "ages where the data stop being a safe guide and the table follows the population's shape.",
        SOURCE,
    )
    return _save(fig, out, "insured_hero.png")


# ── 2. The gap, in Mexico and in the United States ─────────────────────────


def insured_gap(con, out: Path) -> Path:
    g = _query(con, "SELECT * FROM insured_gap")
    styles = {
        "Mexico: insured, all individual life / population": (GREEN, "-", 2.6, "Mexico, insured"),
        "Mexico: CNSF 2013 / population": (MUTED, (0, (4, 3)), 1.8, "Mexico, CNSF 2013"),
        "US: 2017 Unloaded CSO / national table": (VIOLET, "-", 2.4, "United States, insured"),
    }
    fig, axes = _panels(2, top=0.77)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for name, (color, ls, lw, _label_text) in styles.items():
            d = g[(g["sex"] == sex) & (g["comparison"] == name)].dropna()
            if not d.empty:
                ax.plot(d["age"], d["ratio"], color=color, lw=lw, ls=ls)
        ax.axhline(1.0, color=INK_2, lw=0.8)
        ax.set_ylim(0, 1.12)
        ax.set_xlim(20, 85)
        _sex_title(ax, sex)
        ax.set_xlabel("Age")
        if sex == "M":
            ax.set_ylabel("Insured mortality as a share of the national table")
        ax.text(84, 1.03, "same as the national table", fontsize=8.5, color=INK_2, ha="right")
    handles = [
        Line2D([], [], color=color, lw=lw, ls=ls, label=label)
        for color, ls, lw, label in styles.values()
    ]
    axes[0].legend(handles=handles, loc="center left", bbox_to_anchor=(0.0, 0.45), fontsize=9)
    _headline(
        fig,
        "Mexican insured lives sit about three times further below their population than American ones",
        "Ratio of insured to national mortality. A US insured life dies at 45-70% of the national rate "
        "at ages 25-45, and the advantage fades by 85. A Mexican insured life dies at 14-25% of it "
        "from 20 to 65: insurance in Mexico is a small, wealthy, underwritten club.",
        "Source: CNSF Vida Individual 2023-25; SOA 2017 Unloaded CSO; HMD (USA 2019) · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_gap.png")


# ── 3. Products ─────────────────────────────────────────────────────────────


def insured_products(con, out: Path) -> Path:
    labels = {
        "permanent": "Whole life and endowment",
        "credit": "Credit life (term)",
        "term_traditional": "Traditional term",
    }
    fig, axes = _panels(2)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for segment in labels:
            t = _table(con, segment)
            t = t[(t["sex"] == sex) & t["age"].between(25, 80)]
            solid, dotted = _split(t)
            color = PRODUCT_COLOR[segment]
            ax.plot(solid["age"], solid["qx"], color=color, lw=2.4)
            ax.plot(dotted["age"], dotted["qx"], color=color, lw=1.8, ls=(0, (1, 2)))
        ax.set_yscale("log")
        ax.set_ylim(8e-5, 0.1)
        ax.set_xlim(25, 80)
        _sex_title(ax, sex)
        ax.set_xlabel("Age")
        if sex == "M":
            ax.set_ylabel("Probability of dying within a year (log scale)")
    handles = [
        Line2D([], [], color=PRODUCT_COLOR[s], lw=2.4, label=label) for s, label in labels.items()
    ]
    handles.append(Line2D([], [], color=INK_2, lw=1.8, ls=(0, (1, 2)), label="beyond the data"))
    axes[0].legend(handles=handles, loc="upper left", fontsize=9)
    _headline(
        fig,
        "The product matters as much as the person: whole life dies at 2 to 3.5 times the rate of term",
        "Insured mortality by product, 2023-25. Traditional term is underwritten and recent; "
        "whole life and endowments are older, in force for decades, and include savings-type "
        "plans. Dotted: beyond the last age the data support, where the table follows the population's shape.",
        SOURCE,
    )
    return _save(fig, out, "insured_products.png")


# ── 4. What it means for a quote ───────────────────────────────────────────


def insured_premiums(con, out: Path) -> Path:
    p = _query(con, "SELECT * FROM insured_premiums WHERE term = 20")
    tables = [
        (TERM, "Insured, traditional term", GREEN, "-", 2.8),
        (MAIN, "Insured, all products", GREEN, (0, (5, 2)), 1.6),
        ("CNSF 2013", "CNSF 2013 (regulator)", INK_2, (0, (4, 3)), 1.8),
        ("US 2017 Unloaded CSO composite {w} ALB", "US insured (Unloaded CSO)", VIOLET, "-", 2.0),
        ("Mexico population 2023", "Population", POPULATION, "-", 2.0),
    ]
    fig, axes = _panels(2)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        word = "male" if sex == "M" else "female"
        for name, _label_text, color, ls, lw in tables:
            d = p[(p["sex"] == sex) & (p["table"] == name.format(w=word))].sort_values("issue_age")
            ax.plot(d["issue_age"], d["premium_per_1000"], color=color, lw=lw, ls=ls)
            ax.scatter(d["issue_age"], d["premium_per_1000"], s=14, color=color, zorder=3)
        ax.set_yscale("log")
        ax.set_xlim(25, 60)
        ax.set_ylim(0.1, 40)
        _sex_title(ax, sex)
        ax.set_xlabel("Issue age")
        if sex == "M":
            ax.set_ylabel("Net annual premium per 1,000 insured (log scale)")
    handles = [Line2D([], [], color=c, lw=lw, ls=ls, label=lb) for _, lb, c, ls, lw in tables]
    axes[0].legend(handles=handles[::-1], loc="upper left", fontsize=9)
    m = p[(p["sex"] == "M") & (p["issue_age"] == 40)].set_index("table")["premium_per_1000"]
    fig.text(
        0.075,
        0.115,
        f"A man of 40, 20-year term: {m[TERM]:.2f} per 1,000 on the insured table, "
        f"{m['CNSF 2013']:.2f} on CNSF 2013, {m['US 2017 Unloaded CSO composite male ALB']:.2f} "
        f"on the US insured table, {m['Mexico population 2023']:.1f} on the population.",
        fontsize=9.5,
        color=INK,
        va="top",
    )
    fig.subplots_adjust(bottom=0.2)
    _headline(
        fig,
        "A standard term quote costs half or less on the insured table than on the regulator's",
        "Net annual premium of a level 20-year term cover by issue age, at 4% interest, with "
        "no expenses or margins: the cost of the mortality alone. Same code, same interest, "
        "different table.",
        "Source: CNSF Vida Individual 2023-25, CNSF 2013, SOA 2017 CSO, INEGI/CONAPO · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_premiums.png")


# ── 5. League table of countries ────────────────────────────────────────────


def insured_countries(con, out: Path) -> Path:
    c = _query(con, "SELECT * FROM insured_comparison")
    country = {
        "JPN": "Japan", "ESP": "Spain", "ITA": "Italy", "SWE": "Sweden", "CAN": "Canada",
        "FRATNP": "France", "GBR_NP": "United Kingdom", "CHL": "Chile", "USA": "United States",
    }  # fmt: skip
    short = {
        "Mexico insured: Term, traditional": "Mexico insured, traditional term",
        "Mexico insured: Term, credit life": "Mexico insured, credit life",
        "Mexico insured: Whole life and endowment": "Mexico insured, whole life",
    }
    fig, axes = plt.subplots(1, 2, figsize=(12, 8.2), sharex=True)
    fig.subplots_adjust(top=0.8, bottom=0.11, left=0.2, right=0.97, wspace=0.78)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        d = c[c["sex"].isin([sex, "T"])].copy()
        d["premium"] = d["P_term_20_at_40"] * 1000
        rows = []
        for _, r in d.iterrows():
            name = r["table"]
            if r["group"] == "HMD national":
                code = name.split()[0]
                rows.append((f"{country.get(code, code)}, national 2019", r["premium"], MUTED))
            elif name == "Mexico population 2023":
                rows.append(("Mexico, population", r["premium"], POPULATION))
            elif name in short:
                rows.append((short[name], r["premium"], GREEN))
            elif name == "CNSF 2013":
                rows.append(("Mexico, CNSF 2013 (regulator)", r["premium"], INK_2))
            elif name.startswith("US 2017 Unloaded"):
                rows.append(("United States, insured (CSO)", r["premium"], VIOLET))
        keep = sorted(rows, key=lambda t: t[1])
        y = np.arange(len(keep))
        ax.hlines(y, 0.01, [t[1] for t in keep], color=GRID, lw=1)
        ax.scatter([t[1] for t in keep], y, s=48, color=[t[2] for t in keep], zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels([t[0] for t in keep], fontsize=9)
        for tick, (_, _, color) in zip(ax.get_yticklabels(), keep, strict=True):
            tick.set_color(INK if color in (GREEN, VIOLET, POPULATION) else INK_2)
        ax.set_xscale("log")
        ax.set_xlim(0.2, 12)
        ax.xaxis.set_minor_formatter(NullFormatter())
        _sex_title(ax, sex)
        ax.set_xlabel("Net premium per 1,000, 20-year term at 40 (log scale)")
        ax.grid(axis="x")
        ax.grid(axis="y", visible=False)
    _headline(
        fig,
        "Insured Mexicans are priced below the healthiest countries on earth",
        "Cost of mortality for a 20-year term at 40, from each table, same code and 4% interest. "
        "Mexico's population is dearer than any country's national table here; the insured "
        "table, for a standard term product, is cheaper than all of them.",
        "Source: CNSF Vida Individual 2023-25, INEGI/CONAPO, SOA CSO 2017, Human Mortality Database (2019) · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_countries.png")


# ── 6. Who do Mexicans die like? ───────────────────────────────────────────


def insured_matches(con, out: Path) -> Path:
    m = _query(con, "SELECT * FROM insured_matches WHERE rank = 1")
    code = {"FRATNP": "FRA", "GBR_NP": "GBR"}
    fig, axes = _panels(2, sharey=True)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for basis, color in (("population", POPULATION), ("insured", GREEN)):
            d = m[(m["sex"] == sex) & (m["basis"] == basis)].sort_values("age_from")
            x = (d["age_from"] + d["age_to"]) / 2
            ax.plot(x, d["year"], color=color, lw=1.2, alpha=0.6)
            ax.scatter(x, d["year"], s=26, color=color, zorder=3)
            for xi, yi, c in zip(x, d["year"], d["country"], strict=True):
                above = basis == "population"
                ax.text(
                    xi,
                    yi + (3.4 if above else -5.2),
                    code.get(c, c),
                    fontsize=7.5,
                    color=color,
                    ha="center",
                )
        ax.set_xlim(23, 87)
        ax.set_ylim(1945, 2032)
        _sex_title(ax, sex)
        ax.set_xlabel("Age band (midpoint)")
        if sex == "M":
            ax.set_ylabel("Year of the closest national table")
    handles = [
        Line2D([], [], color=POPULATION, lw=1.5, marker="o", ms=5, label="Mexican population"),
        Line2D([], [], color=GREEN, lw=1.5, marker="o", ms=5, label="Mexican insured lives"),
    ]
    axes[0].legend(handles=handles, loc="center left", bbox_to_anchor=(0.0, 0.62), fontsize=9)
    _headline(
        fig,
        "Insured Mexicans die like Spain and Sweden today; the population, like countries decades ago",
        "For each age band, the country and year (1950 onward) whose national mortality is closest "
        "to the Mexican one. The population matches the 1950s-1990s; the insured table needs the "
        "best countries of the present day, and at some ages is lighter than any of them.",
        "Source: CNSF Vida Individual 2023-25, INEGI/CONAPO, Human Mortality Database · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_matches.png")


# ── 7. The pandemic ────────────────────────────────────────────────────────


def insured_pandemic(con, out: Path) -> Path:
    p = _query(con, "SELECT * FROM insured_pandemic")
    g = p.groupby(["source", "year", "band"])[["deaths", "exposure"]].sum().reset_index()
    g["rate"] = g["deaths"] / g["exposure"]
    base = g[g["year"] == 2023].set_index(["source", "band"])["rate"]
    g["index"] = g["rate"] / [base[(s, b)] for s, b in zip(g["source"], g["band"], strict=True)]
    fig, axes = _panels(3, figsize=(12, 6.0), top=0.74)
    for ax, band in zip(axes, ("25-44", "45-64", "65-79"), strict=True):
        for source, color, up in (("population", POPULATION, -1), ("insured", GREEN, 1)):
            d = g[(g["source"] == source) & (g["band"] == band)].sort_values("year")
            ax.plot(d["year"], d["index"], color=color, lw=2.4, marker="o", ms=4)
            peak = d[d["year"] == 2021].iloc[0]
            ax.text(
                2021.18 if up > 0 else 2020.9,
                float(peak["index"]) + (0.12 if up > 0 else 0.13),
                f"{peak['index']:.1f}x",
                color=color,
                fontsize=10,
                fontweight="bold",
                va="center",
                ha="left" if up > 0 else "right",
            )
        ax.axhline(1.0, color=INK_2, lw=0.8)
        ax.set_xlim(2019.8, 2025.3)
        ax.set_ylim(0.6, 3.0)
        ax.set_xticks(range(2020, 2026))
        ax.set_title(f"Ages {band}", loc="left", fontsize=12, fontweight="bold")
        if band == "25-44":
            ax.set_ylabel("Death rate relative to 2023")
    handles = [
        Line2D([], [], color=POPULATION, lw=2.4, marker="o", ms=4, label="Population"),
        Line2D([], [], color=GREEN, lw=2.4, marker="o", ms=4, label="Insured lives"),
    ]
    axes[0].legend(handles=handles, loc="upper right", fontsize=9)
    _headline(
        fig,
        "COVID-19 hit insured lives harder in relative terms: up to 2.7 times their 2023 level in 2021",
        "Death rate of each group relative to its own 2023 rate, both sexes. Insured mortality is "
        "so low that an absolute excess about half the population's is a bigger jump in relative "
        "terms: the protection insured lives enjoy is not proof against a pandemic.",
        "Source: CNSF Vida Individual 2021-25, INEGI deaths, CONAPO population · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_pandemic.png")


# ── 8. Relativities ────────────────────────────────────────────────────────


def insured_relativities(con, out: Path) -> Path:
    r = _query(con, "SELECT * FROM insured_relativities WHERE segment <> 'term_traditional'")
    names = {
        "credit": "Credit life (term)",
        "term_other": "Other term modalities",
        "permanent": "Whole life and endowment",
    }
    order = ["credit", "term_other", "permanent"]
    fig, axes = _panels(2, figsize=(12, 5.8), top=0.76, sharey=False)
    fig.subplots_adjust(left=0.19, wspace=0.12)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        for ages, color, dy in (("25-44", GREEN, 0.14), ("45-65", VIOLET, -0.14)):
            for i, seg in enumerate(order):
                d = r[(r["sex"] == sex) & (r["segment"] == seg) & (r["ages"] == ages)]
                if d.empty:
                    continue
                d = d.iloc[0]
                y = i + dy
                ax.hlines(y, d["lower"], d["upper"], color=color, lw=2.2)
                ax.scatter([d["k"]], [y], color=color, s=40, zorder=3)
                ax.text(d["upper"] * 1.04, y, f"{d['k']:.1f}x", fontsize=9, color=INK, va="center")
        ax.axvline(1.0, color=INK_2, lw=0.9)
        ax.set_xscale("log")
        ax.set_xlim(0.8, 8)
        ax.set_xticks([1, 2, 4, 8])
        ax.set_xticklabels(["1", "2", "4", "8"])
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels([names[s] for s in order] if sex == "M" else [], fontsize=9.5)
        ax.set_ylim(-0.6, len(order) - 0.4)
        _sex_title(ax, sex)
        ax.set_xlabel("Mortality relative to traditional term (log scale), 95% interval")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x")
    handles = [
        Line2D([], [], color=GREEN, lw=2.2, marker="o", ms=5, label="Ages 25-44"),
        Line2D([], [], color=VIOLET, lw=2.2, marker="o", ms=5, label="Ages 45-65"),
    ]
    axes[1].legend(handles=handles, loc="lower right", fontsize=9)
    _headline(
        fig,
        "Against traditional term, credit life dies 1.3 to 2 times as fast and whole life 2 to 3.5 times",
        "Multiplier of the traditional-term table that matches each product's deaths, by "
        "age range. The gap widens with age: mixed health at issue on credit and savings products, "
        "and long durations on whole life, show up as the years go by.",
        SOURCE,
    )
    return _save(fig, out, "insured_relativities.png")


# ── 9. Amount versus count ─────────────────────────────────────────────────


def insured_amount(con, out: Path) -> Path:
    a = _query(con, "SELECT * FROM insured_amount WHERE sex = 'M'")
    names = {
        "term_traditional": "Traditional term",
        "credit": "Credit life",
        "permanent": "Whole life and endowment",
        "all": "All products",
    }
    fig, ax = plt.subplots(figsize=(11, 6.0))
    fig.subplots_adjust(top=0.77, bottom=0.12, left=0.09, right=0.78)
    for seg, color in PRODUCT_COLOR.items():
        d = a[a["segment"] == seg].sort_values("decade")
        ax.plot(
            d["decade"] + 5,
            d["amount_to_count_ratio"],
            color=color,
            lw=2.4 if seg != "all" else 1.6,
            ls="-" if seg != "all" else (0, (4, 3)),
            marker="o",
            ms=5,
        )
        last = d.iloc[-1]
        _label(
            ax,
            last["decade"] + 6.2,
            last["amount_to_count_ratio"],
            names[seg],
            color if seg != "credit" else ORANGE_TEXT,
        )
    ax.axhline(1.0, color=INK_2, lw=0.9)
    ax.set_ylim(0.3, 1.6)
    ax.set_xlim(34, 77)
    ax.set_xlabel("Age (decade midpoint)")
    ax.set_ylabel("Death rate by sum assured / death rate by count")
    ax.text(76, 0.97, "equal", fontsize=8.5, color=INK_2, ha="right", va="top")
    _headline(
        fig,
        "Per peso of cover, traditional term costs 25-40% more than its death count suggests",
        "Ratio of the death rate by claimed amount over sum assured to the death rate by number of "
        "lives, men, 2023-25. Above 1: larger policies die more; below 1, less. Credit-life claims "
        "settle a loan balance, well below the original sum.",
        SOURCE,
    )
    return _save(fig, out, "insured_amount.png")


# ── 10. The tornado ────────────────────────────────────────────────────────


def insured_tornado(con, out: Path) -> Path:
    s = _query(
        con,
        "SELECT choice, alternative, change_vs_base c FROM insured_sensitivity "
        "WHERE sex = 'M' AND issue_age = 40 AND term = 20 AND choice <> 'Base table'",
    )
    s["label"] = s["choice"].str.cat(s["alternative"], sep=": ")
    blend = float(s.loc[s["alternative"].str.startswith("market blend"), "c"].iloc[0])
    s = s[s["c"].abs() > 0.0005].sort_values("c")
    fig, ax = plt.subplots(figsize=(12, 7.4))
    fig.subplots_adjust(top=0.82, bottom=0.09, left=0.5, right=0.95)
    y = np.arange(len(s))
    ax.barh(y, s["c"] * 100, color=[ORANGE if v > 0 else BLUE for v in s["c"]], height=0.62)
    for yi, v in zip(y, s["c"] * 100, strict=True):
        ax.text(
            v + (1.0 if v > 0 else -1.0),
            yi,
            f"{v:+.1f}%",
            va="center",
            ha="left" if v > 0 else "right",
            fontsize=9,
            color=INK,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(s["label"], fontsize=9)
    ax.axvline(0, color=INK_2, lw=0.9)
    ax.set_xlim(min(-20, s["c"].min() * 100 - 8), s["c"].max() * 100 + 12)
    ax.set_xlabel("Change in the net premium of a man of 40, 20-year term")
    ax.grid(axis="y", visible=False)
    ax.text(
        0.99,
        0.02,
        "premium up",
        transform=ax.transAxes,
        color=ORANGE_TEXT,
        ha="right",
        fontsize=9.5,
        fontweight="bold",
    )
    ax.text(
        0.01,
        0.02,
        "premium down",
        transform=ax.transAxes,
        color=BLUE,
        ha="left",
        fontsize=9.5,
        fontweight="bold",
    )
    _headline(
        fig,
        "Which table you quote on matters more than any modelling choice behind it",
        "Each choice between the CNSF statistics and a table, changed one at a time while the "
        "rest stay as in the base table (traditional term, 2023-25, direct P-spline). Quoting a "
        f"traditional-term policy on the market-wide table would overcharge by {blend:.0%}.",
        SOURCE,
    )
    return _save(fig, out, "insured_tornado.png")


# ── 11. Causes ─────────────────────────────────────────────────────────────


def insured_causes(con, out: Path) -> Path:
    from mortality.insured_causes import LABELS

    c = _query(
        con,
        'SELECT sex, "group" AS grp, SUM(deaths) AS deaths FROM insured_causes '
        'WHERE year IN (2023, 2024, 2025) GROUP BY sex, "group"',
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4), sharey=False)
    fig.subplots_adjust(top=0.77, bottom=0.1, left=0.25, right=0.97, wspace=0.75)
    for ax, sex in zip(axes, ("M", "F"), strict=True):
        d = c[(c["sex"] == sex) & (c["grp"] != "not_a_cause_of_death")].copy()
        d["share"] = d["deaths"] / d["deaths"].sum()
        d = d.sort_values("share")
        y = np.arange(len(d))
        ax.barh(y, d["share"] * 100, color=GREEN, height=0.62)
        for yi, v in zip(y, d["share"] * 100, strict=True):
            ax.text(v + 0.3, yi, f"{v:.0f}%", va="center", fontsize=9)
        ax.set_yticks(y)
        ax.set_yticklabels([LABELS.get(g, g) for g in d["grp"]], fontsize=9)
        _sex_title(ax, sex)
        ax.set_xlabel("Share of death claims, 2023-25 (%)")
        ax.grid(axis="y", visible=False)
    _headline(
        fig,
        "Heart attacks lead men's claims and cancer women's; about one claim in eight is too vague to classify",
        "Cause of death claims, grouped by keyword from the text of the claim. The field mixes "
        "underlying and immediate causes (shock, acidosis, arrest), so it describes a pattern, "
        "not an exact cause-of-death statistic.",
        SOURCE,
    )
    return _save(fig, out, "insured_causes.png")


# ── 12. The evidence on the ledger ────────────────────────────────────────


def insured_ledger(con, out: Path) -> Path:
    led = _query(con, "SELECT * FROM insured_ledger")
    years = sorted(led["year"].unique())
    known = led[(led["block"] == "known") & (led["sign"] == "positive")].set_index("year")["claims"]
    pos = led[(led["block"] == "no_detail") & (led["sign"] == "positive")].set_index("year")[
        "claims"
    ]
    neg = led[(led["block"] == "no_detail") & (led["sign"] == "negative")].set_index("year")[
        "claims"
    ]
    fig, ax = plt.subplots(figsize=(11.5, 6.0))
    fig.subplots_adjust(top=0.77, bottom=0.12, left=0.09, right=0.8)
    x = np.arange(len(years))
    w = 0.26
    ax.bar(x - w, [known.get(y, 0) / 1000 for y in years], w, color=GREEN)
    ax.bar(x, [pos.get(y, 0) / 1000 for y in years], w, color=MUTED)
    ax.bar(x + w, [-neg.get(y, 0) / 1000 for y in years], w, color=ORANGE)
    ax.axhline(0, color=INK_2, lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel("Death-claim rows (thousands)")
    ax.set_xlim(-0.6, len(years) - 0.4)
    ax.text(
        len(years) - 0.35,
        known.iloc[-1] / 1000,
        "Claims with age and sex\n(the deaths)",
        color=GREEN,
        fontsize=9.5,
        fontweight="bold",
        va="center",
    )
    ax.text(
        len(years) - 0.35,
        pos.iloc[-1] / 1000 + 1.5,
        "No age or sex:\nnew claims",
        color=INK_2,
        fontsize=9.5,
        fontweight="bold",
        va="center",
    )
    ax.text(
        len(years) - 0.35,
        -neg.iloc[-1] / 1000 - 1.5,
        "No age or sex:\ncancellations",
        color=ORANGE_TEXT,
        fontsize=9.5,
        fontweight="bold",
        va="center",
    )
    _headline(
        fig,
        "A fifth of death-claim rows have no age or sex, and they cancel out: a ledger, not deaths",
        "Rows of the CNSF claims sheet for the death cover. Those without age and sex carry "
        "cancellations that outweigh new claims every year, hold a steady 7,000 claims while real "
        "deaths halved, and cite COVID years after the pandemic: settlements of old claims.",
        SOURCE,
    )
    return _save(fig, out, "insured_ledger.png")


# ── 13. Where the data stop ────────────────────────────────────────────────


def insured_old_ages(con, out: Path) -> Path:
    fig, axes = _panels(2, figsize=(11.5, 6.0), top=0.76)
    cases = (
        ("term_traditional", "Traditional term, men"),
        ("permanent", "Whole life and endowment, men"),
    )
    for ax, (segment, title) in zip(axes, cases, strict=True):
        p = _query(
            con,
            "SELECT age, ratio_population r FROM insured_pooled "
            f"WHERE segment = '{segment}' AND sex = 'M' AND age BETWEEN 20 AND 95",
        )
        t = _table(con, segment)
        t = t[(t["sex"] == "M") & t["age"].between(20, 100)]
        solid, dotted = _split(t)
        ax.axvspan(solid["age"].max(), 100, color=GRID, alpha=0.5, lw=0)
        ax.scatter(p["age"], p["r"], s=11, color=GREEN, alpha=0.4, lw=0)
        ax.plot(solid["age"], solid["ratio_population"], color=GREEN, lw=2.6)
        ax.plot(dotted["age"], dotted["ratio_population"], color=GREEN, lw=2.0, ls=(0, (1, 2)))
        ax.axhline(1.0, color=INK_2, lw=0.8)
        ax.set_ylim(0, 1.15)
        ax.set_xlim(20, 100)
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax.set_xlabel("Age")
        ax.text(21, 1.03, "same as the population", fontsize=8.5, color=INK_2)
        if segment == "term_traditional":
            ax.set_ylabel("Insured mortality as a share of the population's")
            ax.text(
                solid["age"].max() + 1.5,
                0.5,
                "extended by assumption:\nthe gap closes to zero\nby age 105",
                fontsize=8.5,
                color=INK_2,
            )
    _headline(
        fig,
        "Above the sixties the insured data are not a safe guide, so the table follows the population",
        "Dots: raw insured rate as a share of the population's, by age. Where it is steady the line "
        "follows the data. Past the last credible age (a term runs out; few, unrepresentative lives "
        "remain) the raw rates imply insured men dying at a third of Sweden's rate, which no group "
        "of Mexicans plausibly does, so the gap to the population is closed gradually (a judgement).",
        SOURCE,
    )
    return _save(fig, out, "insured_old_ages.png")


# ── 14. The stress test ────────────────────────────────────────────────────


def insured_stress(con, out: Path) -> Path:
    s = _query(
        con,
        "SELECT kind, dampening, extra_pct FROM stress_pandemic_book "
        "WHERE (year = 2021 AND kind IN ('replay', 'observed')) OR kind = 'regulatory'",
    )

    def pick(kind, dampening=None):
        part = s[s["kind"] == kind]
        if dampening is not None:
            part = part[part["dampening"] == dampening]
        return float(part["extra_pct"].iloc[0]) * 100

    bars = [
        ("The population's excess,\ninsured lives at half of it", pick("replay", 0.5), MUTED),
        ("The population's excess,\ninsured lives like everyone", pick("replay", 1.0), INK_2),
        ("The regulator's 99.5th\npercentile table", pick("regulatory"), BLUE),
        ("2021 as insured lives\nlived it", pick("observed"), GREEN),
    ]
    fig, ax = plt.subplots(figsize=(11, 6.0))
    fig.subplots_adjust(top=0.77, bottom=0.17, left=0.09, right=0.97)
    x = np.arange(len(bars))
    ax.bar(x, [b[1] for b in bars], 0.58, color=[b[2] for b in bars])
    for xi, (_, v, _) in zip(x, bars, strict=True):
        ax.text(xi, v + 2.5, f"+{v:.0f}%", ha="center", fontsize=12, fontweight="bold", color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([b[0] for b in bars], fontsize=10)
    ax.set_ylabel("Extra claims in the next 12 months (%)")
    ax.set_ylim(0, max(b[1] for b in bars) * 1.18)
    ax.axhline(pick("regulatory"), color=BLUE, lw=1, ls=(0, (4, 3)), alpha=0.6, zorder=0)
    _headline(
        fig,
        f"The regulator's stress covers {bars[2][1]:.0f}%; 2021 as insured lives lived it added {bars[3][1]:.0f}%",
        "Extra claims of the synthetic in-force book (MXN 742 million of expected claims) when 2021 is "
        "replayed. The first two bars assume insured lives are exposed to half or all of the "
        "population's excess; the last uses the insured lives' own death rates by age band.",
        "Source: CNSF Vida Individual 2021-25, INEGI/CONAPO excess mortality, synthetic book · Mortality Table Builder v2",
    )
    return _save(fig, out, "insured_stress.png")


FIGURES: tuple = (
    insured_hero,
    insured_gap,
    insured_products,
    insured_premiums,
    insured_countries,
    insured_matches,
    insured_pandemic,
    insured_relativities,
    insured_amount,
    insured_tornado,
    insured_causes,
    insured_ledger,
    insured_old_ages,
    insured_stress,
)
