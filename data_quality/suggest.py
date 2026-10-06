"""
Starter rules inferred from a dataset.

``suggest_config(df)`` proposes rules a reviewer would likely want: ID-like
columns that should be unique and non-null, date columns, e-mail formats, and
non-negative bounds on quantity/amount columns.  The suggestions are a
starting point to edit, not a verdict — every rule is derived from column
names and the values actually present.
"""

from __future__ import annotations

import re
import warnings

import pandas as pd

from data_quality.config import QualityConfig

EMAIL_PATTERN = r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"

_ID_NAME = re.compile(r"(^id$|_id$|^id_|Id$|ID$|^uuid$|_key$|^sku$)")
_DATE_NAME = re.compile(r"(date|time|_at$|_on$|^dob$|timestamp)", re.I)
_EMAIL_NAME = re.compile(r"e-?mail", re.I)
_NON_NEGATIVE_NAME = re.compile(
    r"(price|amount|qty|quantity|count|total|cost|revenue|sales|age|weight|stock|units?$)", re.I
)


def _parse_rate(series: pd.Series) -> float:
    sample = series.dropna().astype(str).head(500)
    if sample.empty or sample.str.fullmatch(r"-?\d+(\.\d+)?").all():
        return 0.0  # plain numbers are not dates
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, format="mixed", errors="coerce")
    return float(parsed.notna().mean())


def suggest_config(df: pd.DataFrame) -> QualityConfig:
    """Return a :class:`QualityConfig` with rules inferred from ``df``."""
    unique: list[str] = []
    not_null: list[str] = []
    dates: list[str] = []
    patterns: dict[str, str] = {}
    ranges: dict[str, dict[str, float]] = {}

    for col in df.columns:
        name = str(col)
        s = df[col]
        non_null = s.dropna()
        if non_null.empty:
            continue

        if _ID_NAME.search(name) and non_null.nunique() >= 0.95 * len(non_null):
            unique.append(name)
            not_null.append(name)
            continue

        is_numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        if pd.api.types.is_datetime64_any_dtype(s):
            dates.append(name)
        elif not is_numeric and (_DATE_NAME.search(name) or _parse_rate(s) >= 0.9):
            if _parse_rate(s) >= 0.6:
                dates.append(name)
        if _EMAIL_NAME.search(name) and not is_numeric:
            patterns[name] = EMAIL_PATTERN
        if is_numeric and _NON_NEGATIVE_NAME.search(name):
            ranges[name] = {"min": 0}

    return QualityConfig(
        unique_columns=unique,
        not_null_columns=not_null,
        date_columns=dates,
        date_format=None,
        string_patterns=patterns,
        range_rules=ranges,
    )
