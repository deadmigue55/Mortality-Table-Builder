"""Annuities: value a pension on eight mortality bases and stress longevity and interest."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import ui

from mortality import stress

ui.header(
    "Annuities and longevity",
    "What a pension is worth, and what moves it: mortality basis, future improvement, interest.",
    "A pension promises payments for as long as someone lives. Reserving it takes a view on how "
    "long that is, so the longevity assumption is the biggest single number on an annuity writer's "
    "balance sheet, and the one a reinsurer is asked to take over in a longevity swap.",
)

with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    sex = c1.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True)
    age = c2.slider("Age today", 55, 85, 65)
    pension = c3.select_slider(
        "Annual pension (MXN)",
        [60_000, 120_000, 240_000, 480_000],
        value=120_000,
        format_func=lambda x: f"{x:,.0f}",
    )
    rate = c4.slider("Interest rate (%)", 2.0, 7.0, 4.0, 0.25) / 100
    d1, d2 = st.columns(2)
    scale = d1.slider(
        "Future improvement in mortality (1 = central projection, 0 = none, 2 = double)",
        0.0,
        3.0,
        1.0,
        0.25,
    )
    level = d2.slider("Mortality level shock (%, permanent)", -30, 10, 0, 5) / 100

cube = ui.projection_cube(sex)
ages = np.array([age])


def apv(q_paths: np.ndarray, i: float = rate) -> float:
    return float(stress.annuity_due_from_q(q_paths, i)[0]) * pension


bases = {
    "CNSF 2013, pensions variant": stress.period_q_paths(ui.cnsf_curve("p0.05"), ages),
    "CNSF 2013": stress.period_q_paths(ui.cnsf_curve("base"), ages),
    "Mexico 2023 period table": stress.period_q_paths(ui.graduated_curve(2023, sex), ages),
    "No improvement after 2025": stress.cohort_q_paths(cube, ages, 0.0),
    "Central projection": stress.cohort_q_paths(cube, ages, 1.0),
    "Double the improvement": stress.cohort_q_paths(cube, ages, 2.0),
}
mine = stress.cohort_q_paths(cube, ages, scale, 1.0 + level)
central = apv(bases["Central projection"])
yours = apv(mine)
rows = {name: apv(q) for name, q in bases.items()}
rows["Your scenario"] = yours

ui.metric_row(
    [
        (
            "Cost of the pension for life",
            f"{yours:,.0f} MXN",
            f"{yours / pension:.1f} times the annual pension",
        ),
        (
            "Against the central projection",
            f"{yours / central - 1:+.1%}",
            f"central {central:,.0f} MXN",
        ),
        (
            "Against the regulatory pensions table",
            f"{yours / rows['CNSF 2013, pensions variant'] - 1:+.1%}",
            "regulation is more cautious",
        ),
        (
            "Expected years of payments",
            f"{float(np.sum(np.cumprod(1 - np.concatenate([[0], mine[0, :-1]])))):.1f}",
            "life expectancy of the buyer",
        ),
    ]
)

tab_bases, tab_surv, tab_block = st.tabs(
    ["One pension, many bases", "How long they live", "A whole block"]
)

with tab_bases:
    names = list(rows)
    vals = [rows[n] for n in names]
    colors = [
        ui.INK if n == "Your scenario" else ui.BLUE if n == "Central projection" else ui.MUTED
        for n in names
    ]
    fig = go.Figure(go.Bar(x=[v / 1000 for v in vals], y=names, orientation="h", marker_color=colors,
                           text=[f"{v / central - 1:+.1%}" for v in vals], textposition="outside"))  # fmt: skip
    fig.update_xaxes(
        title="Present value of the pension (MXN thousands)", range=[0, max(vals) / 1000 * 1.18]
    )
    fig.update_yaxes(autorange="reversed")
    ui.show(ui.style(fig, 400, False), key="apv")
    lo, hi = (
        apv(bases["Central projection"], rate - 0.01),
        apv(bases["Central projection"], rate + 0.01),
    )
    st.caption(
        f"One point less interest adds **{lo / central - 1:+.1%}** to this pension and one point more takes "
        f"**{hi / central - 1:+.1%}**; doubling the projected improvement adds only "
        f"**{rows['Double the improvement'] / central - 1:+.1%}**. Rates move an annuity more than the "
        "longevity trend does. Percentages are against the central projection."
    )

with tab_surv:
    j = np.arange(mine.shape[1])
    surv_mine = np.cumprod(1 - np.concatenate([[0], mine[0, :-1]]))
    cen = bases["Central projection"]
    surv_c = np.cumprod(1 - np.concatenate([[0], cen[0, :-1]]))
    per = bases["Mexico 2023 period table"]
    surv_p = np.cumprod(1 - np.concatenate([[0], per[0, :-1]]))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=age + j,
            y=surv_p * 100,
            name="Today's table, no improvement",
            line={"color": ui.MUTED, "dash": "dash", "width": 2},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=age + j,
            y=surv_c * 100,
            name="Central projection",
            line={"color": ui.BLUE, "width": 2.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=age + j, y=surv_mine * 100, name="Your scenario", line={"color": ui.INK, "width": 3}
        )
    )
    fig.update_yaxes(title="Still alive and paid (%)", range=[0, 100])
    fig.update_xaxes(title="Age", range=[age, 105])
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 420), key="surv")
    st.caption(
        f"A {'man' if sex == 'M' else 'woman'} of {age} today is paid until the curve reaches zero. "
        "Pricing on today's table ignores that the person will live their 70s and 80s in the future, "
        "when mortality is lower: the cohort effect."
    )

with tab_block:
    st.markdown(
        "A pension **block** of 20,000 pensioners aged 60 to 95 (illustrative, 60% men, 120,000 a year), "
        "valued on the same bases, and what happens when a **pandemic** hits the block next to a book "
        "of life insurance."
    )
    lg = ui.table("stress_longevity")
    lg = lg[lg["scenario"] != "central"].sort_values("change_vs_central")
    fig = go.Figure(go.Bar(y=lg["label"], x=lg["change_vs_central"] * 100, orientation="h",
                           marker_color=[ui.ORANGE if v > 0 else ui.BLUE for v in lg["change_vs_central"]],
                           text=[f"{v:+.1%}" for v in lg["change_vs_central"]], textposition="outside"))  # fmt: skip
    fig.add_vline(x=0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(
        title="Change in the block's reserve against the central projection (%)", range=[-12, 22]
    )
    ui.show(ui.style(fig, 400, False), key="block")
    hedge = ui.table("stress_hedge")
    h = hedge[hedge["shock"].str.contains("2021")].iloc[0]
    st.markdown(
        f"**Natural hedge.** A repeat of 2021 costs a life-insurance book MXN {h['life_book_change'] / 1e6:,.0f} million and "
        f"frees MXN {-h['annuity_change'] / 1e6:,.0f} million of annuity reserve. An annuity block "
        f"{h['annuity_block_to_offset'] / h['annuity_reserve']:.1f} times this size would offset it exactly. "
        "Longevity works the other way, and the life book gains more than the annuity block loses."
    )
    ui.synthetic_note()
    ui.source_note(["stress_longevity", "stress_hedge"], "stress-tests.md")

st.caption(
    "Annuity-due at the chosen rate, payments annual in advance; cohort path through the projected tables."
)
