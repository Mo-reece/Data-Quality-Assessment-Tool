"""
Command-line interface.

    data-quality orders.csv                         # console summary + HTML report
    data-quality orders.csv -c rules.json --json out.json --fail-under 0.85
    data-quality orders.csv --ref customers=customers.csv
    data-quality orders.csv --suggest rules.json    # write starter rules and exit

Exit codes: 0 success, 1 usage or input error, 2 quality gate failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_quality import __version__
from data_quality.config import CHECK_NAMES, ConfigError, QualityConfig
from data_quality.engine import DataQualityEngine
from data_quality.io import load_table
from data_quality.report import generate_html_report, print_console_summary
from data_quality.suggest import suggest_config

EXIT_OK, EXIT_ERROR, EXIT_GATE = 0, 1, 2


def _fraction(text: str) -> float:
    value = float(text)
    if value > 1:
        value /= 100  # accept 85 as well as 0.85
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1 (or 0 and 100)")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="data-quality",
        description="Profile, validate, and score a dataset; write HTML and JSON reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input_file", nargs="?", help="CSV, TSV, Excel, Parquet, JSON or JSONL file.")
    p.add_argument("-c", "--config", help="JSON rules file (see config_template.json).")
    p.add_argument("-n", "--name", help="Dataset name for reports (default: file name).")
    p.add_argument("-o", "--output", help="HTML report path (default: reports/<name>_quality_report.html).")
    p.add_argument("--json", metavar="PATH", help="Also write the full assessment as JSON ('-' for stdout).")
    p.add_argument("--no-html", action="store_true", help="Skip the HTML report.")
    p.add_argument("--checks", nargs="+", choices=CHECK_NAMES, metavar="CHECK",
                   help=f"Run only these checks: {', '.join(CHECK_NAMES)}.")
    p.add_argument("--ref", action="append", default=[], metavar="NAME=PATH",
                   help="Reference table for referential_integrity rules (repeatable).")
    p.add_argument("--fail-under", type=_fraction, metavar="SCORE",
                   help="Exit with code 2 if the composite score is below SCORE (e.g. 0.85).")
    p.add_argument("--fail-on-critical", action="store_true",
                   help="Exit with code 2 if any check is critical.")
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress the console summary.")
    p.add_argument("--suggest", metavar="PATH", help="Write rules inferred from the data to PATH and exit.")
    p.add_argument("--save-config", metavar="PATH", help="Write the default config to PATH and exit.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    log = (lambda *a: None) if args.quiet or args.json == "-" else (lambda *a: print(*a, file=sys.stderr))

    if args.save_config:
        QualityConfig().save(args.save_config)
        print(f"Default config written to {args.save_config}")
        return EXIT_OK

    if not args.input_file:
        parser.print_help()
        return EXIT_ERROR

    path = Path(args.input_file)
    try:
        if not path.exists():
            raise FileNotFoundError(f"file not found: {path}")
        df = load_table(path)

        if args.suggest:
            suggest_config(df).save(args.suggest)
            print(f"Suggested rules written to {args.suggest} — review them before use.")
            return EXIT_OK

        config = QualityConfig.load(args.config) if args.config else QualityConfig()
        if args.checks:
            config.enabled_checks = set(args.checks)

        refs = {}
        for item in args.ref:
            name, sep, ref_path = item.partition("=")
            if not sep or not name or not ref_path:
                raise ValueError(f"--ref expects NAME=PATH, got '{item}'")
            refs[name] = load_table(ref_path)
    except (OSError, ValueError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    name = args.name or path.stem
    assessment = DataQualityEngine(config).run(df, name=name, reference_dfs=refs)

    if not args.quiet and args.json != "-":
        print_console_summary(assessment)

    if not args.no_html:
        out = args.output or f"reports/{name}_quality_report.html"
        generate_html_report(assessment, output_path=out)
        log(f"HTML report: {out}")

    if args.json == "-":
        print(assessment.to_json())
    elif args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(assessment.to_json(), encoding="utf-8")
        log(f"JSON report: {args.json}")

    if args.fail_under is not None and assessment.composite_score < args.fail_under:
        print(f"Quality gate failed: {assessment.composite_score:.1%} < {args.fail_under:.1%}", file=sys.stderr)
        return EXIT_GATE
    if args.fail_on_critical and assessment.critical_issues:
        names = ", ".join(r.name for r in assessment.critical_issues)
        print(f"Quality gate failed: critical checks — {names}", file=sys.stderr)
        return EXIT_GATE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
