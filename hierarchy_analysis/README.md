# Hierarchy Analysis

Builds, for **every unique CWID**, the contract document hierarchy from the
Swoosh graph, enriches it with supplier details, attaches bundle details, and
saves the result as a **nested JSON** document and an **Excel-readable**
workbook.

This implements the Type 4 flow (`type4_flow.md`) and the graph model in
`graph_schema_v1.md`.

## What it produces

For each CWID:

- **Document hierarchy** — `CWID --HAS_DOCUMENT--> {MA|SA|MAV|SAV|SD}`, nested
  by `CHILD_OF` (child → parent). Nesting is derived from the documented match
  rules (tried in order): `parent_contract_id → contract_id`,
  `parent_document_reference_number → document_reference_number`,
  `ariba_parent_contract_id → ariba_contract_id`. `CHILD_OF` edges are used
  first when the API returns them, with the property rules as fallback.
- **Supplier enrichment** (Step 4, best-effort) — probes
  `ContractWorkspace → MasterAgreement → SubAgreement`, finds the node by
  `cwid`, fetches its full properties and extracts `supplier_address`,
  `supplier_reg_no`, and `services_mentioned` (normalised to a list). Failures
  log a WARN and continue.
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
  - **hierarchy** — one row per node with an indented `tree` label.
  - **suppliers** — consolidated supplier enrichment per CWID.
  - **bundles** — bundle identity + clause fields per bundle.

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
