"""
Reporting — a self-contained HTML report and a console summary.

The HTML report has no external assets and no plotting dependency: charts
are inline SVG/CSS, so a report can be e-mailed, attached to a ticket, or
archived and still render.  Every value that comes from the data (column
names, sample values, file names) is HTML-escaped.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from data_quality import __version__
from data_quality.checks import CheckResult
from data_quality.engine import QualityAssessment

_SEV_LABEL = {"info": "Pass", "warning": "Warning", "critical": "Critical"}


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _title(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _tone(score: float) -> str:
    return "good" if score >= 0.95 else "warn" if score >= 0.70 else "bad"


def _gauge(score: float, grade: str) -> str:
    r = 52
    circ = 2 * 3.14159 * r
    dash = circ * score
    return f"""<svg class="gauge {_tone(score)}" viewBox="0 0 120 120" role="img"
  aria-label="Composite score {score:.0%}, grade {grade}">
  <circle cx="60" cy="60" r="{r}" class="track"/>
  <circle cx="60" cy="60" r="{r}" class="arc" stroke-dasharray="{dash:.1f} {circ:.1f}"
    transform="rotate(-90 60 60)"/>
  <text x="60" y="58" class="pct">{score:.0%}</text>
  <text x="60" y="80" class="grade">Grade {grade}</text>
</svg>"""


def _score_bars(results: list[CheckResult]) -> str:
    rows = []
    for r in results:
        if r.skipped:
            rows.append(f'<div class="bar-row skipped"><span>{_e(_title(r.name))}</span>'
                        f'<div class="bar"></div><b>skipped</b></div>')
        else:
            rows.append(
                f'<div class="bar-row"><span>{_e(_title(r.name))}</span>'
                f'<div class="bar"><i class="{_tone(r.score)}" style="width:{r.score * 100:.1f}%"></i></div>'
                f'<b>{r.score:.0%}</b></div>'
            )
    return "\n".join(rows)


def _check_card(r: CheckResult) -> str:
    if r.skipped:
        status, tone = "Skipped", "muted"
    else:
        status, tone = _SEV_LABEL.get(r.severity, r.severity), _tone(r.score) if not r.passed else "good"
        if r.passed:
            status = "Pass"
    recs = ""
    if r.recommendations:
        recs = "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in r.recommendations) + "</ul>"
    score = "" if r.skipped else f'<span class="score">{r.score:.0%}</span>'
    return f"""<article class="check {tone}">
  <header><h3>{_e(_title(r.name))}</h3><div><span class="pill {tone}">{status}</span>{score}</div></header>
  <p>{_e(r.summary)}</p>{recs}
</article>"""


def _profile_table(assessment: QualityAssessment) -> str:
    rows = []
    for c in assessment.column_profile:
        rng = ""
        if "min" in c:
            rng = f"{_e(c['min'])} – {_e(c['max'])}"
        top = ", ".join(f"{_e(t['value'])} ({t['count']:,})" for t in c.get("top_values", []))
        miss_tone = "bad" if c["missing_pct"] > assessment.config.missing_threshold else ""
        rows.append(
            f"<tr><td><b>{_e(c['column'])}</b></td><td><code>{_e(c['dtype'])}</code></td>"
            f'<td class="num {miss_tone}">{c["missing_pct"]:.1%}</td>'
            f'<td class="num">{c["unique"]:,}</td><td>{rng}</td><td class="top">{top}</td></tr>'
        )
    return "\n".join(rows)


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#667085;--line:#e4e7ec;
--good:#12805c;--warn:#b54708;--bad:#c4320a;--track:#eaecf0;--accent:#2f5bea}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--text:#e6e8ec;--muted:#98a2b3;
--line:#2a303b;--good:#3ccb8f;--warn:#f5a524;--bad:#f97066;--track:#2a303b;--accent:#7b9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.1rem;margin:36px 0 12px}
.meta{color:var(--muted);font-size:.875rem;margin:0}
.top-grid{display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:center;
background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}
.gauge{width:150px;height:150px}.gauge .track{fill:none;stroke:var(--track);stroke-width:12}
.gauge .arc{fill:none;stroke-width:12;stroke-linecap:round}
.gauge.good .arc{stroke:var(--good)}.gauge.warn .arc{stroke:var(--warn)}.gauge.bad .arc{stroke:var(--bad)}
.gauge .pct{font-size:26px;font-weight:700;text-anchor:middle;fill:var(--text)}
.gauge .grade{font-size:11px;text-anchor:middle;fill:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px}
.stat b{display:block;font-size:1.4rem}.stat span{color:var(--muted);font-size:.8rem}
.bars{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px}
.bar-row{display:grid;grid-template-columns:200px 1fr 64px;gap:12px;align-items:center;padding:5px 0;font-size:.875rem}
.bar-row b{text-align:right;font-variant-numeric:tabular-nums}.bar-row.skipped{color:var(--muted)}
.bar{height:10px;background:var(--track);border-radius:5px;overflow:hidden}.bar i{display:block;height:100%}
i.good{background:var(--good)}i.warn{background:var(--warn)}i.bad{background:var(--bad)}
.check{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);
border-radius:10px;padding:14px 18px;margin-bottom:10px}
.check.good{border-left-color:var(--good)}.check.warn{border-left-color:var(--warn)}.check.bad{border-left-color:var(--bad)}
.check header{display:flex;justify-content:space-between;gap:12px;align-items:center}
.check h3{margin:0;font-size:1rem}.check p{margin:6px 0 0;color:var(--muted)}
.check ul{margin:8px 0 0;padding-left:20px}.check li{margin:2px 0}
.pill{font-size:.75rem;font-weight:600;padding:2px 10px;border-radius:999px;border:1px solid currentColor}
.pill.good{color:var(--good)}.pill.warn{color:var(--warn)}.pill.bad{color:var(--bad)}.pill.muted{color:var(--muted)}
.score{margin-left:10px;font-weight:700;font-variant-numeric:tabular-nums}
.table-wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}td.num{text-align:right;font-variant-numeric:tabular-nums}
td.bad{color:var(--bad);font-weight:600}td.top{color:var(--muted);max-width:320px}
code{font-size:.8rem}footer{color:var(--muted);font-size:.8rem;margin-top:32px}
@media (max-width:640px){.top-grid{grid-template-columns:1fr;justify-items:center}
.bar-row{grid-template-columns:120px 1fr 48px}}
@media print{body{background:#fff}.check,.bars,.top-grid,.table-wrap{break-inside:avoid}}
"""


def generate_html_report(assessment: QualityAssessment, output_path: str | Path | None = None) -> str:
    """Build a self-contained HTML report; optionally write it to ``output_path``."""
    s = assessment.summary_dict()
    ordered = sorted(assessment.results, key=lambda r: (r.skipped, r.passed, r.score))
    title = assessment.config.report_title

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} — {_e(assessment.dataset_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<main class="wrap">
<h1>{_e(title)}</h1>
<p class="meta">Dataset <b>{_e(assessment.dataset_name)}</b> · generated {_e(assessment.generated_at)}
 · {assessment.elapsed_seconds:.2f}s · {assessment.memory_usage_mb:.1f} MB in memory</p>

<section class="top-grid">
{_gauge(assessment.composite_score, assessment.grade)}
<div class="stats">
  <div class="stat"><b>{s['rows']:,}</b><span>Rows</span></div>
  <div class="stat"><b>{s['columns']:,}</b><span>Columns</span></div>
  <div class="stat"><b>{s['checks_passed']}/{s['checks_run']}</b><span>Checks passed</span></div>
  <div class="stat"><b>{s['critical']}</b><span>Critical</span></div>
  <div class="stat"><b>{s['warnings']}</b><span>Warnings</span></div>
  <div class="stat"><b>{s['checks_skipped']}</b><span>Skipped (no rules)</span></div>
</div>
</section>

<h2>Check scores</h2>
<div class="bars">{_score_bars(assessment.results)}</div>

<h2>Findings</h2>
{"".join(_check_card(r) for r in ordered)}

<h2>Column profile</h2>
<div class="table-wrap"><table>
<thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Distinct</th><th>Range</th><th>Most common</th></tr></thead>
<tbody>{_profile_table(assessment)}</tbody>
</table></div>

<footer>Data Quality Assessment Tool v{__version__}. Skipped checks are excluded from the composite score.</footer>
</main>
</body>
</html>"""

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html, encoding="utf-8")
    return html


def print_console_summary(assessment: QualityAssessment) -> None:
    """Print a compact text summary to stdout."""
    s = assessment.summary_dict()
    line = "=" * 64
    print(f"\n{line}\n  DATA QUALITY: {s['dataset']}\n{line}")
    print(f"  Rows: {s['rows']:,}  |  Columns: {s['columns']}")
    print(f"  Score: {assessment.composite_score:.1%}  (grade {s['grade']})")
    print(f"  Passed: {s['checks_passed']}/{s['checks_run']}  |  Critical: {s['critical']}"
          f"  |  Warnings: {s['warnings']}  |  Skipped: {s['checks_skipped']}")
    print("-" * 64)
    for r in assessment.results:
        if r.skipped:
            print(f"  [SKIP] {r.name:<26s}  {r.summary}")
            continue
        tag = "[PASS]" if r.passed else "[FAIL]"
        print(f"  {tag} {r.name:<26s} {r.score:>6.1%}  {r.severity.upper()}")
        for rec in r.recommendations:
            print(f"         -> {rec}")
    print(f"{line}\n")
