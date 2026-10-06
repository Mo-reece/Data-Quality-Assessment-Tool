#!/usr/bin/env python3
"""Backwards-compatible entry point; prefer `data-quality` or `python -m data_quality`."""

import sys

from data_quality.cli import main

if __name__ == "__main__":
    sys.exit(main())
