"""Insured lives: the mortality table built from the CNSF industry statistics, for pricing quotes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import ui

GREEN, VIOLET, ORANGE_TEXT = "#0b8a5c", "#7a52c7", "#b34a1d"
LABELS = {
    "term_traditional": "Term, traditional (the standard quote)",
    "all": "All individual life (the market, as a blend of products)",
    "term": "Term, all modalities",
    "credit": "Term, credit life",
    "permanent": "Whole life and endowment",
    "term_other": "Term, other modalities",
}

ui.header(
    "Insured lives",
    "A mortality table for pricing quotes, built from what insurers actually experienced.",
    "The population table tells you how long Mexicans live. A quote is for someone who buys life "
    "insurance: wealthier, underwritten, mostly urban. In Mexico that group dies at one fifth to "
    "one seventh the population's rate, so the right table is not the population's, and not the "
    "regulator's either.",
)

tables = set(ui.sql("SELECT name FROM sqlite_master WHERE type = 'table'")["name"])
if "insured_table" not in tables:
    st.info(
        "The insured-lives tables are not in this data bundle. Run `uv run mortality app-data`."
    )
    st.stop()

t_table, t_quote, t_price, t_prod, t_event, t_built = st.tabs(
    [
        "The table",
        "A quote",
        "What moves the price",
        "Products and sizes",
        "Pandemic and causes",
        "How it was built",
    ]
)

# ── The table ───────────────────────────────────────────────────────────────
with t_table:
    c1, c2, _ = st.columns([2, 1, 1])
    segment = c1.selectbox("Product", list(LABELS), format_func=LABELS.get, key="seg")
    sex = c2.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="sex")
    t = ui.sql(
        "SELECT * FROM insured_table WHERE segment = ? AND sex = ? ORDER BY age", (segment, sex)
    )
    pooled = ui.sql(
        "SELECT age, rate FROM insured_pooled WHERE segment = ? AND sex = ? AND deaths >= 5 "
        "AND age BETWEEN 20 AND 90",
        (segment, sex),
    )
    r40 = t[t["age"] == 40].iloc[0]
    last = int(t.loc[t["source"] != "extended", "age"].max())
    ui.metric_row(
        [
            ("Death rate at 40", f"{r40['qx'] * 1000:.2f} per 1,000", None),
            ("Population", f"{r40['q_population'] * 1000:.2f} per 1,000", None),
            ("CNSF 2013", f"{r40['q_cnsf2013'] * 1000:.2f} per 1,000", None),
            ("Share of the population's rate", f"{r40['ratio_population']:.0%}", None),
            ("Data support the table up to", f"age {last}", None),
        ]
    )
    solid, dotted = t[t["age"] <= last], t[t["age"] >= last]
    fig = go.Figure()
    band = solid.dropna(subset=["qx_lower"])
    fig.add_trace(go.Scatter(x=band["age"], y=band["qx_upper"], line={"width": 0},
                             hoverinfo="skip", showlegend=False))  # fmt: skip
    fig.add_trace(go.Scatter(x=band["age"], y=band["qx_lower"], fill="tonexty", line={"width": 0},
                             fillcolor=ui.rgba(GREEN, 0.2), name="95% interval", hoverinfo="skip"))  # fmt: skip
    fig.add_trace(go.Scatter(x=t["age"], y=t["q_population"], name="Population 2023",
                             line={"color": ui.INK, "width": 2}))  # fmt: skip
    fig.add_trace(go.Scatter(x=t["age"], y=t["q_cnsf2013"], name="CNSF 2013 (regulator)",
                             line={"color": ui.MUTED, "width": 2, "dash": "dash"}))  # fmt: skip
    fig.add_trace(go.Scatter(x=pooled["age"], y=pooled["rate"], mode="markers", name="Raw rates, 2023-25",
                             marker={"size": 5, "color": ui.rgba(GREEN, 0.4)}))  # fmt: skip
    fig.add_trace(go.Scatter(x=solid["age"], y=solid["qx"], name="Insured table",
                             line={"color": GREEN, "width": 3}))  # fmt: skip
    fig.add_trace(go.Scatter(x=dotted["age"], y=dotted["qx"], name="Extended by assumption",
                             line={"color": GREEN, "width": 2.5, "dash": "dot"}))  # fmt: skip
    fig.add_vrect(x0=last, x1=110, fillcolor=ui.GRID, opacity=0.35, line_width=0)
    fig.update_yaxes(type="log", title="Probability of dying within a year (log scale)",
                     range=[np.log10(5e-5), np.log10(1.2)])  # fmt: skip
    fig.update_xaxes(title="Age", range=[18, 110])
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 470), key="insured_curve")
    st.caption(
        f"Green: the {LABELS[segment].split(' (')[0].lower()} table for "
        f"{ui.SEX_NAME[sex].lower()}. Dots are the raw rates it was fitted to. Past age {last} the "
        "insured data stop being a safe guide, so the table follows the population's shape and the "
        "gap closes to zero by 105: a judgement, set out in the write-up."
    )
    cols = ["age", "qx", "qx_lower", "qx_upper", "source", "q_population", "q_cnsf2013"]
    with st.expander("The table itself"):
        st.dataframe(t[cols].round(6), hide_index=True, height=300)
        ui.download(t[cols], f"insured_{segment}_{sex}.csv")
    ui.source_note(["insured_table", "insured_pooled"], "insured-lives.md")

# ── A quote ─────────────────────────────────────────────────────────────────
with t_quote:
    prem = ui.sql("SELECT * FROM insured_premiums")
    margin = ui.sql("SELECT recommended_margin FROM insured_margin LIMIT 1")
    loading = float(margin["recommended_margin"].iloc[0]) if len(margin) else 0.15
    c1, c2, c3 = st.columns(3)
    sex_q = c1.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="qs")
    ages = sorted(prem["issue_age"].unique())
    age_q = c2.select_slider("Issue age", ages, value=40)
    term_q = c3.radio("Term (years)", sorted(prem["term"].unique()), index=1, horizontal=True)
    cut = prem[(prem["sex"] == sex_q) & (prem["issue_age"] == age_q) & (prem["term"] == term_q)]
    cut = cut.sort_values("premium_per_1000")
    names = cut["table"].str.replace("Mexico insured: ", "Insured: ", regex=False)
    colors = [
        GREEN if t.startswith("Mexico insured") else VIOLET if t.startswith("US") else
        ui.INK if t.startswith("Mexico population") else ui.MUTED
        for t in cut["table"]
    ]  # fmt: skip
    fig = go.Figure(go.Bar(y=names, x=cut["premium_per_1000"], orientation="h", marker_color=colors,
                           text=[f"{v:.2f}" for v in cut["premium_per_1000"]], textposition="outside"))  # fmt: skip
    fig.update_xaxes(title="Net annual premium per 1,000 insured", type="log")
    fig.update_yaxes(automargin=True)
    ui.show(ui.style(fig, 430, False), key="quote")
    std = cut[cut["table"] == "Mexico insured: Term, traditional"]["premium_per_1000"]
    cn = cut[cut["table"] == "CNSF 2013"]["premium_per_1000"]
    if len(std) and len(cn):
        st.markdown(
            f"For this quote the standard insured table gives **{std.iloc[0]:.2f}** per 1,000, "
            f"**{std.iloc[0] * (1 + loading):.2f}** with the recommended {loading:.0%} margin, "
            f"against **{cn.iloc[0]:.2f}** on the regulator's table: "
            f"**{1 - std.iloc[0] * (1 + loading) / cn.iloc[0]:.0%} lower** even with the margin."
        )
    st.caption(
        "Net premium of a level term cover at 4% interest: the cost of mortality alone, without "
        "expenses, commission or profit. Which table is used matters more than any modelling "
        "choice behind it (next tab)."
    )
    ui.source_note(["insured_premiums", "insured_margin"], "insured-lives.md")

# ── What moves the price ────────────────────────────────────────────────────
with t_price:
    sens = ui.sql("SELECT * FROM insured_sensitivity")
    refs = sens[["sex", "issue_age", "term"]].drop_duplicates()
    options = {
        f"{ui.SEX_NAME[r.sex]} of {r.issue_age}, {r.term}-year term": r for r in refs.itertuples()
    }
    pick = st.selectbox("Reference policy", list(options))
    ref = options[pick]
    s = sens[
        (sens["sex"] == ref.sex) & (sens["issue_age"] == ref.issue_age) & (sens["term"] == ref.term)
    ]
    s = s[(s["choice"] != "Base table") & (s["change_vs_base"].abs() > 0.0005)].sort_values(
        "change_vs_base"
    )
    label = s["choice"] + ": " + s["alternative"]
    fig = go.Figure(go.Bar(y=label, x=s["change_vs_base"] * 100, orientation="h",
                           marker_color=[ui.ORANGE if v > 0 else ui.BLUE for v in s["change_vs_base"]],
                           text=[f"{v:+.1f}%" for v in s["change_vs_base"] * 100], textposition="outside"))  # fmt: skip
    fig.update_xaxes(title="Change in the net premium (%)")
    fig.update_yaxes(automargin=True)
    ui.show(ui.style(fig, 520, False), key="tornado")
    m = ui.sql("SELECT * FROM insured_margin")
    if len(m):
        row = m[(m["sex"] == ref.sex) & (m["issue_age"] == ref.issue_age) & (m["term"] == ref.term)]
        if len(row):
            st.markdown(
                f"The adverse readings that cannot be ruled out (the no-detail claim rows that "
                f"look like new claims, and lives exposed part of the year) add **"
                f"{row['quadrature_margin'].iloc[0]:.1%}** to this premium in quadrature. The "
                f"recommended margin for adverse deviation is **{row['recommended_margin'].iloc[0]:.0%}**."
            )
    st.caption(
        "Each choice between the CNSF statistics and a table is changed one at a time, the table is "
        "rebuilt with the same code and the premium recomputed. Orange raises the premium, blue lowers it."
    )
    ui.source_note(["insured_sensitivity", "insured_margin"], "insured-lives.md")

# ── Products and sizes ──────────────────────────────────────────────────────
with t_prod:
    sex_p = st.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="ps")
    rel = ui.sql(
        "SELECT * FROM insured_relativities WHERE sex = ? AND segment <> 'term_traditional' "
        "AND ages IN ('25-44', '45-65')",
        (sex_p,),
    )
    names = {"credit": "Credit life (term)", "term_other": "Other term modalities",
             "permanent": "Whole life and endowment"}  # fmt: skip
    fig = go.Figure()
    for ages, color in (("25-44", GREEN), ("45-65", VIOLET)):
        d = rel[rel["ages"] == ages]
        fig.add_trace(go.Scatter(
            x=d["k"], y=d["segment"].map(names), mode="markers", name=f"Ages {ages}",
            marker={"size": 10, "color": color},
            error_x={"type": "data", "symmetric": False, "array": d["upper"] - d["k"],
                     "arrayminus": d["k"] - d["lower"], "color": color},
        ))  # fmt: skip
    fig.add_vline(x=1.0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(title="Mortality relative to traditional term (95% interval)", type="log")
    ui.show(ui.style(fig, 340), key="rel")
    st.caption(
        "The multiplier of the traditional-term table that matches each product's deaths. The gap "
        "widens with age."
    )
    amt = ui.sql("SELECT * FROM insured_amount WHERE sex = ?", (sex_p,))
    seg_names = {"term_traditional": "Traditional term", "credit": "Credit life",
                 "permanent": "Whole life and endowment", "all": "All products"}  # fmt: skip
    fig = go.Figure()
    for seg, color in (
        ("term_traditional", GREEN),
        ("credit", ui.ORANGE),
        ("permanent", VIOLET),
        ("all", ui.INK),
    ):
        d = amt[amt["segment"] == seg].sort_values("decade")
        fig.add_trace(go.Scatter(x=d["decade"] + 5, y=d["amount_to_count_ratio"], mode="lines+markers",
                                 name=seg_names[seg], line={"color": color, "width": 2.5}))  # fmt: skip
    fig.add_hline(y=1.0, line_color=ui.INK_2, line_width=1)
    fig.update_xaxes(title="Age (decade midpoint)")
    fig.update_yaxes(title="Death rate by sum assured / by count")
    ui.show(ui.style(fig, 380), key="amount")
    st.caption(
        "Above 1, larger policies die more: per peso of cover, traditional term costs more than its "
        "death count suggests. Credit-life claims settle a loan balance, far below the original sum."
    )
    ui.source_note(["insured_relativities", "insured_amount"], "insured-lives.md")

# ── Pandemic and causes ─────────────────────────────────────────────────────
with t_event:
    pan = ui.sql("SELECT * FROM insured_pandemic")
    g = pan.groupby(["source", "year", "band"])[["deaths", "exposure"]].sum().reset_index()
    g["rate"] = g["deaths"] / g["exposure"]
    base = g[g["year"] == 2023].set_index(["source", "band"])["rate"]
    g["index"] = [r.rate / base[(r.source, r.band)] for r in g.itertuples()]
    band = st.radio("Ages", ["25-44", "45-64", "65-79"], index=1, horizontal=True)
    fig = go.Figure()
    for source, color, name in (
        ("population", ui.INK, "Population"),
        ("insured", GREEN, "Insured lives"),
    ):
        d = g[(g["source"] == source) & (g["band"] == band)].sort_values("year")
        fig.add_trace(go.Scatter(x=d["year"], y=d["index"], mode="lines+markers", name=name,
                                 line={"color": color, "width": 3}))  # fmt: skip
    fig.add_hline(y=1.0, line_color=ui.INK_2, line_width=1)
    fig.update_yaxes(title="Death rate relative to 2023")
    ui.show(ui.style(fig, 360), key="pan")
    peak = g[(g["source"] == "insured") & (g["band"] == band) & (g["year"] == 2021)]["index"].iloc[
        0
    ]
    st.caption(
        f"In 2021 insured death rates at ages {band} were {peak:.1f} times their 2023 level. "
        "Insured mortality is so low that an absolute excess about half the population's is a "
        "bigger jump in relative terms: a stress test that assumed insured lives are shielded would "
        "have been wrong."
    )
    cz = ui.sql("SELECT sex, \"group\" AS grp, SUM(deaths) AS deaths FROM insured_causes "
                "WHERE year IN (2023, 2024, 2025) GROUP BY sex, \"group\"")  # fmt: skip
    sex_c = st.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="cs")
    d = cz[(cz["sex"] == sex_c) & (cz["grp"] != "not_a_cause_of_death")].copy()
    d["share"] = d["deaths"] / d["deaths"].sum()
    d = d.sort_values("share")
    fig = go.Figure(go.Bar(y=d["grp"].str.replace("_", " "), x=d["share"] * 100, orientation="h",
                           marker_color=GREEN, text=[f"{v:.0f}%" for v in d["share"] * 100],
                           textposition="outside"))  # fmt: skip
    fig.update_xaxes(title="Share of death claims, 2023-25 (%)")
    ui.show(ui.style(fig, 430, False), key="causes")
    st.caption(
        "Grouped by keyword from the text of the claim's cause. The field mixes underlying and "
        "immediate causes, so it shows a pattern, not an exact cause-of-death statistic."
    )
    ui.source_note(["insured_pandemic", "insured_causes"], "insured-lives.md")

# ── How it was built ────────────────────────────────────────────────────────
with t_built:
    st.markdown(
        "**Three things in the data would have gone wrong silently.**\n\n"
        "1. **One death-claim row in five has no age or sex, and they are not deaths.** "
        "Cancellations outweigh new claims every year; the count stays flat while real deaths halve; "
        "COVID causes appear years after the pandemic. They are an adjustment ledger.\n"
        "2. **About 2,300 claims blamed on a sprained ankle are endowment maturities** booked under "
        "the death cover: ages 60 to 69, 3.6 times a normal claim, savings-type plans.\n"
        "3. **Deaths and exposure must refer to the same cover.** The exposure sheet counts every "
        "insured life; deaths are counted against the lives that hold the death cover.\n\n"
        "**Then a table family, not a table:** mortality differs 2 to 4 times between products, so "
        "traditional term, credit life and whole life are graduated on their own and the market "
        "table is a blend of them."
    )
    led = ui.sql("SELECT * FROM insured_ledger")
    years = sorted(led["year"].unique())
    pick = lambda b, s: [  # noqa: E731
        float(led[(led["year"] == y) & (led["block"] == b) & (led["sign"] == s)]["claims"].sum())
        for y in years
    ]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=pick("known", "positive"),
            name="With age and sex (the deaths)",
            marker_color=GREEN,
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=pick("no_detail", "positive"),
            name="No age or sex: new claims",
            marker_color=ui.MUTED,
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=[-v for v in pick("no_detail", "negative")],
            name="No age or sex: cancellations",
            marker_color=ui.ORANGE,
        )
    )
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="Death-claim rows")
    ui.show(ui.style(fig, 380), key="ledger")
    mix = (
        ui.sql("SELECT year, sex, share FROM insured_legacy_mix")
        if "insured_legacy_mix" in tables
        else pd.DataFrame()
    )
    if len(mix):
        women = mix[mix["sex"] == "F"].set_index("year")["share"]
        st.markdown(
            "**Why 2018 to 2020 are not pooled:** the older format's share of women moves from "
            + ", ".join(f"{v:.0%} ({y})" for y, v in women.items())
            + " in a year, which no real portfolio does, and its rates swing by 30% between "
            "pre-pandemic years. It stays as a cross-check."
        )
    st.link_button(
        "Read the full write-up, with every decision and what it costs",
        f"{ui.REPO}/blob/main/docs/insured-lives.md",
        icon=":material/menu_book:",
    )
    ui.source_note(["insured_ledger", "insured_legacy_mix"], "insured-lives.md")
