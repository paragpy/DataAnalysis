"""
GraphDB REST client for the Swoosh graph "collect/nodes" API.

This is the shared REST client used by all hierarchy handlers (Type 4 flow,
Step 4). It exposes the small surface the flow relies on:

    find_node_by_property(tag, prop, value)   -> a single node (or None)
    find_nodes_by_property(prop, value, ...)   -> list of nodes
    get_nodes(vid=..., get_edges=..., ...)     -> list of nodes (optionally
                                                  carrying their edges)

Each node is a dict shaped like:
    {"tag": "...", "vid": "...", "properties": {...}, "edges": [...]}
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import requests

import config

# The dev/staging host uses a self-signed certificate. Silence the noisy
# InsecureRequestWarning when verification is disabled in config.
if not config.VERIFY_SSL:
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        pass


class GraphDBError(RuntimeError):
    """Raised when the graph API cannot be reached or returns an error."""


def _extract_nodes(payload: Any) -> List[Dict[str, Any]]:
    """Normalise an API response into a list of node dicts."""
    if payload is None:
        return []
    if isinstance(payload, list):
        candidate = payload
    elif isinstance(payload, dict):
        for key in ("nodes", "data", "results", "items"):
            if isinstance(payload.get(key), list):
                candidate = payload[key]
                break
        else:
            list_values = [v for v in payload.values() if isinstance(v, list)]
            candidate = list_values[0] if list_values else []
    else:
        return []
    return [
        n for n in candidate
        if isinstance(n, dict) and ("tag" in n or "vid" in n)
    ]


class GraphDB:
    """Thin wrapper around GET {BASE_URL}{NODES_ENDPOINT}."""

    def __init__(self) -> None:
        self.url = config.BASE_URL.rstrip("/") + config.NODES_ENDPOINT
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)

    # -- low level ----------------------------------------------------------

    def _get(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        """Issue a GET with retry/backoff and return the parsed node list."""
        last_error: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES):
            try:
                resp = self.session.get(
                    self.url,
                    params=params,
                    timeout=config.REQUEST_TIMEOUT,
                    verify=config.VERIFY_SSL,
                )
                print(f"      GET {resp.url} -> HTTP {resp.status_code}")
                resp.raise_for_status()
                return _extract_nodes(resp.json())
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES - 1:
                    wait = config.RETRY_BACKOFF_SECONDS * (2 ** attempt)
                    print(
                        f"      attempt {attempt + 1}/{config.MAX_RETRIES} "
                        f"failed ({exc}); retrying in {wait}s ..."
                    )
                    time.sleep(wait)
        raise GraphDBError(f"GET failed for params={params}: {last_error}")

    def _base_params(self) -> Dict[str, str]:
        return {"space_name": config.SPACE_NAME}

    # -- query helpers ------------------------------------------------------

    def find_nodes_by_property(
        self,
        prop: str,
        value: str,
        tag: Optional[str] = None,
        get_edges: bool = False,
        edge_types: Optional[List[str]] = None,
        depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return every node whose `prop` equals `value` (optionally by tag)."""
        params = self._base_params()
        if tag:
            params["tag"] = tag
        params["properties"] = json.dumps({prop: value})
        if get_edges:
            params["get_edges"] = "true"
            if edge_types:
                params["edge_types"] = ",".join(edge_types)
            params["depth"] = str(depth if depth is not None else config.DEFAULT_DEPTH)
        params["limit"] = str(limit if limit is not None else config.DEFAULT_LIMIT)
        return self._get(params)

    def find_node_by_property(
        self, tag: str, prop: str, value: str
    ) -> Optional[Dict[str, Any]]:
        """Return the first node of `tag` whose `prop` equals `value`."""
        nodes = self.find_nodes_by_property(prop, value, tag=tag)
        return nodes[0] if nodes else None

    def get_nodes(
        self,
        vid: str,
        get_edges: bool = False,
        edge_types: Optional[List[str]] = None,
        depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch the node(s) for a vid, optionally traversing edges."""
        params = self._base_params()
        params["vid"] = vid
        if get_edges:
            params["get_edges"] = "true"
            if edge_types:
                params["edge_types"] = ",".join(edge_types)
            params["depth"] = str(depth if depth is not None else config.DEFAULT_DEPTH)
        params["limit"] = str(limit if limit is not None else config.DEFAULT_LIMIT)
        return self._get(params)
