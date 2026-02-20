#!/usr/bin/env python3
"""
data_quality_tool.py  —  Command-line interface for the Data Quality Assessment Tool.

Usage examples
--------------
    # Basic usage — analyse a CSV with default settings:
    python data_quality_tool.py data/sales.csv

    # Specify output report and dataset name:
    python data_quality_tool.py data/sales.csv -o reports/sales_report.html -n "Q1 Sales"

    # Use a custom config file:
    python data_quality_tool.py data/sales.csv -c config.json

    # Run only specific checks:
    python data_quality_tool.py data/sales.csv --checks missing_values outliers duplicates

    # Save default config template:
    python data_quality_tool.py --save-config config_template.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from data_quality.config import QualityConfig
from data_quality.engine import DataQualityEngine
from data_quality.report import generate_html_report, print_console_summary


def _load_dataframe(path: str) -> pd.DataFrame:
    """Autodetect file format and load into a DataFrame."""
    p = Path(path)
    suffix = p.suffix.lower()
    loaders = {
        ".csv": pd.read_csv,
        ".tsv": lambda f: pd.read_csv(f, sep="\t"),
        ".xlsx": pd.read_excel,
        ".xls": pd.read_excel,
        ".parquet": pd.read_parquet,
        ".json": pd.read_json,
    }
    loader = loaders.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported file format: {suffix}")
    return loader(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_quality_tool",
        description="Automated Data Quality Assessment Tool — profile, validate, and report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to the dataset (CSV, TSV, Excel, Parquet, or JSON).",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Path for the HTML report.  Defaults to reports/<name>_quality_report.html.",
    )
    parser.add_argument(
        "-n", "--name",
        default=None,
        help="Dataset name used in the report title.  Defaults to the filename.",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to a JSON config file.  If omitted, default settings are used.",
    )
    parser.add_argument(
        "--checks",
        nargs="+",
        default=None,
        help="Whitespace-separated list of checks to run (e.g. missing_values outliers).",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip HTML report generation; print console summary only.",
    )
    parser.add_argument(
        "--save-config",
        default=None,
        metavar="PATH",
        help="Write the default config template to PATH and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Save config template and exit ---
    if args.save_config:
        QualityConfig().save(args.save_config)
        print(f"Default config written to {args.save_config}")
        return 0

    if not args.input_file:
        parser.print_help()
        return 1

    # --- Load config ---
    if args.config:
        config = QualityConfig.load(args.config)
    else:
        config = QualityConfig()

    if args.checks:
        config.enabled_checks = set(args.checks)

    # --- Load data ---
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: file not found — {input_path}", file=sys.stderr)
        return 1

    print(f"Loading {input_path} …")
    df = _load_dataframe(str(input_path))
    dataset_name = args.name or input_path.stem

    # --- Run engine ---
    engine = DataQualityEngine(config)
    assessment = engine.run(df, name=dataset_name)

    # --- Console summary ---
    print_console_summary(assessment)

    # --- HTML report ---
    if not args.no_html:
        output = args.output or f"reports/{dataset_name}_quality_report.html"
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(assessment, output_path=output)
        print(f"HTML report saved to {output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
