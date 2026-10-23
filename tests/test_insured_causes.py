import pandas as pd
import pytest

from mortality import insured_causes as causes


@pytest.mark.parametrize(
    ("text", "group"),
    [
        ("INFARTO AGUDO DEL MIOCARDIO", "heart_attack_and_ischaemic"),
        ("HIPERTENSIÓN ESENCIAL (PRIMARIA)", "other_circulatory"),
        ("COVID-19, VIRUS IDENTIFICADO", "covid"),
        ("USO EMERGENTE DE U07", "covid"),
        (
            "LUXACION, ESGUINCE Y TORCEDURA DE ARTICULACIONES Y LIGAMENTOS DEL TOBILLO",
            "not_a_cause_of_death",
        ),
        ("TUMOR MALIGNO DE LA MAMA", "cancer"),
        ("DIABETES MELLITUS TIPO 2", "diabetes"),
        ("ENFERMEDAD RENAL CRÓNICA", "kidney"),
        ("OTRAS CIRROSIS DEL HÍGADO Y LAS NO ESPECIFICADAS", "liver"),
        ("INSUFICIENCIA RESPIRATORIA AGUDA", "respiratory"),
        ("CHOQUE SÉPTICO", "infection_and_sepsis"),
        ("OTRAS SEPSIS", "infection_and_sepsis"),
        ("DISPARO DE OTRAS ARMAS DE FUEGO, Y LAS NO ESPECIFICADAS", "violence_and_accidents"),
        ("EVENTO NO ESPECIFICADO, DE INTENCIÓN NO DETERMINADA", "violence_and_accidents"),
        ("CHOQUE, NO CLASIFICADO EN OTRA PARTE", "ill_defined"),
        ("ACIDOSIS", "ill_defined"),
        ("ENFERMEDAD CEREBROVASCULAR, NO ESPECIFICADA", "stroke"),
        ("ALGO QUE NO SE PARECE A NADA", "other"),
        (None, "other"),
        (float("nan"), "other"),
    ],
)
def test_cause_text_goes_to_the_expected_group(text, group):
    assert causes.cause_group(text) == group


def test_every_group_has_a_label():
    assert set(causes.GROUPS) == set(causes.LABELS)


def test_cause_table_counts_only_known_positive_claims_and_shares_add_to_one():
    claims = pd.DataFrame(
        {
            "year": [2024] * 5,
            "age": [40, 41, 66, None, 40],
            "sex": ["M", "M", "F", None, "M"],
            "cause": [
                "INFARTO AGUDO DEL MIOCARDIO",
                "TUMOR MALIGNO DEL COLON",
                "ACIDOSIS",
                "COVID-19",
                "DIABETES",
            ],
            "claims": [3.0, 2.0, 5.0, 9.0, 1.0],
            "amount_claimed": [10.0, 10.0, 10.0, 10.0, -5.0],  # the last is a cancellation
        }
    )
    t = causes.cause_table(claims)
    assert t["deaths"].sum() == 10.0  # no-detail and cancelled rows are out
    shares = t.groupby(["year", "sex", "band"])["share"].sum()
    assert shares.round(9).eq(1.0).all()
    assert set(t["band"]) == {"25-44", "65-79"}
