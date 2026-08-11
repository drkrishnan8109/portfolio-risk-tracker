"""Plotly figures.

Form choices, and why:

* **Every breakdown is a horizontal bar chart.** Each one measures a single thing —
  share of portfolio — across named categories. A donut would be part-to-whole at a
  glance only, capped at ~6 segments, and unreadable for the close values these
  breakdowns produce. A ranked bar reads exactly.
* **One hue, not a categorical palette.** Eight hues for one measure is decoration.
  Risk emphasis lives in the findings section, where it carries meaning.
* **Direct value labels on every bar.** The palette's contrast check warns below 3:1
  on the light surface, and the relief for that is visible labels or a table view.
  This ships both.

Palette values come from the validated reference set (blue slot 1, light `#2a78d6`,
dark `#3987e5`), checked with the palette validator rather than eyeballed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

MAX_BARS = 15
OTHER_LABEL = "Other"


@dataclass(frozen=True)
class Theme:
    surface: str
    text_primary: str
    text_secondary: str
    grid: str
    series: str

    @classmethod
    def for_mode(cls, dark: bool) -> Theme:
        """Dark steps are selected for the dark surface, not an automatic flip."""
        if dark:
            return cls(
                surface="#1a1a19",
                text_primary="#ffffff",
                text_secondary="#c3c2b7",
                grid="#2f2f2d",
                series="#3987e5",
            )
        return cls(
            surface="#fcfcfb",
            text_primary="#0b0b0b",
            text_secondary="#52514e",
            grid="#e8e8e4",
            series="#2a78d6",
        )


def collapse_tail(series: pd.Series, limit: int = MAX_BARS) -> pd.Series:
    """Keep the largest `limit` entries and fold the rest into one 'Other' bar."""
    if len(series) <= limit:
        return series
    head = series.nlargest(limit)
    return pd.concat([head, pd.Series({OTHER_LABEL: float(series.iloc[limit:].sum())})])


def share_bar(
    shares: pd.Series,
    *,
    title: str,
    base_currency: str,
    values: pd.Series | None = None,
    theme: Theme | None = None,
    limit: int = MAX_BARS,
) -> go.Figure:
    """A ranked horizontal bar chart of portfolio shares.

    Args:
        shares: Fractions of the portfolio, indexed by label.
        title: Axis title; the surrounding heading names the chart.
        base_currency: For the money shown in the tooltip.
        values: Optional absolute amounts, indexed the same way.
        theme: Light or dark styling.
        limit: Bars beyond this fold into "Other".
    """
    palette = theme or Theme.for_mode(dark=False)
    plotted = collapse_tail(shares.sort_values(ascending=False), limit)
    ordered = plotted.sort_values()  # plotly draws the first row at the bottom

    amounts = None
    if values is not None:
        amounts = [float(values.get(label, float("nan"))) for label in ordered.index]

    customdata = [[a] for a in amounts] if amounts else None
    hover = (
        "<b>%{y}</b><br>%{x:.1%} of portfolio"
        + (f"<br>%{{customdata[0]:,.0f}} {base_currency}" if amounts else "")
        + "<extra></extra>"
    )

    figure = go.Figure(
        go.Bar(
            x=ordered.to_numpy(),
            y=[str(i) for i in ordered.index],
            orientation="h",
            marker={"color": palette.series, "cornerradius": 4, "line": {"width": 0}},
            text=[f"{v:.1%}" for v in ordered],
            textposition="outside",
            textfont={"color": palette.text_secondary, "size": 12},
            customdata=customdata,
            hovertemplate=hover,
            cliponaxis=False,
        )
    )
    figure.update_layout(
        height=max(220, 30 * len(ordered) + 90),
        margin={"l": 8, "r": 56, "t": 8, "b": 36},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,  # one series: the heading names it
        bargap=0.35,
        font={"color": palette.text_secondary, "size": 12},
        xaxis={
            "title": {"text": title, "font": {"size": 11}},
            "tickformat": ".0%",
            "gridcolor": palette.grid,
            "griddash": "solid",
            "zeroline": False,
            "showline": False,
            "rangemode": "tozero",
        },
        yaxis={
            "showgrid": False,
            "zeroline": False,
            "showline": False,
            "tickfont": {"color": palette.text_primary, "size": 12},
        },
    )
    return figure


def correlation_heatmap(matrix: pd.DataFrame, *, theme: Theme | None = None) -> go.Figure:
    """Correlation matrix as a diverging heatmap.

    Two poles with a neutral midpoint at zero — never a rainbow, and never a hue at
    the midpoint, so "unrelated" reads as absence rather than as another category.
    """
    palette = theme or Theme.for_mode(dark=False)
    figure = go.Figure(
        go.Heatmap(
            z=matrix.to_numpy(),
            x=[str(c) for c in matrix.columns],
            y=[str(i) for i in matrix.index],
            zmin=-1,
            zmax=1,
            colorscale=[
                [0.0, "#2a78d6"],
                [0.5, "#e8e8e4" if palette.surface == "#fcfcfb" else "#3a3a37"],
                [1.0, "#eb6834"],
            ],
            colorbar={"title": {"text": "corr", "side": "right"}, "thickness": 10},
            hovertemplate="<b>%{y}</b> vs <b>%{x}</b><br>correlation %{z:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        height=max(320, 26 * len(matrix) + 120),
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": palette.text_secondary, "size": 11},
        xaxis={"showgrid": False, "tickangle": -45},
        yaxis={"showgrid": False, "autorange": "reversed"},
    )
    return figure
