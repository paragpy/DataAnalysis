"""
Hierarchy construction for a single CWID, using the real graph edge model.

Traversal (all reads, depth 1 per the API behaviour):

  1. Fetch the CWID node by vid (vid == contract_id) with get_edges=true,
     depth=1. Its edges give:
        * outward HAS_DOCUMENT -> the documents that belong to the CWID
        * inward  HAS_BUNDLE   -> the bundle(s) the CWID belongs to
  2. For each document, fetch it by vid (depth 1) and read its CHILD_OF edges to
     discover which OTHER documents it connects to (chunks are excluded).
  3. Fetch each bundle by vid for its identity + clause fields.

Supplier enrichment (Type 4 flow, Step 4) is read from the CWID node itself,
falling back to a best-effort tag probe.

`build_cwid_hierarchy(cwid, db)` returns the record dict, or None when the CWID
has no hierarchy (no documents).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import config
from graph_db import GraphDB, GraphDBError


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _props(node: Dict[str, Any]) -> Dict[str, Any]:
    return node.get("properties", {}) if isinstance(node, dict) else {}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _normalise_list(value: Any) -> List[str]:
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


def _edge_name(edge: Dict[str, Any]) -> Optional[str]:
    # The API uses "name" (e.g. HAS_DOCUMENT); fall back to relation_type.
    return edge.get("name") or _props(edge).get("relation_type")


def _edge_direction(edge: Dict[str, Any]) -> Optional[str]:
    return edge.get("direction")


def _is_chunk(node: Optional[Dict[str, Any]], tag: Optional[str] = None) -> bool:
    tag = tag or (node.get("tag") if isinstance(node, dict) else None)
    return tag in config.EXCLUDE_TAGS


# ---------------------------------------------------------------------------
# Step 4 — supplier enrichment (best-effort READ)
# ---------------------------------------------------------------------------

def _extract_enrichment_from_props(props: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for out_field in config.ENRICHMENT_FIELDS:
        src = config.ENRICHMENT_SOURCE_MAP.get(out_field, out_field)
        value = props.get(src)
        if out_field in config.ENRICHMENT_LIST_FIELDS:
            result[out_field] = _normalise_list(value)
        else:
            result[out_field] = None if _is_empty(value) else value
    return result


def _enrichment_complete(enr: Dict[str, Any]) -> bool:
    for field in config.ENRICHMENT_FIELDS:
        value = enr.get(field)
        if field in config.ENRICHMENT_LIST_FIELDS:
            if value:
                return True
        elif not _is_empty(value):
            return True
    return False


def fetch_graph_properties(
    cwid: str, db: GraphDB, cwid_node: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Enrichment for a CWID. Reads supplier_address / supplier_reg_no /
    services_mentioned from the already-fetched CWID node, then falls back to a
    best-effort tag probe for anything still missing.
    """
    enr = _extract_enrichment_from_props(_props(cwid_node)) if cwid_node else {
        f: ([] if f in config.ENRICHMENT_LIST_FIELDS else None)
        for f in config.ENRICHMENT_FIELDS
    }
    if _enrichment_complete(enr):
        return enr

    for tag in config.ENRICHMENT_PROBE_TAGS:
        try:
            node = db.find_node_by_property(
                tag, config.ENRICHMENT_MATCH_PROPERTY, cwid
            )
        except GraphDBError as exc:
            print(f"      WARN: enrichment probe {tag} failed for {cwid}: {exc}")
            continue
        if node:
            print(f"      enrichment fallback hit for {cwid} via tag {tag!r}")
            return _extract_enrichment_from_props(_props(node))

    print(f"      WARN: enrichment incomplete for {cwid} (best-effort)")
    return enr


# ---------------------------------------------------------------------------
# bundles
# ---------------------------------------------------------------------------

def _bundle_summary(
    node: Dict[str, Any], bundle_type: Optional[str] = None
) -> Dict[str, Any]:
    props = _props(node)
    summary: Dict[str, Any] = {"vid": node.get("vid"), "bundle_type": bundle_type}
    for field in config.BUNDLE_IDENTITY_FIELDS:
        summary[field] = props.get(field)
    summary["clauses"] = {f: props.get(f) for f in config.BUNDLE_CLAUSE_FIELDS}
    return summary


def _fetch_bundles(
    db: GraphDB, bundle_links: Dict[str, Optional[str]]
) -> List[Dict[str, Any]]:
    bundles: List[Dict[str, Any]] = []
    for bundle_vid, bundle_type in bundle_links.items():
        try:
            nodes = db.get_nodes(vid=bundle_vid)
        except GraphDBError as exc:
            print(f"      WARN: bundle fetch failed for {bundle_vid}: {exc}")
            bundles.append({"vid": bundle_vid, "bundle_type": bundle_type,
                            "clauses": {}})
            continue
        if nodes:
            bundles.append(_bundle_summary(nodes[0], bundle_type))
        else:
            bundles.append({"vid": bundle_vid, "bundle_type": bundle_type,
                            "clauses": {}})
    return bundles


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------

def _doc_node(node: Dict[str, Any]) -> Dict[str, Any]:
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


def _collect_documents_and_bundles(
    cwid: str, cwid_node: Dict[str, Any], db: GraphDB
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, Optional[str]]]:
    """
    Walk the graph from the CWID node.

    Returns:
        doc_nodes   : vid -> document node (raw)
        child_parent: child_vid -> parent_vid   (from CHILD_OF edges)
        bundles     : bundle_vid -> bundle_type  (from HAS_BUNDLE / IN_BUNDLE)
    """
    doc_nodes: Dict[str, Dict[str, Any]] = {}
    child_parent: Dict[str, str] = {}
    bundles: Dict[str, Optional[str]] = {}
    queue: List[str] = []

    def register_doc(node: Optional[Dict[str, Any]], vid: Optional[str]) -> None:
        if not vid or vid in doc_nodes:
            return
        tag = node.get("tag") if isinstance(node, dict) else None
        if _is_chunk(node, tag):
            return
        doc_nodes[vid] = node if isinstance(node, dict) else {"vid": vid}
        queue.append(vid)

    # --- 1. CWID edges: outward HAS_DOCUMENT (docs), inward HAS_BUNDLE (bundle)
    for edge in _edges(cwid_node):
        name = _edge_name(edge)
        if name == config.EDGE_HAS_DOCUMENT and \
                _edge_direction(edge) == config.DIRECTION_OUTWARD:
            register_doc(edge.get("destination_node"), edge.get("destination"))
        elif name == config.EDGE_HAS_BUNDLE:
            bundles.setdefault(
                edge.get("destination"), _props(edge).get("bundle_type")
            )

    # --- 2. For each document, read CHILD_OF edges to other documents.
    while queue:
        vid = queue.pop(0)
        try:
            fetched = db.get_nodes(
                vid=vid, get_edges=True, depth=config.DOC_FETCH_DEPTH
            )
        except GraphDBError as exc:
            print(f"      WARN: document fetch failed for {vid}: {exc}")
            continue
        if not fetched:
            continue
        doc = fetched[0]
        doc_nodes[vid] = doc  # replace with the full node

        for edge in _edges(doc):
            name = _edge_name(edge)
            neighbor_vid = edge.get("destination")
            neighbor_node = edge.get("destination_node")

            if name == config.EDGE_HAS_CHUNK or _is_chunk(neighbor_node):
                continue  # never collect chunks

            if name == config.EDGE_CHILD_OF:
                # CHILD_OF points child -> parent.
                if _edge_direction(edge) == config.DIRECTION_OUTWARD:
                    child, parent = vid, neighbor_vid
                else:  # inward: neighbor is the child of this doc
                    child, parent = neighbor_vid, vid
                if child and parent:
                    child_parent[child] = parent
                register_doc(neighbor_node, neighbor_vid)

            elif name == config.EDGE_IN_BUNDLE:
                bundles.setdefault(
                    neighbor_vid, _props(edge).get("bundle_type")
                )

    return doc_nodes, child_parent, bundles


def _build_doc_tree(
    doc_nodes: Dict[str, Dict[str, Any]], child_parent: Dict[str, str]
) -> List[Dict[str, Any]]:
    shaped = {vid: _doc_node(node) for vid, node in doc_nodes.items()}
    roots: List[Dict[str, Any]] = []
    for vid in doc_nodes:
        parent = child_parent.get(vid)
        if parent and parent in shaped and parent != vid:
            shaped[parent]["children"].append(shaped[vid])
        else:
            roots.append(shaped[vid])  # parent is the CWID / unknown -> root
    return roots


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def build_cwid_hierarchy(cwid: str, db: GraphDB) -> Optional[Dict[str, Any]]:
    """
    Build the hierarchy record for one CWID, or return None if it has no
    hierarchy (no documents).
    """
    print(f"  Building hierarchy for CWID {cwid} ...")

    try:
        fetched = db.get_nodes(
            vid=cwid, get_edges=True, depth=config.CWID_FETCH_DEPTH
        )
    except GraphDBError as exc:
        print(f"    WARN: CWID fetch failed for {cwid}: {exc}")
        return None

    cwid_node = next((n for n in fetched if n.get("tag") == config.CWID_TAG), None)
    if cwid_node is None and fetched:
        cwid_node = fetched[0]
    if cwid_node is None:
        print(f"    no CWID node for {cwid} -> no hierarchy")
        return None

    doc_nodes, child_parent, bundle_links = _collect_documents_and_bundles(
        cwid, cwid_node, db
    )

    if not doc_nodes:
        print(f"    {cwid} has no documents -> no hierarchy")
        return None

    children = _build_doc_tree(doc_nodes, child_parent)
    bundles = _fetch_bundles(db, bundle_links)
    enrichment = fetch_graph_properties(cwid, db, cwid_node)

    cprops = _props(cwid_node)
    supplier = cprops.get(config.SUPPLIER_NAME_PROPERTY)
    unique_doc_ids = [
        _props(n).get("unique_doc_id") for n in doc_nodes.values()
        if not _is_empty(_props(n).get("unique_doc_id"))
    ]

    print(f"    {len(doc_nodes)} document(s), {len(bundles)} bundle(s)")

    return {
        "cwid": cwid,
        "vid": cwid_node.get("vid", cwid),
        "contract_id": cprops.get("contract_id", cwid),
        "supplier": supplier,
        "enrichment": enrichment,
        "unique_doc_ids": unique_doc_ids,
        "bundles": bundles,
        "children": children,
    }
