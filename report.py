"""
Reporting module — generates styled HTML reports and console summaries.

Uses only the Python standard library plus matplotlib for chart
generation (base64-encoded PNGs embedded directly in the HTML).
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from data_quality.engine import QualityAssessment


# ── Colour palette ────────────────────────────────────────────────────

_COLORS = {
    "critical": "#e74c3c",
    "warning": "#f39c12",
    "info": "#27ae60",
    "bg": "#f8f9fa",
    "card": "#ffffff",
    "text": "#2c3e50",
    "border": "#dee2e6",
    "primary": "#3498db",
    "gauge_bg": "#ecf0f1",
}


# ── Chart helpers ─────────────────────────────────────────────────────

def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _score_gauge_chart(score: float) -> str:
    """Render a semi-circle gauge for the composite score."""
    fig, ax = plt.subplots(figsize=(4, 2.4), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(3.14159)
    ax.set_theta_direction(-1)
    ax.set_rlim(0, 1)

    # Background arc
    theta_bg = [i * 3.14159 / 100 for i in range(101)]
    ax.fill_between(theta_bg, 0.6, 1.0, color=_COLORS["gauge_bg"], alpha=0.5)

    # Score arc
    theta_score = [i * 3.14159 / 100 for i in range(int(score * 100) + 1)]
    color = _COLORS["info"] if score >= 0.8 else _COLORS["warning"] if score >= 0.6 else _COLORS["critical"]
    ax.fill_between(theta_score, 0.6, 1.0, color=color, alpha=0.8)

    ax.set_axis_off()
    ax.text(0, 0, f"{score:.0%}", ha="center", va="center", fontsize=28, fontweight="bold", color=color)

    return _fig_to_base64(fig)


def _check_scores_bar(assessment: QualityAssessment) -> str:
    """Horizontal bar chart showing each check's score."""
    names = [r.name.replace("_", " ").title() for r in assessment.results]
    scores = [r.score for r in assessment.results]
    colors = [
        _COLORS["info"] if s >= 0.95 else _COLORS["warning"] if s >= 0.7 else _COLORS["critical"]
        for s in scores
    ]

    fig, ax = plt.subplots(figsize=(7, max(2.5, len(names) * 0.45)))
    bars = ax.barh(names, scores, color=colors, edgecolor="white", height=0.6)
    ax.set_xlim(0, 1.05)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.invert_yaxis()
    ax.set_xlabel("Score")
    ax.spines[["top", "right"]].set_visible(False)

    for bar, s in zip(bars, scores):
        ax.text(s + 0.01, bar.get_y() + bar.get_height() / 2, f"{s:.0%}",
                va="center", fontsize=9)

    fig.tight_layout()
    return _fig_to_base64(fig)


def _severity_pie(assessment: QualityAssessment) -> str:
    """Pie chart of check severity counts."""
    counts = {"info": 0, "warning": 0, "critical": 0}
    for r in assessment.results:
        counts[r.severity] += 1

    labels = [k.title() for k, v in counts.items() if v > 0]
    sizes = [v for v in counts.values() if v > 0]
    colors = [_COLORS[k] for k, v in counts.items() if v > 0]

    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%",
           startangle=90, textprops={"fontsize": 10})
    fig.tight_layout()
    return _fig_to_base64(fig)


# ── HTML builder ──────────────────────────────────────────────────────

def _severity_badge(sev: str) -> str:
    color = _COLORS.get(sev, _COLORS["text"])
    return f'<span style="background:{color};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.85em;">{sev.upper()}</span>'


def _build_check_card(r: Any) -> str:
    status_icon = "&#10004;" if r.passed else "&#10008;"
    status_color = _COLORS["info"] if r.passed else _COLORS["critical"]
    recs_html = ""
    if r.recommendations:
        recs_items = "".join(f"<li>{rec}</li>" for rec in r.recommendations)
        recs_html = f'<div style="margin-top:8px;"><strong>Recommendations:</strong><ul style="margin:4px 0 0 16px;">{recs_items}</ul></div>'

    return f"""
    <div style="background:{_COLORS['card']};border:1px solid {_COLORS['border']};border-left:4px solid {_COLORS.get(r.severity, _COLORS['border'])};border-radius:6px;padding:16px;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h3 style="margin:0;color:{_COLORS['text']};">
                <span style="color:{status_color};margin-right:6px;">{status_icon}</span>
                {r.name.replace('_', ' ').title()}
            </h3>
            <div>{_severity_badge(r.severity)} <span style="margin-left:8px;font-weight:bold;">{r.score:.0%}</span></div>
        </div>
        <p style="margin:8px 0 0;color:#555;">{r.summary}</p>
        {recs_html}
    </div>"""


def generate_html_report(assessment: QualityAssessment, output_path: str | Path | None = None) -> str:
    """Build a self-contained HTML quality report.

    Parameters
    ----------
    assessment : QualityAssessment
        Output of ``DataQualityEngine.run()``.
    output_path : str or Path, optional
        If given, the HTML is also written to this file.

    Returns
    -------
    str
        The full HTML document as a string.
    """
    gauge_b64 = _score_gauge_chart(assessment.composite_score)
    bar_b64 = _check_scores_bar(assessment)
    pie_b64 = _severity_pie(assessment)

    check_cards = "\n".join(_build_check_card(r) for r in assessment.results)

    summary = assessment.summary_dict()

    dtype_rows = "".join(
        f"<tr><td>{col}</td><td><code>{dt}</code></td></tr>"
        for col, dt in assessment.dtypes.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{assessment.config.report_title}</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: {_COLORS['bg']}; color: {_COLORS['text']}; line-height: 1.6; padding: 24px; }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    h1 {{ font-size: 1.8em; margin-bottom: 4px; }}
    h2 {{ font-size: 1.3em; margin: 28px 0 12px; border-bottom: 2px solid {_COLORS['primary']}; padding-bottom: 4px; }}
    .meta {{ color: #888; font-size: 0.9em; margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
    .stat-card {{ background: {_COLORS['card']}; border: 1px solid {_COLORS['border']};
                  border-radius: 8px; padding: 16px; text-align: center; }}
    .stat-card .value {{ font-size: 1.8em; font-weight: bold; color: {_COLORS['primary']}; }}
    .stat-card .label {{ font-size: 0.85em; color: #888; }}
    .chart-row {{ display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; margin-bottom: 20px; }}
    .chart-row img {{ max-width: 100%; height: auto; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px;
             background: {_COLORS['card']}; border-radius: 6px; overflow: hidden; }}
    th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid {_COLORS['border']}; font-size: 0.9em; }}
    th {{ background: {_COLORS['primary']}; color: #fff; }}
    footer {{ text-align: center; color: #aaa; font-size: 0.8em; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">

<h1>{assessment.config.report_title}</h1>
<p class="meta">Dataset: <strong>{assessment.dataset_name}</strong> &middot;
   Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &middot;
   Elapsed: {assessment.elapsed_seconds:.2f}s &middot;
   Memory: {assessment.memory_usage_mb:.1f} MB</p>

<!-- ─── Summary stats ─────────────────────────────── -->
<div class="grid">
    <div class="stat-card"><div class="value">{summary['rows']:,}</div><div class="label">Rows</div></div>
    <div class="stat-card"><div class="value">{summary['columns']}</div><div class="label">Columns</div></div>
    <div class="stat-card"><div class="value">{summary['checks_passed']}/{summary['checks_run']}</div><div class="label">Checks Passed</div></div>
    <div class="stat-card"><div class="value" style="color:{_COLORS['critical'] if summary['critical'] else _COLORS['info']};">{summary['critical']}</div><div class="label">Critical Issues</div></div>
</div>

<!-- ─── Charts ────────────────────────────────────── -->
<h2>Quality Score</h2>
<div class="chart-row">
    <img src="data:image/png;base64,{gauge_b64}" alt="Quality gauge" style="max-width:280px;">
    <img src="data:image/png;base64,{pie_b64}" alt="Severity breakdown" style="max-width:260px;">
</div>

<h2>Check Scores</h2>
<div style="text-align:center;margin-bottom:20px;">
    <img src="data:image/png;base64,{bar_b64}" alt="Check scores" style="max-width:700px;">
</div>

<!-- ─── Detailed check results ────────────────────── -->
<h2>Detailed Results</h2>
{check_cards}

<!-- ─── Column types ──────────────────────────────── -->
<h2>Column Data Types</h2>
<table>
<thead><tr><th>Column</th><th>Dtype</th></tr></thead>
<tbody>{dtype_rows}</tbody>
</table>

<footer>Data Quality Assessment Tool v1.0.0 &mdash; generated automatically</footer>
</div>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html


def print_console_summary(assessment: QualityAssessment) -> None:
    """Print a compact, coloured summary to stdout."""
    s = assessment.summary_dict()
    print("\n" + "=" * 60)
    print(f"  DATA QUALITY REPORT: {s['dataset']}")
    print("=" * 60)
    print(f"  Rows: {s['rows']:,}  |  Columns: {s['columns']}")
    print(f"  Composite Score: {assessment.composite_score:.1%}")
    print(f"  Checks Passed: {s['checks_passed']}/{s['checks_run']}")
    print(f"  Critical: {s['critical']}  |  Warnings: {s['warnings']}")
    print("-" * 60)

    for r in assessment.results:
        icon = "[PASS]" if r.passed else "[FAIL]"
        print(f"  {icon} {r.name:<28s}  {r.score:>6.1%}  {r.severity.upper()}")
        if r.recommendations:
            for rec in r.recommendations:
                print(f"         -> {rec}")

    print("=" * 60)
    print(f"  Elapsed: {assessment.elapsed_seconds:.2f}s  |  Memory: {assessment.memory_usage_mb:.1f} MB")
    print("=" * 60 + "\n")
