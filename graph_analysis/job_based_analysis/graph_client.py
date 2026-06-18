"""
Thin client for the Swoosh graph "Get Nodes - Bundle" API.

The client connects using the `space_name` and `properties` query parameters
(plus any optional parameters defined in config.py). Connection details are
read from config.py so nothing has to be passed on the command line.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import requests

import config

# The dev/staging host uses a self-signed certificate. When SSL verification is
# disabled in config, urllib3 emits a noisy InsecureRequestWarning on every
# request — silence it so the progress output stays readable.
if not config.VERIFY_SSL:
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        pass


class GraphAPIError(RuntimeError):
    """Raised when the graph API cannot be reached or returns an error."""


def _build_query_params(swoosh_job_id: str) -> Dict[str, str]:
    """Assemble the query parameters for a single job lookup."""
    params: Dict[str, str] = {"space_name": config.SPACE_NAME}

    # Carry over any optional parameters that have a value configured.
    for key, value in config.EXTRA_QUERY_PARAMS.items():
        if value is not None:
            params[key] = value

    # `properties` is sent as a JSON string, exactly like the Postman call:
    #   properties = {"swoosh_job_id": "JID-..."}
    params["properties"] = json.dumps({"swoosh_job_id": swoosh_job_id})

    return params


def _extract_nodes(payload: Any) -> List[Dict[str, Any]]:
    """
    Normalise the API response into a list of node dicts.

    The endpoint returns node objects shaped like:
        {"tag": "...", "vid": "...", "properties": {...}, "edges": [...]}

    Depending on the deployment the top level may be a bare list or wrapped in
    a container key (e.g. {"nodes": [...]}). Both forms are handled here.
    """
    if payload is None:
        return []

    if isinstance(payload, list):
        candidate = payload
    elif isinstance(payload, dict):
        # Look for the most likely container key, else fall back to any list.
        for key in ("nodes", "data", "results", "items"):
            if isinstance(payload.get(key), list):
                candidate = payload[key]
                break
        else:
            list_values = [v for v in payload.values() if isinstance(v, list)]
            candidate = list_values[0] if list_values else []
    else:
        return []

    # Keep only objects that actually look like nodes (have a tag/vid).
    return [
        node
        for node in candidate
        if isinstance(node, dict) and ("tag" in node or "vid" in node)
    ]


def fetch_nodes(swoosh_job_id: str) -> List[Dict[str, Any]]:
    """
    Call the graph API for a single swoosh job id and return its nodes.

    Retries transient/network failures with exponential backoff.
    """
    url = config.BASE_URL.rstrip("/") + config.NODES_ENDPOINT
    params = _build_query_params(swoosh_job_id)

    last_error: Exception | None = None
    for attempt in range(config.MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                headers=config.HEADERS,
                timeout=config.REQUEST_TIMEOUT,
                verify=config.VERIFY_SSL,
            )
            print(f"        GET {response.url} -> HTTP {response.status_code}")
            response.raise_for_status()
            return _extract_nodes(response.json())
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            # Don't sleep after the final attempt.
            if attempt < config.MAX_RETRIES - 1:
                wait = config.RETRY_BACKOFF_SECONDS * (2 ** attempt)
                print(
                    f"        attempt {attempt + 1}/{config.MAX_RETRIES} failed "
                    f"({exc}); retrying in {wait}s ..."
                )
                time.sleep(wait)

    raise GraphAPIError(
        f"Failed to fetch nodes for swoosh_job_id={swoosh_job_id!r}: {last_error}"
    )
