"""
Hierarchy construction for a single CWID.

Combines three things, per the Type 4 flow and graph_schema_v1.md:

  * the document tree  (HAS_DOCUMENT + CHILD_OF edges / property match rules)
  * supplier enrichment (Step 4 — best-effort READ)
  * bundle details      (graph_schema_v1.md §2.2)

The public entry point is `build_cwid_hierarchy(cwid, db)`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import config
from graph_db import GraphDB, GraphDBError


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _props(node: Dict[str, Any]) -> Dict[str, Any]:
    return node.get("properties", {}) if isinstance(node, dict) else {}


def _prop(node: Dict[str, Any], key: str) -> Any:
    return _props(node).get(key)


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _normalise_list(value: Any) -> List[str]:
    """Normalise a comma-separated string or list into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def _edges(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    edges = node.get("edges") if isinstance(node, dict) else None
    return edges if isinstance(edges, list) else []


def _edge_type(edge: Dict[str, Any]) -> Optional[str]:
    for key in ("edge_type", "type", "name", "label"):
        if edge.get(key):
            return edge[key]
    return None


def _edge_src(edge: Dict[str, Any]) -> Optional[str]:
    for key in ("src", "source", "from", "start", "src_vid", "src_id"):
        if edge.get(key):
            return edge[key]
    return None


def _edge_dst(edge: Dict[str, Any]) -> Optional[str]:
    for key in ("dst", "destination", "to", "end", "dst_vid", "dst_id"):
        if edge.get(key):
            return edge[key]
    return None


# ---------------------------------------------------------------------------
# Step 4 — Graph enrichment (best-effort READ)
# ---------------------------------------------------------------------------

def fetch_graph_properties(cwid: str, db: GraphDB) -> Dict[str, Any]:
    """
    Best-effort lookup of the three enrichment fields for a CWID.

    Probes ENRICHMENT_PROBE_TAGS in order, finds the node by
    ENRICHMENT_MATCH_PROPERTY, fetches its full properties and extracts
    supplier_address / supplier_reg_no / services_mentioned. Any failure logs a
    WARN and continues (enrichment is best-effort).
    """
    default: Dict[str, Any] = {f: None for f in config.ENRICHMENT_FIELDS}
    for field in config.ENRICHMENT_LIST_FIELDS:
        default[field] = []

    for tag in config.ENRICHMENT_PROBE_TAGS:
        try:
            node = db.find_node_by_property(
                tag, config.ENRICHMENT_MATCH_PROPERTY, cwid
            )
        except GraphDBError as exc:
            print(f"      WARN: enrichment probe {tag} failed for {cwid}: {exc}")
            continue

        if not node:
            continue

        # Fetch the full node properties via its vid (Step 4).
        vid = node.get("vid")
        props = _props(node)
        if vid:
            try:
                full = db.get_nodes(vid=vid)
                if full:
                    props = _props(full[0]) or props
            except GraphDBError as exc:
                print(f"      WARN: get_nodes({vid}) failed for {cwid}: {exc}")

        result: Dict[str, Any] = {}
        for field in config.ENRICHMENT_FIELDS:
            value = props.get(field)
            if field in config.ENRICHMENT_LIST_FIELDS:
                result[field] = _normalise_list(value)
            else:
                result[field] = None if _is_empty(value) else value
        result["_supplier_name"] = props.get(config.SUPPLIER_NAME_PROPERTY)
        print(f"      enrichment hit for {cwid} via tag {tag!r}")
        return result

    print(f"      WARN: no enrichment node found for {cwid} (best-effort)")
    return default


# ---------------------------------------------------------------------------
# Bundle details (graph_schema_v1.md §2.2)
# ---------------------------------------------------------------------------

def _bundle_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a Bundle node to its identity + clause fields."""
    props = _props(node)
    summary: Dict[str, Any] = {"vid": node.get("vid")}
    for field in config.BUNDLE_IDENTITY_FIELDS:
        summary[field] = props.get(field)
    clauses = {f: props.get(f) for f in config.BUNDLE_CLAUSE_FIELDS}
    summary["clauses"] = clauses
    return summary


def _collect_bundles(
    db: GraphDB,
    subgraph: List[Dict[str, Any]],
    documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Gather bundle nodes for a CWID from the subgraph, with a fallback query."""
    bundles: Dict[str, Dict[str, Any]] = {}

    # Primary: any Bundle-tag node already present in the traversed subgraph.
    for node in subgraph:
        if node.get("tag") == config.BUNDLE_TAG:
            bundles[node.get("vid")] = node

    # Fallback: query bundles by the documents' swoosh_job_id.
    if not bundles:
        seen_jobs = set()
        for doc in documents:
            job = _prop(doc, config.BUNDLE_LINK_PROPERTY)
            if _is_empty(job) or job in seen_jobs:
                continue
            seen_jobs.add(job)
            try:
                for node in db.find_nodes_by_property(
                    config.BUNDLE_LINK_PROPERTY, job, tag=config.BUNDLE_TAG
                ):
                    bundles[node.get("vid")] = node
            except GraphDBError as exc:
                print(f"      WARN: bundle lookup failed for job {job}: {exc}")

    return [_bundle_summary(n) for n in bundles.values()]


# ---------------------------------------------------------------------------
# Document tree (HAS_DOCUMENT + CHILD_OF)
# ---------------------------------------------------------------------------

def _doc_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a document node for the output hierarchy."""
    props = _props(node)
    return {
        "tag": node.get("tag"),
        "vid": node.get("vid"),
        "unique_doc_id": props.get("unique_doc_id"),
        "contract_id": props.get("contract_id"),
        "document_reference_number": props.get("document_reference_number"),
        "document_title": props.get("document_title"),
        "supplier": props.get(config.SUPPLIER_NAME_PROPERTY),
        "children": [],
    }


def _find_parent_vid_by_edges(
    child: Dict[str, Any], by_vid: Dict[str, Dict[str, Any]]
) -> Optional[str]:
    """Use CHILD_OF edges (child -> parent) on the child node, if present."""
    child_vid = child.get("vid")
    for edge in _edges(child):
        if _edge_type(edge) != config.EDGE_CHILD_OF:
            continue
        src, dst = _edge_src(edge), _edge_dst(edge)
        # CHILD_OF points child -> parent.
        if src == child_vid and dst in by_vid:
            return dst
        if dst == child_vid and src in by_vid:
            return src
    return None


def _find_parent_vid_by_props(
    child: Dict[str, Any],
    documents: List[Dict[str, Any]],
    cwid_vid: Optional[str],
) -> Optional[str]:
    """
    Apply the CHILD_OF property match rules in order.

    Returns the parent document's vid, or None when the child is top-level
    (its parent is the CWID itself / no document parent found).
    """
    child_vid = child.get("vid")
    for child_prop, parent_prop in config.CHILD_OF_RULES:
        value = _prop(child, child_prop)
        if _is_empty(value):
            continue
        matches = [
            d for d in documents
            if d.get("vid") != child_vid and _prop(d, parent_prop) == value
        ]
        # Accept only an unambiguous single document parent.
        if len(matches) == 1:
            return matches[0].get("vid")
    return None  # top-level -> attach under the CWID root


def _build_doc_tree(
    documents: List[Dict[str, Any]], cwid_vid: Optional[str]
) -> List[Dict[str, Any]]:
    """Nest documents into a tree using edges first, then property rules."""
    by_vid = {d.get("vid"): d for d in documents}
    shaped = {d.get("vid"): _doc_node(d) for d in documents}
    roots: List[Dict[str, Any]] = []

    for doc in documents:
        vid = doc.get("vid")
        parent_vid = _find_parent_vid_by_edges(doc, by_vid)
        if parent_vid is None or parent_vid == cwid_vid:
            parent_vid = _find_parent_vid_by_props(doc, documents, cwid_vid)
        if parent_vid and parent_vid in shaped and parent_vid != vid:
            shaped[parent_vid]["children"].append(shaped[vid])
        else:
            roots.append(shaped[vid])

    return roots


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def build_cwid_hierarchy(cwid: str, db: GraphDB) -> Dict[str, Any]:
    """Build the full hierarchy record for one CWID."""
    print(f"  Building hierarchy for CWID {cwid} ...")

    # Pull the CWID subgraph: the CWID node + all nodes sharing its contract_id,
    # with edges traversed so bundles/children come along.
    subgraph = db.find_nodes_by_property(
        config.CWID_MATCH_PROPERTY,
        cwid,
        get_edges=True,
        depth=config.DEFAULT_DEPTH,
    )

    # Fallback to the ariba id if nothing matched on contract_id.
    if not subgraph and config.CWID_MATCH_FALLBACK:
        print(f"    no match on {config.CWID_MATCH_PROPERTY}; "
              f"trying {config.CWID_MATCH_FALLBACK}")
        subgraph = db.find_nodes_by_property(
            config.CWID_MATCH_FALLBACK, cwid, get_edges=True,
            depth=config.DEFAULT_DEPTH,
        )

    cwid_node = next((n for n in subgraph if n.get("tag") == config.CWID_TAG), None)
    documents = [n for n in subgraph if n.get("tag") in config.DOCUMENT_TAGS]
    cwid_vid = cwid_node.get("vid") if cwid_node else None

    print(f"    found {len(documents)} document node(s); "
          f"CWID node {'present' if cwid_node else 'missing'}")

    # Document tree.
    children = _build_doc_tree(documents, cwid_vid)

    # Bundle details.
    bundles = _collect_bundles(db, subgraph, documents)
    print(f"    found {len(bundles)} bundle(s)")

    # Step 4 enrichment.
    enrichment = fetch_graph_properties(cwid, db)
    supplier_name = enrichment.pop("_supplier_name", None)
    if _is_empty(supplier_name) and cwid_node:
        supplier_name = _prop(cwid_node, config.SUPPLIER_NAME_PROPERTY)

    unique_doc_ids = [
        _prop(d, "unique_doc_id") for d in documents
        if not _is_empty(_prop(d, "unique_doc_id"))
    ]

    return {
        "cwid": cwid,
        "vid": cwid_vid,
        "contract_id": _prop(cwid_node, "contract_id") if cwid_node else cwid,
        "supplier": supplier_name,
        "enrichment": enrichment,
        "unique_doc_ids": unique_doc_ids,
        "bundles": bundles,
        "children": children,
    }
