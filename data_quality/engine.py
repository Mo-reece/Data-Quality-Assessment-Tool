"""
Orchestration engine for the Data Quality Assessment Tool.

The engine loads a DataFrame, runs all enabled checks, computes a
composite quality score, and returns a structured assessment that
can be fed to the reporting module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from data_quality.checks import ALL_CHECKS, CheckResult
from data_quality.config import QualityConfig


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

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def critical_issues(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == "warning"]

    def summary_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "rows": self.shape[0],
            "columns": self.shape[1],
            "composite_score": self.composite_score,
            "checks_run": len(self.results),
            "checks_passed": sum(1 for r in self.results if r.passed),
            "critical": len(self.critical_issues),
            "warnings": len(self.warnings),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


class DataQualityEngine:
    """Run data-quality checks and return a :class:`QualityAssessment`.

    Parameters
    ----------
    config : QualityConfig, optional
        Configuration object.  Defaults to ``QualityConfig()`` (all defaults).

    Usage
    -----
    >>> engine = DataQualityEngine()
    >>> assessment = engine.run(df, name="sales_q1")
    >>> print(assessment.composite_score)
    """

    def __init__(self, config: QualityConfig | None = None) -> None:
        self.config = config or QualityConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        name: str = "dataset",
        reference_dfs: dict[str, pd.DataFrame] | None = None,
    ) -> QualityAssessment:
        """Execute all enabled quality checks and return the assessment."""
        t0 = time.perf_counter()

        results: list[CheckResult] = []
        for check_name, check_fn in ALL_CHECKS.items():
            if self.config.enabled_checks and check_name not in self.config.enabled_checks:
                continue
            if check_name == "referential_integrity":
                result = check_fn(df, self.config, reference_dfs)
            else:
                result = check_fn(df, self.config)
            results.append(result)

        composite = self._composite_score(results)
        elapsed = time.perf_counter() - t0
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)

        return QualityAssessment(
            dataset_name=name,
            shape=df.shape,
            columns=df.columns.tolist(),
            dtypes={col: str(df[col].dtype) for col in df.columns},
            results=results,
            composite_score=round(composite, 4),
            elapsed_seconds=round(elapsed, 4),
            memory_usage_mb=round(mem_mb, 2),
            config=self.config,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _composite_score(self, results: list[CheckResult]) -> float:
        """Weighted average of individual check scores."""
        weights = self.config.severity_weights
        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            w = weights.get(r.name, 0.05)
            weighted_sum += r.score * w
            total_weight += w
        return weighted_sum / total_weight if total_weight else 0.0
