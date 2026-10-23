"""Landing page: the pitch, the headline numbers and the tour."""

from __future__ import annotations

import streamlit as st
import ui

summary = ui.table("life_summary")
excess = ui.sql(
    "SELECT SUM(excess) x FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2022"
)
checks = ui.table("validation_results")
docs = ui.table("table_docs")
e0 = summary[summary["year"] == 2023].set_index("sex")["e0"]
excess_total = float(excess["x"].iloc[0])
ratio = {s: ui.graduated_curve(2023, s)[40] / ui.cnsf_curve()[40] for s in ("M", "F")}
insured = ui.sql(
    "SELECT MIN(ratio_population) lo, MAX(ratio_population) hi FROM insured_table "
    "WHERE segment = 'all' AND age BETWEEN 25 AND 65"
).iloc[0]
quote = ui.sql(
    "SELECT \"table\" t, premium_per_1000 p FROM insured_premiums WHERE sex = 'M' AND term = 20 "
    "AND issue_age = 40 AND \"table\" IN ('Mexico insured: Term, traditional', 'CNSF 2013', "
    "'Mexico population 2023')"
).set_index("t")["p"]

st.title("Mortality Table Builder")
st.markdown(
    "##### From three million Mexican death records to prices, reserves and reinsurance: "
    "an end-to-end actuarial pipeline, validated at every step."
)
st.caption(
    "Built by **Miguel Vilchis** · Actuarial Science, UNAM · "
    f"[Code and write-ups on GitHub]({ui.REPO}) · every number on this site comes from the pipeline"
)

ui.metric_row(
    [
        (
            "Life expectancy 2023, women / men",
            f"{e0['F']:.1f} / {e0['M']:.1f}",
            "from INEGI deaths and CONAPO population",
        ),
        (
            "Excess deaths, 2020 to 2022",
            f"{excess_total / 1000:,.0f},000",
            "four independent baselines",
        ),
        (
            "Automated data checks",
            f"{int((checks['status'] == 'PASS').sum())} of {len(checks)}",
            "pass; 4 known warnings, documented",
        ),
        ("Warehouse tables", f"{len(docs)}", "each with a written description"),
    ]
)

st.divider()
left, right = st.columns([1.15, 1])
with left:
    st.subheader("What this is")
    st.markdown(
        """
Mexico publishes no usable mortality table for the population as it is today. The official
regulatory table (CNSF 2013) is more than ten years old and mixes both sexes. This project
rebuilds the table from the raw data, then does with it what an insurer or a reinsurer does:

- **Data to tables.** Registered deaths are completed for late registration, graduated with
  four methods, and turned into life tables with commutation functions.
- **Tables to the future.** Lee-Carter and Cairns-Blake-Dowd projections, cross-checked against an
  independent R implementation, with a backtest that says how wrong they were in the past.
- **Tables to money.** Premiums solved for a target return, reserves, pandemic and longevity
  stress tests, reinsurance structures and a longevity swap.
- **An experience study** of the kind an insurer runs, validated by planting known effects in a
  synthetic portfolio and checking the method finds them (15 of 15), and usable on any real extract.
        """
    )
with right:
    st.subheader("Four things it found")
    st.markdown(
        f"""
1. **Mexicans who buy life insurance die at {insured["lo"]:.0%} to {insured["hi"]:.0%} of the
   population's rate** between 25 and 65. A man of 40's 20-year term costs
   **{quote["Mexico insured: Term, traditional"]:.2f}** per 1,000 on the insured table,
   {quote["CNSF 2013"]:.2f} on the regulator's and {quote["Mexico population 2023"]:.2f} on the population's.
2. **Mexican men aged 40 die at {ratio["M"]:.1f} times the rate in the CNSF regulatory table**, and
   women at {ratio["F"]:.1f} times: a premium priced on the population would be far too dear.
3. **{excess_total / 1000:,.0f},000 more people died in 2020 to 2022 than normal**, 1.56 for each death certified
   as COVID-19, and the regulator's own stress scenario would not have covered a repeat of 2021:
   insured lives were not shielded.
4. **Interest rates move an annuity book more than longevity does**: one point of
   interest is worth more reserve than doubling the projected improvement in mortality.
        """
    )

st.divider()
st.subheader("Take the tour")
tour = [
    (
        ":material/verified_user:",
        "Insured lives",
        "Version 2: the table a quote is priced on, built from the industry's own statistics.",
    ),
    (
        ":material/monitoring:",
        "Mexico's mortality",
        "Explore the tables: pick a year and sex, compare with the regulatory table, see the states.",
    ),
    (
        ":material/trending_up:",
        "The future",
        "Projection fans, scenarios and why annuities are underpriced by ignoring the cohort.",
    ),
    (
        ":material/coronavirus:",
        "The pandemic",
        "Excess deaths by month, age, cause and state, with the range over four baselines.",
    ),
    (
        ":material/calculate:",
        "Price a policy",
        "Live: price a term policy for a target return and watch its profit signature.",
    ),
    (
        ":material/elderly:",
        "Annuities",
        "Live: value a pension on eight bases and stress longevity and interest.",
    ),
    (
        ":material/shield:",
        "Reinsurance lab",
        "Live: choose a treaty and see what it does to the claims distribution.",
    ),
    (
        ":material/science:",
        "Experience study",
        "Insurer-style A/E study. Upload your own policy extract and run it.",
    ),
    (
        ":material/verified:",
        "Trust and methods",
        "Every data check, the sources, the tests and the limits.",
    ),
]
for row in (tour[:5], tour[5:]):
    cols = st.columns(5)
    for col, (icon, title, text) in zip(cols, row, strict=False):  # the last row may be shorter
        with col.container(border=True):
            st.markdown(f"**{icon} {title}**")
            st.caption(text)

st.divider()
with st.expander("Resumen en español"):
    st.markdown(
        f"""
**Mortality Table Builder** reconstruye las tablas de mortalidad de México a partir de los
microdatos de defunciones del INEGI y la población de CONAPO, y las usa como lo haría una
aseguradora o una reaseguradora.

- **Datos a tablas:** las defunciones se completan por registro tardío, se suavizan con cuatro
  métodos y se convierten en tablas de vida con funciones de conmutación.
- **Proyección:** Lee-Carter y Cairns-Blake-Dowd, verificados contra una implementación
  independiente en R y con una prueba retrospectiva de su error histórico.
- **Aplicaciones:** exceso de mortalidad (**{excess_total / 1000:,.0f},000** muertes de 2020 a 2022), precio de
  un seguro temporal para un rendimiento objetivo, reservas, pruebas de estrés de pandemia y
  longevidad, estructuras de reaseguro y un swap de longevidad.
- **Estudio de experiencia:** método validado sembrando efectos conocidos en una cartera
  sintética y comprobando que se recuperan (15 de 15).
- **Tabla de vida asegurada (versión 2):** con las estadísticas de la CNSF de Vida Individual,
  los asegurados mueren a entre {insured["lo"]:.0%} y {insured["hi"]:.0%} de la tasa de la población.
- **Rigor:** {len(checks)} controles automáticos de datos, más de 400 pruebas unitarias y todo
  reproducible con un comando.

La cartera de pólizas es **sintética** y los supuestos de mercado (gastos, comisiones, costo de
capital) son ilustrativos; la mortalidad es real o se deriva de datos reales.
        """
    )
