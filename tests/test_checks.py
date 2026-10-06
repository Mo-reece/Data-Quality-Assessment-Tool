import json
import unittest

import numpy as np
import pandas as pd

from data_quality import ConfigError, QualityConfig, assess, suggest_config
from data_quality.checks import ALL_CHECKS
from data_quality.report import generate_html_report


def clean_df(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "id": np.arange(n),
        "email": [f"u{i}@example.com" for i in range(n)],
        "amount": rng.normal(100, 10, n).round(2),
        "created": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
    })


def result(assessment, name):
    return next(r for r in assessment.results if r.name == name)


class ScoringTest(unittest.TestCase):
    def test_clean_data_scores_high_and_passes(self):
        a = assess(clean_df(), {"unique_columns": ["id"], "date_columns": ["created"]})
        self.assertGreaterEqual(a.composite_score, 0.95)
        self.assertEqual(a.critical_issues, [])

    def test_skipped_checks_are_excluded_from_composite(self):
        df = clean_df()
        df.loc[:39, "amount"] = np.nan  # 20% of one column missing
        a = assess(df)
        skipped = [r for r in a.results if r.skipped]
        self.assertIn("string_patterns", [r.name for r in skipped])
        evaluated = a.evaluated
        weights = a.config.severity_weights
        expected = sum(r.score * weights[r.name] for r in evaluated) / sum(weights[r.name] for r in evaluated)
        self.assertAlmostEqual(a.composite_score, round(expected, 4), places=4)

    def test_score_is_proportional_to_bad_values(self):
        df = clean_df(1000)
        df.loc[0, "email"] = "broken"
        one_bad = result(assess(df, {"string_patterns": {"email": r".+@.+\..+"}}), "string_patterns")
        df.loc[:299, "email"] = "broken"
        many_bad = result(assess(df, {"string_patterns": {"email": r".+@.+\..+"}}), "string_patterns")
        self.assertFalse(one_bad.passed)
        self.assertGreater(one_bad.score, 0.99)
        self.assertEqual(many_bad.score, 0.0)
        self.assertEqual(many_bad.severity, "critical")

    def test_failed_check_is_never_labelled_info(self):
        df = clean_df(1000)
        df.loc[0, "email"] = "broken"
        r = result(assess(df, {"string_patterns": {"email": r".+@.+\..+"}}), "string_patterns")
        self.assertEqual(r.severity, "warning")


class CheckBehaviourTest(unittest.TestCase):
    def test_unique_and_not_null_columns(self):
        df = clean_df()
        df.loc[1, "id"] = 0
        df.loc[2, "id"] = np.nan
        a = assess(df, {"unique_columns": ["id"], "not_null_columns": ["id"]})
        dup = result(a, "duplicates")
        self.assertIn("id", dup.details["unique_key_violations"])
        self.assertEqual(result(a, "missing_values").details["required_violations"], {"id": 1})

    def test_range_rule_on_text_column_reports_non_numeric(self):
        df = pd.DataFrame({"qty": ["1", "2", "x", "-5"]})
        r = result(assess(df, {"range_rules": {"qty": {"min": 0}}}), "range_validation")
        self.assertEqual(r.details["violations"]["qty"]["non_numeric"], 1)
        self.assertEqual(r.details["violations"]["qty"]["below_min"], 1)

    def test_dates_inferred_when_format_is_none(self):
        df = pd.DataFrame({"d": ["2024-01-05", "05 Feb 2024", "garbage", "2999-01-01"]})
        r = result(assess(df, {"date_columns": ["d"], "date_format": None}), "date_validation")
        info = r.details["issues"]["d"]
        self.assertEqual(info["unparseable"], 1)
        self.assertEqual(info["future_dates"], 1)

    def test_referential_integrity_counts_orphan_rows(self):
        orders = pd.DataFrame({"cust": ["a", "b", "zz", "zz", None]})
        customers = pd.DataFrame({"id": ["a", "b"]})
        a = assess(orders, {"reference_rules": [{"child_col": "cust", "parent_df": "c", "parent_col": "id"}]},
                   reference_dfs={"c": customers})
        v = result(a, "referential_integrity").details["violations"]["cust"]
        self.assertEqual((v["orphan_rows"], v["orphan_values"]), (2, 1))

    def test_missing_reference_table_is_reported_not_skipped(self):
        a = assess(clean_df(), {"reference_rules": [{"child_col": "id", "parent_df": "x", "parent_col": "id"}]})
        r = result(a, "referential_integrity")
        self.assertFalse(r.skipped)
        self.assertFalse(r.passed)

    def test_constant_column_flagged(self):
        df = clean_df()
        df["country"] = "UG"
        r = result(assess(df), "cardinality")
        self.assertEqual(r.details["issues"]["country"]["type"], "constant")

    def test_boolean_columns_are_not_treated_as_numeric(self):
        df = pd.DataFrame({"flag": [True, False] * 50, "x": range(100)})
        r = result(assess(df), "outliers")
        self.assertNotIn("flag", r.details.get("by_column", {}))

    def test_dtype_families(self):
        df = clean_df()
        a = assess(df, {"expected_dtypes": {"amount": "numeric", "email": "string", "id": "datetime"}})
        self.assertEqual(list(result(a, "dtype_validation").details["mismatches"]), ["id"])


class EdgeCaseTest(unittest.TestCase):
    def test_every_check_survives_awkward_frames(self):
        frames = {
            "empty": pd.DataFrame(),
            "no_rows": pd.DataFrame({"a": pd.Series([], dtype=float)}),
            "all_null": pd.DataFrame({"a": [None, None], "b": [np.nan, np.nan]}),
            "mixed": pd.DataFrame({"a": [1, "x", None, 3.5], "b": pd.Categorical(["p", "q", "p", None])}),
            "int_names": pd.DataFrame({0: [1, 2, 3], 1: ["a", "b", "c"]}),
        }
        cfg = QualityConfig(date_columns=["a"], range_rules={"a": {"min": 0}},
                            string_patterns={"a": r"\d+"}, unique_columns=["a"])
        for label, df in frames.items():
            with self.subTest(frame=label):
                a = assess(df, cfg)
                self.assertEqual(len(a.results), len(ALL_CHECKS))
                json.dumps(a.to_dict())  # must be JSON-serialisable
                generate_html_report(a)

    def test_report_escapes_data_values(self):
        df = pd.DataFrame({"<script>alert(1)</script>": ["<img src=x onerror=alert(1)>"] * 3})
        html = generate_html_report(assess(df, {"string_patterns": {"<script>alert(1)</script>": r"\d+"}}))
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x", html)


class ConfigTest(unittest.TestCase):
    def test_rejects_unknown_keys_and_bad_values(self):
        for bad in ({"missing_treshold": 0.1}, {"outlier_method": "mad"}, {"enabled_checks": ["nope"]},
                    {"string_patterns": {"a": "("}}, {"range_rules": {"a": {"min": 5, "max": 1}}}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                QualityConfig.from_dict(bad)

    def test_round_trip_and_partial_weights(self):
        cfg = QualityConfig.from_dict({"severity_weights": {"outliers": 0.5}, "enabled_checks": ["outliers"]})
        self.assertEqual(cfg.severity_weights["outliers"], 0.5)
        self.assertEqual(cfg.severity_weights["missing_values"], 0.20)
        again = QualityConfig.from_json(cfg.to_json())
        self.assertEqual(again, cfg)


class SuggestTest(unittest.TestCase):
    def test_suggests_sensible_rules(self):
        df = clean_df()
        df["customer_id"] = ["c1", "c2"] * 100  # repeated FK: must not be marked unique
        cfg = suggest_config(df)
        self.assertEqual(cfg.unique_columns, ["id"])
        self.assertEqual(cfg.date_columns, ["created"])
        self.assertIn("email", cfg.string_patterns)
        self.assertEqual(cfg.range_rules, {"amount": {"min": 0}})


if __name__ == "__main__":
    unittest.main()
