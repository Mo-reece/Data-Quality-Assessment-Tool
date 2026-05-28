"""
Individual data-quality check functions.

Every public function in this module follows the same contract:

    Parameters
    ----------
    df : pd.DataFrame
        The dataset to check.
    config : QualityConfig
        Runtime configuration.

    Returns
    -------
    CheckResult
        A dataclass containing the check name, pass/fail status,
        severity level, detailed findings, and fix recommendations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from data_quality.config import QualityConfig


# ── Result container ──────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Standardised result returned by every check function."""

    name: str
    passed: bool
    severity: str  # "info" | "warning" | "critical"
    score: float  # 0.0 (worst) – 1.0 (perfect)
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────

def _severity(score: float) -> str:
    if score >= 0.95:
        return "info"
    if score >= 0.70:
        return "warning"
    return "critical"


# ── 1. Missing-value analysis ────────────────────────────────────────

def check_missing_values(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Analyse missing values: counts, percentages, and column-level patterns."""
    total_cells = df.shape[0] * df.shape[1]
    missing_per_col = df.isnull().sum()
    missing_pct_per_col = (missing_per_col / len(df)).round(4)
    total_missing = int(missing_per_col.sum())
    overall_pct = total_missing / total_cells if total_cells else 0.0

    flagged_cols = missing_pct_per_col[missing_pct_per_col > config.missing_threshold]
    score = 1.0 - min(overall_pct * 5, 1.0)  # scale: 20% missing -> score 0

    recs: list[str] = []
    if not flagged_cols.empty:
        worst = flagged_cols.idxmax()
        recs.append(
            f"Column '{worst}' has {flagged_cols[worst]:.1%} missing — "
            "consider imputation or removal."
        )
    if overall_pct > 0.10:
        recs.append("Overall missingness exceeds 10 %; review data pipeline.")

    # Detect columns that are completely empty
    empty_cols = list(missing_per_col[missing_per_col == len(df)].index)
    if empty_cols:
        recs.append(f"Columns entirely empty: {empty_cols}. Consider dropping them.")

    return CheckResult(
        name="missing_values",
        passed=flagged_cols.empty,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{total_missing:,} missing values ({overall_pct:.2%}) across {len(flagged_cols)} flagged columns.",
        details={
            "total_missing": total_missing,
            "overall_pct": round(overall_pct, 4),
            "by_column": missing_pct_per_col[missing_pct_per_col > 0].to_dict(),
            "flagged_columns": flagged_cols.to_dict(),
            "empty_columns": empty_cols,
        },
        recommendations=recs,
    )


# ── 2. Duplicate detection ──────────────────────────────────────────

def check_duplicates(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Detect full-row and partial (subset) duplicates."""
    full_dupes = int(df.duplicated().sum())
    full_pct = full_dupes / len(df) if len(df) else 0.0

    partial_dupes = 0
    partial_pct = 0.0
    subset = config.duplicate_subset
    if subset and all(c in df.columns for c in subset):
        partial_dupes = int(df.duplicated(subset=subset).sum())
        partial_pct = partial_dupes / len(df) if len(df) else 0.0

    score = 1.0 - min((full_pct + partial_pct) * 2, 1.0)
    passed = full_dupes == 0 and partial_dupes == 0

    recs: list[str] = []
    if full_dupes:
        recs.append(f"Drop {full_dupes} exact duplicate rows with df.drop_duplicates().")
    if partial_dupes:
        recs.append(
            f"{partial_dupes} partial duplicates on {subset} — "
            "review business rules for deduplication."
        )

    return CheckResult(
        name="duplicates",
        passed=passed,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{full_dupes} full duplicates ({full_pct:.2%}), "
                f"{partial_dupes} partial duplicates ({partial_pct:.2%}).",
        details={
            "full_duplicates": full_dupes,
            "full_pct": round(full_pct, 4),
            "partial_duplicates": partial_dupes,
            "partial_pct": round(partial_pct, 4),
            "subset_columns": subset,
        },
        recommendations=recs,
    )


# ── 3. Data-type validation ─────────────────────────────────────────

def check_dtype_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Verify that columns have the expected dtypes."""
    if not config.expected_dtypes:
        return CheckResult(
            name="dtype_validation",
            passed=True,
            severity="info",
            score=1.0,
            summary="No dtype expectations configured — skipped.",
        )

    mismatches: dict[str, dict[str, str]] = {}
    for col, expected in config.expected_dtypes.items():
        if col not in df.columns:
            mismatches[col] = {"expected": expected, "actual": "COLUMN_MISSING"}
        elif str(df[col].dtype) != expected:
            mismatches[col] = {"expected": expected, "actual": str(df[col].dtype)}

    score = 1.0 - len(mismatches) / max(len(config.expected_dtypes), 1)
    recs = [
        f"Cast '{col}' from {info['actual']} to {info['expected']}."
        for col, info in mismatches.items()
    ]

    return CheckResult(
        name="dtype_validation",
        passed=len(mismatches) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(mismatches)} dtype mismatches out of {len(config.expected_dtypes)} rules.",
        details={"mismatches": mismatches},
        recommendations=recs,
    )


# ── 4. Outlier detection ────────────────────────────────────────────

def check_outliers(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Flag outliers in numeric columns using IQR or Z-score method."""
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    col_outliers: dict[str, dict[str, Any]] = {}
    total_outliers = 0

    for col in numeric_cols:
        series = df[col].dropna()
        if series.empty:
            continue

        if config.outlier_method == "zscore":
            mean, std = series.mean(), series.std()
            if std == 0:
                continue
            z = ((series - mean) / std).abs()
            mask = z > config.outlier_zscore_threshold
        else:  # iqr
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lower = q1 - config.outlier_iqr_factor * iqr
            upper = q3 + config.outlier_iqr_factor * iqr
            mask = (series < lower) | (series > upper)

        n_outliers = int(mask.sum())
        if n_outliers:
            col_outliers[col] = {
                "count": n_outliers,
                "pct": round(n_outliers / len(series), 4),
                "min": float(series.min()),
                "max": float(series.max()),
                "mean": round(float(series.mean()), 4),
            }
            total_outliers += n_outliers

    total_numeric_values = sum(df[c].notna().sum() for c in numeric_cols)
    outlier_pct = total_outliers / total_numeric_values if total_numeric_values else 0.0
    score = 1.0 - min(outlier_pct * 10, 1.0)

    recs: list[str] = []
    for col, info in col_outliers.items():
        if info["pct"] > 0.05:
            recs.append(
                f"'{col}' has {info['pct']:.1%} outliers — "
                "investigate or apply winsorisation / capping."
            )

    return CheckResult(
        name="outliers",
        passed=total_outliers == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{total_outliers} outliers ({outlier_pct:.2%}) across {len(col_outliers)} columns "
                f"[method={config.outlier_method}].",
        details={"by_column": col_outliers, "method": config.outlier_method},
        recommendations=recs,
    )


# ── 5. Cardinality analysis ─────────────────────────────────────────

def check_cardinality(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Flag high-cardinality categoricals and low-cardinality numerics."""
    issues: dict[str, dict[str, Any]] = {}

    for col in df.columns:
        nunique = df[col].nunique()
        ratio = nunique / len(df) if len(df) else 0.0

        if df[col].dtype == "object" or pd.api.types.is_categorical_dtype(df[col]):
            if ratio > config.high_cardinality_threshold:
                issues[col] = {
                    "type": "high_cardinality_categorical",
                    "nunique": nunique,
                    "ratio": round(ratio, 4),
                }
        elif pd.api.types.is_numeric_dtype(df[col]):
            if nunique <= config.low_cardinality_threshold and nunique > 0:
                issues[col] = {
                    "type": "low_cardinality_numeric",
                    "nunique": nunique,
                    "values": sorted(df[col].dropna().unique().tolist()),
                }

    score = 1.0 - min(len(issues) / max(len(df.columns), 1), 1.0)
    recs: list[str] = []
    for col, info in issues.items():
        if info["type"] == "high_cardinality_categorical":
            recs.append(f"'{col}' has {info['nunique']} unique values — consider hashing or grouping.")
        else:
            recs.append(f"'{col}' has only {info['nunique']} unique values — consider encoding as categorical.")

    return CheckResult(
        name="cardinality",
        passed=len(issues) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(issues)} cardinality issues detected.",
        details={"issues": issues},
        recommendations=recs,
    )


# ── 6. String pattern validation ────────────────────────────────────

def check_string_patterns(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Validate string columns against expected regex patterns."""
    if not config.string_patterns:
        return CheckResult(
            name="string_patterns",
            passed=True,
            severity="info",
            score=1.0,
            summary="No string patterns configured — skipped.",
        )

    violations: dict[str, dict[str, Any]] = {}
    for col, pattern in config.string_patterns.items():
        if col not in df.columns:
            violations[col] = {"error": "COLUMN_MISSING", "pattern": pattern}
            continue
        series = df[col].dropna().astype(str)
        if series.empty:
            continue
        matches = series.str.fullmatch(pattern)
        n_violations = int((~matches).sum())
        if n_violations:
            samples = series[~matches].head(5).tolist()
            violations[col] = {
                "pattern": pattern,
                "violations": n_violations,
                "pct": round(n_violations / len(series), 4),
                "samples": samples,
            }

    checked = len(config.string_patterns)
    score = 1.0 - len(violations) / max(checked, 1)
    recs = [
        f"'{col}' has {info.get('violations', 'N/A')} values not matching "
        f"pattern '{info['pattern']}' — clean or standardise."
        for col, info in violations.items()
    ]

    return CheckResult(
        name="string_patterns",
        passed=len(violations) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(violations)} pattern violations across {checked} rules.",
        details={"violations": violations},
        recommendations=recs,
    )


# ── 7. Referential integrity ────────────────────────────────────────

def check_referential_integrity(
    df: pd.DataFrame,
    config: QualityConfig,
    reference_dfs: dict[str, pd.DataFrame] | None = None,
) -> CheckResult:
    """Check that foreign-key values exist in parent tables."""
    if not config.reference_rules or not reference_dfs:
        return CheckResult(
            name="referential_integrity",
            passed=True,
            severity="info",
            score=1.0,
            summary="No referential-integrity rules configured — skipped.",
        )

    violations: dict[str, dict[str, Any]] = {}
    for rule in config.reference_rules:
        child_col = rule["child_col"]
        parent_name = rule["parent_df"]
        parent_col = rule["parent_col"]

        if child_col not in df.columns:
            violations[child_col] = {"error": "CHILD_COLUMN_MISSING"}
            continue
        if parent_name not in reference_dfs:
            violations[child_col] = {"error": f"PARENT_DF '{parent_name}' NOT PROVIDED"}
            continue

        parent_df = reference_dfs[parent_name]
        if parent_col not in parent_df.columns:
            violations[child_col] = {"error": f"PARENT_COLUMN '{parent_col}' MISSING"}
            continue

        child_vals = set(df[child_col].dropna().unique())
        parent_vals = set(parent_df[parent_col].dropna().unique())
        orphans = child_vals - parent_vals

        if orphans:
            violations[child_col] = {
                "orphan_count": len(orphans),
                "sample_orphans": sorted(list(orphans))[:10],
                "parent_table": parent_name,
                "parent_col": parent_col,
            }

    total_rules = len(config.reference_rules)
    score = 1.0 - len(violations) / max(total_rules, 1)
    recs = [
        f"'{col}': {info.get('orphan_count', '?')} orphan values not in "
        f"'{info.get('parent_table', '?')}.{info.get('parent_col', '?')}' — "
        "fix source data or add missing parent records."
        for col, info in violations.items()
        if "orphan_count" in info
    ]

    return CheckResult(
        name="referential_integrity",
        passed=len(violations) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(violations)} referential-integrity violations across {total_rules} rules.",
        details={"violations": violations},
        recommendations=recs,
    )


# ── 8. Statistical distribution ─────────────────────────────────────

def check_statistical_distribution(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Profile numeric distributions — skewness, kurtosis, and uniformity."""
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    profiles: dict[str, dict[str, Any]] = {}
    flags: list[str] = []

    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        skew = float(series.skew())
        kurt = float(series.kurtosis())
        profiles[col] = {
            "mean": round(float(series.mean()), 4),
            "median": round(float(series.median()), 4),
            "std": round(float(series.std()), 4),
            "skewness": round(skew, 4),
            "kurtosis": round(kurt, 4),
            "min": float(series.min()),
            "max": float(series.max()),
        }
        if abs(skew) > 2:
            flags.append(f"'{col}' is highly skewed ({skew:.2f}) — consider log transform.")
        if abs(kurt) > 7:
            flags.append(f"'{col}' has heavy tails (kurtosis={kurt:.2f}) — check for outliers.")

    score = 1.0 - min(len(flags) / max(len(numeric_cols), 1) * 0.5, 1.0)

    return CheckResult(
        name="statistical_distribution",
        passed=len(flags) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"Profiled {len(profiles)} numeric columns; {len(flags)} distribution flags.",
        details={"profiles": profiles},
        recommendations=flags,
    )


# ── 9. Date / time validation ───────────────────────────────────────

def check_date_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Validate date columns: parsability, future dates, and reasonable ranges."""
    if not config.date_columns:
        return CheckResult(
            name="date_validation",
            passed=True,
            severity="info",
            score=1.0,
            summary="No date columns configured — skipped.",
        )

    issues: dict[str, dict[str, Any]] = {}
    for col in config.date_columns:
        if col not in df.columns:
            issues[col] = {"error": "COLUMN_MISSING"}
            continue

        parsed = pd.to_datetime(df[col], format=config.date_format, errors="coerce")
        n_unparseable = int(df[col].notna().sum() - parsed.notna().sum())
        n_future = int((parsed > pd.Timestamp.now()).sum())
        n_too_old = int((parsed < pd.Timestamp("1900-01-01")).sum())

        col_issues: dict[str, Any] = {}
        if n_unparseable:
            col_issues["unparseable"] = n_unparseable
        if n_future:
            col_issues["future_dates"] = n_future
        if n_too_old:
            col_issues["before_1900"] = n_too_old
        if col_issues:
            issues[col] = col_issues

    total = len(config.date_columns)
    score = 1.0 - len(issues) / max(total, 1)
    recs: list[str] = []
    for col, info in issues.items():
        parts = []
        if "unparseable" in info:
            parts.append(f"{info['unparseable']} unparseable")
        if "future_dates" in info:
            parts.append(f"{info['future_dates']} future dates")
        if "before_1900" in info:
            parts.append(f"{info['before_1900']} pre-1900 dates")
        recs.append(f"'{col}': {', '.join(parts)} — validate source data.")

    return CheckResult(
        name="date_validation",
        passed=len(issues) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(issues)} date columns with issues out of {total}.",
        details={"issues": issues},
        recommendations=recs,
    )


# ── 10. Range validation ────────────────────────────────────────────

def check_range_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Check numeric columns fall within configured min/max bounds."""
    if not config.range_rules:
        return CheckResult(
            name="range_validation",
            passed=True,
            severity="info",
            score=1.0,
            summary="No range rules configured — skipped.",
        )

    violations: dict[str, dict[str, Any]] = {}
    for col, bounds in config.range_rules.items():
        if col not in df.columns:
            violations[col] = {"error": "COLUMN_MISSING"}
            continue
        series = df[col].dropna()
        below = above = 0
        if "min" in bounds:
            below = int((series < bounds["min"]).sum())
        if "max" in bounds:
            above = int((series > bounds["max"]).sum())
        if below or above:
            violations[col] = {
                "below_min": below,
                "above_max": above,
                "bounds": bounds,
                "actual_min": float(series.min()),
                "actual_max": float(series.max()),
            }

    total = len(config.range_rules)
    score = 1.0 - len(violations) / max(total, 1)
    recs = [
        f"'{col}': {info.get('below_min', 0)} below min, {info.get('above_max', 0)} above max "
        f"(expected {info.get('bounds', {})}) — clip or investigate."
        for col, info in violations.items()
        if "below_min" in info
    ]

    return CheckResult(
        name="range_validation",
        passed=len(violations) == 0,
        severity=_severity(score),
        score=round(score, 4),
        summary=f"{len(violations)} range violations across {total} rules.",
        details={"violations": violations},
        recommendations=recs,
    )


# ── Registry ─────────────────────────────────────────────────────────
# Maps check names to their callable.  The engine iterates over this.

ALL_CHECKS: dict[str, Any] = {
    "missing_values": check_missing_values,
    "duplicates": check_duplicates,
    "dtype_validation": check_dtype_validation,
    "outliers": check_outliers,
    "cardinality": check_cardinality,
    "string_patterns": check_string_patterns,
    "referential_integrity": check_referential_integrity,
    "statistical_distribution": check_statistical_distribution,
    "date_validation": check_date_validation,
    "range_validation": check_range_validation,
}
