"""Life tables and actuarial functions.

Starts from the graduated rates (``graduated_qx``) and produces, for every year and sex:

* the **life table**: l(x), d(x), L(x), T(x), e(x), with the average years lived in the year
  of death, a(x), taken from the graduated m(x) and q(x) so the table reproduces them exactly;
* **summary measures**: life expectancy at 0, 15, 40, 65 and 80, adult mortality, the median
  and modal age at death, and lifespan disparity (the average years of life lost at death);
* **commutation columns** D, N, S, C, M, R at a chosen interest rate, and the insurance and
  annuity values built on them: whole life, term, endowment, pure endowment, deferred and
  temporary annuities, net premiums and prospective reserves.

The same code builds tables from the CNSF, SOA and HMD rates so every comparison uses one
method. Everything is a plain function on NumPy arrays and pandas frames.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RADIX = 100_000
OMEGA = 110  # the last age of the Mexican tables, where q = 1
INTEREST = 0.04  # reference technical interest rate for stored commutation columns
INTEREST_GRID = (0.03, 0.04, 0.05)  # rates for the stored actuarial values
EXPECTANCY_AGES = (0, 1, 15, 40, 65, 80)


# ── The life table ──────────────────────────────────────────────────────────


def average_years_in_death_year(qx, mx) -> np.ndarray:
    """Fraction of the year lived by those who die in it, implied by m and q.

    From ``q = m / (1 + (1 - a) m)``: ``a = 1 - (m / q - 1) / m``. For a table built with a = 0.5
    above infancy this returns 0.5; for infants it returns the small value that reflects deaths
    clustering in the first weeks. Where m or q is zero the answer is not defined and 0.5 is used.
    """
    q = np.asarray(qx, dtype=float)
    m = np.asarray(mx, dtype=float)
    ok = (q > 0) & (m > 0)
    a = np.full(q.shape, 0.5)
    a[ok] = 1.0 - (m[ok] / q[ok] - 1.0) / m[ok]
    return np.clip(a, 0.0, 1.0)


def build_life_table(age, qx, ax=None, terminal_mx=None, radix: float = RADIX) -> pd.DataFrame:
    """A complete life table from the probabilities of dying.

    ``age`` need not start at 0 (the SOA tables start at 12); l is then the radix at the first
    age. The last age must have q = 1 (the table closes). ``ax`` is the average fraction of the
    year lived by those who die in it (0.5 if not given). The last age is an open interval, so
    ``L = l / m`` there, with ``terminal_mx`` the central rate; if it is not given, ``a`` is used.
    """
    age = np.asarray(age, dtype=int)
    q = np.asarray(qx, dtype=float)
    n = len(age)
    a = np.full(n, 0.5) if ax is None else np.asarray(ax, dtype=float)
    if not np.isclose(q[-1], 1.0):
        raise ValueError("The last age of a life table must have q = 1.")
    l = np.empty(n)  # noqa: E741
    l[0] = radix
    for i in range(n - 1):
        l[i + 1] = l[i] * (1.0 - q[i])
    d = l * q
    big_l = np.empty(n)
    big_l[:-1] = l[1:] + a[:-1] * d[:-1]
    big_l[-1] = l[-1] / terminal_mx if terminal_mx else a[-1] * l[-1]
    t = np.cumsum(big_l[::-1])[::-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.where(l > 0, t / l, 0.0)
    return pd.DataFrame(
        {
            "age": age,
            "qx": q,
            "px": 1.0 - q,
            "ax": a,
            "lx": l,
            "dx": d,
            "Lx": big_l,
            "Tx": t,
            "ex": e,
        }
    )


def _at(table: pd.DataFrame, column: str, age: int) -> float:
    row = table.loc[table["age"] == age, column]
    return float(row.iloc[0]) if len(row) else float("nan")


def lifespan_disparity(table: pd.DataFrame) -> float:
    """Average years of life lost at death, e-dagger (Vaupel and Canudas-Romo).

    A person dying at age x + a still had about ``(1 - a) e(x) + a e(x + 1)`` years ahead of them
    in the table's population. Weighting by the deaths d(x) gives the average. It measures how
    unequal lifespans are: high where many die young as well as old.
    """
    e = table["ex"].to_numpy()
    a = table["ax"].to_numpy()
    e_next = np.append(e[1:], 0.0)
    lost = (1.0 - a) * e + a * e_next
    return float(np.sum(table["dx"].to_numpy() * lost) / table["lx"].iloc[0])


def median_age_at_death(table: pd.DataFrame) -> float:
    """Age at which half of the radix has died, interpolated linearly inside the year."""
    share = table["lx"].to_numpy() / table["lx"].iloc[0]
    ages = table["age"].to_numpy()
    if not (share <= 0.5).any():
        return float("nan")
    k = int(np.argmax(share <= 0.5))
    if k == 0:
        return float(ages[0])
    lo, hi = share[k - 1], share[k]
    return float(ages[k - 1] + (lo - 0.5) / (lo - hi))


def summary(table: pd.DataFrame) -> dict[str, float]:
    """Summary measures of a life table that starts at age 0."""
    out = {f"e{x}": _at(table, "ex", x) for x in EXPECTANCY_AGES}
    l0 = table["lx"].iloc[0]
    adult = table[table["age"] >= 10]
    out.update(
        {
            "q5_0": 1.0 - _at(table, "lx", 5) / l0,
            "q45_15": 1.0 - _at(table, "lx", 60) / _at(table, "lx", 15),
            "survive_to_65": _at(table, "lx", 65) / l0,
            "survive_to_80": _at(table, "lx", 80) / l0,
            "median_age_at_death": median_age_at_death(table),
            "modal_age_at_death": float(adult.loc[adult["dx"].idxmax(), "age"]),
            "lifespan_disparity": lifespan_disparity(table),
        }
    )
    return out


def combine_sexes(male: pd.DataFrame, female: pd.DataFrame, weights_male) -> pd.DataFrame:
    """Both-sexes rates as the population-weighted mix of male and female rates.

    ``male`` and ``female`` have ``age``, ``qx``, ``mx``; ``weights_male`` is the male share of
    the exposed population at each age. Mixing rates (not tables) keeps q and m consistent.
    """
    w = np.asarray(weights_male, dtype=float)
    return pd.DataFrame(
        {
            "age": male["age"].to_numpy(),
            "qx": w * male["qx"].to_numpy() + (1 - w) * female["qx"].to_numpy(),
            "mx": w * male["mx"].to_numpy() + (1 - w) * female["mx"].to_numpy(),
        }
    )


# ── Commutation functions and actuarial values ──────────────────────────────


@dataclass
class Commutation:
    """Commutation columns at interest rate ``i`` and the values built on them.

    ``D(x) = v^x l(x)``, ``C(x) = v^(x+1) d(x)``, and ``N``, ``S``, ``M``, ``R`` are their
    running sums from the oldest age down. Every value is a ratio of these, so any value is a
    handful of array lookups. Ages outside the table: below it every value is undefined (NaN).
    Above it the columns are 0, so a benefit payable beyond the last age is worth 0, while a value
    for a life already older than the last age is 0/0 and returned as NaN.
    """

    age: np.ndarray
    interest: float
    D: np.ndarray
    N: np.ndarray
    S: np.ndarray
    C: np.ndarray
    M: np.ndarray
    R: np.ndarray

    @classmethod
    def from_table(cls, table: pd.DataFrame, interest: float = INTEREST) -> Commutation:
        age = table["age"].to_numpy()
        v = 1.0 / (1.0 + interest)
        d_col = v**age * table["lx"].to_numpy()
        c_col = v ** (age + 1) * table["dx"].to_numpy()
        rev = lambda x: np.cumsum(x[::-1])[::-1]  # noqa: E731
        n_col, m_col = rev(d_col), rev(c_col)
        return cls(age, interest, d_col, n_col, rev(n_col), c_col, m_col, rev(m_col))

    @property
    def v(self) -> float:
        return 1.0 / (1.0 + self.interest)

    @property
    def discount_rate(self) -> float:
        """The annual discount rate d = i / (1 + i)."""
        return self.interest / (1.0 + self.interest)

    def _pick(self, column: np.ndarray, x) -> np.ndarray:
        idx = np.asarray(x, dtype=int) - int(self.age[0])
        inside = (idx >= 0) & (idx < len(column))
        out = np.where(inside, column[np.clip(idx, 0, len(column) - 1)], 0.0)
        return np.where(idx < 0, np.nan, out)

    # survival and insurance
    def pure_endowment(self, x, n):
        """``nEx``: 1 paid at x + n if alive."""
        return self._pick(self.D, np.asarray(x) + n) / self._pick(self.D, x)

    def whole_life_insurance(self, x):
        """``Ax``: 1 paid at the end of the year of death."""
        return self._pick(self.M, x) / self._pick(self.D, x)

    def term_insurance(self, x, n):
        """``A1x:n``: 1 paid at the end of the year of death if within n years."""
        return (self._pick(self.M, x) - self._pick(self.M, np.asarray(x) + n)) / self._pick(
            self.D, x
        )

    def deferred_insurance(self, x, n):
        """``n|Ax``: 1 paid at death if it occurs after n years."""
        return self._pick(self.M, np.asarray(x) + n) / self._pick(self.D, x)

    def endowment_insurance(self, x, n):
        """``Ax:n``: 1 at death within n years or at survival to n, whichever comes first."""
        return self.term_insurance(x, n) + self.pure_endowment(x, n)

    def increasing_whole_life(self, x):
        """``(IA)x``: 1 at the end of the first year of death, 2 for the second, and so on."""
        return self._pick(self.R, x) / self._pick(self.D, x)

    # annuities
    def annuity_due(self, x):
        """``a-due x``: 1 at the start of each year while alive."""
        return self._pick(self.N, x) / self._pick(self.D, x)

    def annuity_immediate(self, x):
        """``ax``: 1 at the end of each year while alive."""
        return self.annuity_due(x) - 1.0

    def temporary_annuity_due(self, x, n):
        """``a-due x:n``: annuity-due for at most n years."""
        return (self._pick(self.N, x) - self._pick(self.N, np.asarray(x) + n)) / self._pick(
            self.D, x
        )

    def deferred_annuity_due(self, x, n):
        """``n| a-due x``: annuity-due starting after n years."""
        return self._pick(self.N, np.asarray(x) + n) / self._pick(self.D, x)

    def annuity_due_monthly(self, x, m: int = 12):
        """``a-due(m) x``: payable m times a year, by the two-term Woolhouse approximation."""
        return self.annuity_due(x) - (m - 1) / (2 * m)

    # premiums and reserves
    def whole_life_premium(self, x):
        """Net annual premium for 1 of whole life insurance, paid for life."""
        return self.whole_life_insurance(x) / self.annuity_due(x)

    def term_premium(self, x, n):
        """Net annual premium for 1 of n-year term insurance, paid for at most n years."""
        return self.term_insurance(x, n) / self.temporary_annuity_due(x, n)

    def endowment_premium(self, x, n):
        """Net annual premium for 1 of n-year endowment insurance."""
        return self.endowment_insurance(x, n) / self.temporary_annuity_due(x, n)

    def whole_life_reserve(self, x, t):
        """Prospective net premium reserve after t years: ``A(x+t) - P(x) a-due(x+t)``."""
        xt = np.asarray(x) + t
        return self.whole_life_insurance(xt) - self.whole_life_premium(x) * self.annuity_due(xt)

    def udd_factor(self, m: int = 12) -> float:
        """``i / i(m)``: converts end-of-year-of-death insurance to the m-thly moment of death
        under a uniform distribution of deaths within the year."""
        i_m = m * ((1.0 + self.interest) ** (1.0 / m) - 1.0)
        return self.interest / i_m

    def columns(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"age": self.age, "Dx": self.D, "Nx": self.N, "Sx": self.S,
             "Cx": self.C, "Mx": self.M, "Rx": self.R}
        )  # fmt: skip

    def values(self, term: int = 20) -> pd.DataFrame:
        """The standard values at every age of the table (NaN where a term runs off the table)."""
        x = self.age
        return pd.DataFrame(
            {
                "age": x,
                "interest": self.interest,
                "A_whole_life": self.whole_life_insurance(x),
                "a_due": self.annuity_due(x),
                "a_due_monthly": self.annuity_due_monthly(x),
                "P_whole_life": self.whole_life_premium(x),
                f"A_term_{term}": self.term_insurance(x, term),
                f"P_term_{term}": self.term_premium(x, term),
                f"A_endowment_{term}": self.endowment_insurance(x, term),
                f"P_endowment_{term}": self.endowment_premium(x, term),
                f"E_{term}": self.pure_endowment(x, term),
            }
        )


# ── Tables for the warehouse ────────────────────────────────────────────────


def mexican_tables(graduated: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    """Life tables for every year and for men (M), women (F) and both sexes (T).

    ``graduated``: year, sex, age, qx, mx (ages 0 to 110). ``population``: year, sex, age,
    population, used only to weight the two sexes into one. Age 110 takes the weight of age 109.
    """
    rows = []
    pop = population.pivot_table(index=["year", "age"], columns="sex", values="population")
    for year, cell in graduated.groupby("year"):
        parts = {s: cell[cell["sex"] == s].sort_values("age").reset_index(drop=True) for s in "MF"}
        if any(p.empty for p in parts.values()):
            continue
        ages = parts["M"]["age"].to_numpy()
        share = pop.loc[year].reindex(ages).ffill()
        weight_male = (share["M"] / (share["M"] + share["F"])).to_numpy()
        parts["T"] = combine_sexes(parts["M"], parts["F"], weight_male)
        for sex, rates in parts.items():
            qx, mx = rates["qx"].to_numpy(), rates["mx"].to_numpy()
            table = build_life_table(
                ages, qx, ax=average_years_in_death_year(qx, mx), terminal_mx=float(mx[-1])
            )
            rows.append(table.assign(year=year, sex=sex, mx=mx))
    columns = ["year", "sex", "age", "qx", "px", "mx", "ax", "lx", "dx", "Lx", "Tx", "ex"]
    return pd.concat(rows, ignore_index=True)[columns]


def _comparison_row(source: str, name: str, sex: str, year, table: pd.DataFrame) -> dict:
    """The comparison measures of one table (blank where the table starts too late)."""
    c = Commutation.from_table(table, INTEREST)
    from_zero = int(table["age"].iloc[0]) == 0
    return {
        "source": source,
        "table": name,
        "sex": sex,
        "year": year,
        "first_age": int(table["age"].iloc[0]),
        "e0": _at(table, "ex", 0) if from_zero else np.nan,
        "e65": _at(table, "ex", 65),
        "lifespan_disparity": lifespan_disparity(table) if from_zero else np.nan,
        "a_due_65": float(c.annuity_due(65)),
        "A_40": float(c.whole_life_insurance(40)),
        "P_term_20_at_40": float(c.term_premium(40, 20)),
        "interest": INTEREST,
    }


def _table_from_q(age, qx, ax=None, terminal_mx=None) -> pd.DataFrame:
    q = np.asarray(qx, dtype=float).copy()
    q[-1] = 1.0  # close the table at its last age
    return build_life_table(age, q, ax=ax, terminal_mx=terminal_mx)


def comparison_table(con, reference_year: int, tables: pd.DataFrame) -> pd.DataFrame:
    """The same measures for the Mexican population, CNSF 2013, SOA Mexican tables and HMD."""
    from mortality import rates  # local import: rates has no dependency on this module

    rows = []
    for sex in ("M", "F", "T"):
        mex = tables[(tables["year"] == reference_year) & (tables["sex"] == sex)]
        if len(mex):
            name = f"Mexico, graduated {reference_year}"
            rows.append(_comparison_row("INEGI/CONAPO", name, sex, reference_year, mex))

    for label, (q, sex) in rates._benchmark_tables(con).items():
        q = q.sort_index()
        source = "CNSF" if "CNSF M 2013" in label else "SOA"
        rows.append(_comparison_row(source, label, sex, None, _table_from_q(q.index, q.to_numpy())))
    existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "cnsf_rates" in existing:
        cnsf = pd.read_sql(
            "SELECT variant, age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' "
            "AND variant IN ('p0.05', 'p99.5') ORDER BY age",
            con,
        )
        for variant, part in cnsf.groupby("variant"):
            name = f"CNSF M 2013 ({variant} percentile)"
            rows.append(
                _comparison_row("CNSF", name, "T", None, _table_from_q(part["age"], part["qx"]))
            )
    if "hmd_life_tables" in existing:
        hmd = pd.read_sql(
            "SELECT country, sex, year, age, mx, qx, ax FROM hmd_life_tables WHERE year = 2019 "
            "AND sex IN ('M', 'F', 'T') ORDER BY country, sex, age",
            con,
        )
        for (country, sex), part in hmd.groupby(["country", "sex"]):
            if len(part) != OMEGA + 1:
                continue
            table = _table_from_q(
                part["age"], part["qx"], ax=part["ax"], terminal_mx=float(part["mx"].iloc[-1])
            )
            rows.append(_comparison_row("HMD", f"{country} 2019", sex, 2019, table))
    return pd.DataFrame(rows)


def build_tables(con) -> list[tuple[str, str]]:
    """Build life tables, summaries, actuarial values and comparisons in the warehouse."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"graduated_qx", "conapo_population"} <= names:
        return []
    graduated = pd.read_sql("SELECT year, sex, age, qx, mx FROM graduated_qx", con)
    population = pd.read_sql(
        "SELECT year, sex, age, population FROM conapo_population WHERE state_code = 0 "
        f"AND year IN ({', '.join(str(int(y)) for y in graduated['year'].unique())})",
        con,
    )
    if graduated.empty or population.empty:
        return []
    tables = mexican_tables(graduated, population)
    if tables.empty:
        return []

    summaries, columns, values = [], [], []
    for (year, sex), t in tables.groupby(["year", "sex"]):
        t = t.reset_index(drop=True)
        summaries.append({"year": year, "sex": sex, **summary(t)})
        columns.append(Commutation.from_table(t, INTEREST).columns().assign(year=year, sex=sex))
        for rate in INTEREST_GRID:
            values.append(Commutation.from_table(t, rate).values().assign(year=year, sex=sex))
    key = ["year", "sex"]
    commutation = pd.concat(columns, ignore_index=True)[
        [*key, "age", "Dx", "Nx", "Sx", "Cx", "Mx", "Rx"]
    ]
    frames = {
        # SQLite column names ignore case, so L(x) and T(x) cannot sit beside l(x) and d(x)
        "life_tables": tables.rename(columns={"Lx": "person_years", "Tx": "total_person_years"}),
        "life_summary": pd.DataFrame(summaries),
        "commutation_columns": commutation,
        "actuarial_values": pd.concat(values, ignore_index=True),
    }
    reference = int(
        con.execute("SELECT year FROM state_smr LIMIT 1").fetchone()[0]
        if "state_smr" in names
        else tables["year"].max()
    )
    frames["life_table_comparison"] = comparison_table(con, reference, tables)

    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    con.execute("CREATE INDEX IF NOT EXISTS ix_life_tables ON life_tables (year, sex, age)")
    return docs


DESCRIPTIONS = {
    "life_tables": (
        "Complete life tables by year and sex (M, F, T = both sexes weighted by population), "
        "ages 0 to 110, from the graduated rates: qx, px, mx, ax, lx (radix 100,000), dx, "
        "person_years (L), total_person_years (T), ex"
    ),
    "life_summary": (
        "Per year and sex: life expectancy at 0, 1, 15, 40, 65 and 80, 5q0, 45q15, survival to "
        "65 and 80, median and modal age at death, lifespan disparity (e-dagger)"
    ),
    "commutation_columns": (
        "Commutation columns Dx, Nx, Sx, Cx, Mx, Rx at 4% interest, by year, sex and age"
    ),
    "actuarial_values": (
        "Whole-life, 20-year term and endowment insurance, annuity-due (annual and monthly), net "
        "annual premiums and the 20-year pure endowment at 3%, 4% and 5% interest, by year, sex "
        "and age"
    ),
    "life_table_comparison": (
        "Life expectancy, annuity-due at 65, whole-life insurance at 40 and 20-year term premium "
        "at 40 from the Mexican population table, CNSF 2013 (base and percentiles), the SOA "
        "Mexican tables and nine HMD countries, all built with the same code at 4% interest"
    ),
}
