"""Causes of death in the insured death claims.

The claim sheet gives the cause as the *text* of an ICD-10 category ("INFARTO AGUDO DEL
MIOCARDIO"). It is not an underlying-cause statistic like INEGI's: it mixes underlying causes
(a tumour, a heart attack) with immediate ones (shock, acidosis, respiratory failure) and a few
entries that cannot cause a death at all (a sprained ankle, 685 claims in 2024). So the causes
are grouped by keyword, the share that stays ill-defined is reported as a measure of how
informative the field is, and the entries that cannot be causes of death get their own group so
their effect on the table can be shown.
"""

from __future__ import annotations

import re

import pandas as pd

from mortality.ingest.cnsf_vi import fold

# Order matters: the first rule that matches wins.
RULES: tuple[tuple[str, str], ...] = (
    ("covid", r"COVID|\bU07\b|SARS"),
    ("not_a_cause_of_death", r"LUXACION|ESGUINCE|TORCEDURA"),
    ("heart_attack_and_ischaemic", r"INFARTO|ISQUEMI|ANGINA|MIOCARD"),
    ("stroke", r"CEREBR|ICTUS|ACCIDENTE VASCULAR|HEMORRAGIA (INTRA|SUB)"),
    (
        "other_circulatory",
        r"CARDIAC|CARDIOG|CARDIOM|HIPERTENSI|ARRITMIA|FIBRILACION|AORT|ARTERI|EMBOLIA|TROMBO|"
        r"VASCULAR|CORAZON|VENOS",
    ),
    (
        "cancer",
        r"TUMOR|NEOPLASIA|CARCINOMA|LEUCEMIA|LINFOMA|MIELOMA|CANCER|MALIGN|SARCOMA|MELANOMA|"
        r"METAST",
    ),
    ("diabetes", r"DIABETES"),
    ("kidney", r"RENAL|NEFR|RINON|UREMIA"),
    ("liver", r"HIGADO|HEPAT|CIRROSIS"),
    ("respiratory", r"RESPIRATORI|NEUMON|PULMON|BRONQU|EPOC|ASMA|PLEUR"),
    (
        "infection_and_sepsis",
        r"SEPSIS|SEPTIC|INFECCI|BACTERI|TUBERCUL|\bVIH\b|INMUNODEFICIENCIA|MENINGITIS|"
        r"STAPHYLO|ESCHERICHIA",
    ),
    (
        "violence_and_accidents",
        r"DISPARO|\bARMA|HOMICID|AGRESI|ACCIDENTE|COLISION|ATROPELL|AHOGAMIENTO|ASFIXIA|"
        r"SUICID|AUTOINFLIGID|INTENCION NO DETERMINADA|TRAUMATISMO|CAIDA|QUEMADURA|"
        r"ENVENENAMIENTO|INTOXICACION|EVENTO NO ESPECIFICADO|APLASTAMIENTO|FRACTURA|LESION",
    ),
    (
        "ill_defined",
        r"CHOQUE|ACIDOSIS|\bPARO\b|FALLA|INSUFICIENCIA MULTIPLE|DESHIDRAT|SINTOMAS|SIGNOS|"
        r"NO ESPECIFICAD|DESCONOCID|ATENCION MEDICA|LIQUIDOS|ELECTROLITOS|HIPOXIA|MUERTE|"
        r"OTROS TRASTORNOS",
    ),
)
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in RULES)
GROUPS = (*(name for name, _ in RULES), "other")
LABELS = {
    "covid": "COVID-19",
    "not_a_cause_of_death": "Entries that cannot cause a death (sprains)",
    "heart_attack_and_ischaemic": "Heart attack and ischaemic heart disease",
    "stroke": "Stroke",
    "other_circulatory": "Other circulatory",
    "cancer": "Cancer",
    "diabetes": "Diabetes",
    "kidney": "Kidney disease",
    "liver": "Liver disease",
    "respiratory": "Respiratory",
    "infection_and_sepsis": "Infection and sepsis",
    "violence_and_accidents": "Violence and accidents",
    "ill_defined": "Ill-defined (shock, acidosis, arrest)",
    "other": "Other",
}
IMPLAUSIBLE = "not_a_cause_of_death"


def cause_group(text: object) -> str:
    """The group of a cause text; ``other`` when no keyword matches, missing text is ``other``."""
    if text is None or (isinstance(text, float) and text != text):
        return "other"
    folded = fold(text)
    for name, pattern in _COMPILED:
        if pattern.search(folded):
            return name
    return "other"


def group_causes(causes: pd.Series) -> pd.Series:
    """Group a series of cause texts, folding each distinct text once."""
    mapping = {text: cause_group(text) for text in causes.dropna().unique()}
    return causes.map(mapping).fillna("other")


def cause_table(claims: pd.DataFrame) -> pd.DataFrame:
    """Death claims by year, sex, age band and cause group (base rule: known age and sex).

    ``claims``: year, age, sex, cause, claims, amount_claimed for the death cover.
    """
    rows = claims[claims["age"].notna() & claims["sex"].notna() & (claims["amount_claimed"] > 0)]
    rows = rows.assign(
        group=group_causes(rows["cause"]),
        band=pd.cut(
            rows["age"].astype(float),
            [0, 25, 45, 65, 80, 200],
            right=False,
            labels=["<25", "25-44", "45-64", "65-79", "80+"],
        ).astype(str),
    )
    out = rows.groupby(["year", "sex", "band", "group"], as_index=False)["claims"].sum()
    total = out.groupby(["year", "sex", "band"])["claims"].transform("sum")
    out["share"] = out["claims"] / total
    return out.rename(columns={"claims": "deaths"})
