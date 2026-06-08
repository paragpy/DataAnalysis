"""
Configuration for the Swoosh Graph Analysis tool.

All connection parameters are configured here in code (NOT passed as CLI
arguments). Only the path to the Excel workbook is supplied at runtime.

Edit the values below to match your environment.
"""

# ---------------------------------------------------------------------------
# API connection
# ---------------------------------------------------------------------------

# Base host for the Swoosh graph API.
BASE_URL = "https://cims-dev-stg.51433.app.standardchartered.com"

# Endpoint that returns the node bundle for a given job.
NODES_ENDPOINT = "/swoosh/graph-api/collect/nodes/"

# The graph space to query.
SPACE_NAME = "swoosh_contract_space"

# Extra query parameters sent with every request. These mirror the optional
# parameters available on the "Get Nodes - Bundle" call. They are kept here so
# the behaviour can be tuned without touching the request code.
#
# Set a value to None (or remove the key) to omit that parameter from the
# request. The `properties` parameter is built per-row from the Excel
# `swoosh_job_id` value, so it is intentionally NOT listed here.
EXTRA_QUERY_PARAMS = {
    # "tag": "CWID",
    # "vid": "CTR-B4-SA-UNKNOWN",
    # "get_edges": "true",
    # "edge_types": "CHILD_OF",
    # "depth": "2",
    "limit": "1000",
}

# HTTP headers. Add an Authorization token / cookie here if your environment
# requires authentication.
HEADERS = {
    "Accept": "application/json",
    # "Authorization": "Bearer <token>",
}

# Verify TLS certificates. Set to False for self-signed dev/staging certs.
VERIFY_SSL = True

# Per-request timeout in seconds.
REQUEST_TIMEOUT = 60

# Retry settings for transient/network failures.
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2  # 2, 4, 8, 16 ...

# ---------------------------------------------------------------------------
# Excel layout
# ---------------------------------------------------------------------------

# Name of the column in the input workbook that holds the swoosh job id.
SWOOSH_JOB_ID_COLUMN = "swoosh_job_id"

# Sheet to read the job list from (the "Jobs and JobID" tab).
INPUT_SHEET_NAME = "Jobs and JobID"

# Name of the new sheet that receives our enriched result. Any existing sheets
# in the workbook (e.g. "CW_level_data") are preserved.
RESULT_SHEET_NAME = "graph_analysis_result"

# Columns from the input sheet to carry into the result sheet (kept before the
# tag count columns). These are the first three columns of "Jobs and JobID".
KEEP_COLUMNS = ["contract_id", "sb_job_id", "swoosh_job_id"]

# Optional explicit output path. When None, the tool writes alongside the input
# file using the input name with an "_graph_analysis" suffix.
OUTPUT_PATH = None

# ---------------------------------------------------------------------------
# Graph node tags
# ---------------------------------------------------------------------------

# All node tags (types) that can appear in the graph. One count column is
# emitted per tag, in this order. Taken from graph_schema_v1.md.
POSSIBLE_TAGS = [
    "CWID",
    "MasterAgreement",
    "SubAgreement",
    "MasterAmendmentVariation",
    "SubAgreementVariation",
    "SupportingDocument",
    "Bundle",
    "Clause",
]

# Name of the final column holding the JSON string of every (tag, vid) pair.
GRAPH_DETAILS_COLUMN = "graph_details_json"

# When True, any tag returned by the API that is not in POSSIBLE_TAGS still
# gets its own count column (appended after the known tags). When False such
# tags are ignored for counting but still included in the JSON bundle.
INCLUDE_UNKNOWN_TAGS = True
