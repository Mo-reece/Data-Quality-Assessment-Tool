"""
Data Quality Assessment Tool
=============================
A modular, production-ready toolkit for automated data quality profiling,
validation, and reporting.

Modules:
    checks  - Individual data quality check functions
    engine  - Orchestration engine that runs checks and aggregates results
    report  - HTML/console report generation with visualizations
    config  - Configuration loading and validation
"""

from data_quality.engine import DataQualityEngine
from data_quality.config import QualityConfig

__version__ = "1.0.0"
__all__ = ["DataQualityEngine", "QualityConfig"]
