"""CNSF 2013: the Mexican regulatory mortality tables currently in force.

Source: Annex 5.3.3-a of the *Circular Única de Seguros y Fianzas* (CUSF), published on the
CNSF's own site ("CNSF Interactiva"). The annex holds nine tables of one-year death or
claim rates for ages 0 to 110, all **mixed-sex** (men and women together):

* four base tables: mortality (``CNSF M``), disability (``Inv``), accidental death
  (``MAcc``) and other benefits (``Otros``);
* five percentile variants used for solvency stress: mortality at the 99.5th percentile
  (higher mortality), mortality at the 0.05th percentile (lower mortality, for private
  pensions), and disability, accidental death and other benefits at the 99.5th percentile.

The tables were built from insurer experience and are published by the regulator; they
are not population mortality. The earlier PDF of the base tables (gob.mx) is used only as
a cross-check.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from mortality.config import Paths, get_paths
from mortality.ingest.download import Download, NotAFileError, fetch

SOURCE = "cnsf"
PAGE_URL = "https://lisfcusf.cnsf.gob.mx/CUSF/A_5_3_3_A"
PDF_URL = "https://www.gob.mx/cms/uploads/attachment/file/73530/ANEXO_5.3.3-a.pdf"
PAGE_FILE = "CUSF_Anexo_5_3_3_A.html"
PDF_FILE = "ANEXO_5.3.3-a.pdf"

AGE_MIN, AGE_MAX = 0, 110
START_MARKER = "ANEXO 5.3.3-a"


@dataclass(frozen=True)
class Block:
    """One of the nine tables, in the order they appear in the annex."""

    table: str
    variant: str  # "base", "p99.5" or "p0.05"
    covers: str


BLOCKS: tuple[Block, ...] = (
    Block("CNSF M 2013", "base", "death of non-disabled lives"),
    Block("CNSF Inv 2013", "base", "disability"),
    Block("CNSF MAcc 2013", "base", "accidental death"),
    Block("CNSF Otros 2013", "base", "other benefits"),
    Block("CNSF M 2013", "p99.5", "death, 99.5th percentile (higher mortality)"),
    Block("CNSF M 2013", "p0.05", "death, 0.05th percentile (lower mortality, private pensions)"),
    Block("CNSF Inv 2013", "p99.5", "disability, 99.5th percentile"),
    Block("CNSF MAcc 2013", "p99.5", "accidental death, 99.5th percentile"),
    Block("CNSF Otros 2013", "p99.5", "other benefits, 99.5th percentile"),
)

_AGE = re.compile(r"\d{1,3}")
_RATE = re.compile(r"\d\.\d{3,8}")
_MODIFIED = re.compile(r"Anexo 5\.3\.3\.A\s+Modificado DOF\s+(\d{2}-\d{2}-\d{4})")


class CNSFParseError(ValueError):
    """The annex does not look like we expect (layout changed, or incomplete download)."""


# ── Download ────────────────────────────────────────────────────────────────


def _check_page(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if START_MARKER not in text:
        raise NotAFileError("The CNSF page does not contain Annex 5.3.3-a (page moved?).")


def _check_pdf(path: Path) -> None:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise NotAFileError(f"{path.name} is not a PDF")


def download(
    *,
    force: bool = False,
    session: requests.Session | None = None,
    paths: Paths | None = None,
) -> list[Download]:
    """Download the annex page (primary source) and the older gob.mx PDF (cross-check)."""
    return [
        fetch(
            PAGE_URL,
            source=SOURCE,
            filename=PAGE_FILE,
            force=force,
            session=session,
            paths=paths,
            validate=_check_page,
        ),
        fetch(
            PDF_URL,
            source=SOURCE,
            filename=PDF_FILE,
            force=force,
            session=session,
            paths=paths,
            validate=_check_pdf,
        ),
    ]


# ── Parsing ─────────────────────────────────────────────────────────────────


def html_to_lines(page: str) -> list[str]:
    """Strip tags and entities; one non-empty trimmed string per line."""
    page = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page)).replace("\xa0", " ")
    return [line.strip() for line in text.splitlines() if line.strip()]


def last_modified(lines: list[str]) -> str | None:
    """Date (dd-mm-yyyy) the CNSF lists for the latest change to Annex 5.3.3.A."""
    joined = "\n".join(lines)
    dates = _MODIFIED.findall(joined)
    return dates[-1] if dates else None


def parse_annex(lines: list[str]) -> pd.DataFrame:
    """Extract all nine tables from the annex text.

    Cells appear as alternating age / rate lines, three age columns per row, so each table
    contributes ``AGE_MAX + 1`` age-rate pairs in sequence.
    """
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(START_MARKER))
    except StopIteration:
        raise CNSFParseError(f"Could not find '{START_MARKER}' in the page.") from None

    pairs_per_table = AGE_MAX - AGE_MIN + 1
    needed = pairs_per_table * len(BLOCKS)

    ages: list[int] = []
    rates: list[float] = []
    expect_age = True
    for line in lines[start:]:
        if expect_age:
            if _AGE.fullmatch(line):
                ages.append(int(line))
                expect_age = False
        elif _RATE.fullmatch(line):
            rates.append(float(line))
            expect_age = True
        elif _AGE.fullmatch(line):
            raise CNSFParseError(f"Two ages in a row near {line!r}: the layout changed.")
        if len(rates) == needed:
            break

    if len(rates) < needed:
        raise CNSFParseError(f"Found {len(rates)} rates, expected {needed}.")

    frames = []
    for number, block in enumerate(BLOCKS):
        lo = number * pairs_per_table
        hi = lo + pairs_per_table
        frame = pd.DataFrame({"age": ages[lo:hi], "qx": rates[lo:hi]})
        if sorted(frame["age"]) != list(range(AGE_MIN, AGE_MAX + 1)):
            raise CNSFParseError(
                f"{block.table} ({block.variant}): ages 0-110 are not all present."
            )
        if not frame["qx"].between(0, 1).all():
            raise CNSFParseError(f"{block.table} ({block.variant}): a rate is outside [0, 1].")
        frame = frame.sort_values("age", ignore_index=True)
        frame.insert(0, "covers", block.covers)
        frame.insert(0, "variant", block.variant)
        frame.insert(0, "table", block.table)
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["age"] = out["age"].astype("int16")
    return out


def parse_pdf_base_tables(pdf_path: Path) -> pd.DataFrame:
    """Read the four base tables from the older gob.mx PDF (used to cross-check the page)."""
    from pypdf import PdfReader  # imported here: only needed for the cross-check

    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    tokens = re.findall(r"(?<![\d.])(\d{1,3})\s+(\d\.\d{3,8})(?![\d])", text)
    needed = (AGE_MAX - AGE_MIN + 1) * 4
    if len(tokens) < needed:
        raise CNSFParseError(f"PDF: found {len(tokens)} age-rate pairs, expected {needed}.")
    frames = []
    for number, block in enumerate(BLOCKS[:4]):
        chunk = tokens[number * 111 : (number + 1) * 111]
        frame = pd.DataFrame(chunk, columns=["age", "qx"]).astype({"age": "int16", "qx": "float64"})
        frame.insert(0, "table", block.table)
        frames.append(frame.sort_values("age", ignore_index=True))
    return pd.concat(frames, ignore_index=True)


def cross_check(page_rates: pd.DataFrame, pdf_rates: pd.DataFrame) -> float:
    """Largest absolute difference between the online page and the PDF for the base tables."""
    base = page_rates[page_rates["variant"] == "base"][["table", "age", "qx"]]
    merged = base.merge(pdf_rates, on=["table", "age"], suffixes=("_page", "_pdf"))
    if len(merged) != len(base):
        raise CNSFParseError("Page and PDF do not cover the same tables and ages.")
    return float((merged["qx_page"] - merged["qx_pdf"]).abs().max())


def process(*, paths: Paths | None = None) -> Path:
    """Parse the downloaded page into ``data/processed/cnsf/rates.parquet``."""
    paths = (paths or get_paths()).ensure()
    page_file = paths.raw / SOURCE / PAGE_FILE
    if not page_file.exists():
        raise FileNotFoundError(f"{page_file} not found. Run the download first.")
    lines = html_to_lines(page_file.read_text(encoding="utf-8", errors="replace"))
    rates = parse_annex(lines)
    rates["source_url"] = PAGE_URL
    rates["annex_modified"] = last_modified(lines)

    out_dir = paths.processed / SOURCE
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "rates.parquet"
    rates.to_parquet(target, index=False)
    return target
