"""
Configuration module for the Data Quality Assessment Tool.

Handles loading, validating, and providing default configuration for
all quality checks. Supports YAML config files and programmatic overrides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class QualityConfig:
    """Configuration for data quality checks.

    Attributes:
        missing_threshold: Max acceptable missing-value fraction (0-1).
        duplicate_subset: Column subset for partial-duplicate detection.
            None means check all columns (full-row duplicates).
        outlier_method: One of 'iqr' or 'zscore'.
        outlier_iqr_factor: IQR multiplier for fence calculation.
        outlier_zscore_threshold: Z-score cutoff for outlier flagging.
        high_cardinality_threshold: Unique-value ratio above which a
            categorical column is flagged as high-cardinality.
        low_cardinality_threshold: Unique-value count below which a
            numeric column is flagged as potentially categorical.
        string_patterns: Mapping of column name -> regex pattern to validate.
        expected_dtypes: Mapping of column name -> expected pandas dtype string.
        range_rules: Mapping of column name -> {"min": ..., "max": ...}.
        date_columns: List of columns expected to contain dates.
        date_format: Expected date format string (strftime-style).
        reference_rules: List of dicts with keys 'child_col', 'parent_df',
            'parent_col' for referential-integrity checks.
        severity_weights: Mapping of check name -> weight (0-1) for the
            composite quality score.
        enabled_checks: Set of check names to run.  None means run all.
        report_title: Title displayed at the top of the HTML report.
    """

    # --- Missing values ---
    missing_threshold: float = 0.05

    # --- Duplicates ---
    duplicate_subset: list[str] | None = None

    # --- Outliers ---
    outlier_method: str = "iqr"
    outlier_iqr_factor: float = 1.5
    outlier_zscore_threshold: float = 3.0

    # --- Cardinality ---
    high_cardinality_threshold: float = 0.9
    low_cardinality_threshold: int = 10

    # --- String patterns ---
    string_patterns: dict[str, str] = field(default_factory=dict)

    # --- Dtype expectations ---
    expected_dtypes: dict[str, str] = field(default_factory=dict)

    # --- Range rules ---
    range_rules: dict[str, dict[str, float]] = field(default_factory=dict)

    # --- Date validation ---
    date_columns: list[str] = field(default_factory=list)
    date_format: str = "%Y-%m-%d"

    # --- Referential integrity ---
    reference_rules: list[dict[str, str]] = field(default_factory=list)

    # --- Scoring ---
    severity_weights: dict[str, float] = field(default_factory=lambda: {
        "missing_values": 0.20,
        "duplicates": 0.10,
        "dtype_validation": 0.10,
        "outliers": 0.10,
        "cardinality": 0.05,
        "string_patterns": 0.10,
        "referential_integrity": 0.15,
        "statistical_distribution": 0.05,
        "date_validation": 0.10,
        "range_validation": 0.05,
    })

    # --- Check selection ---
    enabled_checks: set[str] | None = None

    # --- Reporting ---
    report_title: str = "Data Quality Report"

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise config to a plain dict (JSON-safe)."""
        d = asdict(self)
        if d.get("enabled_checks") is not None:
            d["enabled_checks"] = sorted(d["enabled_checks"])
        return d

    def save(self, path: str | Path) -> None:
        """Write config as JSON."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "QualityConfig":
        """Load config from a JSON file."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if "enabled_checks" in raw and raw["enabled_checks"] is not None:
            raw["enabled_checks"] = set(raw["enabled_checks"])
        return cls(**raw)
