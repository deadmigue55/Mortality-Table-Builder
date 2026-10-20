"""Society of Actuaries Mortality and Other Rate Tables (mort.soa.org).

Tables are published as XTbML (XML). We fetch a curated list by table ID, parse each into
long format (age, optional duration, rate) and keep the source reference, so every number can
be traced to the regulation or study it came from.

Besides the US industry tables, the SOA site hosts several official Mexican tables
(EMSSA 97, Seguro Popular 2008, CNSF 2000-I and older experience), but **not** CNSF 2013,
which has to come from the CNSF's own publications.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from defusedxml import ElementTree as ET

from mortality.config import Paths, get_paths
from mortality.ingest.download import Download, NotAFileError, fetch

SOURCE = "soa"
EXPORT_URL = "https://mort.soa.org/Export.aspx?Type=xml&TableIdentity={table_id}"
PAUSE_SECONDS = 0.5


@dataclass(frozen=True)
class Table:
    table_id: int
    group: str
    label: str


# Curated benchmarks. `group` says what each table is for in this project.
TABLES: tuple[Table, ...] = (
    # Mexico
    Table(15004, "mexico_insured", "CNSF 2000-I individual insured lives (1991-1998)"),
    Table(15005, "mexico_group", "CNSF 2000-G group life (1991-1998)"),
    Table(15006, "mexico_insured", "MEX 2000 male"),
    Table(15007, "mexico_insured", "MEX 2000 female"),
    Table(15002, "mexico_insured", "Experiencia Mexicana individual (1982-1989)"),
    Table(15003, "mexico_group", "Experiencia Mexicana group (1973-1983)"),
    Table(15001, "mexico_insured", "Experiencia Mexicana (1962-1967)"),
    Table(2696, "mexico_pension", "EMSSA 97 pension participants (H)"),
    Table(2697, "mexico_pension", "EMSSA 97 pension participants (M)"),
    Table(2698, "mexico_disabled", "EMSSI 97 disabled pension participants (H)"),
    Table(2699, "mexico_disabled", "EMSSI 97 disabled pension participants (M)"),
    Table(2700, "mexico_population", "Seguro Popular 2008 males"),
    Table(2701, "mexico_population", "Seguro Popular 2008 females"),
    # United States: life insurance valuation (2017 CSO, composite, age nearest and last birthday)
    Table(3361, "us_cso_unloaded", "2017 Unloaded CSO composite male ANB"),
    Table(3362, "us_cso_unloaded", "2017 Unloaded CSO composite female ANB"),
    Table(3363, "us_cso_unloaded", "2017 Unloaded CSO composite male ALB"),
    Table(3364, "us_cso_unloaded", "2017 Unloaded CSO composite female ALB"),
    Table(3287, "us_cso_loaded", "2017 Loaded CSO composite male ANB"),
    Table(3288, "us_cso_loaded", "2017 Loaded CSO composite female ANB"),
    Table(3289, "us_cso_loaded", "2017 Loaded CSO composite male ALB"),
    Table(3290, "us_cso_loaded", "2017 Loaded CSO composite female ALB"),
    # United States: annuities and pensions
    Table(2585, "us_annuity", "2012 IAM period male ANB"),
    Table(2586, "us_annuity", "2012 IAM period female ANB"),
    Table(3531, "us_pension", "Pri-2012 female employee"),
    Table(3532, "us_pension", "Pri-2012 male employee"),
    Table(3533, "us_pension", "Pri-2012 female retiree"),
    Table(3534, "us_pension", "Pri-2012 male retiree"),
    Table(3537, "us_pension", "Pri-2012 female disabled retiree"),
    Table(3538, "us_pension", "Pri-2012 male disabled retiree"),
)


class XTbMLError(ValueError):
    """The XML is not a table we know how to read."""


# ── Download ────────────────────────────────────────────────────────────────


def _check_xml(path: Path) -> None:
    with path.open("rb") as handle:
        head = handle.read(2000).decode("utf-8-sig", errors="replace").lower()
    if "<xtbml" not in head:
        raise NotAFileError(f"{path.name} is not an XTbML file (table missing on mort.soa.org?)")


def download_table(
    table_id: int,
    *,
    session: requests.Session | None = None,
    force: bool = False,
    paths: Paths | None = None,
) -> Download:
    return fetch(
        EXPORT_URL.format(table_id=table_id),
        source=SOURCE,
        filename=f"table_{table_id}.xml",
        force=force,
        session=session,
        paths=paths,
        validate=_check_xml,
    )


def download_all(
    tables: tuple[Table, ...] = TABLES,
    *,
    session: requests.Session | None = None,
    force: bool = False,
    paths: Paths | None = None,
    pause: float = PAUSE_SECONDS,
) -> list[Download]:
    results = []
    for table in tables:
        result = download_table(table.table_id, session=session, force=force, paths=paths)
        results.append(result)
        if not result.skipped:
            time.sleep(pause)
    return results


# ── Parsing ─────────────────────────────────────────────────────────────────


def _text(node, tag: str) -> str | None:
    found = node.find(tag)
    return found.text.strip() if found is not None and found.text else None


def parse_xtbml(xml_bytes: bytes) -> tuple[dict[str, object], pd.DataFrame]:
    """Parse one XTbML document into (metadata, long-format rates).

    The rates frame has ``sub_table`` (1, 2, ...), ``age``, ``duration`` (empty for
    one-dimensional tables) and ``rate``.
    """
    root = ET.fromstring(xml_bytes.decode("utf-8-sig").encode("utf-8"))
    if root.tag != "XTbML":
        raise XTbMLError(f"Expected an XTbML document, got <{root.tag}>")
    head = root.find("ContentClassification")
    if head is None:
        raise XTbMLError("No ContentClassification block.")

    meta: dict[str, object] = {
        "table_id": int(_text(head, "TableIdentity") or 0),
        "name": _text(head, "TableName"),
        "usage": _text(head, "ContentType"),
        "reference": _text(head, "TableReference"),
        "comments": _text(head, "Comments"),
        "keywords": [k.text.strip() for k in head.findall("KeyWord") if k.text],
    }

    frames = []
    for number, table in enumerate(root.findall("Table"), start=1):
        info = table.find("MetaData")
        axes = [a.findtext("AxisName", "").strip().lower() for a in info.findall("AxisDef")]
        scaling = int(_text(info, "ScalingFactor") or 0)
        if scaling != 0:
            raise XTbMLError(f"Table {meta['table_id']}: non-zero ScalingFactor is not supported.")
        values = table.find("Values")
        rows: list[tuple[float, float | None, float]] = []
        if len(axes) == 1:
            for y in values.iter("Y"):
                rows.append((float(y.get("t")), None, float(y.text)))
        elif len(axes) == 2:
            for outer in values.findall("Axis"):
                for y in outer.findall("Y"):
                    rows.append((float(outer.get("t")), float(y.get("t")), float(y.text)))
        else:
            raise XTbMLError(f"Table {meta['table_id']}: unsupported number of axes {axes}.")

        frame = pd.DataFrame(rows, columns=["age", "duration", "rate"])
        frame.insert(0, "sub_table", number)
        frame["sub_axes"] = " x ".join(axes)
        frame["sub_description"] = _text(info, "TableDescription")
        frames.append(frame)

    if not frames:
        raise XTbMLError("No <Table> blocks found.")
    rates = pd.concat(frames, ignore_index=True)
    rates["age"] = rates["age"].astype("int16")
    rates["duration"] = rates["duration"].astype("Int16")
    meta["axes"] = sorted(set(rates["sub_axes"]))
    return meta, rates


def process(tables: tuple[Table, ...] = TABLES, *, paths: Paths | None = None) -> dict[str, Path]:
    """Parse the downloaded XML into ``rates.parquet`` and ``catalog.parquet``."""
    paths = (paths or get_paths()).ensure()
    out_dir = paths.processed / SOURCE
    out_dir.mkdir(parents=True, exist_ok=True)

    rate_frames, catalog = [], []
    for table in tables:
        file = paths.raw / SOURCE / f"table_{table.table_id}.xml"
        if not file.exists():
            raise FileNotFoundError(f"{file} not found. Run the download first.")
        meta, rates = parse_xtbml(file.read_bytes())
        if meta["table_id"] != table.table_id:
            raise XTbMLError(
                f"{file.name} contains table {meta['table_id']}, expected {table.table_id}"
            )
        rates.insert(0, "table_id", table.table_id)
        rate_frames.append(rates)
        catalog.append(
            {
                "table_id": table.table_id,
                "group": table.group,
                "label": table.label,
                "name": meta["name"],
                "usage": meta["usage"],
                "axes": "; ".join(meta["axes"]),
                "min_age": int(rates["age"].min()),
                "max_age": int(rates["age"].max()),
                "reference": meta["reference"],
                "comments": meta["comments"],
                "source_url": EXPORT_URL.format(table_id=table.table_id),
            }
        )

    written = {}
    for name, frame in (
        ("rates", pd.concat(rate_frames, ignore_index=True)),
        ("catalog", pd.DataFrame(catalog)),
    ):
        target = out_dir / f"{name}.parquet"
        frame.to_parquet(target, index=False)
        written[name] = target
    return written
