import io
import zipfile

import pandas as pd
import pytest

from mortality.config import Paths
from mortality.ingest import conapo


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


def population_frame():
    return pd.DataFrame(
        {
            "RENGLON": [1, 2, 3],
            "AÑO": [2019, 2020, 2020],
            "ENTIDAD": ["República Mexicana", " Aguascalientes", " Aguascalientes"],
            "CVE_GEO": [0, 1, 1],
            "EDAD": [0, 0, 1],
            "SEXO": ["Hombres", "Mujeres", "Mujeres"],
            "POBLACION": [1000000.0, 12000.5, 11800.0],
        }
    )


def test_clean_population():
    out = conapo.clean(population_frame(), conapo.WORKBOOKS["population"])
    assert out["sex"].tolist() == ["M", "F", "F"]
    assert out["state"].tolist() == ["República Mexicana", "Aguascalientes", "Aguascalientes"]
    assert out["state_code"].tolist() == [0, 1, 1]
    assert out["is_projection"].tolist() == [False, True, True]
    assert out["population"].tolist() == [1000000.0, 12000.5, 11800.0]
    assert out["age"].tolist() == [0, 0, 1]


def test_clean_life_expectancy_has_no_age():
    raw = pd.DataFrame(
        {
            "AÑO": [1950, 1950, 1950],
            "ENTIDAD": ["República Mexicana"] * 3,
            "CVE_GEO": [0, 0, 0],
            "SEXO": ["Hombres", "Mujeres", "Total"],
            "EV": [44.9, 47.7, 46.3],
        }
    )
    out = conapo.clean(raw, conapo.WORKBOOKS["e0"])
    assert "age" not in out.columns
    assert out["sex"].tolist() == ["M", "F", "T"]


def test_clean_rejects_unknown_sex():
    bad = population_frame().assign(SEXO=["Hombres", "Otro", "Mujeres"])
    with pytest.raises(ValueError, match="SEXO"):
        conapo.clean(bad, conapo.WORKBOOKS["population"])


def test_clean_rejects_missing_columns():
    with pytest.raises(KeyError):
        conapo.clean(population_frame().drop(columns=["EDAD"]), conapo.WORKBOOKS["population"])


def excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_process_reads_workbooks_from_zip(paths):
    deaths = population_frame().rename(columns={"POBLACION": "DEFUNCIONES"})
    e0 = pd.DataFrame(
        {
            "AÑO": [2020],
            "ENTIDAD": ["República Mexicana"],
            "CVE_GEO": [0],
            "SEXO": ["Total"],
            "EV": [75.1],
        }
    )
    folder = paths.raw / "conapo"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / conapo.ZIP_NAME, "w") as zf:
        zf.writestr(
            "inner/" + conapo.WORKBOOKS["population"].member, excel_bytes(population_frame())
        )
        zf.writestr("inner/" + conapo.WORKBOOKS["deaths"].member, excel_bytes(deaths))
        zf.writestr("inner/" + conapo.WORKBOOKS["e0"].member, excel_bytes(e0))

    written = conapo.process(paths=paths)
    assert set(written) == {"population", "deaths", "e0"}
    pop = pd.read_parquet(written["population"])
    assert len(pop) == 3 and pop["population"].sum() == pytest.approx(1023800.5)
    assert pd.read_parquet(written["e0"])["e0"].tolist() == [75.1]


def test_process_needs_download(paths):
    with pytest.raises(FileNotFoundError):
        conapo.process(paths=paths)
