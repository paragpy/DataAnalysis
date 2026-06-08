"""
Hierarchy construction for a single CWID, using the real graph edge model.

Traversal (a single depth-2 read per CWID):

  1. Fetch the CWID node by vid (vid == contract_id) with get_edges=true,
     depth=2. The one response carries:
        * the CWID's edges: outward HAS_DOCUMENT -> its documents, and
          inward HAS_BUNDLE -> the bundle(s) it belongs to;
        * each document's nested edges (inside destination_node): CHILD_OF to
          other documents and IN_BUNDLE to its bundle node (clause fields
          inline). HAS_CHUNK is ignored.
  2. The document tree and bundle details are built from that single response.
     Any bundle referenced only at the CWID level (no inline node) is fetched
     by vid as a fallback.

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
    node: Dict[str, Any],
    bundle_type: Optional[str] = None,
    members: Optional[List[str]] = None,
) -> Dict[str, Any]:
    props = _props(node)
    summary: Dict[str, Any] = {"vid": node.get("vid"), "bundle_type": bundle_type}
    for field in config.BUNDLE_IDENTITY_FIELDS:
        summary[field] = props.get(field)
    summary["clauses"] = {f: props.get(f) for f in config.BUNDLE_CLAUSE_FIELDS}
    summary["members"] = members or []
    return summary


def _bundle_members(node: Dict[str, Any], bundle_vid: str) -> List[str]:
    """Member document vids from a bundle's inward IN_BUNDLE edges."""
    members: List[str] = []
    for edge in _edges(node):
        if _edge_name(edge) != config.EDGE_IN_BUNDLE:
            continue
        dst, src = edge.get("destination"), edge.get("source")
        member = dst if dst and dst != bundle_vid else src
        if member and member != bundle_vid and member not in members:
            members.append(member)
    return members


def _resolve_bundles(
    db: GraphDB,
    bundle_types: Dict[str, Optional[str]],
    bundle_nodes: Dict[str, Dict[str, Any]],
    doc_nodes: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build bundle summaries.

    Bundle node detail (incl. clause fields) comes inline from the depth-2
    IN_BUNDLE destination_node. Each bundle is then fetched by its id at depth 0
    to read its inward IN_BUNDLE edges (the member documents), which are used to
    link the bundle back into the hierarchy. The depth-0 node also backfills the
    clause fields when no inline node was captured.
    """
    bundles: List[Dict[str, Any]] = []
    for bundle_vid in set(bundle_types) | set(bundle_nodes):
        bundle_type = bundle_types.get(bundle_vid)
        node = bundle_nodes.get(bundle_vid)
        members: List[Dict[str, Any]] = []

        # Depth-0 fetch by id -> inward members (+ clauses fallback).
        try:
            fetched = db.get_nodes(
                vid=bundle_vid, get_edges=True, depth=config.BUNDLE_FETCH_DEPTH
            )
        except GraphDBError as exc:
            print(f"      WARN: bundle fetch failed for {bundle_vid}: {exc}")
            fetched = []
        if fetched:
            # Resolve each member vid to its real document type (tag) using the
            # documents already collected from the depth-2 CWID fetch.
            for member_vid in _bundle_members(fetched[0], bundle_vid):
                member_doc = doc_nodes.get(member_vid)
                members.append({
                    "vid": member_vid,
                    "node_type": member_doc.get("tag") if member_doc else None,
                    "unique_doc_id": _props(member_doc).get("unique_doc_id")
                    if member_doc else None,
                })
            if node is None:
                node = fetched[0]

        if node is not None:
            bundles.append(_bundle_summary(node, bundle_type, members))
        else:
            bundles.append({"vid": bundle_vid, "bundle_type": bundle_type,
                            "clauses": {}, "members": members})
        print(f"      bundle {bundle_vid}: {len(members)} member document(s)")
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
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str],
           Dict[str, Optional[str]], Dict[str, Dict[str, Any]]]:
    """
    Walk the depth-2 CWID response in a single pass.

    The CWID node carries its edges; each document's `destination_node` carries
    its own nested edges (CHILD_OF, IN_BUNDLE, HAS_CHUNK). HAS_CHUNK is ignored.

    Returns:
        doc_nodes    : vid -> document node
        child_parent : child_vid -> parent_vid     (from CHILD_OF edges)
        bundle_types : bundle_vid -> bundle_type    (from HAS_BUNDLE / IN_BUNDLE)
        bundle_nodes : bundle_vid -> bundle node    (from IN_BUNDLE destination_node)
    """
    doc_nodes: Dict[str, Dict[str, Any]] = {}
    child_parent: Dict[str, str] = {}
    bundle_types: Dict[str, Optional[str]] = {}
    bundle_nodes: Dict[str, Dict[str, Any]] = {}
    processed: set = set()

    def record_bundle_type(vid: Optional[str], btype: Optional[str]) -> None:
        # A concrete bundle_type (from HAS_BUNDLE) wins over a None placeholder
        # left by an IN_BUNDLE edge, regardless of which is seen first.
        if not vid:
            return
        if vid not in bundle_types or (bundle_types[vid] is None and btype):
            bundle_types[vid] = btype

    def handle_document(node: Optional[Dict[str, Any]]) -> None:
        if not isinstance(node, dict):
            return
        vid = node.get("vid")
        if not vid or _is_chunk(node):
            return
        doc_nodes.setdefault(vid, node)
        if vid in processed:
            return
        processed.add(vid)

        for edge in _edges(node):
            name = _edge_name(edge)
            neighbor_vid = edge.get("destination")
            neighbor_node = edge.get("destination_node")

            if name == config.EDGE_HAS_CHUNK or _is_chunk(neighbor_node):
                continue  # ignore chunks

            if name == config.EDGE_CHILD_OF:
                if _edge_direction(edge) == config.DIRECTION_OUTWARD:
                    child, parent = vid, neighbor_vid     # this doc -> its parent
                else:
                    child, parent = neighbor_vid, vid     # neighbor is the child
                if child and parent:
                    child_parent[child] = parent
                # The neighbor is another document (available inline at depth 2).
                if isinstance(neighbor_node, dict) and \
                        neighbor_node.get("tag") in config.DOCUMENT_TAGS:
                    handle_document(neighbor_node)

            elif name == config.EDGE_IN_BUNDLE:
                if neighbor_vid:
                    if isinstance(neighbor_node, dict):
                        bundle_nodes[neighbor_vid] = neighbor_node
                    record_bundle_type(
                        neighbor_vid, _props(edge).get("bundle_type")
                    )

    # --- CWID edges: HAS_DOCUMENT (documents) + HAS_BUNDLE (bundle refs) ---
    for edge in _edges(cwid_node):
        name = _edge_name(edge)
        if name == config.EDGE_HAS_DOCUMENT and \
                _edge_direction(edge) == config.DIRECTION_OUTWARD:
            handle_document(edge.get("destination_node"))
        elif name == config.EDGE_HAS_BUNDLE:
            record_bundle_type(
                edge.get("destination"), _props(edge).get("bundle_type")
            )

    return doc_nodes, child_parent, bundle_types, bundle_nodes


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

    doc_nodes, child_parent, bundle_types, bundle_nodes = \
        _collect_documents_and_bundles(cwid, cwid_node, db)

    if not doc_nodes:
        print(f"    {cwid} has no documents -> no hierarchy")
        return None

    children = _build_doc_tree(doc_nodes, child_parent)
    bundles = _resolve_bundles(db, bundle_types, bundle_nodes, doc_nodes)
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
