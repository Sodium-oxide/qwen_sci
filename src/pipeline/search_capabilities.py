"""Discover AnySearch's public routing contract; never infer nonexistent tags."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit

from .anysearch import build_anysearch_request, write_json_atomic


CATALOG_VERSION = 1


def _fallback() -> dict:
    return {"schema_version": CATALOG_VERSION, "status": "fallback", "saved_at": 0,
            "channels": {"academic.search": {"description": "Cross-discipline scholarly search (built-in public contract)", "params": {}}},
            "issues": [{"step": "capabilities", "reason": "catalog_unavailable"}]}


def _read(path: Path | None) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path else {}
        return value if isinstance(value, dict) and isinstance(value.get("channels"), dict) and value["channels"] else {}
    except (ValueError, OSError, TypeError):
        return {}


def load_capabilities(client, *, refresh: bool = False) -> dict:
    """Fetch domains then sub-domains, with a durable cache and bounded work.

    Only safe schema fields are saved. API messages and headers may contain
    credentials and are deliberately excluded from this artifact.
    """
    memory = getattr(client, "_capability_catalog", None)
    if memory and not refresh:
        return memory
    endpoint, _ = build_anysearch_request(client.base_url, "capabilities")
    parsed = urlsplit(endpoint)
    api_root = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.removesuffix("/search"), "", ""))
    fingerprint = hashlib.sha256(api_root.encode()).hexdigest()[:16]
    path = client.cache_dir / f"capabilities-{fingerprint}.json" if client.cache_dir else None
    previous = _read(path)
    if previous and not refresh and time.time() - previous.get("saved_at", 0) < 86400:
        client._capability_catalog = previous
        return previous
    started, requests_used, issues, channels = time.monotonic(), 0, [], {}
    headers = {"Authorization": f"Bearer {client.api_key}"} if client.api_key else {}

    def get(route, **params):
        nonlocal requests_used
        remaining = 45 - (time.monotonic() - started)
        if requests_used >= 20 or remaining <= 1:
            raise TimeoutError("catalog budget")
        requests_used += 1
        response = client.session.get(api_root + route, params=params, headers=headers,
                                      timeout=(min(3, remaining), min(8, remaining)))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("code", 0) != 0 or not isinstance(payload.get("data"), Mapping):
            raise ValueError("Invalid capabilities envelope")
        return payload["data"]

    try:
        data = get("/domains")
        domains = data.get("domains")
        if not isinstance(domains, list):
            raise ValueError("Invalid domains")
        # Scientific and general channels are available even if a later
        # specialty domain cannot be loaded within the startup budget.
        domains = sorted(domains, key=lambda d: (d.get("domain") not in {"academic", "general", "code", "health", "legal"}, d.get("domain", "")))
        for domain in domains[:19]:
            name = domain.get("domain", "")
            if not isinstance(name, str) or not re.fullmatch(r"[a-z_]+", name):
                continue
            try:
                details = get("/sub-domains", domain=name)
                for group in details.get("domains", []):
                    for sub in group.get("sub_domains", []):
                        tag = sub.get("sub_domain", "")
                        if isinstance(tag, str) and tag.startswith(name + ".") and isinstance(sub.get("params", {}), Mapping):
                            channels[tag] = {"description": str(sub.get("description", ""))[:1600],
                                             "domain": name, "params": dict(sub.get("params", {}))}
            except Exception as exc:
                issues.append({"domain": name, "error_type": type(exc).__name__})
    except Exception as exc:
        data = {}
        issues.append({"step": "capabilities", "error_type": type(exc).__name__})
    if channels:
        # A partial refresh retains previously verified channels for domains
        # which failed, but replaces successfully returned domains completely.
        failed = {item.get("domain") for item in issues}
        channels = {**{k: v for k, v in previous.get("channels", {}).items() if k.split(".")[0] in failed}, **channels}
        catalog = {"schema_version": CATALOG_VERSION, "status": "partial" if issues else "success",
                   "saved_at": time.time(), "endpoint": api_root,
                   "topology_version": data.get("topology_version"), "channels": channels,
                   "requests_used": requests_used, "issues": issues}
        if path:
            try:
                write_json_atomic(path, catalog)
            except OSError:
                pass
    else:
        catalog = {**previous, "status": "stale", "issues": issues} if previous else _fallback()
    client._capability_catalog = catalog
    return catalog


def validate_route(catalog: Mapping, tag: str, params: Mapping) -> None:
    """Reject unknown keys, missing required keys and invalid typed values.

    The service describes some parameters in prose rather than JSON Schema.
    Preserve that description in the planner's input; only enforce enumerated
    values when the catalog supplies an actual enum (or a single closed list).
    """
    channel = catalog.get("channels", {}).get(tag)
    if not isinstance(channel, Mapping):
        raise ValueError("Unknown AnySearch tag")
    if not isinstance(params, Mapping):
        raise ValueError("AnySearch params must be an object")
    specs = channel.get("params", {})
    unknown = set(params) - set(specs)
    if unknown:
        raise ValueError("Unknown channel parameters: " + ", ".join(sorted(unknown)))
    for key, spec in specs.items():
        spec = spec if isinstance(spec, Mapping) else {}
        value = params.get(key)
        if spec.get("required") and value in (None, ""):
            raise ValueError(f"Missing required channel parameter: {key}")
        if key not in params:
            continue
        if not isinstance(value, (str, int, float, bool)) or value is None:
            raise ValueError(f"Invalid channel parameter type: {key}")
        value_type = spec.get("type")
        if value_type == "string" and not isinstance(value, str):
            raise ValueError(f"Expected a string: {key}")
        if value_type in {"number", "integer"} and (isinstance(value, bool) or not isinstance(value, (int, float)) or (value_type == "integer" and not isinstance(value, int))):
            raise ValueError(f"Expected a number: {key}")
        if (value_type == "boolean" or key in {"open_access", "has_pdf"}) and not (isinstance(value, bool) or str(value).lower() in {"true", "false"}):
            raise ValueError(f"Expected a boolean: {key}")
        if key in {"year_from", "year_to"} and not re.fullmatch(r"\d{4}(?:[-/]\d{2}(?:[-/]\d{2})?)?", str(value)):
            raise ValueError(f"Expected a publication date: {key}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"Invalid enumerated channel parameter: {key}")
        description = str(spec.get("description", ""))
        if key in {"field", "op", "date_type", "order"} and "Values:" in description and "etc" not in description:
            allowed = re.findall(r"`([^`]+)`", description.split("Values:", 1)[1].split(". ", 1)[0])
            if allowed and str(value) not in allowed:
                raise ValueError(f"Invalid enumerated channel parameter: {key}")
    if params.get("year_from") and params.get("year_to") and str(params["year_from"]) > str(params["year_to"]):
        raise ValueError("Publication year range is reversed")
