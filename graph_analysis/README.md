# Graph Analysis

Enriches an Excel workbook with node/tag information pulled from the Swoosh
**Get Nodes - Bundle** graph API.

The tool reads the job list from the **`Jobs and JobID`** sheet and, for every
row, reads the `swoosh_job_id`, calls the graph API, collects every returned
node's `(tag, vid)` pair, and writes the output to a **new sheet**
(`graph_analysis_result`) that keeps the original three columns
(`contract_id`, `sb_job_id`, `swoosh_job_id`). All existing sheets in the
workbook (e.g. `CW_level_data`) are preserved.

Each result row contains:

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
# No arguments: uses job_ids_list.xlsx located in the same folder as the code
python process_excel.py

# Or pass an explicit input (output written next to it as <name>_graph_analysis.xlsx)
python process_excel.py "/path/to/input.xlsx"

# Or specify an explicit output path too
python process_excel.py "/path/to/input.xlsx" "/path/to/output.xlsx"
```

By default the tool reads `job_ids_list.xlsx` from its own folder (configurable
via `INPUT_FILENAME` in `config.py`). Everything else is configured in
`config.py`; the Excel path is optional on the command line.

## Output layout

A new sheet `graph_analysis_result` is added to the workbook:

```
contract_id | sb_job_id | swoosh_job_id | CWID | MasterAgreement | ... | Clause | graph_details_json
```

Where each tag column holds the per-row node count for that tag and
`graph_details_json` holds the full `(tag, vid)` bundle, e.g.:

```json
[{"tag": "Bundle", "vid": "SB-CW162371-0EA1448C"},
 {"tag": "SubAgreement", "vid": "CW162371"}]
```
