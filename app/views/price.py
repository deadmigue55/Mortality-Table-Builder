"""Price a policy: live term-life pricing with the project's own profit-testing engine."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import ui

from mortality import pricing

ui.header(
    "Price a policy",
    "Solve the premium of a level-term life policy for a target return, then see what happens to it.",
    "This is what a pricing actuary does: set a premium so the product earns its hurdle rate, "
    "then test it against mortality that turns out different from the pricing table. The "
    "engine below is the same one behind the written analysis, and the tests prove its core identity.",
)


@st.cache_resource(show_spinner="Loading mortality bases...")
def bases():
    return pricing._bases(ui.connection())


available = bases()
if not available:
    st.error("The demo bundle lacks the tables needed for pricing.")
    st.stop()

with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    sex = c1.radio("Sex", ["M", "F"], format_func=ui.SEX_NAME.get, horizontal=True)
    age = c2.slider("Issue age", 18, 65, 40)
    term = c3.select_slider("Term (years)", [10, 15, 20, 25, 30], value=20)
    sum_assured = c4.select_slider(
        "Sum assured (MXN)", [250_000, 500_000, 1_000_000, 2_000_000, 5_000_000], value=1_000_000,
        format_func=lambda x: f"{x:,.0f}",
    )  # fmt: skip
    c5, c6, c7 = st.columns(3)
    labels = {k: v for k, v in pricing.BASES.items() if k in available}
    # version 2 prices quotes on the insured table; the regulator's table stays as the reference
    if "cnsf" in labels:
        labels["cnsf"] = "CNSF 2013 (the regulator's table, the version 1 basis)"
    if "insured_prudent" in labels:
        labels["insured_prudent"] = "Insured lives + margin (version 2 basis)"
    default = list(labels).index("insured_prudent") if "insured_prudent" in labels else 0
    price_basis = c5.selectbox("Priced on", list(labels), format_func=labels.get, index=default)
    if price_basis.startswith("insured"):
        c5.caption("The statutory reserve stays on CNSF 2013, as the regulator requires.")
    hurdle = c6.slider("Target return (IRR, %)", 5.0, 20.0, 10.0, 0.5) / 100
    invest = c7.slider("Investment return (%)", 2.0, 9.0, 5.0, 0.5) / 100
    with st.expander("Expense, commission and lapse assumptions (illustrative)"):
        e1, e2, e3, e4 = st.columns(4)
        acq = e1.slider("Acquisition, % of premium", 0.0, 0.8, 0.35, 0.05)
        com = e2.slider("First-year commission", 0.0, 0.8, 0.40, 0.05)
        maint = e3.slider("Maintenance per year (MXN)", 0, 600, 250, 25)
        lapse_scale = e4.slider("Lapse level (1 = base)", 0.0, 2.0, 1.0, 0.25)

a = pricing.Assumptions(
    sum_assured=float(sum_assured), hurdle=hurdle, investment_return=invest,
    acquisition_pct=acq, commission_first=com, maintenance=float(maint),
)  # fmt: skip
q = available[price_basis](sex, age, term)
valuation = q  # the reserve is held on the pricing table, as in version 1
if price_basis.startswith("insured") and "cnsf" in available:
    valuation = available["cnsf"](
        sex, age, term
    )  # ...except the regulator's reserve stays on CNSF 2013
premium = pricing.solve_premium(q, a, q_valuation=valuation)
test = pricing.profit_test(q, premium, a, q_valuation=valuation, lapse_scale=lapse_scale)
summ = pricing.summarise(test, hurdle)
net = pricing.net_premium(q, a.valuation_interest, a.sum_assured)

ui.metric_row(
    [
        (
            "Annual gross premium",
            f"{premium:,.0f} MXN",
            f"{1000 * premium / sum_assured:.2f} per 1,000",
        ),
        (
            "Net premium (mortality only)",
            f"{net:,.0f} MXN",
            f"loading {premium / net - 1:.0%} pays expenses",
        ),
        (
            "Return achieved",
            f"{summ['irr']:.1%}" if np.isfinite(summ["irr"]) else "n/a",
            f"target {hurdle:.1%}",
        ),
        ("First-year result", f"{summ['year_1_profit']:,.0f} MXN", "acquisition cost up front"),
        (
            "Pays back",
            f"year {summ['payback_year']}" if summ["payback_year"] else "never",
            "discounted at the target",
        ),
    ]
)

tab_sig, tab_adequacy, tab_tornado, tab_reserve = st.tabs(
    ["Profit signature", "Is the premium safe?", "What moves the return", "Reserves"]
)

with tab_sig:
    cum = test["profit_issued"].cumsum()
    colors = [ui.ORANGE if v < 0 else ui.BLUE for v in test["profit_issued"]]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=test["policy_year"],
            y=test["profit_issued"],
            marker_color=colors,
            name="Profit in the year",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=test["policy_year"],
            y=cum,
            name="Cumulative profit",
            line={"color": ui.INK, "width": 3},
        )
    )
    fig.update_xaxes(title="Policy year", dtick=2)
    fig.update_yaxes(title="MXN per policy issued")
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 420), key="sig")
    r = test.iloc[min(4, len(test) - 1)]
    parts = {
        "Claims": r["claims"], "Commission": r["commission"], "Expenses": r["expenses"],
        "Added to reserves": r["premium"] - r["claims"] - r["commission"] - r["expenses"] - r["profit_per_policy"],
        "Profit": r["profit_per_policy"],
    }  # fmt: skip
    st.caption(
        "Term insurance loses money on day one: acquisition cost and first-year commission arrive "
        "before any premium has been earned. In a renewal year "
        + ", ".join(f"{k.lower()} takes {v / r['premium']:.0%}" for k, v in parts.items())
        + " of the premium."
    )

with tab_adequacy:
    st.markdown(
        "The premium was set on one mortality table. What does it earn if people actually die like "
        "**another** one? The **margin** is the NPV at the target return as a share of the premium: "
        "0 means exactly on target, negative means the product loses against its hurdle."
    )
    rows = []
    for key, label in labels.items():
        qb = available[key](sex, age, term)
        t = pricing.profit_test(qb, premium, a, q_valuation=valuation, lapse_scale=lapse_scale)
        s = pricing.summarise(t, hurdle)
        rows.append(
            {
                "basis": label,
                "margin": s["margin"],
                "irr": s["irr"],
                "cushion": pricing.mortality_cushion(qb, premium, a, q_valuation=valuation),
            }
        )
    ad = np.array([r["margin"] for r in rows])
    fig = go.Figure(
        go.Bar(
            y=[r["basis"] for r in rows][::-1], x=(ad * 100)[::-1], orientation="h",
            marker_color=[ui.BLUE if v >= -1e-9 else ui.ORANGE for v in ad][::-1],
            text=[f"{v:+.0%}" for v in ad][::-1], textposition="outside",
        )
    )  # fmt: skip
    fig.add_vline(x=0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(title="NPV margin at the target return (% of premium)")
    ui.show(ui.style(fig, 360, False), key="adeq")
    own = next(r for r in rows if r["basis"] == labels[price_basis])
    st.caption(
        f"Mortality could run **{own['cushion'] - 1:.0%}** above the pricing table before this policy loses "
        "money over its life. The 99.5th percentile variant is a regulatory stress; the Mexican "
        "population's own mortality is a different risk altogether, one that underwriting is paid to remove."
    )

with tab_tornado:
    grid = pricing.scenario_grid(q, a, premium)
    base_npv = grid.iloc[0]["margin"]
    pairs = [
        ("Mortality ±20%", "mortality -20%", "mortality +20%"),
        ("Pandemic year 2 (x2)", None, "pandemic: year 2 mortality x2"),
        ("Investment return ±1 pt", "investment return +1 pt", "investment return -1 pt"),
        ("Expenses ±10%", "expenses -10%", "expenses +10%"),
        ("Lapses ±25%", "lapse +25%", "lapse -25%"),
    ]
    g = grid.set_index("scenario")["margin"]
    rows_t = [
        (lab, (g[good] - base_npv) * 100 if good else 0.0, (g[bad] - base_npv) * 100)
        for lab, good, bad in pairs
    ]
    rows_t.sort(key=lambda r: abs(r[1]) + abs(r[2]))
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=[r[0] for r in rows_t],
            x=[r[1] for r in rows_t],
            orientation="h",
            marker_color=ui.BLUE,
            name="Favorable",
        )
    )
    fig.add_trace(
        go.Bar(
            y=[r[0] for r in rows_t],
            x=[r[2] for r in rows_t],
            orientation="h",
            marker_color=ui.ORANGE,
            name="Adverse",
        )
    )
    fig.update_layout(barmode="relative")
    fig.update_xaxes(title="Change in NPV margin (% of premium)")
    ui.show(ui.style(fig, 360), key="torn")
    st.caption(
        "One assumption moved at a time, premium held fixed. Mortality decides the return; a "
        "lapse-supported product (no surrender value) is almost indifferent to lapses."
    )

with tab_reserve:
    bel = pricing.best_estimate_liability(q, premium, a, lapse_scale)
    bel_end = np.append(bel[1:], 0.0)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=test["policy_year"],
            y=test["reserve_end"],
            name="Statutory net premium reserve",
            line={"color": ui.BLUE, "width": 3},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=test["policy_year"],
            y=bel_end,
            name="Best-estimate liability",
            line={"color": ui.ORANGE, "width": 3},
        )
    )
    fig.add_hline(y=0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(title="End of policy year", dtick=2)
    fig.update_yaxes(title="Per policy in force (MXN)")
    fig.update_layout(hovermode="x unified")
    ui.show(ui.style(fig, 400), key="res")
    st.caption(
        f"After year 1 the regulator's reserve is **{test['reserve_end'].iloc[0]:,.0f}** while the best-estimate "
        f"liability is **{bel_end[0]:,.0f}**: future premiums outweigh future claims and expenses. The "
        "difference is prudence that releases over the life of the policy."
    )

ui.source_note(["cnsf_rates", "graduated_qx", "projected_qx", "experience_basis"], "pricing.md")
st.caption(
    ":material/science: Expenses, commissions, lapses and the target return are illustrative assumptions; "
    "the mortality is real. The company-experience basis comes from the synthetic portfolio."
)
