"""
Render the nested hierarchy output into an Excel-readable workbook.

Three sheets:
  * "hierarchy" — one row per node, with an indented tree label so the
                  parent/child structure is readable at a glance.
  * "suppliers" — consolidated supplier enrichment, one row per CWID.
  * "bundles"   — bundle identity + clause fields, one row per bundle.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

import config


def _flatten_node(
    node: Dict[str, Any], cwid: str, level: int, rows: List[Dict[str, Any]]
) -> None:
    """Append a document node (and its children) as flattened rows."""
    indent = config.EXCEL_INDENT * level
    label = f"{indent}{node.get('tag') or '?'}: " + (
        node.get("unique_doc_id")
        or node.get("document_reference_number")
        or node.get("vid")
        or ""
    )
    rows.append({
        "cwid": cwid,
        "level": level,
        "tree": label,
        "node_type": node.get("tag"),
        "vid": node.get("vid"),
        "contract_id": node.get("contract_id"),
        "document_reference_number": node.get("document_reference_number"),
        "unique_doc_id": node.get("unique_doc_id"),
        "document_title": node.get("document_title"),
        "supplier": node.get("supplier"),
    })
    for child in node.get("children", []):
        _flatten_node(child, cwid, level + 1, rows)


def _append_bundle_rows(
    bundle: Dict[str, Any], cwid: str, rows: List[Dict[str, Any]]
) -> None:
    """Render a bundle (level 1) and its member documents (level 2)."""
    btype = bundle.get("bundle_type") or ""
    bid = bundle.get("bundle_id") or bundle.get("vid") or ""
    rows.append({
        "cwid": cwid,
        "level": 1,
        "tree": f"{config.EXCEL_INDENT}Bundle [{btype}]: {bid}",
        "node_type": config.BUNDLE_TAG,
        "vid": bundle.get("vid"),
        "contract_id": None,
        "document_reference_number": None,
        "unique_doc_id": None,
        "document_title": None,
        "supplier": None,
    })
    for member in bundle.get("members", []):
        # Members may be enriched dicts {vid, node_type, unique_doc_id} or, for
        # backward compatibility, a plain vid string.
        if isinstance(member, dict):
            mvid = member.get("vid")
            mtype = member.get("node_type") or "BundleMember"
            mdoc = member.get("unique_doc_id") or mvid
        else:
            mvid, mtype, mdoc = member, "BundleMember", member
        rows.append({
            "cwid": cwid,
            "level": 2,
            "tree": f"{config.EXCEL_INDENT * 2}{mtype}: {mdoc}",
            "node_type": mtype,
            "vid": mvid,
            "contract_id": None,
            "document_reference_number": None,
            "unique_doc_id": mdoc,
            "document_title": None,
            "supplier": None,
        })


def _hierarchy_rows(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in document.get("hierarchy", []):
        cwid = record.get("cwid")
        # The CWID itself is the level-0 root row.
        rows.append({
            "cwid": cwid,
            "level": 0,
            "tree": f"{config.CWID_TAG}: {cwid}",
            "node_type": config.CWID_TAG,
            "vid": record.get("vid"),
            "contract_id": record.get("contract_id"),
            "document_reference_number": None,
            "unique_doc_id": None,
            "document_title": None,
            "supplier": record.get("supplier"),
        })
        for child in record.get("children", []):
            _flatten_node(child, cwid, 1, rows)
        # Link bundles back into the tree under their CWID.
        if config.SHOW_BUNDLES_IN_HIERARCHY:
            for bundle in record.get("bundles", []):
                _append_bundle_rows(bundle, cwid, rows)
    return rows


def _supplier_rows(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in document.get("hierarchy", []):
        enr = record.get("enrichment", {})
        services = enr.get("services_mentioned") or []
        rows.append({
            "cwid": record.get("cwid"),
            "supplier": record.get("supplier"),
            "supplier_address": enr.get("supplier_address"),
            "supplier_reg_no": enr.get("supplier_reg_no"),
            "services_mentioned": ", ".join(services)
            if isinstance(services, list) else services,
        })
    return rows


def _bundle_rows(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in document.get("hierarchy", []):
        cwid = record.get("cwid")
        for bundle in record.get("bundles", []):
            row = {"cwid": cwid}
            for field in config.BUNDLE_IDENTITY_FIELDS:
                row[field] = bundle.get(field)
            clauses = bundle.get("clauses", {})
            for field in config.BUNDLE_CLAUSE_FIELDS:
                row[field] = clauses.get(field)
            rows.append(row)
    return rows


def write_excel(document: Dict[str, Any], output_path: str) -> None:
    """Write the three readable sheets to `output_path`."""
    hierarchy_df = pd.DataFrame(_hierarchy_rows(document))
    suppliers_df = pd.DataFrame(_supplier_rows(document))
    bundles_df = pd.DataFrame(_bundle_rows(document))

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        hierarchy_df.to_excel(writer, sheet_name="hierarchy", index=False)
        suppliers_df.to_excel(writer, sheet_name="suppliers", index=False)
        bundles_df.to_excel(writer, sheet_name="bundles", index=False)

    print(
        f"  Excel written: {output_path} "
        f"(hierarchy={len(hierarchy_df)}, suppliers={len(suppliers_df)}, "
        f"bundles={len(bundles_df)} rows)"
    )
