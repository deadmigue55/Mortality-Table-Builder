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

### CONAPO: Conciliación Demográfica 1950–2019 and Proyecciones 2020–2070
- **What:** mid-year population by single year of age, sex and state.
- **Why:** the denominator (central exposure, E<sub>x</sub>).
- **Where:** CONAPO open data on gob.mx / datos.gob.mx. The [data dictionary](https://www.gob.mx/cms/uploads/attachment/file/847790/DICCIONARIO_2023_v3_07082023.pdf) describes the mid-year population table (year, state, age, sex, population).
- **Notes:** the conciliation harmonizes censuses, surveys and administrative records. CONAPO also publishes its own deaths and life-table indicators, which we use as a cross-check.

## Mexico: regulatory and industry tables

### CNSF (Comisión Nacional de Seguros y Fianzas) and AMIS
- **What:** tables used by Mexican insurers for pricing and reserves, e.g. **CNSF 2000-I** (individual insurance experience) and **EMSSA-09** (social security / pensions experience).
- **Why:** the regulatory benchmark. The CNSF builds its tables from insurer data and deliberately overstates mortality for solvency. A 2021 study using INEGI data found estimates substantially different from EMSSA-09 ([UNAM/INEGI research](https://rde.inegi.org.mx/rde_14/doctos/rde_14_art1.pdf); [UNAM thesis repository](https://ru.dgb.unam.mx/bitstream/20.500.14330/TES01000840308/3/0840308.pdf)).
- **Where:** CNSF publications and the Circular Única de Seguros y Fianzas (CUSF). The tables currently in force must be confirmed against the latest CUSF and the Diario Oficial de la Federación before use.

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
- **Citation:** HMD. Human Mortality Database. Max Planck Institute for Demographic Research (Germany), University of California, Berkeley (USA), and French Institute for Demographic Studies (France). Available at www.mortality.org (data downloaded on [date]).

## Download log

Each download script appends to `data/raw/MANIFEST.csv`: source, file, URL, download date and SHA-256 checksum, so every result can be traced back to its exact inputs.
