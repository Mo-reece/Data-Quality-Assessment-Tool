"""
Configuration for the Data Quality Assessment Tool.

``QualityConfig`` is a plain dataclass that round-trips through JSON, so the
same rules file drives the CLI, the Python API, and the browser app.  Values
are validated on construction: a typo in a rules file fails loudly instead of
silently disabling a check.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

CHECK_NAMES: tuple[str, ...] = (
    "missing_values",
    "duplicates",
    "dtype_validation",
    "outliers",
    "cardinality",
    "string_patterns",
    "referential_integrity",
    "statistical_distribution",
    "date_validation",
    "range_validation",
)

DEFAULT_WEIGHTS: dict[str, float] = {
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
}


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


@dataclass
class QualityConfig:
    """Rules and thresholds for a quality assessment.

    Attributes:
        missing_threshold: Max acceptable missing fraction per column (0-1).
        not_null_columns: Columns that must contain no missing values at all.
        duplicate_subset: Column subset for partial-duplicate detection.
        unique_columns: Columns that must be unique (e.g. primary keys).
        outlier_method: ``"iqr"`` or ``"zscore"``.
        outlier_iqr_factor: IQR multiplier for the outlier fences.
        outlier_zscore_threshold: Absolute z-score cutoff.
        high_cardinality_threshold: Unique ratio above which a text column is
            flagged (columns listed in ``unique_columns`` are exempt).
        low_cardinality_threshold: Unique count at or below which a numeric
            column is flagged as possibly categorical.
        string_patterns: ``{column: regex}`` — every non-null value must fully
            match.
        expected_dtypes: ``{column: dtype}`` — compared against
            ``str(df[col].dtype)``.  ``"numeric"``, ``"string"``,
            ``"datetime"`` and ``"bool"`` match any dtype of that family.
        range_rules: ``{column: {"min": x, "max": y}}`` (either bound optional).
        date_columns: Columns expected to contain dates.
        date_format: strftime format for ``date_columns``; ``None`` infers it.
        allow_future_dates: When False, dates after today are flagged.
        min_date: Dates before this (ISO string) are flagged.
        reference_rules: ``[{"child_col", "parent_df", "parent_col"}]``.
        severity_weights: Weight of each check in the composite score.
        enabled_checks: Checks to run; ``None`` runs all.
        report_title: Title of the HTML report.
    """

    missing_threshold: float = 0.05
    not_null_columns: list[str] = field(default_factory=list)

    duplicate_subset: list[str] | None = None
    unique_columns: list[str] = field(default_factory=list)

    outlier_method: str = "iqr"
    outlier_iqr_factor: float = 1.5
    outlier_zscore_threshold: float = 3.0

    high_cardinality_threshold: float = 0.9
    low_cardinality_threshold: int = 10

    string_patterns: dict[str, str] = field(default_factory=dict)
    expected_dtypes: dict[str, str] = field(default_factory=dict)
    range_rules: dict[str, dict[str, float]] = field(default_factory=dict)

    date_columns: list[str] = field(default_factory=list)
    date_format: str | None = "%Y-%m-%d"
    allow_future_dates: bool = False
    min_date: str = "1900-01-01"

    reference_rules: list[dict[str, str]] = field(default_factory=list)

    severity_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    enabled_checks: set[str] | None = None
    report_title: str = "Data Quality Report"

    def __post_init__(self) -> None:
        if self.enabled_checks is not None:
            self.enabled_checks = set(self.enabled_checks)
        self.validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`ConfigError` describing the first invalid value."""
        if not 0 <= self.missing_threshold <= 1:
            raise ConfigError("missing_threshold must be between 0 and 1.")
        if self.outlier_method not in ("iqr", "zscore"):
            raise ConfigError("outlier_method must be 'iqr' or 'zscore'.")
        if self.outlier_iqr_factor <= 0 or self.outlier_zscore_threshold <= 0:
            raise ConfigError("Outlier thresholds must be positive.")
        if not 0 < self.high_cardinality_threshold <= 1:
            raise ConfigError("high_cardinality_threshold must be in (0, 1].")
        if self.enabled_checks is not None:
            unknown = self.enabled_checks - set(CHECK_NAMES)
            if unknown:
                raise ConfigError(
                    f"Unknown check(s) {sorted(unknown)}. Valid: {', '.join(CHECK_NAMES)}."
                )
        unknown_weights = set(self.severity_weights) - set(CHECK_NAMES)
        if unknown_weights:
            raise ConfigError(f"severity_weights has unknown check(s) {sorted(unknown_weights)}.")
        if any(w < 0 for w in self.severity_weights.values()):
            raise ConfigError("severity_weights must be non-negative.")
        for col, pattern in self.string_patterns.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"Invalid regex for column '{col}': {exc}") from None
        for col, bounds in self.range_rules.items():
            if not isinstance(bounds, dict) or not bounds or not set(bounds) <= {"min", "max"}:
                raise ConfigError(f"range_rules['{col}'] must be an object with 'min' and/or 'max'.")
            if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
                raise ConfigError(f"range_rules['{col}']: min is greater than max.")
        for rule in self.reference_rules:
            missing = {"child_col", "parent_df", "parent_col"} - set(rule)
            if missing:
                raise ConfigError(f"reference rule {rule} is missing {sorted(missing)}.")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        d = asdict(self)
        if d["enabled_checks"] is not None:
            d["enabled_checks"] = sorted(d["enabled_checks"])
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: str | Path) -> None:
        """Write the config as JSON."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualityConfig":
        """Build a config from a dict, rejecting unknown keys.

        Missing keys keep their defaults, so a rules file only needs to state
        what differs.  ``severity_weights`` entries are merged over the
        defaults rather than replacing them.
        """
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ConfigError(f"Unknown config key(s): {sorted(unknown)}.")
        raw = dict(raw)
        if "severity_weights" in raw:
            raw["severity_weights"] = {**DEFAULT_WEIGHTS, **(raw["severity_weights"] or {})}
        return cls(**raw)

    @classmethod
    def from_json(cls, text: str) -> "QualityConfig":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config is not valid JSON: {exc}") from None
        if not isinstance(raw, dict):
            raise ConfigError("Config must be a JSON object.")
        return cls.from_dict(raw)

    @classmethod
    def load(cls, path: str | Path) -> "QualityConfig":
        """Load a config from a JSON file."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
