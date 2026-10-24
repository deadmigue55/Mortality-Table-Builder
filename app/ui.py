"""Shared pieces of the dashboard: data access, theme, charts and page furniture.

The dashboard reads one small SQLite file (``app/data/demo.sqlite``), built from the warehouse by
``mortality app-data``, so it runs anywhere without the 170 MB warehouse or any raw data. The live
labs call the same Python engines the pipeline uses (``mortality.pricing``, ``.stress``,
``.reinsurance``, ``.experience``): what the page computes is what the tests check.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("mortality") is None:  # running from a checkout without installing
    sys.path.insert(0, str(ROOT / "src"))

DATA = Path(os.environ.get("MTB_APP_DATA", ROOT / "app" / "data"))
REPO = "https://github.com/deadmigue55/Mortality-Table-Builder"

INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE, AQUA, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#9a998f"
SEX_COLOR = {"M": BLUE, "F": ORANGE, "T": INK_2}
SEX_NAME = {"M": "Men", "F": "Women", "T": "Both sexes"}


# ── Data ────────────────────────────────────────────────────────────────────


@st.cache_resource(show_spinner=False)
def connection() -> sqlite3.Connection:
    path = DATA / "demo.sqlite"
    if not path.exists():
        st.error(f"{path} not found. Run `uv run mortality app-data` first.")
        st.stop()
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(show_spinner=False)
def sql(query: str, params: tuple = ()) -> pd.DataFrame:
    # numpy integers would be bound as blobs by sqlite3 and match nothing
    params = tuple(p.item() if isinstance(p, np.generic) else p for p in params)
    return pd.read_sql(query, connection(), params=params)


def table(name: str) -> pd.DataFrame:
    return sql(f'SELECT * FROM "{name}"')


@st.cache_data(show_spinner=False)
def inforce() -> pd.DataFrame:
    return pd.read_parquet(DATA / "inforce.parquet")


def sample_extract_path() -> Path:
    return DATA / "sample_policies.csv"


@st.cache_data(show_spinner=False)
def cnsf_curve(variant: str = "base", name: str = "CNSF M 2013") -> np.ndarray:
    df = sql(
        'SELECT age, qx FROM cnsf_rates WHERE "table" = ? AND variant = ? ORDER BY age',
        (name, variant),
    )
    return df.set_index("age")["qx"].reindex(range(111)).ffill().to_numpy()


@st.cache_data(show_spinner=False)
def graduated_curve(year: int, sex: str) -> np.ndarray:
    df = sql(
        "SELECT age, qx FROM graduated_qx WHERE year = ? AND sex = ? ORDER BY age", (year, sex)
    )
    return df.set_index("age")["qx"].reindex(range(111)).ffill().to_numpy()


@st.cache_data(show_spinner=False)
def projection_cube(sex: str) -> np.ndarray:
    df = sql("SELECT year, age, qx FROM projected_qx WHERE sex = ?", (sex,))
    return df.pivot_table(index="year", columns="age", values="qx").sort_index().to_numpy()


# ── Charts ──────────────────────────────────────────────────────────────────


def style(fig: go.Figure, height: int = 420, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        template="plotly_white",
        font={"family": "Inter, Segoe UI, Helvetica, Arial, sans-serif", "size": 13, "color": INK},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel={"font_size": 12},
        showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0, "title": None},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def rgba(color: str, alpha: float) -> str:
    """A hex color as an rgba() string, for translucent bands."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def show(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})


# Mexican states on a tile grid: (abbreviation, row, column). A cartogram without map files.
STATE_TILES: dict[int, tuple[str, int, int]] = {
    2: ("BC", 0, 0), 26: ("SON", 0, 1), 8: ("CHH", 0, 2), 5: ("COA", 0, 3), 19: ("NL", 0, 4),
    28: ("TAM", 0, 5),
    3: ("BCS", 1, 0), 25: ("SIN", 1, 1), 10: ("DUR", 1, 2), 32: ("ZAC", 1, 3), 24: ("SLP", 1, 4),
    18: ("NAY", 2, 1), 14: ("JAL", 2, 2), 1: ("AGS", 2, 3), 11: ("GTO", 2, 4), 22: ("QRO", 2, 5),
    13: ("HGO", 2, 6), 30: ("VER", 2, 7), 31: ("YUC", 2, 9),
    6: ("COL", 3, 2), 16: ("MIC", 3, 3), 15: ("MEX", 3, 4), 9: ("CDMX", 3, 5), 29: ("TLA", 3, 6),
    21: ("PUE", 3, 7), 27: ("TAB", 3, 8), 4: ("CAM", 3, 9), 23: ("QR", 3, 10),
    12: ("GRO", 4, 4), 17: ("MOR", 4, 5), 20: ("OAX", 4, 7), 7: ("CHP", 4, 8),
}  # fmt: skip


def tile_map(
    values: pd.Series, names: pd.Series, title: str, fmt: str = ".0%", colorscale=None, mid=None
) -> go.Figure:
    """A tile-grid map of the 32 states. ``values`` and ``names`` are indexed by state code."""
    codes = [c for c in STATE_TILES if c in values.index]
    x = [STATE_TILES[c][2] for c in codes]
    y = [-STATE_TILES[c][1] for c in codes]
    z = [float(values[c]) for c in codes]
    text = [f"{STATE_TILES[c][0]}<br>{format(values[c], fmt)}" for c in codes]
    hover = [f"<b>{names[c]}</b><br>{title}: {format(values[c], fmt)}" for c in codes]
    colorscale = colorscale or [[0, "#d9e8fa"], [0.5, "#7db0ea"], [1, "#c24a14"]]
    marker = {
        "symbol": "square", "size": 52, "color": z, "colorscale": colorscale,
        "colorbar": {"title": None, "tickformat": fmt, "thickness": 12, "len": 0.8},
        "line": {"color": "#fcfcfb", "width": 2},
    }  # fmt: skip
    if mid is not None:
        marker["cmid"] = mid
    fig = go.Figure(
        go.Scatter(x=x, y=y, mode="markers+text", marker=marker, text=text, hovertext=hover,
                   hoverinfo="text", textfont={"size": 10, "color": INK}, showlegend=False)
    )  # fmt: skip
    fig.update_xaxes(visible=False, range=[-0.7, 10.7])
    fig.update_yaxes(visible=False, range=[-4.7, 0.7], scaleanchor="x")
    return style(fig, height=380, legend=False)


# ── Page furniture ──────────────────────────────────────────────────────────


def header(title: str, lead: str, why: str | None = None) -> None:
    st.title(title)
    st.markdown(f"##### {lead}")
    if why:
        st.info(f"**Why it matters.** {why}", icon=":material/lightbulb:")


def source_note(tables: list[str], doc: str | None = None) -> None:
    refs = ", ".join(f"`{t}`" for t in tables)
    link = f" · [Method and results]({REPO}/blob/main/docs/{doc})" if doc else ""
    st.caption(f"Built from the warehouse tables {refs}{link}")


def synthetic_note() -> None:
    st.caption(
        ":material/science: The book of policies is **synthetic**, generated with planted effects to "
        "validate the method. It illustrates the analysis; it is not a real insurer."
    )


def metric_row(items: list[tuple[str, str, str | None]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value, note) in zip(cols, items, strict=True):
        col.metric(label, value)
        if note:
            col.caption(note)


def download(df: pd.DataFrame, name: str, label: str = "Download as CSV") -> None:
    st.download_button(
        label, df.to_csv(index=False).encode("utf-8"), file_name=name, mime="text/csv",
        icon=":material/download:",
    )  # fmt: skip


def money(x: float, unit: str = "") -> str:
    if abs(x) >= 1e9:
        return f"{x / 1e9:,.1f} bn{unit}"
    if abs(x) >= 1e6:
        return f"{x / 1e6:,.0f} M{unit}"
    return f"{x:,.0f}{unit}"
