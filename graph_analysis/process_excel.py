"""
Swoosh Graph Analysis — Excel enrichment tool.

Usage:
    python process_excel.py /path/to/ClauseAnalysis_Status.xlsx
    python process_excel.py /path/to/input.xlsx /path/to/output.xlsx

For every row in the workbook this tool:
  1. reads the `swoosh_job_id`,
  2. calls the Swoosh graph API (Get Nodes - Bundle),
  3. collects every node's (tag, vid) pair,
  4. writes one count column per possible tag, and
  5. appends a final column with the full (tag, vid) bundle as a JSON string.

All connection settings live in config.py; only the Excel path(s) are passed
on the command line.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List

import pandas as pd

import config
from graph_client import GraphAPIError, fetch_nodes


def _resolve_output_path(input_path: str) -> str:
    """Decide where to write the enriched workbook."""
    if config.OUTPUT_PATH:
        return config.OUTPUT_PATH
    root, ext = os.path.splitext(input_path)
    ext = ext if ext.lower() in (".xlsx", ".xls") else ".xlsx"
    return f"{root}_graph_analysis{ext}"


def _summarise_nodes(nodes: List[Dict[str, Any]]):
    """
    Turn a list of node dicts into:
      - tag_counts: Counter of how many nodes carry each tag
      - bundle: list of {"tag": ..., "vid": ...} for every node
    """
    tag_counts: Counter = Counter()
    bundle: List[Dict[str, Any]] = []

    for node in nodes:
        tag = node.get("tag")
        vid = node.get("vid")
        if tag:
            tag_counts[tag] += 1
        bundle.append({"tag": tag, "vid": vid})

    return tag_counts, bundle


def process_workbook(input_path: str, output_path: str | None = None) -> str:
    """Read the workbook, enrich every row, and write the result."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input Excel file not found: {input_path}")

    output_path = output_path or _resolve_output_path(input_path)

    df = pd.read_excel(input_path)

    if config.SWOOSH_JOB_ID_COLUMN not in df.columns:
        raise KeyError(
            f"Column {config.SWOOSH_JOB_ID_COLUMN!r} not found in workbook. "
            f"Available columns: {list(df.columns)}"
        )

    # Discover which tags actually need columns: the known ones always, plus any
    # unknown tags we encounter (if enabled).
    known_tags = list(config.POSSIBLE_TAGS)
    extra_tags: List[str] = []

    # Per-row accumulators, filled during the pass over the workbook.
    per_row_counts: List[Counter] = []
    per_row_json: List[str] = []

    total = len(df)
    print(f"Processing {total} row(s) from {input_path}")

    for idx, raw_job_id in enumerate(df[config.SWOOSH_JOB_ID_COLUMN], start=1):
        job_id = "" if pd.isna(raw_job_id) else str(raw_job_id).strip()

        if not job_id:
            print(f"  [{idx}/{total}] skipped — empty swoosh_job_id")
            per_row_counts.append(Counter())
            per_row_json.append(json.dumps([]))
            continue

        try:
            nodes = fetch_nodes(job_id)
            tag_counts, bundle = _summarise_nodes(nodes)
            per_row_counts.append(tag_counts)
            per_row_json.append(json.dumps(bundle, ensure_ascii=False))

            # Track any tags outside the known list so they still get a column.
            if config.INCLUDE_UNKNOWN_TAGS:
                for tag in tag_counts:
                    if tag not in known_tags and tag not in extra_tags:
                        extra_tags.append(tag)

            print(
                f"  [{idx}/{total}] {job_id} -> {len(nodes)} node(s), "
                f"{len(tag_counts)} distinct tag(s)"
            )
        except GraphAPIError as exc:
            # Record the error inline rather than aborting the whole run.
            print(f"  [{idx}/{total}] {job_id} -> ERROR: {exc}")
            per_row_counts.append(Counter())
            per_row_json.append(json.dumps({"error": str(exc)}, ensure_ascii=False))

    # Build the count columns (one per tag) before the JSON column.
    tag_columns = known_tags + sorted(extra_tags)
    for tag in tag_columns:
        df[tag] = [counts.get(tag, 0) for counts in per_row_counts]

    # The (tag, vid) bundle JSON string goes in the very last column.
    df[config.GRAPH_DETAILS_COLUMN] = per_row_json

    df.to_excel(output_path, index=False)
    print(f"Done. Wrote enriched workbook to {output_path}")
    return output_path


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        print("Error: path to the Excel workbook is required.", file=sys.stderr)
        return 2

    input_path = argv[1]
    output_path = argv[2] if len(argv) > 2 else None

    try:
        process_workbook(input_path, output_path)
    except (FileNotFoundError, KeyError, GraphAPIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
