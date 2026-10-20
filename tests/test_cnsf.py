import pandas as pd
import pytest

from mortality.config import Paths
from mortality.ingest import cnsf, download


def fake_rate(block: int, age: int) -> float:
    return round(0.0001 * (block + 1) + 0.000001 * age, 6)


def annex_html(blocks: int = 9, drop_last_rate: bool = False, swap_two_ages: bool = False) -> str:
    """Build a page shaped like the CNSF annex: header text, then 3 age/rate columns per row."""
    cells = ['<script>var x = "12";</script><p>Modificación</p>']
    cells.append("<li>Anexo 5.3.3.A Modificado DOF 08-01-2016</li>")
    cells.append("<h2>ANEXO 5.3.3-a</h2><p>Tabla</p><td>CNSF M 2013</td><td>Edad</td><td>2013</td>")
    for block in range(blocks):
        cells.append(f"<td>Edad</td><td>CNSF {block} 2013</td>")
        for row in range(37):
            for age in (row, row + 37, row + 74):
                cells.append(f"<td>{age}</td><td>{fake_rate(block, age):.6f}</td>")
    html = "".join(cells)
    if drop_last_rate:
        html = html.rsplit("<td>", 1)[0]
    if swap_two_ages:
        html = html.replace("<td>1</td><td>", "<td>1</td><td>2</td><td>", 1)
    return f"<html><body>{html}<footer>Pie 2026</footer></body></html>"


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


def test_html_to_lines_strips_tags_scripts_and_entities():
    lines = cnsf.html_to_lines(
        "<script>alert(1)</script><td>A&nbsp;&amp;&nbsp;B</td><td> </td><p>x</p>"
    )
    assert lines == ["A & B", "x"]


def test_parse_annex_reads_nine_tables():
    rates = cnsf.parse_annex(cnsf.html_to_lines(annex_html()))
    assert len(rates) == 9 * 111
    assert rates.groupby(["table", "variant"]).size().eq(111).all()
    assert rates[["table", "variant"]].drop_duplicates().shape[0] == 9
    first = rates[(rates.table == "CNSF M 2013") & (rates.variant == "base")].sort_values("age")
    assert first["age"].tolist() == list(range(111))
    assert first["qx"].iloc[0] == fake_rate(0, 0)
    assert first["qx"].iloc[74] == fake_rate(0, 74)  # third column of the first row
    p05 = rates[(rates.table == "CNSF M 2013") & (rates.variant == "p0.05")]
    assert p05["qx"].iloc[110] == fake_rate(5, 110)  # block order matches the annex


def test_parse_annex_ignores_text_after_the_last_table():
    page = annex_html() + "<p>1</p><p>0.123456</p>"
    assert len(cnsf.parse_annex(cnsf.html_to_lines(page))) == 999


def test_parse_annex_without_marker():
    with pytest.raises(cnsf.CNSFParseError, match="Could not find"):
        cnsf.parse_annex(cnsf.html_to_lines("<p>nothing here</p>"))


def test_parse_annex_with_missing_table():
    with pytest.raises(cnsf.CNSFParseError, match="expected 999"):
        cnsf.parse_annex(cnsf.html_to_lines(annex_html(blocks=8)))


def test_parse_annex_with_truncated_cell():
    with pytest.raises(cnsf.CNSFParseError):
        cnsf.parse_annex(cnsf.html_to_lines(annex_html(drop_last_rate=True)))


def test_parse_annex_detects_layout_change():
    with pytest.raises(cnsf.CNSFParseError, match="Two ages"):
        cnsf.parse_annex(cnsf.html_to_lines(annex_html(swap_two_ages=True)))


def test_parse_annex_rejects_rates_above_one():
    page = annex_html().replace("0.000100", "1.500000", 1)
    with pytest.raises(cnsf.CNSFParseError, match="outside"):
        cnsf.parse_annex(cnsf.html_to_lines(page))


def test_last_modified():
    assert cnsf.last_modified(cnsf.html_to_lines(annex_html())) == "08-01-2016"
    assert cnsf.last_modified(["nothing"]) is None


def test_cross_check_reports_largest_difference():
    page = cnsf.parse_annex(cnsf.html_to_lines(annex_html()))
    pdf = page[page.variant == "base"][["table", "age", "qx"]].copy()
    assert cnsf.cross_check(page, pdf) == 0.0
    pdf.loc[pdf.index[5], "qx"] += 0.0004
    assert cnsf.cross_check(page, pdf) == pytest.approx(0.0004)


def test_cross_check_needs_same_coverage():
    page = cnsf.parse_annex(cnsf.html_to_lines(annex_html()))
    pdf = page[(page.variant == "base") & (page.table == "CNSF M 2013")][["table", "age", "qx"]]
    with pytest.raises(cnsf.CNSFParseError):
        cnsf.cross_check(page, pdf)


class Resp:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body


class Session:
    def __init__(self, page: bytes, pdf: bytes = b"%PDF-1.5 demo"):
        self.page, self.pdf = page, pdf

    def get(self, url, **kwargs):
        return Resp(self.pdf if url.endswith(".pdf") else self.page)


def test_download_and_process(paths):
    session = Session(annex_html().encode())
    results = cnsf.download(session=session, paths=paths)
    assert [r.path.name for r in results] == [cnsf.PAGE_FILE, cnsf.PDF_FILE]
    assert {r["source"] for r in download.read_manifest(paths)} == {"cnsf"}

    target = cnsf.process(paths=paths)
    rates = pd.read_parquet(target)
    assert len(rates) == 999
    assert (rates["annex_modified"] == "08-01-2016").all()
    assert rates["source_url"].eq(cnsf.PAGE_URL).all()


def test_download_rejects_wrong_page(paths):
    with pytest.raises(download.NotAFileError, match=r"Annex 5\.3\.3-a"):
        cnsf.download(session=Session(b"<html>moved</html>"), paths=paths)


def test_download_rejects_non_pdf(paths):
    session = Session(annex_html().encode(), pdf=b"<html>nope</html>")
    with pytest.raises(download.NotAFileError, match="not a PDF"):
        cnsf.download(session=session, paths=paths)


def test_process_needs_download(paths):
    with pytest.raises(FileNotFoundError):
        cnsf.process(paths=paths)
