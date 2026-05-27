# Data Quality Assessment Tool

A modular, production-ready Python toolkit for automated data quality profiling, validation, and reporting.

## Features

| Check | Description |
|-------|-------------|
| **Missing Values** | Counts, percentages, column-level patterns, empty-column detection |
| **Duplicates** | Full-row and partial (subset) duplicate detection |
| **Data Type Validation** | Verify columns match expected dtypes |
| **Outlier Detection** | IQR and Z-score methods with per-column stats |
| **Cardinality Analysis** | High-cardinality categoricals, low-cardinality numerics |
| **String Pattern Validation** | Regex-based validation (emails, IDs, codes, etc.) |
| **Referential Integrity** | Foreign-key / orphan-value detection across tables |
| **Statistical Distribution** | Skewness, kurtosis, and distribution profiling |
| **Date/Time Validation** | Parsability, future dates, unreasonable ranges |
| **Range Validation** | Min/max boundary checks on numeric columns |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run against a CSV with default settings
python data_quality_tool.py data/your_dataset.csv

# Specify output path and dataset name
python data_quality_tool.py data/sales.csv -o reports/sales_report.html -n "Q1 Sales"

# Use a custom config
python data_quality_tool.py data/sales.csv -c config_template.json

# Run only specific checks
python data_quality_tool.py data/sales.csv --checks missing_values outliers duplicates

# Console-only output (skip HTML)
python data_quality_tool.py data/sales.csv --no-html

# Export default config template
python data_quality_tool.py --save-config my_config.json
```

## Python API

```python
import pandas as pd
from data_quality import DataQualityEngine, QualityConfig
from data_quality.report import generate_html_report, print_console_summary

df = pd.read_csv("data/orders.csv")

config = QualityConfig(
    missing_threshold=0.05,
    outlier_method="iqr",
    string_patterns={"email": r"[^@]+@[^@]+\.[^@]+"},
    range_rules={"price": {"min": 0, "max": 10000}},
    date_columns=["order_date"],
)

engine = DataQualityEngine(config)
assessment = engine.run(df, name="orders")

# Console summary
print_console_summary(assessment)

# HTML report
generate_html_report(assessment, output_path="reports/orders.html")

# Programmatic access
print(assessment.composite_score)       # 0.0 - 1.0
print(assessment.critical_issues)       # list of failed checks
print(assessment.summary_dict())        # dict for logging / dashboards
```

## Pipeline Integration (Quality Gate)

```python
THRESHOLD = 0.80
assessment = DataQualityEngine().run(df, name="pipeline_check")

if assessment.composite_score < THRESHOLD:
    raise RuntimeError(f"Quality gate failed: {assessment.composite_score:.1%}")
```

## Project Structure

```
day06-data-quality-tool/
├── data_quality/
│   ├── __init__.py        # Package exports
│   ├── checks.py          # 10 individual check functions
│   ├── config.py          # QualityConfig dataclass (JSON serialisable)
│   ├── engine.py          # Orchestration engine + QualityAssessment
│   └── report.py          # HTML report generation + console printer
├── data/                  # Place datasets here
├── reports/               # Generated HTML reports
├── data_quality_tool.py   # CLI entry point (argparse)
├── demo_notebook.ipynb    # Full walkthrough with synthetic data
├── config_template.json   # Editable config template
├── requirements.txt
└── README.md
```

## Configuration

Copy `config_template.json` and edit to match your dataset. Key options:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `missing_threshold` | 0.05 | Flag columns with > 5 % missing |
| `outlier_method` | `"iqr"` | `"iqr"` or `"zscore"` |
| `outlier_iqr_factor` | 1.5 | IQR multiplier for fences |
| `outlier_zscore_threshold` | 3.0 | Z-score cutoff |
| `string_patterns` | `{}` | `{column: regex}` pairs |
| `range_rules` | `{}` | `{column: {min, max}}` pairs |
| `date_columns` | `[]` | Columns to validate as dates |
| `enabled_checks` | `null` | Run all checks, or list specific ones |
| `severity_weights` | see template | Weights for composite score |

## Supported File Formats

CSV, TSV, Excel (.xlsx/.xls), Parquet, JSON — auto-detected from file extension.

## Testing

Run the regression test suite before changing the CLI or package layout:

```bash
python -m unittest discover -s tests -v
```

The GitHub Actions workflow in `.github/workflows/python-tests.yml` runs the same command on pull requests and pushes to `main`.

## Requirements

- Python 3.10+
- pandas, numpy, matplotlib (see requirements.txt)
