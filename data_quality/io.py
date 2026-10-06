"""
File loading.

``load_table`` accepts a path or raw bytes plus a filename, so the CLI and the
browser app share one loader.  CSV delimiters are sniffed (comma, semicolon,
tab, pipe) and common text encodings are tried before giving up.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd

SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xls", ".parquet", ".json", ".jsonl")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the file as text.")


def _read_delimited(text: str, default_sep: str = ",") -> pd.DataFrame:
    try:
        sep = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
    except csv.Error:
        sep = default_sep
    return pd.read_csv(io.StringIO(text), sep=sep)


def load_table(source: str | Path | bytes, filename: str | None = None) -> pd.DataFrame:
    """Load a table from a path, or from bytes with ``filename`` giving the type."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        filename = filename or path.name
        data = path.read_bytes()
    else:
        data = source
        if not filename:
            raise ValueError("filename is required when loading from bytes.")

    suffix = Path(filename).suffix.lower()
    if suffix in (".csv", ".txt"):
        return _read_delimited(_decode(data))
    if suffix == ".tsv":
        return pd.read_csv(io.StringIO(_decode(data)), sep="\t")
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(io.BytesIO(data))
    if suffix == ".parquet":
        return pd.read_parquet(io.BytesIO(data))
    if suffix == ".jsonl":
        return pd.read_json(io.StringIO(_decode(data)), lines=True)
    if suffix == ".json":
        text = _decode(data)
        try:
            return pd.read_json(io.StringIO(text))
        except ValueError:
            return pd.read_json(io.StringIO(text), lines=True)
    raise ValueError(
        f"Unsupported file type '{suffix or filename}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
    )
