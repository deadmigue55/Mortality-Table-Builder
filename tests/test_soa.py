import pandas as pd
import pytest

from mortality.config import Paths
from mortality.ingest import download, soa


def xtbml(table_id=15004, tables="") -> bytes:
    return (
        '﻿<?xml version="1.0" encoding="utf-8"?><XTbML><ContentClassification>'
        f"<TableIdentity>{table_id}</TableIdentity><TableReference>CNSF ref</TableReference>"
        "<ContentType tc='4'>Insured Lives Mortality</ContentType>"
        "<TableName>Demo table</TableName><Comments>demo</Comments>"
        "<KeyWord>Aggregate</KeyWord><KeyWord>Mexico</KeyWord></ContentClassification>"
        f"{tables}</XTbML>"
    ).encode()


ONE_D = (
    "<Table><MetaData><ScalingFactor>0</ScalingFactor><TableDescription>one</TableDescription>"
    '<AxisDef id="Age"><AxisName>Age</AxisName></AxisDef></MetaData>'
    '<Values><Axis><Y t="12">0.0004</Y><Y t="13">0.0005</Y></Axis></Values></Table>'
)

TWO_D = (
    "<Table><MetaData><ScalingFactor>0</ScalingFactor><TableDescription>select</TableDescription>"
    '<AxisDef id="Age"><AxisName>Age</AxisName></AxisDef>'
    '<AxisDef id="Duration"><AxisName>Duration</AxisName></AxisDef></MetaData>'
    '<Values><Axis t="30"><Y t="1">0.001</Y><Y t="2">0.002</Y></Axis>'
    '<Axis t="31"><Y t="1">0.0011</Y><Y t="2">0.0021</Y></Axis></Values></Table>'
)


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


def test_parse_one_dimensional():
    meta, rates = soa.parse_xtbml(xtbml(tables=ONE_D))
    assert meta["table_id"] == 15004 and meta["name"] == "Demo table"
    assert meta["reference"] == "CNSF ref" and "Mexico" in meta["keywords"]
    assert rates[["age", "rate"]].to_numpy().tolist() == [[12, 0.0004], [13, 0.0005]]
    assert rates["duration"].isna().all()
    assert meta["axes"] == ["age"]


def test_parse_two_dimensional_select_table():
    meta, rates = soa.parse_xtbml(xtbml(tables=ONE_D + TWO_D))
    assert sorted(rates["sub_table"].unique()) == [1, 2]
    select = rates[rates.sub_table == 2]
    assert len(select) == 4
    row = select[(select.age == 31) & (select.duration == 2)].iloc[0]
    assert row["rate"] == pytest.approx(0.0021)
    assert meta["axes"] == ["age", "age x duration"]


def test_parse_rejects_other_documents():
    with pytest.raises(soa.XTbMLError):
        soa.parse_xtbml(b"<html></html>")
    with pytest.raises(soa.XTbMLError, match="No <Table>"):
        soa.parse_xtbml(xtbml(tables=""))


def test_parse_rejects_scaling_factors():
    scaled = ONE_D.replace("<ScalingFactor>0<", "<ScalingFactor>3<")
    with pytest.raises(soa.XTbMLError, match="ScalingFactor"):
        soa.parse_xtbml(xtbml(tables=scaled))


def test_curated_tables_are_unique_and_include_mexico():
    ids = [t.table_id for t in soa.TABLES]
    assert len(ids) == len(set(ids))
    assert {15004, 2700, 3361, 2585, 3533} <= set(ids)
    assert any(t.group.startswith("mexico") for t in soa.TABLES)


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


class Session:
    def __init__(self, body):
        self.body, self.urls = body, []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return Resp(self.body)


def test_download_saves_xml_and_logs(paths):
    session = Session(xtbml(tables=ONE_D))
    result = soa.download_table(15004, session=session, paths=paths)
    assert result.path.name == "table_15004.xml"
    assert session.urls == ["https://mort.soa.org/Export.aspx?Type=xml&TableIdentity=15004"]
    assert download.read_manifest(paths)[0]["source"] == "soa"


def test_download_rejects_html(paths):
    with pytest.raises(download.NotAFileError):
        soa.download_table(1, session=Session(b"<html>Error</html>"), paths=paths)
    assert not list((paths.raw / "soa").glob("*"))


def test_process_builds_rates_and_catalog(paths):
    tables = (soa.Table(15004, "mexico_insured", "demo"), soa.Table(3361, "us_cso_unloaded", "cso"))
    folder = paths.raw / "soa"
    folder.mkdir(parents=True)
    (folder / "table_15004.xml").write_bytes(xtbml(15004, ONE_D))
    (folder / "table_3361.xml").write_bytes(xtbml(3361, ONE_D + TWO_D))
    written = soa.process(tables, paths=paths)
    rates = pd.read_parquet(written["rates"])
    catalog = pd.read_parquet(written["catalog"])
    assert set(rates["table_id"]) == {15004, 3361}
    assert catalog.set_index("table_id").loc[15004, "group"] == "mexico_insured"
    assert catalog.set_index("table_id").loc[3361, "max_age"] == 31
    assert "CNSF ref" in catalog["reference"].tolist()


def test_process_detects_wrong_table_id(paths):
    folder = paths.raw / "soa"
    folder.mkdir(parents=True)
    (folder / "table_15004.xml").write_bytes(xtbml(999, ONE_D))
    with pytest.raises(soa.XTbMLError, match="expected 15004"):
        soa.process((soa.Table(15004, "g", "l"),), paths=paths)


def test_process_needs_download(paths):
    with pytest.raises(FileNotFoundError):
        soa.process((soa.Table(15004, "g", "l"),), paths=paths)
