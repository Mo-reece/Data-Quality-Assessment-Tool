"""
Data Quality Assessment Tool
============================
Profile, validate, and score tabular data; produce HTML and JSON reports.

    >>> from data_quality import assess, load_table
    >>> result = assess(load_table("orders.csv"), {"unique_columns": ["order_id"]})
    >>> result.composite_score, result.grade

Modules:
    checks  - individual check functions
    engine  - orchestration, scoring, and column profiling
    config  - validated, JSON-serialisable rules
    io      - file loading (CSV, TSV, Excel, Parquet, JSON)
    suggest - starter rules inferred from a dataset
    report  - self-contained HTML report and console summary
"""

__version__ = "2.0.0"

from data_quality.config import ConfigError, QualityConfig  # noqa: E402
from data_quality.engine import DataQualityEngine, QualityAssessment, assess  # noqa: E402
from data_quality.io import load_table  # noqa: E402
from data_quality.suggest import suggest_config  # noqa: E402

__all__ = [
    "ConfigError",
    "DataQualityEngine",
    "QualityAssessment",
    "QualityConfig",
    "assess",
    "load_table",
    "suggest_config",
    "__version__",
]
