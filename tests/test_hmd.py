import pytest

from mortality.config import HMDCredentials, Paths
from mortality.ingest import download, hmd

LOGIN_HTML = (
    '<form><input name="ReturnUrl"><input name="Email"><input name="Password">'
    '<input name="__RequestVerificationToken" type="hidden" value="tok123"></form>'
)

DEATHS = """Chile, Deaths (period 1x1), \tLast modified: 12 Jan 2026;  Methods Protocol: v6 (2017)

  Year          Age             Female            Male           Total
  1992           0              1890.00         2319.00         4209.00
  1992           1               150.00          222.00          372.00
  1992         110+                 .              1.00            1.00
"""

LIFE = """Chile, Life tables (period 1x1), Males\tLast modified: 12 Jan 2026

  Year          Age         mx       qx    ax      lx      dx      Lx       Tx     ex
  1992           0      0.02319  0.02250  0.10  100000    2250   97975  6900000  69.00
  1992         110+     0.63850  1.00000  1.57      15      15      24       24   1.57
"""


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


# ── parsing ─────────────────────────────────────────────────────────────────


def test_read_table_deaths():
    df = hmd.read_table(DEATHS)
    assert df["age"].tolist() == [0, 1, 110]
    assert df["age_open"].tolist() == [False, False, True]
    assert df["Female"].isna().tolist() == [False, False, True]  # "." means missing
    assert df["year"].tolist() == [1992, 1992, 1992]


def test_read_table_rejects_garbage():
    with pytest.raises(ValueError):
        hmd.read_table("title\n\n a b\n 1 2\n")


def test_tidy_counts_long_format():
    out = hmd.tidy_counts(hmd.read_table(DEATHS), "CHL")
    assert len(out) == 9  # 3 ages x 3 sexes
    assert set(out["sex"]) == {"F", "M", "T"}
    row = out[(out.age == 0) & (out.sex == "M")].iloc[0]
    assert row["value"] == 2319 and row["country"] == "CHL"


def test_tidy_life_table():
    out = hmd.tidy_life_table(hmd.read_table(LIFE), "CHL", "M")
    assert {"country", "sex", "year", "age", "mx", "qx", "ex"} <= set(out.columns)
    assert out["sex"].unique().tolist() == ["M"]
    lowered = [c.lower() for c in out.columns]
    assert len(lowered) == len(set(lowered))  # no names that differ only by case
    assert {"lx", "person_years", "total_person_years"} <= set(out.columns)


def test_process_builds_three_files(paths):
    folder = paths.raw / "hmd"
    folder.mkdir(parents=True)
    for item in hmd.ITEMS:
        text = DEATHS if item.startswith(("Deaths", "Exposures")) else LIFE
        (folder / f"CHL_{item}.txt").write_text(text, encoding="utf-8")
    written = hmd.process(["CHL"], paths=paths)
    assert set(written) == {"deaths", "exposures", "life_tables"}
    import pandas as pd

    tables = pd.read_parquet(written["life_tables"])
    assert set(tables["sex"]) == {"F", "M", "T"}
    assert len(pd.read_parquet(written["deaths"])) == 9


def test_process_needs_download(paths):
    with pytest.raises(FileNotFoundError):
        hmd.process(["CHL"], paths=paths)


# ── login ───────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, text="", status=200, url="https://www.mortality.org/Home/Index"):
        self.text, self.status_code, self.url = text, status, url
        self.body = text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        yield self.body


class FakeSession:
    def __init__(self, accept=True):
        self.accept, self.headers, self.cookies, self.posted = accept, {}, {}, None

    def get(self, url, **kwargs):
        if url.endswith("/Account/Login"):
            return FakeResponse(LOGIN_HTML, url=url)
        return FakeResponse(DEATHS, url=url)

    def post(self, url, data=None, **kwargs):
        self.posted = data
        if self.accept:
            self.cookies["Authorization"] = "x"
            return FakeResponse(url="https://www.mortality.org/Home/Index")
        return FakeResponse(LOGIN_HTML, url=hmd.LOGIN_URL)


CREDS = HMDCredentials("me@example.com", "pw")


def test_login_posts_token_and_credentials():
    session = hmd.login(CREDS, FakeSession())
    assert session.posted == {
        "Email": "me@example.com",
        "Password": "pw",
        "__RequestVerificationToken": "tok123",
    }


def test_login_failure_message_has_no_password():
    with pytest.raises(hmd.HMDLoginError) as err:
        hmd.login(CREDS, FakeSession(accept=False))
    assert "pw" not in str(err.value).replace("password", "")
    assert "HMD_USERNAME" in str(err.value)


def test_login_without_token_fails():
    class NoToken(FakeSession):
        def get(self, url, **kwargs):
            return FakeResponse("<html>nothing</html>", url=url)

    with pytest.raises(hmd.HMDLoginError, match="token"):
        hmd.login(CREDS, NoToken())


# ── downloading ─────────────────────────────────────────────────────────────


def test_download_item_saves_and_logs(paths):
    result = hmd.download_item("CHL", "Deaths_1x1", session=FakeSession(), paths=paths)
    assert result.path.name == "CHL_Deaths_1x1.txt"
    assert download.read_manifest(paths)[0]["source"] == "hmd"
    assert "hmd.v6/CHL/STATS/Deaths_1x1.txt" in download.read_manifest(paths)[0]["url"]


def test_html_instead_of_table_is_rejected(paths):
    class Expired(FakeSession):
        def get(self, url, **kwargs):
            return FakeResponse(LOGIN_HTML, url=url)

    with pytest.raises(download.NotAFileError):
        hmd.download_item("CHL", "Deaths_1x1", session=Expired(), paths=paths)
    assert not list((paths.raw / "hmd").glob("*"))


def test_download_countries_fetches_every_item(paths):
    results = hmd.download_countries(["CHL", "ESP"], session=FakeSession(), paths=paths, pause=0)
    assert len(results) == 2 * len(hmd.ITEMS)
    assert len(download.read_manifest(paths)) == 2 * len(hmd.ITEMS)


def test_default_countries_exclude_mexico():
    assert "MEX" not in hmd.DEFAULT_COUNTRIES
    assert {"USA", "CAN", "CHL", "ESP"} <= set(hmd.DEFAULT_COUNTRIES)
