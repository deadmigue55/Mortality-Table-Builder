"""The future: projections, scenarios, how wrong they were, and the cohort effect."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
import ui

ui.header(
    "The future",
    "Where Mexican mortality is heading, how uncertain that is, and how wrong forecasts used to be.",
    "A pension, an annuity or a whole-life policy is a bet on how long people live decades from now. "
    "A table that ignores future improvement underprices longevity; one that overstates it overprices.",
)

MEASURES = {"e0": "Life expectancy at birth (years)", "e65": "Life expectancy at 65 (years)",
            "a65": "Annuity at 65: present value of 1 a year (4%)"}  # fmt: skip
SCENARIOS = {
    "rebased_long_run": ("Long-run trend (Lee-Carter, since 1970)", ui.BLUE),
    "rebased_recent": ("Recent trend (last 25 years)", ui.ORANGE),
    "cbd_rebased": ("Cairns-Blake-Dowd", ui.AQUA),
    "pre_covid_trend": ("Pre-COVID trend, not rebased", ui.MUTED),
    "conapo_official": ("CONAPO official", ui.INK_2),
}  # fmt: skip

tab_fan, tab_back, tab_cohort = st.tabs(
    ["Scenarios and fan", "How wrong were we?", "Cohort vs period"]
)

with tab_fan:
    c1, c2, c3 = st.columns([1, 1, 2])
    measure = c1.selectbox("Measure", list(MEASURES), format_func=MEASURES.get, index=1)
    sex = c2.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True)
    scen = ui.sql(
        "SELECT * FROM projection_scenarios WHERE measure = ? AND sex = ?", (measure, sex)
    )
    options = [s for s in SCENARIOS if s in set(scen["scenario"])]
    shown = c3.multiselect("Scenarios", options, default=["rebased_long_run", "rebased_recent", "conapo_official"],
                           format_func=lambda s: SCENARIOS[s][0])  # fmt: skip
    fig = go.Figure()
    obs = scen[scen["scenario"] == "observed"]
    fig.add_trace(
        go.Scatter(
            x=obs["year"], y=obs["p50"], name="Observed", line={"color": ui.INK, "width": 2.5}
        )
    )
    for key in shown:
        part = scen[scen["scenario"] == key].sort_values("year")
        label, color = SCENARIOS[key]
        if part["p05"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=part["year"],
                    y=part["p95"],
                    line={"width": 0},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
            fig.add_trace(go.Scatter(x=part["year"], y=part["p05"], fill="tonexty", line={"width": 0},
                                     fillcolor=ui.rgba(color, 0.15),
                                     hoverinfo="skip", showlegend=False))  # fmt: skip
        fig.add_trace(
            go.Scatter(
                x=part["year"], y=part["p50"], name=label, line={"color": color, "width": 2.5}
            )
        )
    fig.update_yaxes(title=MEASURES[measure])
    fig.update_xaxes(range=[1950, 2070])
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 470), key="fan")
    st.caption(
        "Shaded bands are the 90% interval of the stochastic scenarios. The two Lee-Carter variants "
        "differ in what they assume about the future: that the long-run pace of improvement returns, or that "
        "the slower recent pace continues. The honest range is between them; the single biggest "
        "uncertainty in a Mexican longevity price is which one you believe."
    )
    ui.source_note(["projection_scenarios", "projected_qx"], "projection.md")

with tab_back:
    st.markdown(
        "A forecast is only as credible as its record. The model was **refitted from past dates** and "
        "scored against what really happened, 10 and 20 years ahead."
    )
    bt = ui.table("projection_backtest")
    bt["model"] = bt["model"].str.replace("_", " ")
    c1, c2 = st.columns(2)
    horizon = c1.radio("Years ahead", sorted(bt["horizon"].unique()), horizontal=True)
    quantity = c2.radio(
        "Error in",
        ["e65_error", "e0_error"],
        format_func=lambda x: (
            "life expectancy at 65" if x == "e65_error" else "life expectancy at birth"
        ),
        horizontal=True,
    )
    part = bt[bt["horizon"] == horizon]
    fig = go.Figure()
    for sex_key in ("M", "F"):
        sub = part[part["sex"] == sex_key]
        for model, grp in sub.groupby("model"):
            fig.add_trace(go.Scatter(x=grp["origin"], y=grp[quantity], mode="markers+lines",
                                     name=f"{ui.SEX_NAME[sex_key]}, {model}",
                                     line={"width": 1.5}, marker={"size": 7}))  # fmt: skip
    fig.add_hline(y=0, line_color=ui.INK, line_width=1)
    fig.update_yaxes(title="Forecast minus actual (years); positive = too optimistic")
    fig.update_xaxes(title="Year the forecast was made")
    ui.show(ui.style(fig, 430), key="bt")
    cal = ui.table("projection_calibration")
    st.caption(
        "Men's improvement slowed after 1999, so forecasts made earlier were optimistic by years. The "
        "model's own uncertainty bands covered only 40% to 60% of these outcomes, so the dashboard's "
        "fan adds an empirical band calibrated on exactly these errors "
        f"({len(cal)} calibration constants)."
    )
    ui.source_note(["projection_backtest", "projection_calibration"], "projection.md")

with tab_cohort:
    st.markdown(
        "An annuity priced on **this year's** table assumes the person who turns 65 will die at "
        "today's rates all their life. They will not: they live their 70s and 80s in the future."
    )
    cohort = ui.table("cohort_tables")
    sex_c = st.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True, key="cs")
    part = cohort[cohort["sex"] == sex_c]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=part["year_at_65"], y=part["period_a65"], name="Priced on the period table",
                             line={"color": ui.MUTED, "width": 2.5, "dash": "dash"}))  # fmt: skip
    fig.add_trace(go.Scatter(x=part["year_at_65"], y=part["cohort_a65"], name="Priced along the cohort",
                             line={"color": ui.SEX_COLOR[sex_c], "width": 3}))  # fmt: skip
    fig.update_yaxes(title="Annuity at 65 (present value of 1 a year, 4%)")
    fig.update_xaxes(title="Year the person turns 65")
    ui.show(ui.style(fig, 400), key="cohort")
    gap = part["annuity_understated_pct"]
    ui.metric_row(
        [
            (
                "Annuity understated, retiring 2025",
                f"{gap.iloc[0]:.1%}",
                "if priced on the period table",
            ),
            (
                "Annuity understated, retiring 2050",
                f"{gap[part['year_at_65'] == 2050].iloc[0]:.1%}",
                None,
            ),
            (
                "Life expectancy at 65, cohort, 2025",
                f"{part['cohort_e65'].iloc[0]:.1f} years",
                f"period {part['period_e65'].iloc[0]:.1f}",
            ),
        ]
    )
    st.caption(
        f"On a book of annuities, {gap.iloc[0]:.1%} of the reserve is the difference between a period "
        "and a cohort table."
    )
    ui.source_note(["cohort_tables"], "projection.md")
