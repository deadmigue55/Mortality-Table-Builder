# Results by step

One section per step of the pipeline, with the findings that matter most. Each section ends with a link to the full write-up, and the mathematics behind every method is in the [handbook](handbook/README.md). Expand a step to read it.

<details>
<summary><b>3. Data quality</b>: no age heaping, late registrations completed</summary>

- Death certificates show no age heaping (Whipple 98 to 101), comparable to the HMD countries.
- Late registrations are completed with an actuarial chain-ladder triangle per age band: 2024 gains 2.3%, within 1% of CONAPO's independent projection.
- Unknown sex and age are allocated proportionally (0.45% to 0.61% of deaths); unspecified-residence deaths stay in the national count.
- COVID years are flagged from cause-of-death codes (2020 to 2022).

[Full write-up](data-quality.md)
</details>

<details>
<summary><b>4. Crude rates</b>: Mexican men die 3 times as fast as the regulatory table says</summary>

- Mexican men die **3.0x** as fast as the CNSF 2013 table predicts at ages 25 to 84 (4.1x at 40 to 44); women 1.8x.
- Age-standardized male mortality rose **51%** in 2020 and was back at the 2019 level by 2023.
- Chihuahua and Colima run about 19% above their age mix, Sinaloa 19% below.
- Men aged 25 to 29 die at 6.7x the rate of Spanish men, 1.6x that of US men.

<table>
<tr>
<td width="50%"><img src="img/mortality_curve.png" alt="Mortality curve against the CNSF 2013 table"></td>
<td width="50%"><img src="img/covid_shock.png" alt="Pandemic shock by age"></td>
</tr>
</table>

[Full write-up](crude-rates.md)
</details>

<details>
<summary><b>5. Graduation</b>: four methods, digit preference found, old ages closed</summary>

- Four methods are compared on every year and sex; smoothing is chosen by a quasi-AIC whose dispersion is estimated from the crude rates themselves.
- Heligman-Pollard fits about 9x worse than the P-spline in 2023: Mexican men's young-adult plateau is not something a parametric law bends to.
- **Digit preference in men's death records:** +1.3% to +2.5% excess deaths at ages ending in 0 and 5, every year, invisible to the Whipple index.
- **Crude old-age data are not credible:** above about 88, women's rates overtake men's (a sign of age exaggeration), so ages 90 to 110 come from a Kannisto logistic fitted on 75 to 89, with men floored at women.
- Output: `graduated_qx`, a complete 0 to 110 table per year and sex.

<table>
<tr>
<td width="50%"><img src="img/graduation_fit.png" alt="Graduation fit"></td>
<td width="50%"><img src="img/old_age_closure.png" alt="Old-age closure"></td>
</tr>
</table>

[Full write-up](graduation.md)
</details>

<details>
<summary><b>6. Life tables</b>: validated against HMD and CONAPO</summary>

- Life expectancy at birth 2023: men **72.9**, women **78.9**; within 0.7 years of CONAPO in 2022 to 2024, and the same code reproduces HMD's published life expectancy to 0.007 years.
- COVID cost men **5.9 to 6.9 years** of life expectancy, depending on whether INEGI or CONAPO death counts are used.
- A pension annuity at 65 costs 14.94 on CNSF 2013 and 12.21 for Mexican men: valuing the population on the regulatory table overstates it by **22%** (13% for women).
- A 20-year term at 40 has a net premium of **6.6 per 1,000** for men on population mortality, against 1.7 on CNSF 2013.
- Mexican men's lifespans are the least equal of any country compared (disparity 14.6 years against 9.9 in Japan).

<table>
<tr>
<td width="50%"><img src="img/annuity_values.png" alt="Annuity values"></td>
<td width="50%"><img src="img/term_premiums.png" alt="Term premiums"></td>
</tr>
</table>

[Full write-up](life-tables.md)
</details>

<details>
<summary><b>7. Projection</b>: cross-checked in R, backtested, honest about uncertainty</summary>

- Lee-Carter and CBD are fitted to CONAPO 1970 to 2019 with process and drift uncertainty, back-tested over four origins and **cross-checked against StMoMo in R** (agreement to 0.00002 years).
- A forecast made in 1999 would have overshot men's 2019 life expectancy by **3.9 years**: men's improvement slowed to 15% of its earlier pace.
- Men's life expectancy reaches 77 by 2050 on the long trend, **74 if the last 20 years repeat**; CONAPO's official projection says 77.
- A pension annuity at 65 costs 6% more by 2050 on the long trend, 2% on the recent one. Pricing on a period table understates the cost by about **2.6%** against the cohort.
- INEGI and CONAPO disagree on who dies: INEGI shows **34% fewer deaths for men aged 15 to 39**, 10% to 16% more above 60.
- The model's own fan is too narrow (it covered 40% to 60% of backtests), so the projection carries an empirical band calibrated on the backtest errors.

<table>
<tr>
<td width="50%"><img src="img/projection_fan_e0.png" alt="Projection fan"></td>
<td width="50%"><img src="img/longevity_risk.png" alt="Longevity risk"></td>
</tr>
</table>

[Full write-up](projection.md)
</details>

<details>
<summary><b>8. Experience study</b>: validated by planting a known truth</summary>

- Works on any policy extract: `mortality experience run --policies my_extract.csv`. A synthetic portfolio of 573,000 policies with planted effects, lapses, expiries, a claims lag and injected data defects **validates the method** (every effect in it is an illustrative assumption, not an estimate for any company).
- Exact exposure from dates (Lexis split at anniversaries and calendar years); data validation with a record-and-death reconciliation that balances exactly.
- A/E by count and by amount with intervals; limited-fluctuation and Bühlmann-Straub credibility; a Poisson GLM that **recovers 15 of 15 planted effects** inside their 95% intervals.
- **Claims-lag (IBNR) correction:** the latest quarter reads 0.72 raw and 0.88 completed, within 2% of the truth.
- A derived company basis with a prudent margin: on this book, CNSF 2013 overprices women's 20-year term by 34% and the in-force claims run 12% lower.

<table>
<tr>
<td width="50%"><img src="img/experience_overview.png" alt="A/E overview"></td>
<td width="50%"><img src="img/experience_impact.png" alt="Financial impact"></td>
</tr>
</table>

[Full write-up](experience-study.md)
</details>

<details>
<summary><b>9a. Excess mortality</b>: 746,000 excess deaths, four baselines</summary>

- About **746,000 excess deaths in 2020 to 2022** (range 676,000 to 791,000 over four independent baselines), 1.56 per certified COVID-19 death, 13.0 million years of life lost.
- Men aged 65 to 69 died at **1.70x** the expected rate in 2021. 64% of the excess was certified as COVID-19; the rest mostly as heart disease, diabetes and respiratory causes.
- Estado de México, Ciudad de México and Tlaxcala were highest (about 48%), Colima lowest (19%). The baselines predict 2023 to within 4%.

<table>
<tr>
<td width="50%"><img src="img/excess_waves.png" alt="Excess mortality waves"></td>
<td width="50%"><img src="img/excess_age_profile.png" alt="Excess by age"></td>
</tr>
</table>

[Full write-up](excess-mortality.md)
</details>

<details>
<summary><b>9b. Pricing and reserves</b>: a term policy priced for a 10% return</summary>

- A 40-year-old, 20-year term: **2.32 per 1,000** against a net premium of 1.74. It loses 87% of its first premium on day one and is in profit by year 9.
- On the CNSF premium, the population's mortality would cost a man of 40 171% of premium, while the synthetic company book's women earn 31% to 41%.
- Mortality of ±20% moves the margin by ±11.6%; a year of doubled mortality costs 6.5 points of IRR.
- The best-estimate liability is negative (-2,230) where the statutory reserve holds 776.

<table>
<tr>
<td width="50%"><img src="img/pricing_signature.png" alt="Profit signature"></td>
<td width="50%"><img src="img/pricing_adequacy.png" alt="Pricing adequacy"></td>
</tr>
</table>

[Full write-up](pricing.md)
</details>

<details>
<summary><b>9c. Stress tests</b>: the regulator's stress would not have covered 2021</summary>

- Replaying 2021 on the in-force book adds **60% to the next year's claims** (MXN 447 million on 742 million), 71% of it from policyholders aged 50 and over: more than the regulator's own 99.5th percentile table (+51%) if insureds die like the population.
- For an annuity book, one point less interest (+8.1%) matters more than doubling the projected improvement (+2.3%); the regulatory pensions table holds 16% more than the central projection.
- An annuity block 1.2 times the size of the life book would offset a repeat of 2021 exactly, while a 20% fall in mortality gains the life book more than it costs the annuities.

<table>
<tr>
<td width="50%"><img src="img/stress_pandemic.png" alt="Pandemic stress"></td>
<td width="50%"><img src="img/stress_longevity.png" alt="Longevity stress"></td>
</tr>
</table>

[Full write-up](stress-tests.md)
</details>

<details>
<summary><b>9d. Reinsurance</b>: what each cover costs per peso of capital relieved</summary>

- On a simulated year of claims the **pandemic is 41% of the claims capital**, and policies of 2 million or more hold 49% of the sum at risk.
- Quota share and surplus treaties cost about 20% of the capital they relieve, a per-life excess of loss 9%, a stop loss 6%. A per-life cover stays worth buying only while the reinsurer asks under 6.9% on its own capital.
- YRT experience rating with credibility that allows for claim-size variability: full credibility takes about 3,000 deaths for amounts, not 1,082.
- A longevity swap on the annuity block needs capital of 3% of the reserve and a fee of about 18 basis points a year.

<table>
<tr>
<td width="50%"><img src="img/reinsurance_risk.png" alt="Reinsurance risk"></td>
<td width="50%"><img src="img/reinsurance_structures.png" alt="Reinsurance structures"></td>
</tr>
</table>

[Full write-up](reinsurance.md)
</details>

<details>
<summary><b>10. Dashboard, workbook and report</b></summary>

- **Streamlit dashboard** (`uv run mortality app`): ten pages (the newest is **Insured lives**) over a shareable demo bundle built from an allow-list of derived tables; four live labs call the same engines the tests check; a Trust page lists all 122 data checks, the sources with checksums and the limits; the app is tested headlessly in CI.
- **Excel workbook** (`uv run mortality export-excel`): lx, dx, Dx, Nx, Cx and Mx as live formulas driven by one interest cell, a premium calculator, a rate card and the stress results; recomputed by an independent formula engine in the tests and matched to the Python functions to 1e-9.
- **Methodology report** ([PDF](../reports/methodology.pdf), Quarto and Typst): 13 pages with a Spanish executive summary; every number in the text is computed from the data bundle when the report is rendered.

[Deployment guide](deploy.md)
</details>

<details>
<summary><b>11. Insured lives</b>: the table for a quote, three traps, a 15% margin</summary>

- The CNSF's individual life statistics 2021 to 2025 give **81,000 deaths** and about **20 million insured lives a year** in the base years 2023 to 2025. Every column total is reconciled to the raw cells.
- **A table family**: traditional term, credit life, and whole life and endowments are graduated on their own (direct and relational P-splines, Gompertz-Makeham and Brass compared by one common dispersion and out-of-sample shape); other term modalities are an age-varying multiple of traditional term; the market-wide table is an exposure-weighted blend.
- **Three traps**: a fifth of death claims are a cancellation-heavy ledger (+11% to +25% on a quote if counted); 2,300 sprain-coded claims are endowment maturities (ages 60 to 69, 3.6 times a normal claim); deaths against the wrong cover would lower a quote by 11%.
- **A man of 40, 20-year term, per 1,000**: 0.85 insured traditional term, 1.20 market, 1.74 CNSF 2013, 2.52 US insured, 6.62 population.
- **The pandemic**: insured death rates up to 2.7 times their 2023 level in 2021 against 1.7 for the population.
- **Not used, and why**: the 2018 to 2020 format (women's share of lives goes 46%, 36%, 37% in three years); above the credible range the table is the population's shape by assumption.

<table>
<tr>
<td width="50%"><img src="img/insured_ledger.png" alt="The ledger"></td>
<td width="50%"><img src="img/insured_old_ages.png" alt="Where the data stop"></td>
</tr>
</table>

[Full write-up](insured-lives.md)
</details>
