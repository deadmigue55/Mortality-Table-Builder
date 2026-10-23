"""How much each modelling choice moves the price of a standard quote.

Every choice that stands between the CNSF statistics and a table is changed one at a time, the
table is rebuilt with the same code, and the net annual premium of three reference policies is
recomputed at 4% interest. Nothing is hidden in an average: the table lists every choice, the
alternatives considered, and what each does to the premium, so a reader can disagree with a
choice and see what the disagreement is worth.

The margin for adverse deviation is then sized from the adverse choices that cannot be ruled
out, combined in quadrature (they are different, independent ways of being wrong).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mortality import insured, pricing

INTEREST = 0.04
PRODUCT = "term_traditional"  # the standard quote
# (sex, issue age, term): a man and a woman of 40 on a 20-year term, a man of 55 on 10 years
REFERENCES = (("M", 40, 20), ("F", 40, 20), ("M", 55, 10))
PRICING_YEAR = 2026
TABLE_YEAR = 2024  # the middle of the base years: where the pooled table sits in time
DESCRIPTIONS = {
    "insured_sensitivity": (
        "Net annual premium per 1,000 of reference term policies when each modelling choice is "
        "changed one at a time: what was changed, the alternative, the premium and its change "
        "from the base table"
    ),
    "insured_margin": (
        "The margin for adverse deviation sized from the adverse modelling choices, combined in "
        "quadrature, for each reference policy, and the loading recommended"
    ),
}


@dataclass(frozen=True)
class Scenario:
    choice: str  # the modelling choice that changes
    alternative: str  # what it changes to
    kwargs: dict  # arguments of ``insured.segment_q`` that change
    adverse: bool = False  # a reading that cannot be ruled out and raises mortality
    note: str = ""


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("Base table", "traditional term, 2023-25, direct P-spline", {}),
    Scenario(
        "What counts as a death",
        "net of cancelled claims",
        {"rule": "net"},
        note="Cancelled claims may or may not be real deaths",
    ),
    Scenario(
        "What counts as a death",
        "keeping the maturity payments coded as sprains",
        {"rule": "with_maturities"},
        note="Endowment maturities booked under the death cover; they are not deaths",
    ),
    Scenario(
        "What counts as a death",
        "plus the no-detail rows with a positive amount",
        {"rule": "plus_positive"},
        adverse=True,
        note="If part of the adjustment ledger were new deaths",
    ),
    Scenario(
        "What counts as a death",
        "plus every no-detail row",
        {"rule": "plus_all"},
        note="The reading the evidence rejects",
    ),
    Scenario("Exposure", "lives exposed part of the year: 10%", {"turnover": 0.10}, adverse=True),
    Scenario("Exposure", "lives exposed part of the year: 20%", {"turnover": 0.20}),
    Scenario("Years pooled", "2023-24 only", {"years": (2023, 2024)}),
    Scenario("Years pooled", "2024-25 only", {"years": (2024, 2025)}),
    Scenario("Graduation", "relational P-spline", {"method": "relational"}),
    Scenario("Graduation", "Gompertz-Makeham", {"method": "makeham"}),
    Scenario("Graduation", "Brass against the population", {"method": "brass"}),
    Scenario("Old ages meet the population", "at age 95", {"converge_age": 95}),
    Scenario("Old ages meet the population", "at age 115", {"converge_age": 115}),
)


def premium_per_1000(q_by_age: np.ndarray, issue_age: int, term: int) -> float:
    """Net annual premium per 1,000 of a level term cover, at 4% interest."""
    q = pricing.q_path(np.asarray(q_by_age, dtype=float), issue_age, term)
    return float(1000.0 * pricing.net_premium(q, INTEREST))


def _premiums(tables: dict[str, pd.Series]) -> dict[tuple[str, int, int], float]:
    return {
        ref: premium_per_1000(tables[ref[0]].reindex(range(111)).to_numpy(), ref[1], ref[2])
        for ref in REFERENCES
    }


def improvement_factor(rates: pd.DataFrame, sex: str, years: float) -> np.ndarray:
    """Multiplier by age for ``years`` of improvement at the projected annual rates."""
    r = rates[rates["sex"] == sex].set_index("age")["annual_improvement"].reindex(range(111))
    return ((1.0 - r.fillna(0.0).clip(lower=0.0)) ** years).to_numpy()


def sensitivity_table(
    claims: pd.DataFrame,
    exposure: pd.DataFrame,
    pop: pd.DataFrame,
    *,
    all_cover_exposure: pd.DataFrame | None = None,
    market_tables: dict[str, dict[str, pd.Series]] | None = None,
    improvement: pd.DataFrame | None = None,
    amount_ratio: float | None = None,
) -> pd.DataFrame:
    """Premiums of the reference policies under the base table and every alternative."""
    rows: list[dict] = []

    def add(choice, alternative, tables, adverse=False, note=""):
        for (sex, age, term), premium in _premiums(tables).items():
            rows.append(
                {
                    "choice": choice,
                    "alternative": alternative,
                    "sex": sex,
                    "issue_age": age,
                    "term": term,
                    "premium_per_1000": premium,
                    "adverse": adverse,
                    "note": note,
                }
            )

    for s in SCENARIOS:
        tables = insured.segment_q(PRODUCT, claims, exposure, pop, **s.kwargs)
        add(s.choice, s.alternative, tables, s.adverse, s.note)
    base = insured.segment_q(PRODUCT, claims, exposure, pop)

    if all_cover_exposure is not None:
        tables = insured.segment_q(PRODUCT, claims, all_cover_exposure, pop)
        add("Exposure", "every insured life, whatever the cover (exposure sheet)", tables)
    for name, tables in (market_tables or {}).items():
        add("Which table", name, tables)
    if improvement is not None:
        years = PRICING_YEAR - TABLE_YEAR
        rolled = {
            sex: base[sex] * improvement_factor(improvement, sex, years) for sex in ("M", "F")
        }
        add("Improvement", f"rolled to {PRICING_YEAR} at the projected rates", rolled)
    if amount_ratio is not None:
        add(
            "Basis",
            "by sum assured: larger policies die more",
            {sex: np.minimum(base[sex] * amount_ratio, 1.0) for sex in ("M", "F")},
            note="A different measure, not a doubt about this one: claimed amount over sum "
            "assured against the count rate",
        )

    out = pd.DataFrame(rows)
    key = ["sex", "issue_age", "term"]
    base_premium = (
        out[out["choice"] == "Base table"].set_index(key)["premium_per_1000"].rename("base")
    )
    out = out.join(base_premium, on=key)
    out["change_vs_base"] = out["premium_per_1000"] / out["base"] - 1.0
    return out.drop(columns="base")


def margin_table(sensitivity: pd.DataFrame) -> pd.DataFrame:
    """Size a margin from the adverse alternatives: their changes in quadrature, per policy."""
    adverse = sensitivity[sensitivity["adverse"] & (sensitivity["change_vs_base"] > 0)]
    rows = []
    for (sex, age, term), g in adverse.groupby(["sex", "issue_age", "term"]):
        rows.append(
            {
                "sex": sex,
                "issue_age": age,
                "term": term,
                "adverse_choices": len(g),
                "quadrature_margin": float(np.sqrt((g["change_vs_base"] ** 2).sum())),
            }
        )
    out = pd.DataFrame(rows)
    # one loading for the product: the largest of the reference policies, rounded up to 5%
    out["recommended_margin"] = float(np.ceil(out["quadrature_margin"].max() / 0.05) * 0.05)
    return out


def build_tables(con) -> list[tuple[str, str]]:
    """Create the sensitivity and margin tables; returns (name, description)."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"cnsf_vi_claims", "cnsf_vi_issued", "cnsf_vi_exposure", "graduated_qx"} <= names:
        return []
    claims = pd.read_sql(
        "SELECT year, age, sex, plan, modality, coverage, cause, claims, amount_claimed "
        f"FROM cnsf_vi_claims WHERE coverage = '{insured.DEATH_COVER}'",
        con,
    )
    issued = pd.read_sql(
        "SELECT year, age, sex, plan, modality, SUM(insured) AS insured FROM cnsf_vi_issued "
        f"WHERE coverage = '{insured.DEATH_COVER}' GROUP BY year, age, sex, plan, modality",
        con,
    )
    every_life = pd.read_sql(
        "SELECT year, age, sex, plan, modality, SUM(insured) AS insured FROM cnsf_vi_exposure "
        "GROUP BY year, age, sex, plan, modality",
        con,
    )
    pop = pd.read_sql("SELECT sex, age, qx FROM graduated_qx WHERE year = 2023", con)
    improvement = (
        pd.read_sql("SELECT sex, age, annual_improvement FROM insured_improvement", con)
        if "insured_improvement" in names
        else None
    )
    ratio = None
    if "insured_amount" in names:
        amount = pd.read_sql(
            "SELECT decade, deaths, amount_to_count_ratio FROM insured_amount "
            f"WHERE segment = '{PRODUCT}' AND decade BETWEEN 30 AND 60",
            con,
        )
        ratio = float(np.average(amount["amount_to_count_ratio"], weights=amount["deaths"]))
    market: dict[str, dict[str, pd.Series]] = {}
    if "insured_table" in names:
        table = pd.read_sql("SELECT segment, sex, age, qx FROM insured_table", con)
        for segment, label in (("all", "market blend of all products"), ("term", "all term")):
            part = table[table["segment"] == segment]
            if len(part):
                market[label] = {
                    s: part[part["sex"] == s].set_index("age")["qx"] for s in ("M", "F")
                }

    sensitivity = sensitivity_table(
        claims,
        issued,
        pop,
        all_cover_exposure=every_life,
        market_tables=market,
        improvement=improvement,
        amount_ratio=ratio,
    )
    frames = {"insured_sensitivity": sensitivity, "insured_margin": margin_table(sensitivity)}
    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
