"""Mortality Table Builder: the dashboard. Run with ``uv run mortality app``."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # lets pages ``import ui``

PAGES = [
    ("views/home.py", "Overview", ":material/home:", "overview"),
    ("views/insured.py", "Insured lives", ":material/verified_user:", "insured"),
    ("views/tables.py", "Mexico's mortality", ":material/monitoring:", "mortality"),
    ("views/future.py", "The future", ":material/trending_up:", "future"),
    ("views/pandemic.py", "The pandemic", ":material/coronavirus:", "pandemic"),
    ("views/price.py", "Price a policy", ":material/calculate:", "price"),
    ("views/annuity.py", "Annuities", ":material/elderly:", "annuities"),
    ("views/reinsure.py", "Reinsurance lab", ":material/shield:", "reinsurance"),
    ("views/experience.py", "Experience study", ":material/science:", "experience"),
    ("views/trust.py", "Trust and methods", ":material/verified:", "trust"),
]

st.set_page_config(
    page_title="Mortality Table Builder",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

here = Path(__file__).resolve().parent
available = [
    st.Page(here / path, title=title, icon=icon, url_path=slug, default=slug == "overview")
    for path, title, icon, slug in PAGES
    if (here / path).exists()
]
navigation = st.navigation(available)

with st.sidebar:
    st.markdown("**Mortality Table Builder**")
    st.caption(
        "An end-to-end actuarial pipeline for Mexico. Real data, validated methods, "
        "illustrative books."
    )
    st.link_button("Source code", "https://github.com/deadmigue55/Mortality-Table-Builder",
                   icon=":material/code:")  # fmt: skip

navigation.run()
