"""Mexico's mortality: the life tables, the benchmarks and the states."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import ui

from mortality import export

ui.header(
    "Mexico's mortality",
    "The tables rebuilt from registered deaths and the population, against the official ones.",
    "Every price, reserve and capital figure downstream starts from a mortality table. If the "
    "table is a decade old, or wrong for the population it is used on, so is everything built on it.",
)

summary = ui.table("life_summary")
years = sorted(int(y) for y in summary["year"].unique())
tab_table, tab_bench, tab_time, tab_states, tab_method = st.tabs(
    ["Life table", "Against the benchmarks", "Over time", "The states", "How it was built"]
)

# ── Life table ──────────────────────────────────────────────────────────────
with tab_table:
    c1, c2, _ = st.columns([1, 1, 2])
    year = c1.selectbox("Year", years[::-1], index=years[::-1].index(2023) if 2023 in years else 0)
    sex = c2.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True)
    row = summary[(summary["year"] == year) & (summary["sex"] == sex)].iloc[0]
    ui.metric_row(
        [
            ("Life expectancy at birth", f"{row['e0']:.1f} years", None),
            ("Life expectancy at 65", f"{row['e65']:.1f} years", None),
            ("Chance of dying 15 to 60", f"{row['q45_15']:.0%}", None),
            ("Reach 80", f"{row['survive_to_80']:.0%}", None),
            (
                "Lifespan disparity",
                f"{row['lifespan_disparity']:.1f} years",
                "smaller = more equal",
            ),
        ]
    )
    lt = ui.sql("SELECT * FROM life_tables WHERE year = ? AND sex = ? ORDER BY age", (year, sex))
    grad = ui.sql("SELECT * FROM graduated_qx WHERE year = ? AND sex = ? ORDER BY age", (year, sex))
    base, low, high = ui.cnsf_curve("base"), ui.cnsf_curve("p0.05"), ui.cnsf_curve("p99.5")
    ages = np.arange(0, 111)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ages, y=high, line={"width": 0}, hoverinfo="skip", showlegend=False))
    fig.add_trace(
        go.Scatter(x=ages, y=low, fill="tonexty", fillcolor="rgba(154,153,143,0.25)",
                   line={"width": 0}, name="CNSF 2013 range (p0.05 to p99.5)", hoverinfo="skip")
    )  # fmt: skip
    fig.add_trace(go.Scatter(x=ages, y=base, name="CNSF 2013 (regulatory)",
                             line={"color": ui.MUTED, "width": 2, "dash": "dash"}))  # fmt: skip
    fig.add_trace(go.Scatter(x=grad["age"], y=grad["qx"], name=f"Mexico {year}, graduated",
                             line={"color": ui.SEX_COLOR[sex], "width": 3}))  # fmt: skip
    fig.update_yaxes(type="log", title="Probability of dying within a year (log scale)")
    fig.update_xaxes(title="Age")
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 440), key="qx")
    ratio = grad.set_index("age")["qx"].reindex(range(18, 91)) / base[18:91]
    st.caption(
        f"Between 18 and 90 the Mexican {ui.SEX_NAME[sex].lower()} of {year} die at "
        f"**{ratio.median():.1f} times** the median CNSF 2013 rate (peak {ratio.max():.1f} times at age "
        f"{int(ratio.idxmax())}). The CNSF table is mixed-sex, so it is far too light for men and "
        "much closer for women."
    )
    left, right = st.columns(2)
    with left:
        f2 = go.Figure(go.Scatter(x=lt["age"], y=lt["lx"] / 1000, fill="tozeroy",
                                  line={"color": ui.SEX_COLOR[sex]}, fillcolor="rgba(42,120,214,0.15)"))  # fmt: skip
        f2.update_yaxes(title="Alive out of 100 (survivors)", range=[0, 100])
        f2.update_xaxes(title="Age")
        ui.show(ui.style(f2, 330, False), key="lx")
    with right:
        f3 = go.Figure(
            go.Scatter(x=lt["age"], y=lt["ex"], line={"color": ui.SEX_COLOR[sex], "width": 3})
        )
        f3.update_yaxes(title="Years of life still to live")
        f3.update_xaxes(title="Age")
        ui.show(ui.style(f3, 330, False), key="ex")
    cols = ["age", "qx", "lx", "dx", "ex"]
    with st.expander("The table itself"):
        st.dataframe(lt[cols].round(5), hide_index=True, height=300)
        ui.download(lt[cols], f"life_table_{sex}_{year}.csv")
    st.download_button(
        "Download the Excel workbook with live commutation formulas",
        export.workbook_bytes(ui.connection()),
        file_name="Mortality_Table_Builder.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/table_view:",
        help="Dx, Nx, Mx as Excel formulas driven by one interest cell, and a premium calculator.",
    )
    ui.source_note(["life_tables", "graduated_qx", "cnsf_rates", "life_summary"], "life-tables.md")

# ── Benchmarks ──────────────────────────────────────────────────────────────
with tab_bench:
    st.markdown(
        "**Actual-to-expected ratio** of the Mexican population's deaths against each table that "
        "has been used in Mexico, ages 25 to 84. Above 1 means people die *faster* than the table says."
    )
    ae = ui.sql(
        "SELECT * FROM benchmark_ae WHERE age_group = '25-84' ORDER BY benchmark, sex, year"
    )
    year_b = st.select_slider("Year", sorted(ae["year"].unique()), value=2019)
    cut = ae[ae["year"] == year_b].copy()
    cut["label"] = cut["benchmark"].str.replace(r" \(.*\)", "", regex=True)
    fig = go.Figure()
    for sex_key in ("M", "F"):
        part = cut[cut["sex"] == sex_key].sort_values("ae")
        fig.add_trace(
            go.Bar(y=part["label"], x=part["ae"], orientation="h", name=ui.SEX_NAME[sex_key],
                   marker_color=ui.SEX_COLOR[sex_key],
                   error_x={"type": "data", "symmetric": False, "array": part["ae_upper"] - part["ae"],
                            "arrayminus": part["ae"] - part["ae_lower"], "color": ui.INK_2}))  # fmt: skip
    fig.add_vline(x=1.0, line_color=ui.INK, line_width=1)
    fig.update_layout(barmode="group")
    fig.update_xaxes(title="Actual deaths / expected deaths")
    ui.show(ui.style(fig, 520), key="ae")
    st.caption(
        "Tables built from insured lives (CNSF 2000-I, Experiencia Mexicana) sit well below the "
        "population, which is what selection by underwriting should do. The pension tables (EMSSA) "
        "and the 2013 regulatory table are the closest. Bars show 95% intervals."
    )
    ui.source_note(["benchmark_ae"], "crude-rates.md")

# ── Over time ───────────────────────────────────────────────────────────────
with tab_time:
    co = ui.sql(
        "SELECT year, sex, e0, is_projection FROM conapo_life_expectancy WHERE state_code = 0 "
        "AND sex IN ('M', 'F') ORDER BY year"
    )
    fig = go.Figure()
    for sex_key in ("M", "F"):
        part = co[co["sex"] == sex_key]
        obs = part[part["is_projection"] == 0]
        proj = part[part["is_projection"] == 1]
        fig.add_trace(go.Scatter(x=obs["year"], y=obs["e0"], name=f"{ui.SEX_NAME[sex_key]}, CONAPO",
                                 line={"color": ui.SEX_COLOR[sex_key], "width": 2.5}))  # fmt: skip
        fig.add_trace(go.Scatter(x=proj["year"], y=proj["e0"], name=f"{ui.SEX_NAME[sex_key]}, CONAPO projection",
                                 line={"color": ui.SEX_COLOR[sex_key], "width": 2, "dash": "dot"}))  # fmt: skip
        mine = summary[summary["sex"] == sex_key]
        fig.add_trace(go.Scatter(x=mine["year"], y=mine["e0"], mode="markers+lines",
                                 name=f"{ui.SEX_NAME[sex_key]}, this project (INEGI)",
                                 marker={"size": 9, "symbol": "diamond", "color": ui.SEX_COLOR[sex_key],
                                         "line": {"color": "white", "width": 1}},
                                 line={"color": ui.SEX_COLOR[sex_key], "width": 1}))  # fmt: skip
    fig.add_vrect(x0=2019.5, x1=2022.5, fillcolor=ui.ORANGE, opacity=0.08, line_width=0,
                  annotation_text="COVID-19", annotation_position="top left")  # fmt: skip
    fig.update_yaxes(title="Life expectancy at birth (years)")
    fig.update_xaxes(range=[1950, 2070])
    ui.show(ui.style(fig, 460), key="e0")
    st.caption(
        "Life expectancy rose for seventy years, fell sharply in 2020 and 2021 (by about six years "
        "for men, depending on the source) and had largely recovered by 2023. Diamonds are this "
        "project's own tables from INEGI deaths; the lines are CONAPO's official series."
    )
    ui.source_note(["conapo_life_expectancy", "life_summary"], "life-tables.md")

# ── States ──────────────────────────────────────────────────────────────────
with tab_states:
    smr = ui.table("state_smr").set_index("state")
    names = smr["state_name"]
    metric = st.radio(
        "Show", ["Standardized mortality ratio", "Excess mortality 2020 to 2022"], horizontal=True
    )
    if metric.startswith("Standardized"):
        fig = ui.tile_map(smr["smr"], names, "SMR", fmt=".2f", mid=1.0,
                          colorscale=[[0, ui.AQUA], [0.5, "#f1f0ec"], [1, ui.ORANGE]])  # fmt: skip
        ui.show(fig, key="smr")
        hi, lo = smr["smr"].idxmax(), smr["smr"].idxmin()
        st.caption(
            f"Mortality after removing the effect of each state's age structure, against the national "
            f"rate (1.00). **{names[hi]}** dies {smr.loc[hi, 'smr'] - 1:.0%} faster than its ages predict; "
            f"**{names[lo]}** {1 - smr.loc[lo, 'smr']:.0%} slower. Year {int(smr['year'].iloc[0])}."
        )
    else:
        ex = ui.sql(
            "SELECT state, state_name, SUM(observed) o, SUM(expected) e FROM excess_state "
            "WHERE year BETWEEN 2020 AND 2022 GROUP BY state, state_name"
        ).set_index("state")
        ex["p"] = ex["o"] / ex["e"] - 1
        fig = ui.tile_map(ex["p"], ex["state_name"], "Excess", fmt=".0%")
        ui.show(fig, key="exc")
        st.caption(
            "Deaths above what each state's own 2023 mortality predicts, as a share of expected."
        )
    st.caption("Each square is a state, laid out roughly where it is on the map.")
    ui.source_note(["state_smr", "excess_state"], "crude-rates.md")

# ── Methods ─────────────────────────────────────────────────────────────────
with tab_method:
    st.markdown(
        "Raw death rates are jagged: at some ages a few hundred deaths decide the value. The pipeline "
        "**completes** late registrations (chain ladder), then **graduates** the rates with a "
        "penalized spline chosen by a dispersion-corrected information criterion, and closes the "
        "old ages with a Kannisto model."
    )
    c1, c2 = st.columns(2)
    year_m = c1.selectbox("Year", years[::-1], key="gy")
    sex_m = c2.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="gs")
    crude = ui.sql(
        "SELECT * FROM crude_rates_single WHERE year = ? AND sex = ? ORDER BY age", (year_m, sex_m)
    )
    grad = ui.sql(
        "SELECT * FROM graduated_qx WHERE year = ? AND sex = ? ORDER BY age", (year_m, sex_m)
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=grad["age"], y=grad["mx_upper"], line={"width": 0}, hoverinfo="skip", showlegend=False
        )
    )
    fig.add_trace(go.Scatter(x=grad["age"], y=grad["mx_lower"], fill="tonexty", line={"width": 0},
                             fillcolor="rgba(42,120,214,0.18)", name="95% interval", hoverinfo="skip"))  # fmt: skip
    fig.add_trace(go.Scatter(x=crude["age"], y=crude["mx"], mode="markers", name="Crude rate",
                             marker={"size": 5, "color": ui.MUTED}))  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=grad["age"],
            y=grad["mx"],
            name="Graduated",
            line={"color": ui.SEX_COLOR[sex_m], "width": 3},
        )
    )
    fig.update_yaxes(type="log", title="Central death rate (log scale)")
    fig.update_xaxes(title="Age")
    ui.show(ui.style(fig, 440), key="grad")
    st.caption(
        "Gray dots are the crude rates; the line is the graduated table that feeds every later step. "
        "Digit preference (more deaths reported at ages ending in 0 and 5 among men) is detected and "
        "smoothed away, and the crude old-age sex crossover from about age 88, a sign of age "
        "exaggeration, is corrected."
    )
    ui.source_note(["crude_rates_single", "graduated_qx"], "graduation.md")
