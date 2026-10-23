"""The pandemic: excess mortality in Mexico, 2020 to 2022."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
import ui

ui.header(
    "The pandemic",
    "How many more people died than would have, who they were, and where, with the uncertainty shown.",
    "Excess mortality is the honest measure of a pandemic's toll, because certification of causes "
    "is incomplete. It is also the shock every life insurer, annuity writer and reinsurer has to "
    "stress-test against.",
)

summary = ui.sql(
    "SELECT * FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2022"
).set_index("year")
tot, lo, hi = summary["excess"].sum(), summary["excess_low"].sum(), summary["excess_high"].sum()
covid = summary["covid_coded"].sum()
yll = ui.sql(
    "SELECT SUM(years_lost) y FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2022"
)["y"].iloc[0]
ui.metric_row(
    [
        (
            "Excess deaths 2020 to 2022",
            f"{tot:,.0f}",
            f"range {lo / 1000:,.0f}k to {hi / 1000:,.0f}k",
        ),
        ("Per certified COVID-19 death", f"{tot / covid:.2f}", f"{covid:,.0f} certified"),
        ("Years of life lost", f"{yll / 1e6:.1f} million", f"{yll / tot:.1f} per excess death"),
        ("Peak P-score (2021)", f"{summary.loc[2021, 'p_score']:.0%}", "deaths above expected"),
    ]
)

tab_waves, tab_base, tab_age, tab_cause, tab_state = st.tabs(
    ["Waves", "Four baselines", "Who died", "Of what", "Where"]
)

with tab_waves:
    m = ui.sql("SELECT * FROM excess_monthly ORDER BY year, month")
    m["x"] = m["year"] + (m["month"] - 0.5) / 12
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=m["x"], y=m["baseline"] / 1000, name="Expected (baseline)",
                             line={"color": ui.INK_2, "width": 2, "dash": "dash"}))  # fmt: skip
    fig.add_trace(go.Scatter(x=m["x"], y=m["deaths"] / 1000, name="All deaths", fill="tonexty",
                             fillcolor=ui.rgba(ui.ORANGE, 0.3), line={"color": ui.INK, "width": 2.5}))  # fmt: skip
    fig.add_trace(go.Scatter(x=m["x"], y=m["covid_deaths"] / 1000, name="Certified as COVID-19",
                             line={"color": ui.BLUE, "width": 2}, fill="tozeroy",
                             fillcolor=ui.rgba(ui.BLUE, 0.25)))  # fmt: skip
    fig.update_yaxes(title="Deaths per month (thousands)")
    fig.update_xaxes(range=[2020, 2025], dtick=1)
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 450), key="waves")
    peak = m.loc[m["deaths"].idxmax()]
    st.caption(
        f"The orange gap is excess. The worst month, {int(peak['year'])}-{int(peak['month']):02d}, had "
        f"{peak['deaths']:,.0f} deaths against about {peak['baseline']:,.0f} expected. The baseline "
        "keeps the normal seasonal shape, so winter peaks are not mistaken for excess."
    )
    st.dataframe(
        summary[
            [
                "observed",
                "expected_central",
                "excess",
                "excess_low",
                "excess_high",
                "p_score",
                "covid_coded",
            ]
        ]
        .rename(
            columns={
                "expected_central": "expected",
                "excess_low": "low",
                "excess_high": "high",
                "covid_coded": "certified COVID-19",
            }
        )
        .style.format(
            {
                "observed": "{:,.0f}",
                "expected": "{:,.0f}",
                "excess": "{:,.0f}",
                "low": "{:,.0f}",
                "high": "{:,.0f}",
                "p_score": "{:.1%}",
                "certified COVID-19": "{:,.0f}",
            }
        ),
        width="stretch",
    )
    ui.source_note(["excess_monthly", "excess_summary"], "excess-mortality.md")

with tab_base:
    st.markdown(
        '"Excess" is observed minus a **counterfactual nobody observed**, so one baseline gives a '
        "number that looks more certain than it is. Four baselines, built on different assumptions, "
        "bracket it."
    )
    base = ui.sql(
        "SELECT year, method, SUM(expected) e FROM excess_baselines WHERE year BETWEEN 2020 AND 2023 "
        "GROUP BY year, method"
    )
    obs = ui.sql(
        "SELECT year, observed FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2023"
    ).set_index("year")["observed"]
    labels = {"flat_2019": "Flat 2019 rates", "trend_2014_2019": "Trend 2014 to 2019",
              "interpolation_to_2023": "Interpolation to 2023", "lee_carter": "Lee-Carter"}  # fmt: skip
    colors = [ui.BLUE, ui.ORANGE, ui.AQUA, ui.MUTED]
    fig = go.Figure()
    for (method, label), color in zip(labels.items(), colors, strict=True):
        part = base[base["method"] == method].set_index("year")
        fig.add_trace(go.Bar(x=part.index, y=part["e"] / 1000, name=label, marker_color=color))
    fig.add_trace(go.Scatter(x=obs.index, y=obs.values / 1000, mode="markers+lines", name="Observed deaths",
                             line={"color": ui.INK, "width": 2.5}, marker={"size": 10}))  # fmt: skip
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="Deaths (thousands)", range=[600, 1150])
    fig.update_xaxes(dtick=1)
    ui.show(ui.style(fig, 430), key="base")
    gap = summary["expected_high"] / summary["expected_low"] - 1
    st.caption(
        f"The baselines agree within {gap.loc[2020]:.1%} in 2020, {gap.loc[2021]:.1%} in 2021 and "
        f"{gap.loc[2022]:.1%} in 2022, and widen as they are carried further from 2019. In 2023, after the "
        "pandemic, they should match the observed deaths: they do, within about 4%, which is how we know "
        "mortality returned to trend."
    )
    ui.source_note(["excess_baselines"], "excess-mortality.md")

with tab_age:
    age = ui.table("excess_mortality")
    year = st.radio("Year", [2020, 2021, 2022], horizontal=True, index=1)
    part = age[age["year"] == year]
    fig = go.Figure()
    for sex in ("M", "F"):
        s = part[part["sex"] == sex].sort_values("band")
        fig.add_trace(
            go.Bar(
                x=s["age_group"],
                y=s["p_score"] * 100,
                name=ui.SEX_NAME[sex],
                marker_color=ui.SEX_COLOR[sex],
            )
        )
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="Deaths above expected (%)")
    fig.update_xaxes(title="Age group", type="category")
    ui.show(ui.style(fig, 430), key="age")
    s65 = part[(part["age_group"] == "65-69") & (part["sex"] == "M")]["p_score"].iloc[0]
    st.caption(
        f"In {year}, men aged 65 to 69 died at **{1 + s65:.2f} times** the expected rate. The excess "
        "is small and even negative in infants, rises through the working ages and plateaus at about "
        "two thirds above normal from 45 to 75: this age profile is what the stress tests replay."
    )
    ui.source_note(["excess_mortality"], "excess-mortality.md")

with tab_cause:
    cause = ui.table("excess_by_cause")
    cause = cause[cause["year"].between(2020, 2022)]
    pivot = cause.groupby(["label"])["excess"].sum().sort_values()
    fig = go.Figure(go.Bar(y=pivot.index, x=pivot.values, orientation="h",
                           marker_color=[ui.BLUE if v > 0 else ui.MUTED for v in pivot.values]))  # fmt: skip
    fig.update_xaxes(title="Excess deaths, 2020 to 2022")
    ui.show(ui.style(fig, 430, False), key="cause")
    top = pivot.sort_values(ascending=False)
    st.caption(
        f"{top.index[0]} accounts for {top.iloc[0] / top[top > 0].sum():.0%} of the positive excess. The rest is "
        "mostly heart disease, diabetes and respiratory causes: deaths the pandemic caused or hastened "
        "that were not certified as COVID-19. Causes are by chapter of the ICD-10; the baseline is the "
        "2023 cause structure scaled by population."
    )
    ui.source_note(["excess_by_cause"], "excess-mortality.md")

with tab_state:
    es = ui.table("excess_state")
    year_s = st.radio("Year", [2020, 2021, 2022, "2020 to 2022"], horizontal=True)
    if year_s == "2020 to 2022":
        g = es.groupby(["state", "state_name"], as_index=False)[["observed", "expected"]].sum()
    else:
        g = es[es["year"] == year_s].copy()
    g["p"] = g["observed"] / g["expected"] - 1
    g = g.set_index("state")
    ui.show(ui.tile_map(g["p"], g["state_name"], "Excess", fmt=".0%"), key="smap")
    hi_s, lo_s = g["p"].idxmax(), g["p"].idxmin()
    st.caption(
        f"{g.loc[hi_s, 'state_name']} had {g.loc[hi_s, 'p']:.0%} more deaths than its own 2023 mortality predicts; "
        f"{g.loc[lo_s, 'state_name']} {g.loc[lo_s, 'p']:.0%}. The center of the country, with the densest cities, "
        "was hit hardest."
    )
    ui.source_note(["excess_state"], "excess-mortality.md")
