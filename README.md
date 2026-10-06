# Data Quality Assessment Tool

Profile, validate, and score a tabular dataset before you trust it — missing values,
duplicate rows and keys, malformed formats, impossible dates, out-of-range numbers,
outliers, and orphaned foreign keys. Every finding comes with a count, examples, and
what to do about it.

Use it three ways, all running the same Python engine:

| | |
|---|---|
| **Web app** | Drop a file in the browser. Runs locally via Pyodide — the file is never uploaded. |
| **CLI** | `data-quality orders.csv -c rules.json --fail-under 0.9` — a quality gate for pipelines and CI. |
| **Python** | `assess(df, {"unique_columns": ["order_id"]})` inside notebooks, Airflow, dbt hooks, etc. |

## Install

```bash
pip install "git+https://github.com/Mo-reece/Data-Quality-Assessment-Tool.git"
# Excel / Parquet support:
pip install "data-quality-assessment[all] @ git+https://github.com/Mo-reece/Data-Quality-Assessment-Tool.git"
```

Requires Python 3.10+ with pandas 2 or 3.

## CLI

```bash
data-quality orders.csv                                  # console summary + reports/orders_quality_report.html
data-quality orders.csv --suggest rules.json             # infer starter rules from the data, then edit them
data-quality orders.csv -c rules.json --json out.json    # also write machine-readable results
data-quality orders.csv -c rules.json --ref customers=customers.csv   # foreign-key checks
data-quality orders.csv -c rules.json --fail-under 0.9 --fail-on-critical -q
```

Exit codes: `0` success · `1` bad input or rules · `2` quality gate failed — so a failing
dataset stops a pipeline or CI job:

```yaml
- run: data-quality data/export.csv -c rules.json --fail-under 0.9 --json quality.json -q
```

Supported files: CSV (delimiter sniffed), TSV, Excel, Parquet, JSON, JSONL.

## Rules file

Only state what differs from the defaults; unknown keys and invalid values are rejected
with a clear message rather than silently ignored.

```json
{
  "not_null_columns": ["order_id", "customer_id"],
  "unique_columns": ["order_id"],
  "string_patterns": { "email": "[^@\\s]+@[^@\\s]+\\.[A-Za-z]{2,}" },
  "range_rules": { "quantity": { "min": 1, "max": 100 } },
  "date_columns": ["order_date"],
  "date_format": "%Y-%m-%d",
  "reference_rules": [
    { "child_col": "customer_id", "parent_df": "customers", "parent_col": "customer_id" }
  ]
}
```

Rules exported from the web app work unchanged with the CLI. All options:

| Key | Default | Meaning |
|---|---|---|
| `missing_threshold` | `0.05` | Flag columns missing more than this fraction |
| `not_null_columns` | `[]` | Columns that must have no missing values |
| `unique_columns` | `[]` | Columns that must be unique (keys) |
| `duplicate_subset` | `null` | Columns that together identify a row |
| `string_patterns` | `{}` | `{column: regex}`, full match required |
| `range_rules` | `{}` | `{column: {"min": x, "max": y}}` |
| `date_columns` / `date_format` | `[]` / `"%Y-%m-%d"` | `null` format = detect automatically |
| `allow_future_dates` / `min_date` | `false` / `"1900-01-01"` | Date plausibility |
| `expected_dtypes` | `{}` | Exact dtype or a family: `numeric`, `integer`, `float`, `string`, `datetime`, `bool` |
| `reference_rules` | `[]` | Foreign keys checked against reference tables |
| `outlier_method` | `"iqr"` | `"iqr"` or `"zscore"` (+ `outlier_iqr_factor`, `outlier_zscore_threshold`) |
| `severity_weights` | see `config.py` | Weight of each check in the composite score |
| `enabled_checks` | all | Restrict to a subset of checks |

## Scoring

Each check scores 0–100% in proportion to how much data is affected (1% bad values costs
5 points; 20% drives a check to zero). The composite is a weighted average of the checks
that ran — a check with no rules configured is reported as **skipped** and excluded, so
it can't inflate the score. Grades: A ≥ 95, B ≥ 85, C ≥ 70, D ≥ 50, F below.

## Python API

```python
from data_quality import assess, load_table, suggest_config
from data_quality.report import generate_html_report

df = load_table("orders.csv")
rules = suggest_config(df)            # a QualityConfig you can adjust
rules.range_rules["quantity"] = {"min": 1}

result = assess(df, rules, name="orders", reference_dfs={"customers": load_table("customers.csv")})
result.composite_score, result.grade   # 0.891, "B"
result.critical_issues                 # failed checks scoring below 70%
result.to_dict()                       # JSON-safe, for logs or dashboards
generate_html_report(result, "reports/orders.html")
```

## Web app

The site in `web/` loads [Pyodide](https://pyodide.org) in a Web Worker and runs this
package unchanged. `scripts/build_web.sh` copies the package and sample data into `web/`;
Vercel runs it on deploy (`vercel.json`). To run locally:

```bash
sh scripts/build_web.sh
python -m http.server 8765 -d web
```

## Development

```bash
pip install -e ".[all]"
python -m unittest discover -s tests -v
python examples/make_sample_data.py   # regenerate the synthetic sample files
```

## Project layout

```
data_quality/
  checks.py    the ten checks
  config.py    validated, JSON-serialisable rules
  engine.py    orchestration, scoring, column profile
  io.py        file loading (paths or bytes)
  suggest.py   starter rules inferred from data
  report.py    self-contained HTML report + console summary
  cli.py       `data-quality` command
web/           browser app (static; Pyodide)
examples/      synthetic orders/customers data and rules
tests/
```

## License

MIT
