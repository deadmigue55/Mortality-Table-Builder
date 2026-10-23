# Putting the dashboard online

The dashboard reads one small file, `app/data/demo.sqlite` (about 3.5 MB), plus two others in `app/data/`. Nothing else is needed, so it deploys anywhere Streamlit runs. The bundle contains only derived tables: no raw data and no Human Mortality Database data (a test fails if either appears).

## Streamlit Community Cloud (free)

1. Sign in at <https://share.streamlit.io> with GitHub and choose **Create app**.
2. Repository: `deadmigue55/Mortality-Table-Builder`, branch `main`, main file path `app/streamlit_app.py`.
3. Advanced settings: Python **3.12**.
4. Deploy. The first start installs the dependencies from `pyproject.toml` (about two minutes).
5. Set sharing to **public** (app menu, Settings, Sharing); a private app sends every visitor to a login page. The deployed app is <https://mortality-table-builder.streamlit.app/>.
6. Add the public URL to the README (a line under the badges) and to the portfolio site.

The app sleeps after about 12 hours without a visitor on the free tier and wakes on the next visit, which then waits behind a wake-up page. To avoid that for the first visitor, `.github/workflows/keep-alive.yml` opens the app in a real browser every six hours (`scripts/keep_alive.py`, Playwright), clicks the wake-up button if it finds one, and fails, which makes GitHub email the owner, if the app is down or shows "Error running app". A plain HTTP request does not count as a visit; a browser does. GitHub pauses scheduled workflows after 60 days without a commit to the repository: any commit, or **Run workflow** in the Actions tab, restarts them.

## Run it locally

```sh
uv sync --all-extras
uv run mortality app
```

## Refreshing the data

After rebuilding the warehouse (`uv run mortality db build`), refresh the bundle and the workbook, then commit:

```sh
uv run mortality app-data
uv run mortality export-excel
```

`mortality app-data` refuses to finish if a table outside its allow-list, or a row from the Human Mortality Database, ends up in the bundle.

## The report

```sh
quarto render reports/methodology.qmd
```

needs [Quarto](https://quarto.org) 1.4 or newer. The PDF is built with Typst, which Quarto bundles, so no LaTeX is required. Numbers in the text are computed from the bundle when the report renders.
