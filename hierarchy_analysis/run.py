"""
Hierarchy Analysis — entry point.

For every unique CWID this tool:
  1. builds the contract document hierarchy (HAS_DOCUMENT + CHILD_OF),
  2. enriches each CWID with supplier details (Type 4 flow, Step 4),
  3. attaches bundle details (graph_schema_v1.md §2.2),
  4. assembles the Step 6 output document, and
  5. saves it as a nested JSON file AND an Excel-readable workbook.

Usage:
    python run.py                       # CWIDs read from job_ids_list.xlsx
    python run.py CW199938 CW233206     # explicit CWIDs

Connection and behaviour settings live in config.py; only the (optional) list
of CWIDs is passed on the command line.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

import config
from excel_writer import write_excel
from graph_db import GraphDB, GraphDBError
from hierarchy import build_cwid_hierarchy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# CWID discovery
# ---------------------------------------------------------------------------

def _locate_input_workbook() -> str | None:
    """Find the job list workbook beside this script or in graph_analysis."""
    candidates = [
        os.path.join(SCRIPT_DIR, config.INPUT_FILENAME),
        os.path.join(
            SCRIPT_DIR, os.pardir, "graph_analysis", "job_based_analysis",
            config.INPUT_FILENAME,
        ),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None


def load_unique_cwids() -> List[str]:
    """Read unique, order-preserved CWIDs from the input workbook."""
    import pandas as pd

    path = _locate_input_workbook()
    if not path:
        raise FileNotFoundError(
            f"Could not find {config.INPUT_FILENAME!r}. Pass CWIDs as arguments "
            f"or place the workbook beside run.py."
        )

    print(f"Reading CWIDs from {path} (sheet {config.INPUT_SHEET_NAME!r})")
    df = pd.read_excel(path, sheet_name=config.INPUT_SHEET_NAME)
    if config.CWID_COLUMN not in df.columns:
        raise KeyError(
            f"Column {config.CWID_COLUMN!r} not found. Columns: {list(df.columns)}"
        )

    seen: set = set()
    cwids: List[str] = []
    for raw in df[config.CWID_COLUMN]:
        if pd.isna(raw):
            continue
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value)
            cwids.append(value)
    return cwids


# ---------------------------------------------------------------------------
# Step 6 — build output document
# ---------------------------------------------------------------------------

def build_output_document(cwids: List[str], db: GraphDB) -> Dict[str, Any]:
    """Assemble {header, hierarchy[], suppliers[]} for all CWIDs."""
    hierarchy: List[Dict[str, Any]] = []
    suppliers: List[Dict[str, Any]] = []
    seen_suppliers: set = set()

    for idx, cwid in enumerate(cwids, start=1):
        print(f"[{idx}/{len(cwids)}] CWID {cwid}")
        record = build_cwid_hierarchy(cwid, db)
        hierarchy.append(record)

        # Consolidate suppliers (Step 5 spirit): one entry per supplier name.
        name = record.get("supplier")
        enr = record.get("enrichment", {})
        key = name or record.get("cwid")
        if key not in seen_suppliers:
            seen_suppliers.add(key)
            suppliers.append({
                "supplier": name,
                "supplier_address": enr.get("supplier_address"),
                "services_mentioned": enr.get("services_mentioned", []),
                "supplier_reg_no": enr.get("supplier_reg_no"),
            })

    return {
        "header": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "space_name": config.SPACE_NAME,
            "cwid_count": len(cwids),
        },
        "hierarchy": hierarchy,
        "suppliers": suppliers,
    }


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def save_outputs(document: Dict[str, Any]) -> None:
    json_path = os.path.join(SCRIPT_DIR, config.JSON_OUTPUT_FILENAME)
    excel_path = os.path.join(SCRIPT_DIR, config.EXCEL_OUTPUT_FILENAME)

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=False)
    print(f"  JSON written: {json_path}")

    # One JSON file per CWID (hierarchy record), if enabled.
    if config.PER_CWID_JSON_DIR:
        per_dir = os.path.join(SCRIPT_DIR, config.PER_CWID_JSON_DIR)
        os.makedirs(per_dir, exist_ok=True)
        for record in document.get("hierarchy", []):
            cwid = record.get("cwid") or "unknown"
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in cwid)
            with open(os.path.join(per_dir, f"{safe}.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(record, fh, indent=2, ensure_ascii=False)
        print(f"  Per-CWID JSON written to: {per_dir}/")

    write_excel(document, excel_path)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: List[str]) -> int:
    print("=" * 70)
    print("Hierarchy Analysis")
    print("=" * 70)
    print(f"  API endpoint : {config.BASE_URL.rstrip('/') + config.NODES_ENDPOINT}")
    print(f"  space_name   : {config.SPACE_NAME}")

    try:
        cwids = argv[1:] if len(argv) > 1 else load_unique_cwids()
    except (FileNotFoundError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not cwids:
        print("No CWIDs to process.", file=sys.stderr)
        return 1

    print(f"  CWIDs        : {len(cwids)} unique")
    print("=" * 70)

    db = GraphDB()
    try:
        document = build_output_document(cwids, db)
    except GraphDBError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\nSaving outputs ...")
    save_outputs(document)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
