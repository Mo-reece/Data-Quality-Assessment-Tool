"""
Orchestration engine for the Data Quality Assessment Tool.

The engine runs every enabled check over a DataFrame, profiles each column,
and combines the check scores into one weighted composite score.  Skipped
checks (nothing configured to evaluate) are reported but excluded from the
composite, so an unconfigured rule never inflates the result.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from data_quality import __version__
from data_quality.checks import ALL_CHECKS, CheckResult
from data_quality.config import QualityConfig


def to_jsonable(value: Any) -> Any:
    """Recursively convert numpy/pandas values into JSON-serialisable ones."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    return value


def profile_columns(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-column profile: type, completeness, distinct values, and range."""
    n = len(df)
    profile = []
    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        entry: dict[str, Any] = {
            "column": str(col),
            "dtype": str(s.dtype),
            "non_null": int(len(non_null)),
            "missing": int(n - len(non_null)),
            "missing_pct": round((n - len(non_null)) / n, 4) if n else 0.0,
            "unique": int(non_null.nunique()),
        }
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and len(non_null):
            entry.update(min=non_null.min(), max=non_null.max(), mean=round(float(non_null.mean()), 4))
        elif pd.api.types.is_datetime64_any_dtype(s) and len(non_null):
            entry.update(min=non_null.min(), max=non_null.max())
        if len(non_null):
            top = non_null.astype(str).value_counts().head(3)
            entry["top_values"] = [{"value": k[:80], "count": int(v)} for k, v in top.items()]
        profile.append(to_jsonable(entry))
    return profile


@dataclass
class QualityAssessment:
    """Aggregated output produced by the engine."""

    dataset_name: str
    shape: tuple[int, int]
    columns: list[str]
    dtypes: dict[str, str]
    results: list[CheckResult]
    composite_score: float
    elapsed_seconds: float
    memory_usage_mb: float
    config: QualityConfig
    column_profile: list[dict[str, Any]]
    generated_at: str

    @property
    def evaluated(self) -> list[CheckResult]:
        """Checks that actually ran (not skipped)."""
        return [r for r in self.results if not r.skipped]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.evaluated)

    @property
    def critical_issues(self) -> list[CheckResult]:
        return [r for r in self.evaluated if r.severity == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.evaluated if r.severity == "warning"]

    @property
    def grade(self) -> str:
        s = self.composite_score
        return "A" if s >= 0.95 else "B" if s >= 0.85 else "C" if s >= 0.70 else "D" if s >= 0.50 else "F"

    def summary_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "rows": int(self.shape[0]),
            "columns": int(self.shape[1]),
            "composite_score": self.composite_score,
            "grade": self.grade,
            "checks_run": len(self.evaluated),
            "checks_skipped": len(self.results) - len(self.evaluated),
            "checks_passed": sum(1 for r in self.evaluated if r.passed),
            "critical": len(self.critical_issues),
            "warnings": len(self.warnings),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full JSON-safe representation, suitable for logs or dashboards."""
        return to_jsonable({
            "tool_version": __version__,
            "generated_at": self.generated_at,
            "summary": self.summary_dict(),
            "results": [asdict(r) for r in self.results],
            "columns": self.column_profile,
            "memory_usage_mb": self.memory_usage_mb,
            "config": self.config.to_dict(),
        })

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class DataQualityEngine:
    """Run data-quality checks and return a :class:`QualityAssessment`.

    >>> assessment = DataQualityEngine(QualityConfig(unique_columns=["id"])).run(df, name="orders")
    >>> assessment.composite_score
    """

    def __init__(self, config: QualityConfig | None = None) -> None:
        self.config = config or QualityConfig()

    def run(
        self,
        df: pd.DataFrame,
        name: str = "dataset",
        reference_dfs: dict[str, pd.DataFrame] | None = None,
    ) -> QualityAssessment:
        """Execute all enabled checks and return the assessment."""
        t0 = time.perf_counter()
        enabled = self.config.enabled_checks

        results: list[CheckResult] = []
        for check_name, check_fn in ALL_CHECKS.items():
            if enabled is not None and check_name not in enabled:
                continue
            if check_name == "referential_integrity":
                results.append(check_fn(df, self.config, reference_dfs))
            else:
                results.append(check_fn(df, self.config))

        return QualityAssessment(
            dataset_name=name,
            shape=(int(df.shape[0]), int(df.shape[1])),
            columns=[str(c) for c in df.columns],
            dtypes={str(c): str(df[c].dtype) for c in df.columns},
            results=results,
            composite_score=round(self._composite_score(results), 4),
            elapsed_seconds=round(time.perf_counter() - t0, 4),
            memory_usage_mb=round(df.memory_usage(deep=True).sum() / (1024 * 1024), 2),
            config=self.config,
            column_profile=profile_columns(df),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def _composite_score(self, results: list[CheckResult]) -> float:
        """Weighted average of the scores of checks that actually ran."""
        weights = self.config.severity_weights
        total_weight = weighted_sum = 0.0
        for r in results:
            if r.skipped:
                continue
            w = weights.get(r.name, 0.05)
            weighted_sum += r.score * w
            total_weight += w
        return weighted_sum / total_weight if total_weight else 1.0


def assess(
    df: pd.DataFrame,
    config: QualityConfig | dict[str, Any] | None = None,
    name: str = "dataset",
    reference_dfs: dict[str, pd.DataFrame] | None = None,
) -> QualityAssessment:
    """One-call convenience wrapper: ``assess(df, {"unique_columns": ["id"]})``."""
    if isinstance(config, dict):
        config = QualityConfig.from_dict(config)
    return DataQualityEngine(config).run(df, name=name, reference_dfs=reference_dfs)
