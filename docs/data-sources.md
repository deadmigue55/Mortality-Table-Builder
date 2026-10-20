# Data sources

Raw data is never committed to this repository. Download scripts (roadmap step 2) fetch each source into `data/raw/`, and every downloaded file is logged with its source URL and download date.

## Mexico: population mortality

### INEGI: Estadísticas de Defunciones Registradas (EDR)
- **What:** registered deaths microdata, one row per death, with age, sex, state and municipality of residence, cause of death (ICD-10), and year of occurrence and registration.
- **Why:** the numerator (deaths, D<sub>x</sub>) for the Mexican tables.
- **Where:** inegi.org.mx, Estadísticas de Defunciones Registradas (microdata and open data). Variable dictionaries are in the [INEGI microdata catalog](https://www.inegi.org.mx/rnm/index.php/catalog/1140).
- **Notes:**
  - Deaths are recorded mainly through the Civil Registry and forensic medical services (SEMEFO), based on the death certificate.
  - From the 2024 edition, electronic death certificates from the Health Secretariat feed the statistics, so watch for breaks in the series.
  - Use **year of occurrence**, not year of registration, and allow for late registration in the most recent years.

**How the files work (verified October 2026):**

| Item | Detail |
|---|---|
| Download | One DBF ZIP per *registration* year, about 30 MB, containing `DEFUNyy.dbf` (about 800,000 to 1,100,000 rows, 74 columns), code catalogs and a PDF description |
| Locations | 2023 onward: `contenidos/programas/edr/microdatos/defunciones/<year>/defunciones_base_datos_<year>_dbf.zip`. 2020 to 2022: the same name under `programas/mortalidad/microdatos/defunciones/<year>/`. Earlier years are **not** at these addresses; INEGI answers bad URLs with a normal-looking HTML page, so the downloader checks that it received a real ZIP |
| Age | `EDAD` is a 4-digit code: first digit = unit (1 hours, 2 days, 3 months, 4 years), last three = value. `4998` = not specified |
| Sex | `SEXO`: 1 male, 2 female, 9 not specified (about 0.1% of deaths) |
| Residence | `ENT_RESID`: 01 to 32 are states, 33 and 34 residents abroad, 99 not specified |
| Late registration | Each file also holds deaths that occurred in earlier years (about 2% of a file). A year of occurrence is complete only after the *next* year's file is loaded, so the latest year is always understated |
| Unknown dates | `ANIO_OCUR = 9999` means year of occurrence unknown (about 330 deaths per file) |

**What we kept from the 74 columns:** sex, age code (decoded into unit, value and completed years), state of residence, year and month of occurrence, year of registration, type of death, cause (ICD-10) and the Mexican cause list.

### CONAPO: Conciliación Demográfica 1950–2019 and Proyecciones 2020–2070
- **What:** mid-year population by single year of age, sex and state.
- **Why:** the denominator (central exposure, E<sub>x</sub>).
- **Where:** CONAPO open data on gob.mx / datos.gob.mx. The [data dictionary](https://www.gob.mx/cms/uploads/attachment/file/847790/DICCIONARIO_2023_v3_07082023.pdf) describes the mid-year population table (year, state, age, sex, population).
- **Notes:** the conciliation harmonizes censuses, surveys and administrative records. CONAPO also publishes its own deaths and life-table indicators, which we use as a cross-check.

**How the file works (verified October 2026):** a single 80 MB ZIP (`ConDem50a19_ProyPob20a70.zip`, published August 2023) with long-format Excel workbooks: one row per year, state (national plus 32), single age 0 to 109 and sex.

| Workbook | Use |
|---|---|
| `0_Pob_Mitad_1950_2070.xlsx` | Mid-year (1 July) population, the exposure. State rows add up exactly to the national total |
| `1_Defunciones_1950_2070.xlsx` | CONAPO's modelled deaths, a cross-check against INEGI |
| `6_Esperanza_Vida_Nacer_1950_2070.xlsx` | Life expectancy at birth (74.8 in 2019, 68.9 in 2020, 68.8 in 2021) |

**Important:** 1950 to 2019 are reconciled estimates, but **2020 onward are projections** from the 2020 census base made before the full COVID-19 impact was known. Recent exposure is therefore a model output, not a count, and modelled 2022 deaths (about 789,000) sit below INEGI's registered 832,000. Rates for 2020 onward carry that uncertainty, which the project reports instead of hiding.

## Mexico: regulatory and industry tables

### CNSF (Comisión Nacional de Seguros y Fianzas)
- **What:** the **CNSF 2013** tables, the regulatory mortality tables currently in force in Mexico for life insurance pricing and reserves. Older tables (e.g. **CNSF 2000-I**, **EMSSA-09** for pensions) are kept as historical comparisons.
- **Why:** the regulatory benchmark. The CNSF builds its tables from insurer data and deliberately overstates mortality for solvency. A 2021 study using INEGI data found estimates substantially different from EMSSA-09 ([UNAM/INEGI research](https://rde.inegi.org.mx/rde_14/doctos/rde_14_art1.pdf); [UNAM thesis repository](https://ru.dgb.unam.mx/bitstream/20.500.14330/TES01000840308/3/0840308.pdf)).
- **Where:** CNSF publications and the Circular Única de Seguros y Fianzas (CUSF).
- **Context:**
  - The 2013 tables rest on experience that is now over a decade old, so they predate the COVID-19 years and recent mortality improvement. That gap is part of the motivation for this project.
  - In practice, each insurer also builds its own experience tables, which are not public. A transparent population table built from official data is the closest public substitute and a useful check on both.

## United States: industry benchmarks

### Society of Actuaries: Mortality and Other Rate Tables (MORT)
- **What:** hundreds of published tables in XTbML (XML), CSV and Excel, e.g. **2017 CSO** (life insurance valuation), **2012 IAM** (individual annuities) and **Pri-2012** (private pension plans).
- **Why:** industry-standard benchmarks and a check on our table-building methods.
- **Where:** [mort.soa.org](https://mort.soa.org/Help.aspx). The R package [mortSOA](https://cloud.r-project.org/web/packages/mortSOA/refman/mortSOA.html) reads tables by ID. Pri-2012 background is on the [SOA Pri-2012 page](https://www.soa.org/resources/experience-studies/2019/pri-2012-private-mortality-tables/).

## International comparison

### Human Mortality Database (HMD)
- **What:** high-quality period and cohort life tables, deaths and exposures for about 40 countries. Mexico is **not** included, which is why this project builds its own Mexican tables.
- **Why:** comparison countries (e.g. USA, Spain, Chile, Canada) and long series for fitting projection models.
- **Access:** free, but requires [registration](https://www.mortality.org/Account/Auth) and accepting the user agreement. Credentials go in a local `.env` file, never in the repo.
- **Terms (summary, check the current agreement):** scientific use only; cite HMD as the source; do not redistribute the data. Data is downloaded locally and never committed.
- **How we use it:** `uv run mortality ingest hmd` logs in with the credentials in `.env` and downloads, for nine comparison countries, five period files at single-year-of-age resolution (deaths, exposure-to-risk, and female / male / both-sexes life tables). Countries: USA, Canada, Chile (Latin America), Spain, Italy, France (total population), Japan (longevity leader), Sweden (longest clean series) and the United Kingdom.
- **Coverage (October 2026):** Sweden from 1751, France from 1816, USA from 1933, Chile from 1992; most series end in 2022 to 2024. Rates recomputed from deaths and exposure match HMD's published rates (median difference 0.03%); the larger gaps are tiny-count cells at the oldest ages.
- **Naming note:** HMD's `lx` (survivors) and `Lx` (person-years) differ only by case, which SQL treats as one name, so `Lx` and `Tx` are stored as `person_years` and `total_person_years`.
- **Citation:** HMD. Human Mortality Database. Max Planck Institute for Demographic Research (Germany), University of California, Berkeley (USA), and French Institute for Demographic Studies (France). Available at www.mortality.org (data downloaded on [date]).

## Download log

Each download script appends to `data/raw/MANIFEST.csv`: source, file, URL, download date and SHA-256 checksum, so every result can be traced back to its exact inputs.
