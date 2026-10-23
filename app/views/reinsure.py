"""Reinsurance lab: choose a treaty and see what it does to the claims distribution."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import ui

from mortality import experience as ex
from mortality import reinsurance as re
from mortality import stress

ui.header(
    "Reinsurance lab",
    "Pick a treaty, set the market terms, and watch it reshape a year of claims on a 392,000-policy book.",
    "A reinsurer is paid to take risk off a cedant's hands. The cedant's question is which cover buys "
    "the most capital relief per peso, and the answer depends on where the risk really is: large "
    "policies, or a pandemic that hits every policy at once.",
)
ui.synthetic_note()

BAND = {"M": "Men", "F": "Women"}


@st.cache_data(show_spinner=False)
def book():
    """The in-force block's sums assured, probabilities of dying and P-scores of 2021."""
    block = ui.inforce()
    basis = ui.sql("SELECT sex, age, duration_group, multiplier FROM experience_basis")
    q = stress.first_year_q(block, ui.cnsf_curve("base"), ex._multiplier_lookup(basis))
    excess = ui.sql("SELECT * FROM excess_mortality")
    scores = stress.pscore_by_age(excess, 2021)
    return block["sum_assured"].to_numpy(float), q, block, scores


@st.cache_data(show_spinner="Simulating claims...")
def simulate(sims: int, level_sigma: float, p_pandemic: float, dampening: float):
    sa, q, block, scores = book()
    terms = re.Terms(sims=sims, level_sigma=level_sigma, pandemic_probability=p_pandemic,
                     pandemic_dampening=dampening)  # fmt: skip
    q_event = re.pandemic_q(block, q, scores, dampening)
    return re.simulate_claims(sa, q, q_event, terms)


with st.container(border=True):
    st.markdown("**The risk**")
    r1, r2, r3, r4 = st.columns(4)
    p_years = r1.select_slider(
        "A pandemic like 2021 once every... (years)", [10, 20, 30, 50, 100], value=30
    )
    dampening = r2.slider("Insured excess as share of the population's", 0.0, 1.0, 0.5, 0.1)
    sigma = r3.slider("Uncertainty of the mortality level (%)", 0.0, 10.0, 5.0, 0.5) / 100
    sims = r4.select_slider("Simulated years", [2000, 5000, 10000], value=5000)
    st.markdown("**The market**")
    m1, m2 = st.columns(2)
    re_coc = m1.slider("Return the reinsurer asks on its capital (%)", 3.0, 12.0, 6.0, 0.5) / 100
    ce_coc = m2.slider("The cedant's own cost of capital (%)", 6.0, 14.0, 10.0, 0.5) / 100

terms = re.Terms(sims=sims, level_sigma=sigma, pandemic_probability=1 / p_years,
                 pandemic_dampening=dampening, reinsurer_coc=re_coc, cedant_coc=ce_coc)  # fmt: skip
sim = simulate(sims, sigma, 1 / p_years, dampening)
totals = sim.totals
gross = re.distribution(totals, terms.quantile)

tab_cover, tab_table, tab_layers, tab_rating = st.tabs(
    [
        "Design a cover",
        "All the standard covers",
        "Which layers are worth buying",
        "Rating and longevity swap",
    ]
)

with tab_cover:
    kind = st.radio(
        "Cover", ["Quota share", "Surplus", "Per-life excess of loss", "Stop loss (aggregate)", "Per-life XL + stop loss"],
        horizontal=True,
    )  # fmt: skip
    mean = gross["mean"]
    if kind == "Quota share":
        share = st.slider("Share ceded", 0.05, 0.9, 0.3, 0.05)
        rec = re.quota_share(sim, share)
        premium = re.proportional_premium(rec, terms)
    elif kind == "Surplus":
        s1, s2 = st.columns(2)
        ret = s1.select_slider(
            "Retention (MXN)",
            [250_000, 500_000, 1_000_000, 2_000_000, 5_000_000],
            value=1_000_000,
            format_func=lambda x: f"{x / 1e6:g}M",
        )
        lines = s2.slider("Lines", 1, 20, 9)
        rec = re.surplus(sim, float(ret), lines)
        premium = re.proportional_premium(rec, terms)
    elif kind == "Per-life excess of loss":
        s1, s2 = st.columns(2)
        ret = s1.select_slider(
            "Retention (MXN)",
            [250_000, 500_000, 1_000_000, 2_000_000, 5_000_000],
            value=1_000_000,
            format_func=lambda x: f"{x / 1e6:g}M",
        )
        limit = s2.select_slider(
            "Limit (MXN)",
            [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000, 50_000_000],
            value=8_000_000,
            format_func=lambda x: f"{x / 1e6:g}M",
        )
        rec = re.per_life_xl(sim, float(ret), float(limit))
        premium = re.non_proportional_premium(rec, terms)
    elif kind == "Stop loss (aggregate)":
        s1, s2 = st.columns(2)
        attach = s1.slider("Attaches at (% of expected claims)", 100, 200, 125, 5)
        limit = s2.slider("Limit (% of expected claims)", 10, 150, 100, 10)
        rec = re.stop_loss(totals, attach / 100 * mean, limit / 100 * mean)
        premium = re.non_proportional_premium(rec, terms)
    else:
        s1, s2 = st.columns(2)
        ret = s1.select_slider(
            "Per-life retention (MXN)",
            [500_000, 1_000_000, 2_000_000],
            value=1_000_000,
            format_func=lambda x: f"{x / 1e6:g}M",
        )
        attach = s2.slider(
            "Stop loss attaches at (% of retained expected claims)", 100, 200, 125, 5
        )
        xl = re.per_life_xl(sim, float(ret), 8.0 * ret)
        left = totals - xl
        sl = re.stop_loss(left, attach / 100 * left.mean(), left.mean())
        rec = xl + sl
        premium = re.non_proportional_premium(xl, terms) + re.non_proportional_premium(sl, terms)
    row = re.evaluate(kind, "", sim, rec, premium, terms)
    net = totals - rec
    ui.metric_row(
        [
            ("Capital before", ui.money(gross["capital"], " MXN"), "99.5% claims over the mean"),
            (
                "Capital after",
                ui.money(row["capital"], " MXN"),
                f"{row['relief_share']:.0%} relieved",
            ),
            ("Net cost a year", ui.money(row["cost"], " MXN"), "premium less expected recoveries"),
            (
                "Price of relief",
                f"{row['price_of_relief']:.1%}" if np.isfinite(row["price_of_relief"]) else "n/a",
                f"cedant's cost of capital {ce_coc:.0%}",
            ),
            (
                "Worth buying?",
                "Yes" if row["worth_buying"] else "No",
                "price below the cedant's cost",
            ),
        ]
    )
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=totals / 1e6,
            name="Before reinsurance",
            marker_color=ui.MUTED,
            opacity=0.6,
            nbinsx=70,
            histnorm="probability",
        )
    )
    fig.add_trace(
        go.Histogram(
            x=net / 1e6,
            name="After reinsurance",
            marker_color=ui.BLUE,
            opacity=0.6,
            nbinsx=70,
            histnorm="probability",
        )
    )
    fig.add_vline(
        x=gross["var_995"] / 1e6,
        line_color=ui.ORANGE,
        line_dash="dash",
        annotation_text="99.5% before",
        annotation_position="top left",
    )
    fig.add_vline(
        x=row["retained_var_995"] / 1e6,
        line_color=ui.BLUE,
        line_dash="dash",
        annotation_text="99.5% after",
        annotation_position="top right",
    )
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title="Next year's claims, MXN million")
    fig.update_yaxes(title="Share of simulated years")
    ui.show(ui.style(fig, 400), key="hist")
    st.caption(
        f"Expected claims {ui.money(mean, ' MXN')}; standard deviation {ui.money(gross['sd'], ' MXN')} "
        f"({gross['cv']:.1%} of the mean). After the cover the standard deviation falls "
        f"{row['sd_reduction']:.0%}. The right tail of the gray histogram is the pandemic years."
    )


def short_name(name: str) -> str:
    return name.split(",")[0].replace("Per-life ", "").replace("Stop loss ", "SL ")


with tab_table:
    table = re.structure_table(sim, terms)
    view = table[
        [
            "structure",
            "family",
            "expected_recoveries",
            "cost",
            "capital_relief",
            "relief_share",
            "price_of_relief",
            "worth_buying",
        ]
    ].copy()
    view["expected_recoveries"] = view["expected_recoveries"] / 1e6
    view["cost"] = view["cost"] / 1e6
    view["capital_relief"] = view["capital_relief"] / 1e6
    st.dataframe(
        view.rename(columns={"structure": "Cover", "family": "Type", "expected_recoveries": "Expected recoveries (M)", "cost": "Net cost (M)",
                             "capital_relief": "Capital relieved (M)", "relief_share": "Share of capital", "price_of_relief": "Price of relief", "worth_buying": "Worth it"})
        .style.format({"Expected recoveries (M)": "{:,.1f}", "Net cost (M)": "{:,.1f}", "Capital relieved (M)": "{:,.0f}",
                       "Share of capital": "{:.0%}", "Price of relief": "{:.1%}"}, na_rep="n/a"),
        hide_index=True, width="stretch",
    )  # fmt: skip
    x = view[view["family"] != "none"]
    fig = go.Figure()
    for fam, color in (
        ("proportional", ui.ORANGE),
        ("excess of loss", ui.BLUE),
        ("combined", ui.INK),
    ):
        part = x[x["family"] == fam]
        fig.add_trace(go.Scatter(x=part["capital_relief"], y=part["cost"], mode="markers+text", name=fam.capitalize(),
                                 text=part["structure"].map(short_name),
                                 textposition="top center", marker={"size": 13, "color": color}))  # fmt: skip
    top = float(x["capital_relief"].max()) * 1.1
    fig.add_trace(go.Scatter(x=[0, top], y=[0, ce_coc * top], mode="lines", name=f"Cedant's cost of capital ({ce_coc:.0%})",
                             line={"color": ui.AQUA, "dash": "dash"}))  # fmt: skip
    fig.update_xaxes(title="Capital relieved (MXN million)")
    fig.update_yaxes(title="Net cost a year (MXN million)")
    ui.show(ui.style(fig, 430), key="cost")
    st.caption(
        "Covers below the dashed line cost less than the cedant's own cost of holding the capital."
    )

with tab_layers:
    fr = re.retention_frontier(sim, terms)
    xl = fr[(fr["family"] == "excess of loss") & fr["marginal_price"].notna()].sort_values(
        "parameter"
    )
    fig = go.Figure(
        go.Scatter(
            x=xl["parameter"] / 1e6,
            y=xl["marginal_price"] * 100,
            mode="lines+markers",
            line={"color": ui.BLUE, "width": 2.5},
        )
    )
    fig.add_hline(
        y=ce_coc * 100,
        line_color=ui.AQUA,
        line_dash="dash",
        annotation_text="Cedant's cost of capital",
    )
    fig.update_xaxes(
        type="log",
        title="Retention, MXN million (layer up to the next retention)",
        tickvals=[0.1, 0.25, 0.5, 1, 2, 5, 10],
    )
    fig.update_yaxes(title="Price of the layer (% of capital relieved)")
    ui.show(ui.style(fig, 400, False), key="layers")
    cheap = xl[xl["marginal_price"] < ce_coc]
    st.caption(
        f"{len(cheap)} of {len(xl)} layers cost less than {ce_coc:.0%} of the capital they relieve at a reinsurer return of {re_coc:.1%}. "
        "Raise the reinsurer's required return in the controls above and the layers cross the line: "
        "the case for per-life cover disappears once the reinsurer asks for too much."
    )
    sens = re.price_sensitivity(sim, terms)
    st.dataframe(
        sens.rename(columns={"reinsurer_coc": "Reinsurer return", "cutoff_retention": "Worthwhile layers up to", "net_benefit": "Net benefit (MXN)",
                             "xl_price_of_relief": "Per-life XL price", "stop_loss_price_of_relief": "Stop loss price"})
        .style.format({"Reinsurer return": "{:.0%}", "Worthwhile layers up to": "{:,.0f}", "Net benefit (MXN)": "{:,.0f}",
                       "Per-life XL price": "{:.1%}", "Stop loss price": "{:.1%}"}, na_rep="none"),
        hide_index=True, width="stretch",
    )  # fmt: skip

with tab_rating:
    st.markdown(
        "**Experience rating of a yearly renewable term treaty.** The reinsurer's rate is adjusted by the cedant's "
        "own experience, but only as far as the data are credible. Claim *amounts* need more experience than claim "
        "*counts*, because claim sizes vary."
    )
    r = ui.table("reinsurance_yrt_rating")
    r["segment"] = (
        r["dimension"].map({"channel": "Channel", "uw_class": "UW class", "sex": "Sex"})
        + ": "
        + r["level"].astype(str)
    )
    r = r.sort_values("experience_factor")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=r["ae_amount"],
            y=r["segment"],
            mode="markers",
            name="Amount A/E",
            marker={"size": 10, "color": ui.MUTED},
        )
    )
    fig.add_trace(go.Scatter(x=r["experience_factor"], y=r["segment"], mode="markers", name="Rated factor", marker={"size": 13, "color": ui.BLUE},
                             text=[f"credibility {z:.0%}" for z in r["credibility"]], hovertemplate="%{y}<br>factor %{x:.2f}<br>%{text}<extra></extra>"))  # fmt: skip
    fig.add_vline(x=1.0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(title="Relative to the manual rate (1.0)")
    ui.show(ui.style(fig, 400), key="yrt")
    st.markdown(
        "**Longevity swap** on the 20,000-pensioner block: the reinsurer pays the pensions actually due, the cedant pays a fixed schedule."
    )
    sw = ui.table("reinsurance_longevity_swap").iloc[0]
    dist = ui.table("reinsurance_longevity_distribution")
    ui.metric_row(
        [
            ("Central reserve", ui.money(sw["central_reserve"], " MXN"), None),
            (
                "Risk capital",
                ui.money(sw["capital"], " MXN"),
                f"{sw['capital_ratio']:.1%} of the reserve",
            ),
            (
                "Fee",
                f"{sw['fee_bps_per_year']:.0f} bp a year",
                f"{sw['fee_share_of_reserve']:.1%} of the reserve in total",
            ),
            (
                "Pool risk share of variance",
                f"{sw['pool_share_of_variance']:.0%}",
                "trend risk dominates",
            ),
        ]
    )
    fig = go.Figure(go.Bar(x=[f"{x * 100:g}%" for x in dist["level"]], y=dist["change_vs_central"] * 100,
                           marker_color=[ui.BLUE if v < 0 else ui.ORANGE for v in dist["change_vs_central"]]))  # fmt: skip
    fig.update_xaxes(title="Percentile of the reserve")
    fig.update_yaxes(title="Reserve against central (%)")
    ui.show(ui.style(fig, 300, False), key="swap")

ui.source_note(["reinsurance_*", "excess_mortality", "experience_basis"], "reinsurance.md")
