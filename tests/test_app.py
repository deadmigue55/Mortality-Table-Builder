"""The dashboard: every page runs on the committed demo bundle, and the bundle is safe to share."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from mortality import demo

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
BUNDLE = APP / "data" / "demo.sqlite"
PAGES = sorted(p.stem for p in (APP / "views").glob("*.py"))

pytestmark = pytest.mark.skipif(not BUNDLE.exists(), reason="demo bundle not built")


@pytest.fixture(scope="module", autouse=True)
def app_on_path():
    sys.path.insert(0, str(APP))
    yield
    sys.path.remove(str(APP))


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_errors(page):
    at = AppTest.from_file(str(APP / "views" / f"{page}.py"), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_entry_point_builds_the_navigation():
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]


def test_bundle_holds_no_hmd_or_raw_microdata():
    assert demo.forbidden_in(BUNDLE) == []
    assert demo.hmd_rows_in(BUNDLE) == 0


def test_bundle_is_small_enough_to_commit():
    total = sum(f.stat().st_size for f in (APP / "data").iterdir())
    assert total < 15e6


def test_bundle_has_every_table_the_pages_read():
    con = sqlite3.connect(BUNDLE)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    con.close()
    needed = {"life_tables", "graduated_qx", "cnsf_rates", "projected_qx", "excess_mortality",
              "experience_basis", "validation_results", "pricing_premiums",
              "insured_table", "insured_premiums", "insured_sensitivity", "insured_pandemic",
              "insured_causes", "insured_ledger", "insured_relativities"}  # fmt: skip
    assert needed <= have
