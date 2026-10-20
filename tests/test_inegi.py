import io
import struct
import zipfile

import pandas as pd
import pytest

from mortality.config import Paths
from mortality.ingest import download, inegi


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


# ── helpers ─────────────────────────────────────────────────────────────────


def make_dbf(rows: list[dict[str, str]]) -> bytes:
    """Build a minimal dBase III file with character fields (enough for dbfread)."""
    names = list(rows[0])
    widths = {n: max(len(r[n]) for r in rows) or 1 for n in names}
    header_len = 32 + 32 * len(names) + 1
    record_len = 1 + sum(widths.values())
    out = io.BytesIO()
    out.write(struct.pack("<BBBBIHH20x", 3, 126, 1, 1, len(rows), header_len, record_len))
    for n in names:
        out.write(struct.pack("<11sc4xBB14x", n.encode(), b"C", widths[n], 0))
    out.write(b"\r")
    for r in rows:
        out.write(b" " + b"".join(r[n].ljust(widths[n]).encode("latin-1") for n in names))
    out.write(b"\x1a")
    return out.getvalue()


def make_zip(dbf_name: str, rows: list[dict[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(dbf_name, make_dbf(rows))
        zf.writestr("Descripcion_BD.pdf", b"%PDF-")
    return buf.getvalue()


ROWS = [
    {"SEXO": "1", "EDAD": "4065", "ENT_RESID": "09", "ANIO_OCUR": "2024", "MES_OCURR": "03",
     "ANIO_REGIS": "2024", "TIPO_DEFUN": "4", "CAUSA_DEF": "I219", "LISTA_MEX": "28"},
    {"SEXO": "2", "EDAD": "2005", "ENT_RESID": "15", "ANIO_OCUR": "2023", "MES_OCURR": "12",
     "ANIO_REGIS": "2024", "TIPO_DEFUN": "4", "CAUSA_DEF": "P220", "LISTA_MEX": "50"},
    {"SEXO": "9", "EDAD": "4998", "ENT_RESID": "99", "ANIO_OCUR": "9999", "MES_OCURR": "99",
     "ANIO_REGIS": "2024", "TIPO_DEFUN": "9", "CAUSA_DEF": "R99", "LISTA_MEX": "99"},
]  # fmt: skip


# ── age decoding ────────────────────────────────────────────────────────────


def test_decode_edad():
    out = inegi.decode_edad(
        pd.Series(["4065", "4001", "4120", "3011", "2005", "1012", "4998", "0", "7001"])
    )
    assert out["age_years"].tolist() == [65, 1, 120, 0, 0, 0, pd.NA, pd.NA, pd.NA]
    assert out["age_unit"].tolist() == [
        "years",
        "years",
        "years",
        "months",
        "days",
        "hours",
        pd.NA,
        pd.NA,
        pd.NA,
    ]
    assert out["age_value"].tolist()[:2] == [65, 1]


def test_decode_edad_handles_numbers_and_junk():
    out = inegi.decode_edad(pd.Series([4040, None, "abc"]))
    assert out["age_years"].tolist() == [40, pd.NA, pd.NA]


# ── cleaning ────────────────────────────────────────────────────────────────


def raw_frame():
    return pd.DataFrame(ROWS)


def test_clean_deaths_columns_and_values():
    out = inegi.clean_deaths(raw_frame(), 2024)
    assert out["sex"].tolist() == ["M", "F", pd.NA]
    assert out["age_years"].tolist() == [65, 0, pd.NA]
    assert out["state"].tolist() == ["09", "15", "99"]
    assert out["resident_in_mexico"].tolist() == [True, True, False]
    assert out["occ_year"].tolist() == [2024, 2023, pd.NA]  # 9999 means unknown
    assert out["occ_month"].tolist() == [3, 12, pd.NA]
    assert (out["file_year"] == 2024).all()


def test_clean_deaths_flags_foreign_residents():
    raw = raw_frame().assign(ENT_RESID=["33", "01", "32"])
    out = inegi.clean_deaths(raw, 2024)
    assert out["resident_in_mexico"].tolist() == [False, True, True]


def test_clean_deaths_requires_core_columns():
    with pytest.raises(KeyError):
        inegi.clean_deaths(raw_frame().drop(columns=["EDAD"]), 2024)


# ── reading and processing ──────────────────────────────────────────────────


def test_read_deaths_zip(tmp_path):
    zip_path = tmp_path / "d.zip"
    zip_path.write_bytes(make_zip("DEFUN24.dbf", ROWS))
    df = inegi.read_deaths_zip(zip_path, 2024)
    assert len(df) == 3
    assert df["cause"].tolist() == ["I219", "P220", "R99"]
    assert df["age_years"].tolist() == [65, 0, pd.NA]


def test_read_deaths_zip_finds_lowercase_member(tmp_path):
    zip_path = tmp_path / "d.zip"
    zip_path.write_bytes(make_zip("defun22.DBF", ROWS))
    assert len(inegi.read_deaths_zip(zip_path, 2022)) == 3


def test_read_deaths_zip_without_death_table(tmp_path):
    zip_path = tmp_path / "d.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("OTHER.dbf", b"")
    with pytest.raises(FileNotFoundError):
        inegi.read_deaths_zip(zip_path, 2024)


def test_process_year_writes_parquet(paths):
    folder = paths.raw / "inegi"
    folder.mkdir(parents=True)
    (folder / inegi.zip_name(2024)).write_bytes(make_zip("DEFUN24.dbf", ROWS))
    target = inegi.process_year(2024, paths=paths)
    assert target == paths.processed / "inegi" / "deaths_2024.parquet"
    df = pd.read_parquet(target)
    assert len(df) == 3
    assert inegi.process_year(2024, paths=paths) == target  # reused, not rebuilt


def test_process_year_needs_download(paths):
    with pytest.raises(FileNotFoundError):
        inegi.process_year(2019, paths=paths)


# ── URLs and downloading ────────────────────────────────────────────────────


def test_candidate_urls_order():
    assert "/edr/" in inegi.candidate_urls(2024)[0]
    assert "/mortalidad/" in inegi.candidate_urls(2021)[0]
    assert all(
        u.endswith("defunciones_base_datos_2022_dbf.zip") for u in inegi.candidate_urls(2022)
    )


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body


class RoutedSession:
    """Serves a real ZIP only for URLs containing ``good``; HTML for everything else."""

    def __init__(self, good: str, zip_body: bytes):
        self.good, self.zip_body, self.seen = good, zip_body, []

    def get(self, url, **kwargs):
        self.seen.append(url)
        return Resp(self.zip_body if self.good in url else b"<!DOCTYPE html>not found")


def test_download_year_falls_back_to_next_url(paths):
    session = RoutedSession("/mortalidad/", make_zip("DEFUN23.dbf", ROWS))
    result = inegi.download_year(2023, session=session, paths=paths)
    assert len(session.seen) == 2  # first guess (edr) was HTML, second worked
    assert "/mortalidad/" in result.url
    assert result.path.name == inegi.zip_name(2023)


def test_download_year_gives_helpful_error(paths):
    session = RoutedSession("nothing-matches", b"")
    with pytest.raises(FileNotFoundError, match=r"inegi\.org\.mx/programas/edr"):
        inegi.download_year(2010, session=session, paths=paths)
    assert download.read_manifest(paths) == []


def test_download_year_reuses_local_file(paths):
    folder = paths.raw / "inegi"
    folder.mkdir(parents=True)
    (folder / inegi.zip_name(2010)).write_bytes(make_zip("DEFUN10.dbf", ROWS))
    session = RoutedSession("zzz", b"")
    result = inegi.download_year(2010, session=session, paths=paths)
    assert result.skipped and session.seen == []


# ── year arguments ──────────────────────────────────────────────────────────


def test_parse_years():
    assert inegi.parse_years(["2020-2022", "2024"]) == [2020, 2021, 2022, 2024]
    assert inegi.parse_years(["2020,2018"]) == [2018, 2020]
    with pytest.raises(ValueError):
        inegi.parse_years(["2024-2020"])
