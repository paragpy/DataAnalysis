"""
Configuration for the Hierarchy Analysis tool.

All connection and behaviour settings are configured here in code (NOT passed
as CLI arguments). Edit the values below to match your environment.

The tool builds, for every unique CWID, the contract document hierarchy
(per the graph edge model), enriches it with supplier details (Type 4 flow,
Step 4) and bundle details (graph_schema_v1.md §2.2), then saves the result as
a nested JSON document and an Excel-readable workbook.
"""

# ---------------------------------------------------------------------------
# API connection (same Swoosh graph API used by graph_analysis)
# ---------------------------------------------------------------------------

BASE_URL = "https://cims-dev-stg.51433.app.standardchartered.com"
NODES_ENDPOINT = "/swoosh/graph-api/collect/nodes/"
SPACE_NAME = "swoosh_contract_space"

# HTTP headers. Add an Authorization token / cookie here if required.
HEADERS = {
    "Accept": "application/json",
    # "Authorization": "Bearer <token>",
}

# The dev/staging host uses a self-signed certificate, so verification is off
# by default. Set True against a CA-trusted environment.
VERIFY_SSL = False

REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2  # 2, 4, 8, 16 ...

# Default query limit and traversal depth for subgraph pulls.
DEFAULT_LIMIT = 1000
DEFAULT_DEPTH = 3

# Depth used when fetching a CWID node (gives outward HAS_DOCUMENT documents and
# inward HAS_BUNDLE bundle) and when fetching each document (gives CHILD_OF links
# to other documents). Both are depth 1, as per the API behaviour.
CWID_FETCH_DEPTH = 1
DOC_FETCH_DEPTH = 1

# ---------------------------------------------------------------------------
# Source of CWIDs
# ---------------------------------------------------------------------------

# When no CWID is passed on the command line, unique CWIDs are read from this
# workbook (the same job list used by graph_analysis). The file is looked up in
# this folder first, then in ../graph_analysis/job_based_analysis/.
INPUT_FILENAME = "job_ids_list.xlsx"
INPUT_SHEET_NAME = "Jobs and JobID"

# Column in the input sheet that holds the CWID (contract workspace id).
CWID_COLUMN = "contract_id"

# ---------------------------------------------------------------------------
# Graph tags / edges (graph_schema_v1.md)
# ---------------------------------------------------------------------------

# Tag of the contract-workspace (top-level) node.
CWID_TAG = "CWID"

# Document node tags, top-level first. CHILD_OF nesting is derived from
# properties (see CHILD_OF_RULES below), not from this order.
DOCUMENT_TAGS = [
    "MasterAgreement",
    "SubAgreement",
    "MasterAmendmentVariation",
    "SubAgreementVariation",
    "SupportingDocument",
]

BUNDLE_TAG = "Bundle"
CHUNK_TAG = "Chunk"

# Tags that are never collected into the hierarchy (chunks are excluded).
EXCLUDE_TAGS = ["Chunk"]

# Edge type names (the API exposes these as the edge "name" field).
EDGE_HAS_DOCUMENT = "HAS_DOCUMENT"
EDGE_CHILD_OF = "CHILD_OF"
EDGE_IN_BUNDLE = "IN_BUNDLE"
EDGE_HAS_BUNDLE = "HAS_BUNDLE"
EDGE_HAS_CHUNK = "HAS_CHUNK"

# Edge direction values relative to the queried node.
DIRECTION_OUTWARD = "outward"
DIRECTION_INWARD = "inward"

# Property used to match all nodes belonging to one CWID. Per the HAS_DOCUMENT
# match rule, a CWID and all its documents share the same contract_id; the
# fallback is ariba_contract_id.
CWID_MATCH_PROPERTY = "contract_id"
CWID_MATCH_FALLBACK = "ariba_contract_id"

# CHILD_OF match rules (child property -> parent property), tried in order.
# A document is a child of the document/CWID whose `parent` property value
# equals the child's `child` property value.
CHILD_OF_RULES = [
    ("parent_contract_id", "contract_id"),
    ("parent_document_reference_number", "document_reference_number"),
    ("ariba_parent_contract_id", "ariba_contract_id"),
]

# ---------------------------------------------------------------------------
# Step 4 — Graph enrichment (best-effort READ)
# ---------------------------------------------------------------------------

# Tags probed (in order) when looking up enrichment for a CWID.
ENRICHMENT_PROBE_TAGS = ["ContractWorkspace", "MasterAgreement", "SubAgreement"]

# Property used by the enrichment probe to locate the node for a CWID.
ENRICHMENT_MATCH_PROPERTY = "cwid"

# The three enrichment fields extracted (Step 4).
ENRICHMENT_FIELDS = ["supplier_address", "supplier_reg_no", "services_mentioned"]

# Maps each output enrichment field to the node property it is read from.
# (The CWID/document node stores the registration number as
# `supplier_registration_number`.)
ENRICHMENT_SOURCE_MAP = {
    "supplier_address": "supplier_address",
    "supplier_reg_no": "supplier_registration_number",
    "services_mentioned": "services_mentioned",
}

# Fields that are comma-separated strings or lists and should be normalised to
# a list of strings.
ENRICHMENT_LIST_FIELDS = ["services_mentioned"]

# Property used as the supplier display name in the hierarchy/supplier output.
SUPPLIER_NAME_PROPERTY = "supplier_legal_name"

# ---------------------------------------------------------------------------
# Bundle details (graph_schema_v1.md §2.2)
# ---------------------------------------------------------------------------

BUNDLE_IDENTITY_FIELDS = ["bundle_id", "swoosh_job_id", "sb_job_id"]
BUNDLE_CLAUSE_FIELDS = [
    "governing_law",
    "assignment_novation",
    "license_grant",
    "right_to_use",
    "divested_business_clause",
    "recovery_resolution_planning",
    "termination_for_convenience",
]

# When edges cannot be resolved, fall back to linking bundles to a CWID by
# matching the bundle's swoosh_job_id against the documents' swoosh_job_id.
BUNDLE_LINK_PROPERTY = "swoosh_job_id"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

# Output files are written into this folder (next to the code) by default.
JSON_OUTPUT_FILENAME = "hierarchy_output.json"
EXCEL_OUTPUT_FILENAME = "hierarchy_output.xlsx"

# Also write one JSON file per CWID into this subfolder (set to None to skip).
PER_CWID_JSON_DIR = "per_cwid_json"

# Plain-text list of CWIDs that had no hierarchy (no documents). These CWIDs are
# excluded from both the JSON and the Excel outputs.
NO_HIERARCHY_FILENAME = "cwids_without_hierarchy.txt"

# Indentation unit used to render the tree label in the Excel "hierarchy" sheet.
EXCEL_INDENT = "    "
