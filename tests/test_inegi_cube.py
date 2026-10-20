import zipfile

import pandas as pd
import pytest

from mortality.config import Paths
from mortality.ingest import download, inegi_cube

GROUPS = [
    ("Menores de 1 año", 100, 60, 39, 1),
    ("1-4 años", 20, 11, 9, 0),
    ("5-9 años", 1234, 700, 534, 0),
    ("85 años y más", 5000, 2000, 2995, 5),
    ("No especificado", 10, 7, 2, 1),
]


def fmt(n: int) -> str:
    """INEGI style: thousands separator in quotes, blank for zero."""
    if n == 0:
        return " "
    return f'"{n:,}"' if n >= 1000 else f" {n}"


def export(year=2019, groups=GROUPS, with_filter=False, tweak_total=0) -> str:
    totals = [sum(g[i] for g in groups) for i in range(1, 5)]
    totals[0] += tweak_total
    lines = ["Defunciones registradas (mortalidad general)", f",Año de registro : {year}"]
    if with_filter:
        lines.append(",Ent y mun de ocurrencia : Total")
    lines += [",", "", "Consulta de: Defunciones registradas \xa0 Por: Edad \xa0 Según: Sexo"]
    lines.append(" , Total, Hombre, Mujer, No especificado")
    lines.append("Total," + ",".join(fmt(t) for t in totals))
    for label, *values in groups:
        lines.append(f"{label}," + ",".join(fmt(v) for v in values))
    lines += ["", "", "Fuente: INEGI. Estadísticas de Defunciones Registradas (EDR)."]
    return "\r\n".join(lines) + "\r\n"


def as_bytes(text: str) -> bytes:
    return text.encode("cp1252")


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


# ── parsing ─────────────────────────────────────────────────────────────────


def test_parse_reads_year_groups_and_sexes():
    year, df = inegi_cube.parse_csv(inegi_cube.decode(as_bytes(export(2018))))
    assert year == 2018
    assert set(df["sex"]) == {"M", "F", "U"}
    assert df["deaths"].sum() == 100 + 20 + 1234 + 5000 + 10
    row = df[(df.age_group == "5-9 años") & (df.sex == "F")].iloc[0]
    assert (row.age_lo, row.age_hi, row.deaths) == (5, 9, 534)


def test_parse_age_bounds_including_open_and_unknown():
    _, df = inegi_cube.parse_csv(export())
    bounds = df.drop_duplicates("age_group").set_index("age_group")[["age_lo", "age_hi"]]
    assert bounds.loc["Menores de 1 año"].tolist() == [0, 0]
    assert bounds.loc["1-4 años"].tolist() == [1, 4]
    assert (
        pd.isna(bounds.loc["85 años y más", "age_hi"])
        and bounds.loc["85 años y más", "age_lo"] == 85
    )
    assert bounds.loc["No especificado"].isna().all()


def test_parse_treats_blank_cells_as_zero():
    _, df = inegi_cube.parse_csv(export())
    unknown_sex = df[(df.age_group == "1-4 años") & (df.sex == "U")].iloc[0]
    assert unknown_sex.deaths == 0


def test_parse_records_extra_filters():
    _, df = inegi_cube.parse_csv(export(with_filter=True))
    assert df["filters"].iloc[0] == "Ent y mun de ocurrencia: Total"
    _, df = inegi_cube.parse_csv(export(with_filter=False))
    assert df["filters"].iloc[0] == ""


def test_parse_rejects_totals_that_do_not_add_up():
    with pytest.raises(inegi_cube.CubeError, match="do not add up"):
        inegi_cube.parse_csv(export(tweak_total=1))


def test_parse_rejects_rows_where_sexes_do_not_add_up():
    bad = [("Menores de 1 año", 100, 60, 39, 5), *GROUPS[1:]]  # 60 + 39 + 5 != 100
    with pytest.raises(inegi_cube.CubeError, match="sexes do not add up"):
        inegi_cube.parse_csv(export(groups=bad))


def test_parse_rejects_unknown_layouts():
    with pytest.raises(inegi_cube.CubeError, match="Año de registro"):
        inegi_cube.parse_csv("nothing useful\nhere")
    wrong_columns = export().replace("Mujer", "Femenino")
    with pytest.raises(inegi_cube.CubeError, match="column header"):
        inegi_cube.parse_csv(wrong_columns)
    other_group = [("Mayores de 200", 5, 2, 3, 0)]
    with pytest.raises(inegi_cube.CubeError, match="Unrecognised age group"):
        inegi_cube.parse_csv(export(groups=other_group))


def test_decode_accepts_cp1252_and_utf8():
    assert "año" in inegi_cube.decode("año".encode("cp1252"))
    assert "año" in inegi_cube.decode("﻿año".encode())


# ── importing ───────────────────────────────────────────────────────────────


def make_zip(tmp_path, files: dict[str, str]):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, as_bytes(text))
    return path


def test_import_stores_files_under_the_year_inside_them(paths, tmp_path):
    archive = make_zip(tmp_path, {"2018.csv": export(2018), "2017.csv": export(2025)})
    imported = inegi_cube.import_files([archive], paths=paths)
    assert [i.year for i in imported] == [2018, 2025]
    mislabeled = next(i for i in imported if i.original_name == "2017.csv")
    assert mislabeled.year == 2025 and mislabeled.renamed
    assert not next(i for i in imported if i.year == 2018).renamed
    assert (paths.raw / "inegi_cube" / "registered_2025.csv").exists()
    manifest = download.read_manifest(paths)
    assert {m["file"] for m in manifest} == {
        "inegi_cube/registered_2018.csv",
        "inegi_cube/registered_2025.csv",
    }
    assert "exported by hand" in manifest[0]["url"]


def test_import_rejects_duplicate_years(paths, tmp_path):
    archive = make_zip(tmp_path, {"a.csv": export(2019), "b.csv": export(2019)})
    with pytest.raises(inegi_cube.CubeError, match="More than one file"):
        inegi_cube.import_files([archive], paths=paths)
    assert not list((paths.raw / "inegi_cube").glob("*"))


def test_import_validates_before_writing_anything(paths, tmp_path):
    archive = make_zip(
        tmp_path, {"2018.csv": export(2018), "2019.csv": export(2019, tweak_total=3)}
    )
    with pytest.raises(inegi_cube.CubeError):
        inegi_cube.import_files([archive], paths=paths)
    assert not list((paths.raw / "inegi_cube").glob("*"))


def test_import_accepts_loose_csv_files(paths, tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_bytes(as_bytes(export(2016)))
    imported = inegi_cube.import_files([csv_path], paths=paths)
    assert imported[0].year == 2016


def test_import_refuses_nested_paths_and_other_types(paths, tmp_path):
    nested = tmp_path / "nested.zip"
    with zipfile.ZipFile(nested, "w") as zf:
        zf.writestr("../evil.csv", as_bytes(export(2019)))
    with pytest.raises(inegi_cube.CubeError, match="Unexpected path"):
        inegi_cube.import_files([nested], paths=paths)
    other = tmp_path / "data.xlsx"
    other.write_bytes(b"x")
    with pytest.raises(inegi_cube.CubeError, match=r"\.csv or \.zip"):
        inegi_cube.import_files([other], paths=paths)


def test_import_rejects_empty_zip(paths, tmp_path):
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("notes.txt", "hello")
    with pytest.raises(inegi_cube.CubeError, match="No CSV"):
        inegi_cube.import_files([empty], paths=paths)


def test_process_builds_one_parquet(paths, tmp_path):
    archive = make_zip(tmp_path, {"2018.csv": export(2018), "2019.csv": export(2019)})
    inegi_cube.import_files([archive], paths=paths)
    target = inegi_cube.process(paths=paths)
    df = pd.read_parquet(target)
    assert sorted(df["reg_year"].unique()) == [2018, 2019]
    assert len(df) == 2 * len(GROUPS) * 3


def test_process_needs_an_import(paths):
    with pytest.raises(FileNotFoundError):
        inegi_cube.process(paths=paths)


def test_process_detects_a_renamed_raw_file(paths, tmp_path):
    inegi_cube.import_files([make_zip(tmp_path, {"2018.csv": export(2018)})], paths=paths)
    raw = paths.raw / "inegi_cube"
    (raw / "registered_2018.csv").rename(raw / "registered_2017.csv")
    with pytest.raises(inegi_cube.CubeError, match="registration year 2018"):
        inegi_cube.process(paths=paths)
