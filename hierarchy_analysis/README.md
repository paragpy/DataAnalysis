# Hierarchy Analysis

Builds, for **every unique CWID**, the contract document hierarchy from the
Swoosh graph, enriches it with supplier details, attaches bundle details, and
saves the result as a **nested JSON** document and an **Excel-readable**
workbook.

This implements the Type 4 flow (`type4_flow.md`) and the graph model in
`graph_schema_v1.md`.

## What it produces

For each CWID:

- **Document hierarchy** — built from a **single `depth=2` read** per CWID:
  1. Fetch the CWID node by `vid` (vid == `contract_id`) with
     `get_edges=true, depth=2`. The one response carries the CWID's edges
     (**outward `HAS_DOCUMENT`** documents, **inward `HAS_BUNDLE`** bundle refs)
     and, inside each document's `destination_node`, that document's **nested
     edges**: **`CHILD_OF`** to other documents and **`IN_BUNDLE`** to its
     bundle node (clause fields inline).
  2. The document tree and bundle details are built from that single response;
     **chunks (`HAS_CHUNK` / `Chunk` nodes) are ignored.** A bundle referenced
     only at the CWID level (no inline node) is fetched by `vid` as a fallback.
  Edge direction (`outward`/`inward`) is honoured: for `CHILD_OF`, an outward
  edge means the queried node is the child, an inward edge means it is the
  parent.
- **Supplier enrichment** (Step 4, best-effort) — probes
  `ContractWorkspace → MasterAgreement → SubAgreement`, finds the node by
  `cwid`, fetches its full properties and extracts `supplier_address`,
  `supplier_reg_no`, and `services_mentioned` (normalised to a list). Failures
  log a WARN and continue.
- **Bundle linkage** — after the depth-2 pass, each bundle is fetched **by its
  id at `depth=0`** (`get_edges=true`). That returns the bundle's inward
  `IN_BUNDLE` edges (its **member documents**), which are stored on the bundle
  and rendered back into the Excel **`hierarchy`** sheet: the bundle appears at
  level 1 under its CWID and its member documents at level 2. Each member is
  resolved against the depth-2 documents so its **real node type**
  (`MasterAgreement` / `SubAgreement` / …) is shown rather than a generic label.
- **Bundle details** (`graph_schema_v1.md` §2.2) — `bundle_id`,
  `swoosh_job_id`, `sb_job_id` plus the nullable clause fields
  (`governing_law`, `assignment_novation`, `license_grant`, `right_to_use`,
  `divested_business_clause`, `recovery_resolution_planning`,
  `termination_for_convenience`).

## Output

- `hierarchy_output.json` — the Step 6 output document:

  ```json
  {
    "header":   { "generated_at": "...", "space_name": "...", "cwid_count": N },
    "hierarchy": [ { "cwid", "supplier", "enrichment", "unique_doc_ids",
                     "bundles": [...], "children": [...] } ],
    "suppliers": [ { "supplier", "supplier_address", "services_mentioned",
                     "supplier_reg_no" } ]
  }
  ```

- `per_cwid_json/<CWID>.json` — one hierarchy record per CWID.
- `hierarchy_output.xlsx` — three readable sheets:
  - **hierarchy** — one row per node with an indented `tree` label; bundles
    (level 1) and their member documents (level 2) are linked under each CWID.
  - **suppliers** — consolidated supplier enrichment per CWID.
  - **bundles** — bundle identity + clause fields per bundle.
- `cwids_without_hierarchy.txt` — CWIDs that had **no documents**. These are
  **excluded from both the JSON and the Excel** and listed here only, one per
  line.

## Configuration

All connection and behaviour settings live in [`config.py`](config.py) (not on
the command line): `BASE_URL`, `SPACE_NAME`, `HEADERS`/auth, `VERIFY_SSL`
(defaults `False` for the self-signed staging cert), the tag/edge names, the
`CHILD_OF` match rules, the enrichment probe tags/fields, and the bundle field
lists.

## Source of CWIDs

By default the unique CWIDs come from the `contract_id` column of the
`Jobs and JobID` sheet in `job_ids_list.xlsx` (looked up beside this script,
then in `../graph_analysis/job_based_analysis/`). You can also pass CWIDs
explicitly on the command line.

## Install & run

```bash
pip install -r requirements.txt

# CWIDs read from job_ids_list.xlsx
python run.py

# Or explicit CWIDs
python run.py CW199938 CW233206
```
