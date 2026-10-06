"""
Individual data-quality check functions.

Every check takes ``(df, config)`` and returns a :class:`CheckResult`.
Scores run from 0.0 (worst) to 1.0 (perfect) and are proportional to how
much of the data is affected, so one bad value in a million-row column costs
almost nothing while a column that is half wrong costs a lot.

A check with nothing to evaluate (no rules configured, no numeric columns)
returns ``skipped=True``; the engine leaves skipped checks out of the
composite score instead of counting them as perfect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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
    skipped: bool = False


# ── Helpers ───────────────────────────────────────────────────────────

# Score penalty per unit of affected data: 1% bad values costs 5 points and
# 20% bad values drives a check to zero.
_PENALTY = 5

def _result(name: str, score: float, passed: bool, summary: str,
            details: dict[str, Any], recs: list[str]) -> CheckResult:
    score = float(min(max(score, 0.0), 1.0))
    return CheckResult(
        name=name,
        passed=passed,
        severity="info" if passed else ("warning" if score >= 0.70 else "critical"),
        score=round(score, 4),
        summary=summary,
        details=details,
        recommendations=recs,
    )


def _skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, passed=True, severity="info", score=1.0,
                       summary=f"Skipped — {reason}", skipped=True)


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    """Numeric columns, excluding booleans (True/False are not measurements)."""
    return [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
    ]


def _is_text(series: pd.Series) -> bool:
    return (
        pd.api.types.is_object_dtype(series)
        or pd.api.types.is_string_dtype(series)
        or isinstance(series.dtype, pd.CategoricalDtype)
    )


def _py(value: Any) -> Any:
    """Convert a numpy/pandas scalar into a plain Python value."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


# ── 1. Missing values ─────────────────────────────────────────────────

def check_missing_values(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Missing-value counts per column, required columns, and empty columns."""
    if df.empty:
        return _skipped("missing_values", "dataset has no rows.")

    n = len(df)
    missing = df.isna().sum()
    pct = missing / n
    total_missing = int(missing.sum())
    overall_pct = total_missing / df.size

    flagged = pct[pct > config.missing_threshold]
    required_violations = {
        c: int(missing[c]) for c in config.not_null_columns if c in df.columns and missing[c] > 0
    }
    absent_required = [c for c in config.not_null_columns if c not in df.columns]
    empty_cols = [str(c) for c in missing[missing == n].index]

    # Overall missingness drives the score; required-column gaps are penalised
    # on top because they usually break downstream joins or keys.
    penalty = overall_pct * _PENALTY
    if config.not_null_columns:
        bad = sum(required_violations.values()) / (n * len(config.not_null_columns))
        penalty += bad * _PENALTY + len(absent_required) / len(config.not_null_columns)
    score = 1.0 - penalty

    recs: list[str] = []
    for col in flagged.sort_values(ascending=False).index[:5]:
        recs.append(f"'{col}' is {pct[col]:.1%} missing — fill from source, impute, or drop the column.")
    for col, count in required_violations.items():
        recs.append(f"'{col}' is required but has {count:,} missing values.")
    if absent_required:
        recs.append(f"Required column(s) not found: {absent_required}.")
    if empty_cols:
        recs.append(f"Columns entirely empty: {empty_cols} — consider dropping them.")

    return _result(
        "missing_values",
        score,
        passed=flagged.empty and not required_violations and not absent_required,
        summary=f"{total_missing:,} missing values ({overall_pct:.2%} of cells); "
                f"{len(flagged)} column(s) above the {config.missing_threshold:.0%} threshold.",
        details={
            "total_missing": total_missing,
            "overall_pct": round(overall_pct, 4),
            "by_column": {str(k): round(float(v), 4) for k, v in pct[pct > 0].items()},
            "flagged_columns": {str(k): round(float(v), 4) for k, v in flagged.items()},
            "required_violations": required_violations,
            "required_missing_columns": absent_required,
            "empty_columns": empty_cols,
        },
        recs=recs,
    )


# ── 2. Duplicates and uniqueness ──────────────────────────────────────

def check_duplicates(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Full-row duplicates, subset duplicates, and unique-key violations."""
    if df.empty:
        return _skipped("duplicates", "dataset has no rows.")

    n = len(df)
    full = int(df.duplicated().sum())

    subset = [c for c in (config.duplicate_subset or []) if c in df.columns]
    partial = int(df.duplicated(subset=subset).sum()) if subset else 0

    key_violations: dict[str, dict[str, Any]] = {}
    for col in config.unique_columns:
        if col not in df.columns:
            key_violations[col] = {"error": "column not found"}
            continue
        values = df[col].dropna()
        dupes = values[values.duplicated(keep=False)]
        if not dupes.empty:
            key_violations[col] = {
                "duplicate_rows": int(values.duplicated().sum()),
                "sample_values": [_py(v) for v in dupes.drop_duplicates().head(5)],
            }

    key_bad = sum(v.get("duplicate_rows", n) for v in key_violations.values())
    key_pct = key_bad / (n * len(config.unique_columns)) if config.unique_columns else 0.0
    score = 1.0 - (full / n + partial / n + key_pct) * _PENALTY

    recs: list[str] = []
    if full:
        recs.append(f"Remove {full:,} exact duplicate rows (e.g. df.drop_duplicates()).")
    if partial:
        recs.append(f"{partial:,} rows repeat on {subset} — confirm the business rule for deduplication.")
    for col, info in key_violations.items():
        if "error" in info:
            recs.append(f"Unique column '{col}' was not found in the data.")
        else:
            recs.append(f"'{col}' should be unique but {info['duplicate_rows']:,} rows reuse an existing value.")

    return _result(
        "duplicates",
        score,
        passed=not (full or partial or key_violations),
        summary=f"{full:,} exact duplicate rows ({full / n:.2%}); {partial:,} subset duplicates; "
                f"{len(key_violations)} unique-key violation(s).",
        details={
            "full_duplicates": full,
            "full_pct": round(full / n, 4),
            "partial_duplicates": partial,
            "subset_columns": subset or None,
            "unique_key_violations": key_violations,
        },
        recs=recs,
    )


# ── 3. Data types ─────────────────────────────────────────────────────

_DTYPE_FAMILIES: dict[str, Callable[[pd.Series], bool]] = {
    "numeric": lambda s: pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s),
    "integer": pd.api.types.is_integer_dtype,
    "float": pd.api.types.is_float_dtype,
    "string": _is_text,
    "datetime": pd.api.types.is_datetime64_any_dtype,
    "bool": pd.api.types.is_bool_dtype,
}


def check_dtype_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Verify that columns have the expected dtypes."""
    if not config.expected_dtypes:
        return _skipped("dtype_validation", "no expected_dtypes configured.")

    mismatches: dict[str, dict[str, str]] = {}
    for col, expected in config.expected_dtypes.items():
        if col not in df.columns:
            mismatches[col] = {"expected": expected, "actual": "column not found"}
            continue
        family = _DTYPE_FAMILIES.get(expected.lower())
        ok = family(df[col]) if family else str(df[col].dtype) == expected
        if not ok:
            mismatches[col] = {"expected": expected, "actual": str(df[col].dtype)}

    score = 1.0 - len(mismatches) / len(config.expected_dtypes)
    return _result(
        "dtype_validation",
        score,
        passed=not mismatches,
        summary=f"{len(mismatches)} of {len(config.expected_dtypes)} column type rule(s) failed.",
        details={"mismatches": mismatches},
        recs=[f"'{c}' is {i['actual']}, expected {i['expected']}." for c, i in mismatches.items()],
    )


# ── 4. Outliers ───────────────────────────────────────────────────────

def check_outliers(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Flag outliers in numeric columns using the IQR or z-score method."""
    numeric = _numeric_columns(df)
    if not numeric or df.empty:
        return _skipped("outliers", "no numeric columns.")

    by_col: dict[str, dict[str, Any]] = {}
    total = 0
    values_checked = 0
    for col in numeric:
        s = df[col].dropna().astype(float)
        values_checked += len(s)
        if len(s) < 4:
            continue
        if config.outlier_method == "zscore":
            std = s.std()
            if not std:
                continue
            mask = ((s - s.mean()) / std).abs() > config.outlier_zscore_threshold
            lower = s.mean() - config.outlier_zscore_threshold * std
            upper = s.mean() + config.outlier_zscore_threshold * std
        else:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if not iqr:
                continue
            lower = q1 - config.outlier_iqr_factor * iqr
            upper = q3 + config.outlier_iqr_factor * iqr
            mask = (s < lower) | (s > upper)
        count = int(mask.sum())
        if count:
            by_col[str(col)] = {
                "count": count,
                "pct": round(count / len(s), 4),
                "lower_fence": round(float(lower), 4),
                "upper_fence": round(float(upper), 4),
                "min": float(s.min()),
                "max": float(s.max()),
                "sample_values": [float(v) for v in s[mask].head(5)],
            }
            total += count

    pct = total / values_checked if values_checked else 0.0
    recs = [
        f"'{c}' has {i['count']:,} values outside [{i['lower_fence']:g}, {i['upper_fence']:g}] "
        f"({i['pct']:.1%}) — confirm they are real before capping or excluding."
        for c, i in sorted(by_col.items(), key=lambda kv: -kv[1]["pct"])[:5]
    ]
    return _result(
        "outliers",
        1.0 - pct * 10,
        passed=pct <= 0.01,
        summary=f"{total:,} outlying values ({pct:.2%}) across {len(by_col)} numeric column(s) "
                f"[{config.outlier_method}].",
        details={"by_column": by_col, "method": config.outlier_method},
        recs=recs,
    )


# ── 5. Cardinality ────────────────────────────────────────────────────

def check_cardinality(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Flag constant columns, near-unique text columns, and low-cardinality numerics."""
    if df.empty:
        return _skipped("cardinality", "dataset has no rows.")

    n = len(df)
    issues: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        s = df[col]
        nunique = int(s.nunique(dropna=True))
        key = str(col)
        if nunique == 1 and n > 1:
            issues[key] = {"type": "constant", "nunique": 1, "value": _py(s.dropna().iloc[0])}
        elif _is_text(s) and col not in config.unique_columns and n >= 20:
            ratio = nunique / n
            if ratio > config.high_cardinality_threshold:
                issues[key] = {"type": "high_cardinality_text", "nunique": nunique, "ratio": round(ratio, 4)}
        elif col in _numeric_columns(df) and 1 < nunique <= config.low_cardinality_threshold and n >= 50:
            issues[key] = {
                "type": "low_cardinality_numeric",
                "nunique": nunique,
                "values": sorted(_py(v) for v in s.dropna().unique()),
            }

    recs: list[str] = []
    for col, info in issues.items():
        if info["type"] == "constant":
            recs.append(f"'{col}' holds a single value everywhere — it carries no information.")
        elif info["type"] == "high_cardinality_text":
            recs.append(f"'{col}' is almost unique ({info['nunique']:,} values) — if it is an ID, "
                        "add it to unique_columns; if it is a category, standardise spelling.")
        else:
            recs.append(f"'{col}' has only {info['nunique']} distinct numbers — it may be a coded category.")

    # Cardinality findings are advisory, so they weigh lightly.
    return _result(
        "cardinality",
        1.0 - len(issues) / len(df.columns) * 0.5,
        passed=not any(i["type"] == "constant" for i in issues.values()),
        summary=f"{len(issues)} column(s) with unusual cardinality.",
        details={"issues": issues},
        recs=recs,
    )


# ── 6. String patterns ────────────────────────────────────────────────

def check_string_patterns(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Validate columns against ``{column: regex}`` rules (full match)."""
    if not config.string_patterns:
        return _skipped("string_patterns", "no string_patterns configured.")

    violations: dict[str, dict[str, Any]] = {}
    fractions: list[float] = []
    for col, pattern in config.string_patterns.items():
        if col not in df.columns:
            violations[col] = {"pattern": pattern, "error": "column not found"}
            fractions.append(1.0)
            continue
        s = df[col].dropna().astype(str)
        if s.empty:
            fractions.append(0.0)
            continue
        bad = ~s.str.fullmatch(pattern).fillna(False).astype(bool)
        count = int(bad.sum())
        fractions.append(count / len(s))
        if count:
            violations[col] = {
                "pattern": pattern,
                "violations": count,
                "pct": round(count / len(s), 4),
                "samples": s[bad].drop_duplicates().head(5).tolist(),
            }

    recs = [
        f"'{c}': column not found." if "error" in i else
        f"'{c}': {i['violations']:,} value(s) ({i['pct']:.1%}) don't match the expected format, e.g. {i['samples'][:3]}."
        for c, i in violations.items()
    ]
    return _result(
        "string_patterns",
        1.0 - sum(fractions) / len(fractions) * _PENALTY,
        passed=not violations,
        summary=f"{len(violations)} of {len(config.string_patterns)} format rule(s) have violations.",
        details={"violations": violations},
        recs=recs,
    )


# ── 7. Referential integrity ──────────────────────────────────────────

def check_referential_integrity(
    df: pd.DataFrame,
    config: QualityConfig,
    reference_dfs: dict[str, pd.DataFrame] | None = None,
) -> CheckResult:
    """Check that foreign-key values exist in parent tables."""
    if not config.reference_rules:
        return _skipped("referential_integrity", "no reference_rules configured.")
    reference_dfs = reference_dfs or {}

    violations: dict[str, dict[str, Any]] = {}
    fractions: list[float] = []
    for rule in config.reference_rules:
        child, parent_name, parent_col = rule["child_col"], rule["parent_df"], rule["parent_col"]
        if child not in df.columns:
            violations[child] = {"error": "child column not found"}
            fractions.append(1.0)
            continue
        parent = reference_dfs.get(parent_name)
        if parent is None:
            violations[child] = {"error": f"reference table '{parent_name}' was not provided"}
            fractions.append(1.0)
            continue
        if parent_col not in parent.columns:
            violations[child] = {"error": f"column '{parent_col}' not found in '{parent_name}'"}
            fractions.append(1.0)
            continue

        values = df[child].dropna()
        orphan_mask = ~values.isin(set(parent[parent_col].dropna()))
        orphan_rows = int(orphan_mask.sum())
        fractions.append(orphan_rows / len(values) if len(values) else 0.0)
        if orphan_rows:
            orphans = values[orphan_mask].drop_duplicates()
            violations[child] = {
                "orphan_rows": orphan_rows,
                "orphan_values": int(len(orphans)),
                "sample_orphans": [_py(v) for v in orphans.head(10)],
                "parent_table": parent_name,
                "parent_col": parent_col,
            }

    recs = [
        f"'{c}': {i['error']}." if "error" in i else
        f"'{c}': {i['orphan_rows']:,} row(s) reference values missing from "
        f"{i['parent_table']}.{i['parent_col']}, e.g. {i['sample_orphans'][:3]}."
        for c, i in violations.items()
    ]
    return _result(
        "referential_integrity",
        1.0 - sum(fractions) / len(fractions) * _PENALTY,
        passed=not violations,
        summary=f"{len(violations)} of {len(config.reference_rules)} reference rule(s) failed.",
        details={"violations": violations},
        recs=recs,
    )


# ── 8. Distribution ───────────────────────────────────────────────────

def check_statistical_distribution(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Profile numeric distributions — skewness and heavy tails."""
    numeric = [c for c in _numeric_columns(df) if df[c].notna().sum() >= 10]
    if not numeric:
        return _skipped("statistical_distribution", "no numeric columns with 10+ values.")

    profiles: dict[str, dict[str, Any]] = {}
    flags: list[str] = []
    for col in numeric:
        s = df[col].dropna().astype(float)
        skew, kurt = float(s.skew()), float(s.kurtosis())
        profiles[str(col)] = {
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "std": round(float(s.std()), 4),
            "skewness": round(skew, 4) if np.isfinite(skew) else None,
            "kurtosis": round(kurt, 4) if np.isfinite(kurt) else None,
            "min": float(s.min()),
            "max": float(s.max()),
        }
        if np.isfinite(skew) and abs(skew) > 2:
            flags.append(f"'{col}' is highly skewed ({skew:.2f}) — averages will mislead; report the median.")
        if np.isfinite(kurt) and abs(kurt) > 7:
            flags.append(f"'{col}' has heavy tails (kurtosis {kurt:.1f}) — check the extreme values.")

    # Skew is often a genuine property of the data, so this is advisory.
    return _result(
        "statistical_distribution",
        1.0 - len(flags) / len(numeric) * 0.25,
        passed=True,
        summary=f"Profiled {len(profiles)} numeric column(s); {len(flags)} distribution note(s).",
        details={"profiles": profiles},
        recs=flags,
    )


# ── 9. Dates ──────────────────────────────────────────────────────────

def check_date_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Validate date columns: parsability, future dates, and implausibly old dates."""
    if not config.date_columns:
        return _skipped("date_validation", "no date_columns configured.")

    today = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    floor = pd.Timestamp(config.min_date)
    issues: dict[str, dict[str, Any]] = {}
    fractions: list[float] = []
    for col in config.date_columns:
        if col not in df.columns:
            issues[col] = {"error": "column not found"}
            fractions.append(1.0)
            continue
        raw = df[col].dropna()
        if raw.empty:
            fractions.append(0.0)
            continue
        if pd.api.types.is_datetime64_any_dtype(raw):
            parsed = raw
        elif config.date_format:
            parsed = pd.to_datetime(raw.astype(str), format=config.date_format, errors="coerce")
        else:
            parsed = pd.to_datetime(raw.astype(str), format="mixed", errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_localize(None)

        unparseable = parsed.isna()
        future = (parsed >= today) if not config.allow_future_dates else pd.Series(False, index=parsed.index)
        too_old = parsed < floor
        bad = int((unparseable | future | too_old).sum())
        fractions.append(bad / len(raw))

        col_issues: dict[str, Any] = {}
        if unparseable.any():
            col_issues["unparseable"] = int(unparseable.sum())
            col_issues["unparseable_samples"] = [str(v) for v in raw[unparseable].drop_duplicates().head(5)]
        if future.any():
            col_issues["future_dates"] = int(future.sum())
        if too_old.any():
            col_issues["before_min_date"] = int(too_old.sum())
        if col_issues:
            valid = parsed.dropna()
            if not valid.empty:
                col_issues["range"] = [valid.min().date().isoformat(), valid.max().date().isoformat()]
            issues[col] = col_issues

    recs: list[str] = []
    for col, info in issues.items():
        if "error" in info:
            recs.append(f"Date column '{col}' was not found.")
            continue
        parts = []
        if "unparseable" in info:
            fmt = config.date_format or "any recognised format"
            parts.append(f"{info['unparseable']:,} not in {fmt} (e.g. {info['unparseable_samples'][:2]})")
        if "future_dates" in info:
            parts.append(f"{info['future_dates']:,} in the future")
        if "before_min_date" in info:
            parts.append(f"{info['before_min_date']:,} before {config.min_date}")
        recs.append(f"'{col}': {'; '.join(parts)}.")

    return _result(
        "date_validation",
        1.0 - sum(fractions) / len(fractions) * _PENALTY,
        passed=not issues,
        summary=f"{len(issues)} of {len(config.date_columns)} date column(s) have problems.",
        details={"issues": issues},
        recs=recs,
    )


# ── 10. Ranges ────────────────────────────────────────────────────────

def check_range_validation(df: pd.DataFrame, config: QualityConfig) -> CheckResult:
    """Check numeric columns fall within configured min/max bounds."""
    if not config.range_rules:
        return _skipped("range_validation", "no range_rules configured.")

    violations: dict[str, dict[str, Any]] = {}
    fractions: list[float] = []
    for col, bounds in config.range_rules.items():
        if col not in df.columns:
            violations[col] = {"error": "column not found"}
            fractions.append(1.0)
            continue
        raw = df[col].dropna()
        if raw.empty:
            fractions.append(0.0)
            continue
        s = pd.to_numeric(raw, errors="coerce")
        non_numeric = int(s.isna().sum())
        below = int((s < bounds["min"]).sum()) if "min" in bounds else 0
        above = int((s > bounds["max"]).sum()) if "max" in bounds else 0
        fractions.append((below + above + non_numeric) / len(raw))
        if below or above or non_numeric:
            violations[col] = {
                "below_min": below,
                "above_max": above,
                "non_numeric": non_numeric,
                "bounds": bounds,
                "actual_min": _py(s.min()) if s.notna().any() else None,
                "actual_max": _py(s.max()) if s.notna().any() else None,
            }

    recs: list[str] = []
    for col, i in violations.items():
        if "error" in i:
            recs.append(f"Range column '{col}' was not found.")
            continue
        parts = []
        if i["below_min"]:
            parts.append(f"{i['below_min']:,} below {i['bounds']['min']}")
        if i["above_max"]:
            parts.append(f"{i['above_max']:,} above {i['bounds']['max']}")
        if i["non_numeric"]:
            parts.append(f"{i['non_numeric']:,} not numeric")
        recs.append(f"'{col}': {', '.join(parts)} (observed {i['actual_min']} – {i['actual_max']}).")

    return _result(
        "range_validation",
        1.0 - sum(fractions) / len(fractions) * _PENALTY,
        passed=not violations,
        summary=f"{len(violations)} of {len(config.range_rules)} range rule(s) have violations.",
        details={"violations": violations},
        recs=recs,
    )


# ── Registry ──────────────────────────────────────────────────────────

ALL_CHECKS: dict[str, Callable[..., CheckResult]] = {
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
