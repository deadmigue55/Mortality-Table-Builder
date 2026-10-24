"""Trust and methods: the data checks, the sources, the catalog and the limits."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
import ui

ui.header(
    "Trust and methods",
    "How you can check this work: every data check, every source, every table, every limit.",
    "Numbers without provenance are decoration. Every figure on this site comes from a table "
    "in a warehouse that is rebuilt from the sources with one command, and over a hundred automated "
    "checks run each time. The ones that warn are listed, with the reason.",
)

checks = ui.table("validation_results")
n_pass, n_warn, n_fail = (int((checks["status"] == s).sum()) for s in ("PASS", "WARN", "FAIL"))
ui.metric_row(
    [
        ("Checks passing", f"{n_pass} of {len(checks)}", None),
        ("Warnings", f"{n_warn}", "known data gaps, explained below"),
        ("Failures", f"{n_fail}", "the build exits with an error if any fail"),
        ("Unit tests", "300+", "run on every commit"),
    ]
)

tab_checks, tab_sources, tab_catalog, tab_limits = st.tabs(
    ["Data checks", "Sources", "Table catalog", "Limits and honesty"]
)

with tab_checks:
    prefix = checks["name"].str.split("_").str[0]
    groups = ["all", *sorted(prefix.unique())]
    c1, c2 = st.columns([1, 2])
    group = c1.selectbox("Area", groups)
    only = c2.radio("Show", ["Everything", "Warnings only"], horizontal=True)
    view = checks if group == "all" else checks[prefix == group]
    if only == "Warnings only":
        view = view[view["status"] != "PASS"]
    st.dataframe(
        view[["name", "severity", "status", "violations", "what"]].rename(columns={"name": "Check", "severity": "If it fails", "status": "Result", "violations": "Violations", "what": "Rule"}),
        hide_index=True, width="stretch", height=420,
    )  # fmt: skip
    by_area = checks.assign(area=prefix).groupby(["area", "status"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for status, color in (("PASS", ui.AQUA), ("WARN", ui.ORANGE), ("FAIL", "#c0392b")):
        if status in by_area:
            fig.add_trace(
                go.Bar(x=by_area.index, y=by_area[status], name=status, marker_color=color)
            )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="Checks")
    ui.show(ui.style(fig, 300), key="areas")
    st.markdown("**The four warnings, and why they are warnings and not failures**")
    for _, w in checks[checks["status"] == "WARN"].iterrows():
        st.markdown(f"- `{w['name']}`: {w['what']}")
    st.caption(
        "Severity is chosen deliberately: a FAIL stops the build (an identity that must hold, like deaths adding up); "
        "a WARN records a limitation of the data that the analysis already corrects or states."
    )

with tab_sources:
    man = ui.table("source_manifest")
    st.markdown(
        "Every file the pipeline downloads is logged with its URL, date and **SHA-256**; a data check recomputes "
        "the checksums, so the inputs cannot change silently."
    )
    st.dataframe(
        man[["source", "file", "bytes", "downloaded_at", "sha256", "url"]],
        hide_index=True,
        width="stretch",
        height=300,
    )
    st.markdown(
        """
| Source | Used for | License note |
|---|---|---|
| **INEGI** registered deaths (microdata, 2020 to 2024) and interactive tables (2014 to 2019) | observed deaths, cause, state | open government data |
| **CONAPO** population and projections, 1950 to 2070 | exposure, long history, official benchmark | open government data |
| **CNSF** 2013 regulatory mortality tables (CUSF Annex 5.3.3-a) | expected basis and pricing | public regulation |
| **SOA** mort.soa.org tables (29, including 13 Mexican) | benchmark tables | public |
| **Human Mortality Database** (9 countries) | international comparison | used in the pipeline, **never redistributed**: this site's data bundle excludes it |
        """
    )

with tab_catalog:
    docs = ui.table("table_docs")
    q = st.text_input("Search the 92 tables", placeholder="e.g. excess, reserve, credibility")
    view = (
        docs
        if not q
        else docs[
            docs.apply(
                lambda r: q.lower() in f"{r['table_name']} {r['description']}".lower(), axis=1
            )
        ]
    )
    st.dataframe(
        view.rename(columns={"table_name": "Table", "description": "What it holds"}),
        hide_index=True,
        width="stretch",
        height=480,
    )

with tab_limits:
    st.markdown(
        """
Real analysis is honest about what it cannot say. The limits of this project, by area:

**Data**
- Single-year-of-age deaths exist only from 2020; 2014 to 2019 are five-year groups, so single-age rates and the older projection history come from CONAPO's reconstruction.
- INEGI and CONAPO disagree on *who* dies (men 15 to 39: 34% fewer deaths in INEGI), which breaks life expectancy at 65 across the 2019/2020 join. The projection rebases to the INEGI level and documents it.
- 2024 still awaits the 2025 file's late registrations; the quality tables estimate and add them.

**Methods**
- The model's own projection uncertainty covers only 40% to 60% of backtest outcomes, so an empirical band is added.
- The pandemic stress assumes the insured population died like the general one, or at half the excess: an assumption, not an estimate, until a real company supplies its 2020 to 2021 experience.

**Books and markets**
- The insurance portfolio, the annuity block, expenses, commissions, lapses, the 10% hurdle, the reinsurer's cost of capital and the pandemic probability are **illustrative assumptions**, labeled wherever they appear.
- Reinsurance results assume no credit risk, no basis risk and a one-year static block. Solvency capital under the CNSF's rules is out of scope.

**What this is not.** It is not a pricing basis for a regulated product, a reserve certification, or a substitute for a company's own experience. It is a worked, tested demonstration of the method.
        """
    )
    st.link_button(
        "Read the methodology in the repository",
        f"{ui.REPO}/tree/main/docs",
        icon=":material/menu_book:",
    )
