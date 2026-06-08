# Graph Analysis

Enriches an Excel workbook with node/tag information pulled from the Swoosh
**Get Nodes - Bundle** graph API.

For every row in the workbook the tool reads the `swoosh_job_id`, calls the
graph API, collects every returned node's `(tag, vid)` pair, and writes:

- **one count column per possible tag** (how many nodes of that tag the job
  produced), and
- **a final column** (`graph_details_json`) containing the full list of
  `{"tag": ..., "vid": ...}` pairs as a JSON string.

## Possible tags

Taken from `graph_schema_v1.md`:

| Tag | Abbr | Description |
| --- | --- | --- |
| `CWID` | CW | Contract Workspace ID — top-level Ariba entity |
| `MasterAgreement` | MA | Top-level contract document |
| `SubAgreement` | SA | Country/entity-level agreement under a MA |
| `MasterAmendmentVariation` | MAV | Variation/amendment to a MA |
| `SubAgreementVariation` | SAV | Variation/amendment to a SA |
| `SupportingDocument` | SD | Ancillary docs (schedules, appendices, exhibits) |
| `Bundle` | — | A created bundle grouping Type-1 / clause nodes |
| `Clause` | — | Targeted content chunks from a document |

Any tag returned by the API that is not in this list still gets its own count
column (appended after the known tags) unless `INCLUDE_UNKNOWN_TAGS` is set to
`False` in `config.py`.

## Configuration

All connection settings live in [`config.py`](config.py) — **not** on the
command line. Review/adjust before running:

- `BASE_URL`, `NODES_ENDPOINT`, `SPACE_NAME`
- `HEADERS` (add an `Authorization` token / cookie if required)
- `VERIFY_SSL` (set `False` for self-signed staging certs)
- `EXTRA_QUERY_PARAMS` (e.g. `limit`, `depth`, `get_edges`)
- `SWOOSH_JOB_ID_COLUMN` (defaults to `swoosh_job_id`)

The request is issued exactly like the Postman call:

```
GET {BASE_URL}{NODES_ENDPOINT}
    ?space_name=swoosh_contract_space
    &limit=1000
    &properties={"swoosh_job_id":"JID-..."}
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
# Output written next to the input as <name>_graph_analysis.xlsx
python process_excel.py "/path/to/20260608_ClauseAnalysis Status.xlsx"

# Or specify an explicit output path
python process_excel.py "/path/to/input.xlsx" "/path/to/output.xlsx"
```

Only the Excel path(s) are passed at runtime; everything else is configured in
`config.py`.

## Output layout

```
<original columns...> | CWID | MasterAgreement | ... | Clause | graph_details_json
```

Where each tag column holds the per-row node count for that tag and
`graph_details_json` holds the full `(tag, vid)` bundle, e.g.:

```json
[{"tag": "Bundle", "vid": "SB-CW162371-0EA1448C"},
 {"tag": "SubAgreement", "vid": "CW162371"}]
```
