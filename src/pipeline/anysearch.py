"""Shared AnySearch discovery adapter. Search snippets are never paper evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import requests


DEFAULT_ANYSEARCH_BASE_URL = "https://api.anysearch.com"
DEFAULT_ANYSEARCH_TAG = "academic.search"


def text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_doi(value: Any) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text(value), flags=re.I).strip().lower()


def _url(value: Any) -> str:
    value = text(value)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _config_get(config: Any, key: str, default: Any = None) -> Any:
    return config.get(key, default) if isinstance(config, Mapping) else getattr(config, key, default)


def as_bool(value: Any) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "on"} if isinstance(value, str) else bool(value)


def build_anysearch_request(base_url: str, query: str, limit: int = 10, *, tag: str = DEFAULT_ANYSEARCH_TAG,
                            params: Mapping[str, Any] | None = None) -> tuple[str, dict]:
    """Build the public REST request; an MCP URL is a separate protocol."""
    base = text(base_url).rstrip("/")
    if not _url(base) or not text(query):
        raise ValueError("AnySearch requires an HTTP(S) base URL and a query")
    parsed = urlsplit(base)
    if parsed.query or parsed.fragment or parsed.path.lower().endswith(("/mcp", "/sse")):
        raise ValueError("AnySearch REST base URL must not be an MCP URL or contain a query or fragment")
    if parsed.path.endswith("/v1/search"):
        endpoint = base
    elif parsed.path.endswith("/v1"):
        endpoint = base + "/search"
    else:
        endpoint = base + "/v1/search"
    payload = {"query": query.strip(), "max_results": min(10, max(1, int(limit))), "format": "json"}
    if text(tag):
        payload["tag"] = text(tag)
    if params:
        if not isinstance(params, Mapping):
            raise ValueError("AnySearch params must be an object")
        payload["params"] = dict(params)
    return endpoint, payload


def identity_keys(paper: Mapping[str, Any]) -> set[str]:
    external = paper.get("externalIds") or {}
    external = external if isinstance(external, Mapping) else {}
    doi = normalize_doi(paper.get("doi") or external.get("DOI"))
    title = re.sub(r"[^\w]+", "", text(paper.get("title") or paper.get("paper_title")).casefold())
    pid = text(paper.get("paperId") or paper.get("paper_id") or paper.get("openalex_id") or paper.get("node_id"))
    pid = re.sub(r"^https?://(?:api\.)?openalex\.org/", "", pid, flags=re.I)
    version = text(paper.get("version")) if paper.get("source_type") in {"dataset", "code"} else ""
    if version == "unspecified":
        version = ""
    source_type = text(paper.get("source_type"))
    suffix = f":source_type:{source_type}" if source_type and source_type not in {"paper", "preprint"} else ""
    suffix += f":version:{version}" if version else ""
    keys = {key + suffix for key in (f"doi:{doi}" if doi else "", f"title:{title}" if title else "", f"id:{pid}" if pid else "") if key}
    for name, value in source_identifiers(paper).items():
        if value:
            keys.add(f"{name}:{value.casefold()}{suffix}")
    return keys


def source_identifiers(paper: Mapping[str, Any]) -> dict[str, str]:
    """Extract identifiers from source URLs, never from discovery snippets."""
    external = paper.get("externalIds") or paper.get("identifiers") or {}
    external = external if isinstance(external, Mapping) else {}
    url = _url(paper.get("url") or paper.get("landing_url") or paper.get("link"))
    parsed = urlsplit(url)
    host, path = (parsed.hostname or "").lower(), unquote(parsed.path)
    pmcid = text(paper.get("pmcid") or external.get("PMCID") or external.get("pmcid"))
    arxiv = text(external.get("ArXiv") or external.get("arxiv"))
    repository = text(paper.get("repository_id"))
    if host in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "europepmc.org"}:
        match = re.search(r"\bPMC\d+\b", path, re.I)
        pmcid = pmcid or (match.group().upper() if match else "")
    if host in {"arxiv.org", "export.arxiv.org"}:
        match = re.search(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?$", path)
        arxiv = arxiv or (match.group(1) if match else "")
    if host in {"github.com", "gitlab.com"}:
        repository = repository or "/".join(path.strip("/").split("/")[:2])
        repository = f"{host}/{repository}" if repository and not repository.startswith(host + "/") else repository
    if host.endswith("zenodo.org"):
        match = re.search(r"/records?/(\d+)", path)
        repository = repository or ("zenodo:" + match.group(1) if match else "")
    return {"pmcid": pmcid.upper(), "arxiv": re.sub(r"v\d+$", "", arxiv), "repository": repository}


def merge_papers(papers: list[dict]) -> list[dict]:
    """Merge cross-provider duplicates, retaining missing metadata and all origins."""
    merged: list[dict] = []
    for raw in papers:
        keys = identity_keys(raw)
        matches = [i for i, item in enumerate(merged) if keys & identity_keys(item)]
        if not matches:
            merged.append(dict(raw))
            continue
        target = merged[matches[0]]
        for other in [*(merged[i] for i in matches[1:]), raw]:
            for key, value in other.items():
                if key in {"retrieval_provenance", "discovery_provenance", "oa_locations", "openalex_oa_locations"}:
                    records = list(target.get(key) or [])
                    for record in value or []:
                        if record not in records:
                            records.append(record)
                    target[key] = records
                elif isinstance(value, dict) and isinstance(target.get(key), dict):
                    target[key] = {**value, **{k: v for k, v in target[key].items() if v not in (None, "", [], {})}}
                elif target.get(key) in (None, "", [], {}):
                    target[key] = value
        for i in reversed(matches[1:]):
            merged.pop(i)
    return merged


def normalize_anysearch_paper(raw: Mapping[str, Any]) -> dict:
    title = text(raw.get("title") or raw.get("name"))
    if not title:
        return {}
    identifiers = raw.get("identifiers") or raw.get("externalIds") or {}
    identifiers = identifiers if isinstance(identifiers, Mapping) else {}
    landing = _url(raw.get("url") or raw.get("landing_url") or raw.get("link"))
    doi = normalize_doi(raw.get("doi") or identifiers.get("doi") or identifiers.get("DOI"))
    if not doi and landing:
        parsed = urlsplit(landing)
        if (parsed.hostname or "").lower() in {"doi.org", "dx.doi.org"}:
            candidate = unquote(parsed.path).lstrip("/")
            if re.fullmatch(r"10\.\d{4,9}/\S+", candidate):
                doi = normalize_doi(candidate)
    openalex_id = ""
    for value in (raw.get("openalex_id"), identifiers.get("OpenAlex"), raw.get("id"), raw.get("paperId")):
        match = re.fullmatch(r"(?:https?://openalex.org/)?(W\d+)", text(value), re.I)
        if match:
            openalex_id = match.group(1).upper()
            break
    year = raw.get("year") or raw.get("publication_year")
    source_type = text(raw.get("source_type") or raw.get("resource_type")).lower()
    source_type = {"software": "code"}.get(source_type, source_type)
    if not source_type:
        host = (urlsplit(landing).hostname or "").lower()
        if host in {"github.com", "gitlab.com"}:
            source_type = "code"
        elif host in {"zenodo.org", "figshare.com", "datadryad.org"}:
            source_type = "dataset"
    stable_key = doi or re.sub(r"\W+", "", title.casefold()) + ":" + str(year or "")
    if source_type and source_type not in {"paper", "preprint"}:
        stable_key += ":source_type:" + source_type
    if text(raw.get("version")) and source_type in {"dataset", "code"}:
        stable_key += ":version:" + text(raw["version"])
    pid = openalex_id or "AS" + hashlib.sha256(stable_key.encode()).hexdigest()[:24]
    open_pdf = raw.get("openAccessPdf")
    open_pdf = open_pdf if isinstance(open_pdf, Mapping) else {}
    pdf = _url(raw.get("pdf_url") or raw.get("fulltext_url") or open_pdf.get("url"))
    if not pdf and landing and urlsplit(landing).path.lower().endswith(".pdf"):
        pdf = landing
    locations = []
    raw_locations = raw.get("oa_locations")
    raw_locations = raw_locations if isinstance(raw_locations, list) else []
    for item in [*raw_locations, {"pdf_url": pdf, "landing_url": landing}]:
        if not isinstance(item, Mapping):
            continue
        location = {"source": "anysearch.oa_location", "pdf_url": _url(item.get("pdf_url")), "landing_url": _url(item.get("landing_url") or item.get("landing_page_url"))}
        if (location["pdf_url"] or location["landing_url"]) and location not in locations:
            locations.append(location)
    external = {"DOI": doi} if doi else {}
    arxiv = text(identifiers.get("ArXiv") or identifiers.get("arxiv"))
    if arxiv:
        external["ArXiv"] = arxiv
    authors = []
    for author in raw.get("authors") if isinstance(raw.get("authors"), list) else []:
        name = text(author.get("name") or author.get("display_name")) if isinstance(author, Mapping) else text(author)
        if name:
            authors.append({"name": name})
    return {
        "paperId": pid, "provider": "anysearch", "api_platform": "anysearch",
        "provider_paper_id": text(raw.get("id") or raw.get("paper_id") or raw.get("paperId")),
        "openalex_id": openalex_id, "title": title, "doi": doi, "externalIds": external,
        "year": year, "abstract": text(raw.get("abstract")), "discovery_snippet": text(raw.get("snippet")),
        "discovery_content": text(raw.get("content")),
        "authors": authors,
        "venue": text(raw.get("venue") or raw.get("journal")), "url": landing,
        "openAccessPdf": {"url": pdf} if pdf else {},
        "oa_locations": locations,
        # This is not an OpenAlex OA assertion. Keep the provider provenance.
        "openalex_oa_locations": [{"source": x["source"], "pdf_url": x["pdf_url"], "landing_page_url": x["landing_url"], "oa_evidence": "declared_pdf_url" if x["pdf_url"] else ""} for x in locations],
        "source_type": source_type,
        "version": text(raw.get("version")), "repository_id": text(raw.get("repository_id")),
        "discovery_provenance": [{"provider": "anysearch", "provider_paper_id": text(raw.get("id") or raw.get("paper_id") or raw.get("paperId")), "url": landing}],
    } | _identifier_fields(raw, landing)


def _identifier_fields(raw: Mapping, landing: str) -> dict:
    identifiers = source_identifiers({**raw, "url": landing})
    external = dict(raw.get("externalIds") or raw.get("identifiers") or {})
    doi = normalize_doi(raw.get("doi") or external.get("DOI") or external.get("doi"))
    if not doi and (urlsplit(landing).hostname or "").lower() in {"doi.org", "dx.doi.org"}:
        doi = normalize_doi(unquote(urlsplit(landing).path).lstrip("/"))
    if doi:
        external["DOI"] = doi
    if identifiers["pmcid"]:
        external["PMCID"] = identifiers["pmcid"]
    if identifiers["arxiv"]:
        # Keep the requested preprint version in provenance and download URL.
        match = re.search(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?$", urlsplit(landing).path)
        external["ArXiv"] = text(external.get("ArXiv") or external.get("arxiv")) or (match.group(1) if match else identifiers["arxiv"])
    return {"externalIds": external, "pmcid": identifiers["pmcid"], "repository_id": identifiers["repository"]}


def parse_anysearch_response(payload: Any) -> list[dict]:
    rows = payload if isinstance(payload, list) else None
    if isinstance(payload, Mapping):
        if ("code" in payload and payload["code"] != 0) or payload.get("error"):
            # Error messages may contain credentials; never include them in diagnostics.
            raise ValueError("AnySearch returned an unsuccessful response")
        rows = next((payload[key] for key in ("results", "papers", "data") if isinstance(payload.get(key), list)), None)
        if rows is None and isinstance(payload.get("data"), Mapping):
            rows = payload["data"].get("results")
    if not isinstance(rows, list):
        raise ValueError("AnySearch response must contain a results, papers or data list")
    papers = [paper for row in rows if isinstance(row, Mapping) and (paper := normalize_anysearch_paper(row))]
    if rows and not papers:
        raise ValueError("AnySearch returned no valid paper records")
    return merge_papers(papers)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@dataclass
class SearchResult:
    papers: list[dict] = field(default_factory=list)
    status: str = "provider_failure"
    attempts: int = 0
    cached: bool = False

    @property
    def successful(self) -> bool:
        return self.status in {"success", "valid_empty"}


class AnySearchClient:
    def __init__(self, base_url: str | None = None, *, api_key: str | None = None, timeout: float = 30,
                 max_retries: int = 1, cache_dir: str | Path | None = None, cache_ttl: int = 604800,
                 enabled: bool = True, session: Any = None, tag: str = DEFAULT_ANYSEARCH_TAG):
        self.base_url = text(os.getenv("ANYSEARCH_BASE_URL", DEFAULT_ANYSEARCH_BASE_URL) if base_url is None else base_url).rstrip("/")
        self.api_key = os.getenv("ANYSEARCH_API_KEY", "") if api_key is None else api_key
        self.tag = text(tag)
        self.timeout = min(120.0, max(1.0, float(timeout)))
        self.max_retries = min(3, max(0, int(max_retries)))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = max(0, int(cache_ttl))
        self.enabled = enabled
        self.session = session or requests.Session()

    def capabilities(self, *, refresh: bool = False) -> dict:
        from .search_capabilities import load_capabilities
        return load_capabilities(self, refresh=refresh)

    def search(self, query: str, limit: int = 10, *, tag: str | None = None,
               params: Mapping[str, Any] | None = None, max_attempts: int | None = None) -> SearchResult:
        if not self.enabled:
            return SearchResult(status="disabled")
        if not self.base_url:
            return SearchResult(status="unconfigured")
        try:
            selected_tag = self.tag if tag is None else tag
            if tag is not None or params is not None:
                from .search_capabilities import validate_route
                validate_route(self.capabilities(), selected_tag, params or {})
            endpoint, payload = build_anysearch_request(self.base_url, query, limit, tag=selected_tag, params=params)
        except (TypeError, ValueError):
            return SearchResult(status="invalid_request" if tag is not None or params is not None else "provider_failure")
        limit = payload["max_results"]
        fingerprint = hashlib.sha256(json.dumps(["anysearch_rest_v2", endpoint, payload], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / (fingerprint + ".json") if self.cache_dir else None
        if path and self.cache_ttl:
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(cached, dict) or not isinstance(cached.get("papers"), list):
                    raise ValueError("Invalid AnySearch cache record")
                ttl = min(self.cache_ttl, 21600) if cached.get("status") == "valid_empty" else self.cache_ttl
                if cached.get("status") in {"success", "valid_empty"} and time.time() - float(cached["saved_at"]) < ttl:
                    return SearchResult(papers=cached["papers"], status=cached["status"], cached=True)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        status = "provider_failure"
        attempt_limit = self.max_retries + 1 if max_attempts is None else min(self.max_retries + 1, max(0, int(max_attempts)))
        for attempt in range(attempt_limit):
            try:
                from .adaptive_search import charge_acquisition_http
                charge_acquisition_http()
                response = self.session.post(endpoint, json=payload,
                                             headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}, timeout=(5.0, self.timeout))
                if response.status_code == 429 or response.status_code >= 500:
                    status = "rate_limited" if response.status_code == 429 else "provider_failure"
                    continue
                response.raise_for_status()
                papers = parse_anysearch_response(response.json())[:limit]
                result = SearchResult(papers=papers, status="success" if papers else "valid_empty", attempts=attempt + 1)
                if path:
                    try:
                        write_json_atomic(path, {"papers": papers, "status": result.status, "saved_at": time.time()})
                    except OSError:
                        pass
                return result
            except (requests.Timeout, requests.ConnectionError):
                status = "provider_failure"
            except (requests.RequestException, ValueError, TypeError):
                return SearchResult(status="provider_failure", attempts=attempt + 1)
        return SearchResult(status=status, attempts=attempt_limit)


def anysearch_from_survey_config(config: Any, *, cache_dir: str | Path | None = None) -> AnySearchClient:
    api = _config_get(config, "APIInfo", {}) or {}
    settings = _config_get(_config_get(config, "ModuleInfo"), "WorkCollector", {}) or {}
    enabled = as_bool(_config_get(settings, "enable_anysearch_discovery", False))
    basic = _config_get(config, "BasicInfo")
    return AnySearchClient(
        _config_get(api, "anysearch_base_url") or None,
        tag=_config_get(api, "anysearch_tag", DEFAULT_ANYSEARCH_TAG),
        timeout=_config_get(api, "anysearch_timeout_seconds", 30), max_retries=_config_get(api, "anysearch_max_retries", 1),
        cache_dir=cache_dir or Path(str(_config_get(basic, "cache_path", "./database"))) / "anysearch", enabled=enabled,
    )


def with_anysearch_lanes(plan: Any, *, enabled: bool, result_limit: int = 10) -> Any:
    """Upgrade generated and cached project/SH/slot plans without changing identity."""
    if isinstance(plan, list):
        return [with_anysearch_lanes(item, enabled=enabled, result_limit=result_limit) for item in plan]
    if not isinstance(plan, Mapping):
        return plan
    upgraded = {key: with_anysearch_lanes(value, enabled=enabled, result_limit=result_limit) for key, value in plan.items()}
    lanes = upgraded.get("query_lanes")
    if not enabled or not isinstance(lanes, list):
        return upgraded
    existing = {text(lane.get("query")) for lane in lanes if lane.get("provider") == "anysearch"}
    interleaved = []
    for lane in lanes:
        interleaved.append(lane)
        query = text(lane.get("query"))
        if lane.get("provider") != "openalex" or not query or query in existing:
            continue
        added = {key: value for key, value in lane.items() if key not in {"provider_filter", "sort", "hard_filter_applied", "retrieval_cache"}}
        added.update(provider="anysearch", lane="anysearch_discovery", lane_id=str(lane.get("lane_id") or lane.get("lane") or "discovery") + ":anysearch", result_limit=result_limit)
        interleaved.append(added)
        existing.add(query)
    upgraded["query_lanes"] = interleaved
    return upgraded
