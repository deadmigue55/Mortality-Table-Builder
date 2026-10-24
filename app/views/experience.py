"""Experience study: an insurer-style A/E study, its validation, and a way to run it on your data."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import ui

from mortality import experience as ex

ui.header(
    "Experience study",
    "The study an insurer runs on its own claims: are policyholders dying faster or slower than the table says?",
    "Pricing, reserving and reinsurance all rest on how a company's own policyholders die. An "
    "experience study answers it, and an honest one has to show its data problems, its credibility "
    "and the claims that have happened but not yet been reported.",
)
ui.synthetic_note()


@st.cache_data(
    show_spinner="Running the study (about 10 seconds for 40,000 policies)...",
    max_entries=3,  # each entry holds a whole study; unbounded, uploads fill the server's RAM
    ttl=3600,
)
def run_study(raw: bytes, s: str, e: str, x: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "extract.csv"
        path.write_bytes(raw)
        policies = ex.load_extract(path)
    smr = ui.table("state_smr")
    smr_map = {f"{int(a):02d}": float(b) for a, b in zip(smr["state"], smr["smr"], strict=True)}
    return ex.run_study(policies, pd.Series(ui.cnsf_curve("base")), smr_map, s, e, x)


def show_run(data: bytes, s: str, e: str, x: str) -> None:
    try:
        res = run_study(data, s, e, x)
    except (ValueError, KeyError) as err:
        st.error(f"The extract could not be processed: {err}")
        return
    o = res["overview"].iloc[0]
    ui.metric_row(
        [
            ("Policies", f"{o['policies']:,.0f}", None),
            ("Deaths", f"{o['deaths']:,.0f}", None),
            ("Overall A/E", f"{o['deaths'] / o['expected_deaths']:.2f}", "vs CNSF 2013"),
            ("Sum assured", ui.money(o["sum_assured_in_force_mxn"], " MXN"), None),
        ]
    )
    r1, r2 = st.tabs(["Reconciliation and data checks", "A/E and relativities"])
    with r1:
        st.dataframe(res["dq_reconciliation"], hide_index=True, width="stretch")
        st.dataframe(res["dq_checks"], hide_index=True, width="stretch")
    with r2:
        ae_run = res["ae_one_way"]
        dims = [d for d in DIM_NAMES if d in set(ae_run["dimension"])]
        dim_run = st.selectbox("Cut by", dims, format_func=DIM_NAMES.get, key="rd")
        ae_chart(ae_run[ae_run["years"] == "all_years"], dim_run, "rae", False)
        st.dataframe(res["relativities"].round(3), hide_index=True, width="stretch")
    ui.download(res["ae_one_way"], "ae_one_way.csv", "Download the A/E table")


tab_study, tab_valid, tab_run = st.tabs(
    ["The study", "Does the method work?", "Run it on your data"]
)

DIM_NAMES = {"sex": "Sex", "uw_class": "Underwriting class", "channel": "Sales channel", "product": "Product",
             "amount_band": "Sum assured", "duration_group": "Policy year", "age_group": "Age group",
             "region": "Region", "calendar_year": "Calendar year"}  # fmt: skip


def ae_chart(df: pd.DataFrame, dimension: str, key: str, use_amount: bool) -> None:
    part = df[df["dimension"] == dimension]
    col, lo, hi = (
        ("ae_amount", "ae_amount_lower", "ae_amount_upper")
        if use_amount
        else ("ae", "ae_lower", "ae_upper")
    )
    fig = go.Figure(
        go.Scatter(
            x=part[col], y=part["level"].astype(str), mode="markers",
            marker={"size": 11, "color": ui.BLUE},
            error_x={"type": "data", "symmetric": False, "array": part[hi] - part[col], "arrayminus": part[col] - part[lo], "color": ui.INK_2},
            text=[f"{d:,.0f} deaths" for d in part["deaths"]], hovertemplate="%{y}: A/E %{x:.2f}<br>%{text}<extra></extra>",
        )
    )  # fmt: skip
    fig.add_vline(x=1.0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(
        title="Actual / expected, with 95% interval"
        + (" (by amount)" if use_amount else " (by count)")
    )
    fig.update_yaxes(autorange="reversed")
    ui.show(ui.style(fig, max(260, 70 + 42 * len(part)), False), key=key)


with tab_study:
    ov = ui.table("experience_overview").iloc[0]
    ui.metric_row(
        [
            ("Policies studied", f"{ov['policies']:,.0f}", "after data validation"),
            (
                "Deaths",
                f"{ov['deaths']:,.0f}",
                f"{ov['exposure_years'] / 1e6:.1f} million policy-years",
            ),
            (
                "Overall A/E vs CNSF 2013",
                f"{ov['deaths'] / ov['expected_deaths']:.2f}",
                "this book dies slower than the table",
            ),
            ("Sum assured in force", ui.money(ov["sum_assured_in_force_mxn"], " MXN"), None),
        ]
    )
    ae = ui.table("experience_ae")
    c1, c2, c3 = st.columns([1, 1, 1])
    window = c1.radio(
        "Period",
        ["all_years", "excluding_2020_2022"],
        format_func=lambda x: "All years" if x == "all_years" else "Excluding the pandemic years",
        horizontal=True,
    )
    dims_here = [d for d in DIM_NAMES if d in set(ae["dimension"])]
    dim = c2.selectbox(
        "Cut by", dims_here, format_func=DIM_NAMES.get, index=dims_here.index("uw_class")
    )
    amount = c3.toggle("Weight by sum assured", value=False)
    ae_chart(ae[ae["years"] == window], dim, "ae", amount)
    st.caption(
        "A/E below 1 means fewer deaths than the CNSF 2013 table predicts. **Preferred and standard risks die "
        "far below the table; rated risks above it**, which is what underwriting should do. Dots are "
        "point estimates with 95% intervals."
    )
    st.markdown("#### The most recent quarters look better than they are")
    q = ui.table("experience_ae_quarterly")
    q["when"] = q["year"].astype(str) + " Q" + q["quarter"].astype(str)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=q["when"], y=q["ae"], name="As reported", marker_color=ui.MUTED))
    fig.add_trace(
        go.Scatter(
            x=q["when"],
            y=q["ae_completed"],
            name="After the claims-lag correction",
            line={"color": ui.BLUE, "width": 3},
            mode="lines+markers",
        )
    )
    fig.add_hline(y=1.0, line_color=ui.INK, line_width=1)
    fig.update_yaxes(title="Actual / expected")
    ui.show(ui.style(fig, 360), key="lag")
    st.caption(
        "Deaths are reported late. The latest quarter shows only a part of its claims, so a naive study "
        "reads good news that is just missing data. The study estimates the reporting-delay curve from older quarters "
        "and completes the recent ones (IBNR)."
    )
    imp = ui.table("experience_impact")
    allp = imp[imp["product"] == "ALL"].iloc[0]
    st.markdown(
        f"#### What it means in money\nOn the in-force block, expected claims over the next 12 months fall "
        f"**{-allp['claims_12m_change_pct']:.0%}** against the CNSF table and the present value of all future death benefits "
        f"**{-allp['pv_change_pct']:.0%}** (MXN {-(allp['pv_experience'] - allp['pv_cnsf']) / 1e9:,.1f} billion). "
        "The unisex regulatory table overprices women's term insurance by up to about 30% and is "
        "close for men: a segmentation opportunity."
    )
    pr = ui.table("experience_pricing")
    pr["who"] = pr["sex"].map(ui.SEX_NAME) + ", " + pr["issue_age"].astype(str)
    st.dataframe(
        pr[["who", "premium_cnsf_per_1000", "premium_experience_per_1000", "change_pct"]]
        .rename(columns={"who": "20-year term, issue age", "premium_cnsf_per_1000": "Net premium per 1,000 on CNSF",
                         "premium_experience_per_1000": "on the company's experience", "change_pct": "Change"})
        .style.format({"Net premium per 1,000 on CNSF": "{:.2f}", "on the company's experience": "{:.2f}", "Change": "{:+.0%}"}),
        hide_index=True, width="stretch",
    )  # fmt: skip
    ui.source_note(
        ["experience_ae", "experience_ae_quarterly", "experience_impact", "experience_pricing"],
        "experience-study.md",
    )

with tab_valid:
    st.markdown(
        "How do you know a study method is right when the truth is unknown? **Plant a known truth and check the method finds it.** "
        "The synthetic portfolio was generated with 15 planted rating effects (sex, underwriting class, channel, age, "
        "region...). The study never sees them."
    )
    rec = ui.table("experience_recovery")
    rec["name"] = rec["factor"] + ": " + rec["level"].astype(str)
    rec = rec.iloc[::-1]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rec["relativity"], y=rec["name"], mode="markers", name="Estimated (95% interval)", marker={"size": 11, "color": ui.BLUE},
                             error_x={"type": "data", "symmetric": False, "array": rec["upper"] - rec["relativity"], "arrayminus": rec["relativity"] - rec["lower"], "color": ui.BLUE}))  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=rec["planted"],
            y=rec["name"],
            mode="markers",
            name="Planted truth",
            marker={"size": 12, "symbol": "diamond", "color": ui.ORANGE},
        )
    )
    fig.add_vline(x=1.0, line_color=ui.INK, line_width=1)
    fig.update_xaxes(title="Relativity to the base class")
    ui.show(ui.style(fig, 560), key="rec")
    st.caption(
        f"**{int(rec['inside_interval'].sum())} of {len(rec)}** planted effects fall inside the study's 95% interval "
        "(about 14 or 15 expected by chance alone). The same machinery recovers the select factors of the "
        "first policy years and the reporting-lag curve to within 2% of the truth. "
        "The reconciliation from the raw extract to the clean file balances to the record and to the death."
    )
    rc = ui.table("experience_dq_reconciliation")
    st.dataframe(
        rc.rename(columns={"step": "Step", "records": "Records", "deaths": "Deaths"}).style.format(
            {"Records": "{:,.0f}", "Deaths": "{:,.0f}"}
        ),
        hide_index=True,
        width="stretch",
    )
    dq = ui.table("experience_dq_checks")
    with st.expander("The data defects found in the extract"):
        st.dataframe(dq, hide_index=True, width="stretch")
    ui.source_note(
        ["experience_recovery", "experience_dq_checks", "experience_dq_reconciliation"],
        "experience-study.md",
    )

with tab_run:
    st.markdown(
        "Upload a policy extract in the format below (or use the sample) and run the **same pipeline**: validation with "
        "reconciliation, exact exposure, A/E with intervals, GLM relativities, select period, claims-lag completion, "
        "financial impact. Nothing is stored: the file is processed in memory and discarded."
    )
    template = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        ex.write_template(Path(tmp) / "t.csv")
        template.write((Path(tmp) / "t.csv").read_text())
    c1, c2 = st.columns(2)
    c1.download_button(
        "Download the column template",
        template.getvalue(),
        "policy_extract_template.csv",
        "text/csv",
        icon=":material/download:",
    )
    use_sample = c2.toggle("Use the 40,000-policy sample (synthetic)", value=True)
    uploaded = None if use_sample else st.file_uploader("Policy extract (CSV)", type=["csv"])
    d1, d2, d3 = st.columns(3)
    start = d1.date_input("Study starts", pd.Timestamp("2014-01-01"))
    end = d2.date_input("Study ends", pd.Timestamp("2024-06-30"))
    extract = d3.date_input("Extract taken on", pd.Timestamp("2024-08-15"))
    data = None
    if use_sample:
        data = ui.sample_extract_path().read_bytes()
    elif uploaded is not None:
        data = uploaded.getvalue()
    if data is None:
        st.info("Upload a CSV, or switch on the sample, to run the study.")
    else:
        key = (hash(data), str(start), str(end), str(extract))
        if st.button("Run the study", type="primary", icon=":material/play_arrow:"):
            st.session_state["experience_run"] = key
        if st.session_state.get("experience_run") == key:
            show_run(data, str(start), str(end), str(extract))
    st.caption(
        "The command line does the same on large files: `uv run mortality experience run --policies extract.csv ...`"
    )
