"""Human Mortality Database (mortality.org): comparison countries.

HMD requires a free login and its terms allow scientific use only and forbid
redistributing the data, so raw files stay in ``data/raw/hmd`` (git-ignored). Mexico is
not an HMD country; these populations are the international benchmark for Mexico's tables.

Per country we keep five period files at single-year-of-age resolution (1x1):
deaths, exposure-to-risk and the female, male and both-sexes life tables.

Citation: Human Mortality Database. Max Planck Institute for Demographic Research
(Germany), University of California, Berkeley (USA), and French Institute for
Demographic Studies (France). www.mortality.org (data downloaded in October 2026).
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

from mortality.config import HMDCredentials, Paths, get_paths, hmd_credentials
from mortality.ingest.download import USER_AGENT, Download, NotAFileError, fetch

SOURCE = "hmd"
BASE = "https://www.mortality.org"
LOGIN_URL = f"{BASE}/Account/Login"
FILE_URL = BASE + "/File/GetDocument/hmd.v6/{country}/STATS/{item}.txt"

# United States and Canada (North America), Chile (Latin America), Spain / Italy / France
# (Southern Europe), Japan (longevity leader), Sweden (longest clean series), United Kingdom.
DEFAULT_COUNTRIES = ("USA", "CAN", "CHL", "ESP", "ITA", "FRATNP", "JPN", "SWE", "GBR_NP")

ITEMS = ("Deaths_1x1", "Exposures_1x1", "bltper_1x1", "mltper_1x1", "fltper_1x1")
PAUSE_SECONDS = 0.5  # be polite to a free academic service

SEX_BY_COLUMN = {"Female": "F", "Male": "M", "Total": "T"}
SEX_BY_LIFE_TABLE = {"bltper": "T", "mltper": "M", "fltper": "F"}


class HMDLoginError(RuntimeError):
    """Login failed (wrong credentials, or the account needs to be re-registered)."""


# ── Session ─────────────────────────────────────────────────────────────────


def login(
    creds: HMDCredentials | None = None, session: requests.Session | None = None
) -> requests.Session:
    """Log in to mortality.org and return the authenticated session."""
    creds = creds or hmd_credentials()
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)

    page = http.get(LOGIN_URL, timeout=30)
    page.raise_for_status()
    token = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page.text
    ) or re.search(r'value="([^"]+)"[^>]*name="__RequestVerificationToken"', page.text)
    if not token:
        raise HMDLoginError("Could not find the login form's security token (site changed?).")

    resp = http.post(
        LOGIN_URL,
        data={
            "Email": creds.username,
            "Password": creds.password,
            "__RequestVerificationToken": token.group(1),
        },
        timeout=30,
    )
    if (
        resp.status_code != 200
        or "Account/Login" in resp.url
        or "Authorization" not in http.cookies
    ):
        raise HMDLoginError(
            "HMD login failed. Check HMD_USERNAME and HMD_PASSWORD in .env "
            "(accounts created before July 2022 must re-register at mortality.org)."
        )
    return http


def _check_text_table(path: Path) -> None:
    """Reject HTML (e.g. an expired-login page) saved in place of a data file."""
    with path.open("rb") as handle:
        head = handle.read(600).decode("utf-8", errors="replace").lower()
    if "<html" in head or "<!doctype" in head or "year" not in head:
        raise NotAFileError(f"{path.name} is not an HMD data table (login expired?)")


def download_item(
    country: str,
    item: str,
    *,
    session: requests.Session,
    force: bool = False,
    paths: Paths | None = None,
) -> Download:
    return fetch(
        FILE_URL.format(country=country, item=item),
        source=SOURCE,
        filename=f"{country}_{item}.txt",
        force=force,
        session=session,
        paths=paths,
        validate=_check_text_table,
    )


def download_countries(
    countries: tuple[str, ...] | list[str] = DEFAULT_COUNTRIES,
    *,
    session: requests.Session | None = None,
    force: bool = False,
    paths: Paths | None = None,
    pause: float = PAUSE_SECONDS,
) -> list[Download]:
    """Download every item for each country (logging in once)."""
    http = session or login()
    results: list[Download] = []
    for country in countries:
        for item in ITEMS:
            result = download_item(country, item, session=http, force=force, paths=paths)
            results.append(result)
            if not result.skipped:
                time.sleep(pause)
    return results


# ── Parsing ─────────────────────────────────────────────────────────────────


def read_table(text: str) -> pd.DataFrame:
    """Parse an HMD text table (a title line, a blank line, then whitespace-separated columns).

    ``Age`` becomes an integer, with ``age_open`` marking the open-ended top group ("110+").
    """
    df = pd.read_csv(
        io.StringIO(text),
        sep=r"\s+",
        skiprows=2,
        na_values=["."],
        dtype={"Age": "string"},
    )
    if not {"Year", "Age"} <= set(df.columns):
        raise ValueError("Unexpected HMD table: no Year/Age columns.")
    age = df["Age"].str.strip()
    df["age_open"] = age.str.endswith("+")
    df["Age"] = pd.to_numeric(age.str.rstrip("+"), errors="raise").astype("int16")
    df["Year"] = pd.to_numeric(df["Year"], errors="raise").astype("int16")
    return df.rename(columns={"Year": "year", "Age": "age"})


def _stem(item: str) -> str:
    return item.split("_")[0]


def tidy_counts(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """Deaths or exposures: Female / Male / Total columns become one row per sex."""
    long = df.melt(
        id_vars=["year", "age", "age_open"],
        value_vars=list(SEX_BY_COLUMN),
        var_name="sex",
        value_name="value",
    )
    long["sex"] = long["sex"].map(SEX_BY_COLUMN)
    long.insert(0, "country", country)
    return long


def tidy_life_table(df: pd.DataFrame, country: str, sex: str) -> pd.DataFrame:
    # lx (survivors) and Lx (person-years) differ only by case, which SQL treats as the same
    # name, so the capitalised ones get descriptive names.
    out = df.rename(columns={"Lx": "person_years", "Tx": "total_person_years"}).copy()
    out.insert(0, "sex", sex)
    out.insert(0, "country", country)
    return out


def process(
    countries: tuple[str, ...] | list[str] = DEFAULT_COUNTRIES,
    *,
    paths: Paths | None = None,
) -> dict[str, Path]:
    """Build ``deaths``, ``exposures`` and ``life_tables`` Parquet files for all countries."""
    paths = (paths or get_paths()).ensure()
    raw = paths.raw / SOURCE
    out_dir = paths.processed / SOURCE
    out_dir.mkdir(parents=True, exist_ok=True)

    deaths, exposures, tables = [], [], []
    for country in countries:
        for item in ITEMS:
            file = raw / f"{country}_{item}.txt"
            if not file.exists():
                raise FileNotFoundError(f"{file} not found. Run the download first.")
            df = read_table(file.read_text(encoding="utf-8"))
            stem = _stem(item)
            if stem == "Deaths":
                deaths.append(tidy_counts(df, country))
            elif stem == "Exposures":
                exposures.append(tidy_counts(df, country))
            else:
                tables.append(tidy_life_table(df, country, SEX_BY_LIFE_TABLE[stem]))

    written = {}
    for name, frames in (("deaths", deaths), ("exposures", exposures), ("life_tables", tables)):
        target = out_dir / f"{name}.parquet"
        pd.concat(frames, ignore_index=True).to_parquet(target, index=False)
        written[name] = target
    return written
