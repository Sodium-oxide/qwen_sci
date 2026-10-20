"""Acquire real source content. Search snippets never enter reading results."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

from .anysearch import normalize_doi, source_identifiers, text, write_json_atomic
from .scholarly_metadata import EUROPE_PMC_API, biomedical_identity, parse_repository_jats, resolve_biomedical_metadata
from .source_retry import SOURCE_READER_REVISION, source_access_context, source_retry_allowed, source_route_fingerprint
from src.agents.survey_agent.modules.fulltext_resolution import public_repository_route


class SourceRequestBudgetExceeded(RuntimeError):
    pass


def _page_metadata(html, url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    metadata = {}
    for tag in soup.find_all("meta"):
        name = str(tag.get("name") or tag.get("property") or "").lower()
        if name and tag.get("content"):
            metadata[name] = str(tag["content"])
    doi = normalize_doi(metadata.get("citation_doi") or metadata.get("dc.identifier", ""))
    if not doi.startswith("10."):
        doi = ""
    scholarly = bool(doi or metadata.get("citation_title") or metadata.get("citation_pmid"))
    abstract_node = soup.select_one("section.abstract, div.abstract, #abstract, #abstract1")
    abstract = abstract_node.get_text(" ", strip=True) if abstract_node else text(metadata.get("citation_abstract"))
    pdf = urljoin(url, metadata["citation_pdf_url"]) if metadata.get("citation_pdf_url") else ""
    version = text(metadata.get("citation_version") or metadata.get("version"))
    download_urls = []
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or node.get_text())
            records = data if isinstance(data, list) else [data]
            for item in records:
                if not isinstance(item, Mapping):
                    continue
                version = version or text(item.get("version"))
                if item.get("@type") in {"ScholarlyArticle", "MedicalScholarlyArticle"}:
                    scholarly = True
                    abstract = abstract or text(item.get("abstract"))
                for distribution in item.get("distribution", []) if isinstance(item.get("distribution"), list) else [item.get("distribution")]:
                    if isinstance(distribution, Mapping) and distribution.get("contentUrl"):
                        download_urls.append(urljoin(url, distribution["contentUrl"]))
        except (TypeError, ValueError):
            pass
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"])
        if re.search(r"\.(?:csv|tsv|zip|hdf5|h5|parquet|tar\.gz|nc)(?:\?|$)", href, re.I):
            download_urls.append(href)
    for node in soup.select("script, style, nav, footer, header, aside, form"):
        node.decompose()
    article = soup.select_one("article, main, #maincontent, .article-body") or soup.body or soup
    body = article.get_text("\n", strip=True)
    return {"doi": doi, "pmid": text(metadata.get("citation_pmid")), "pmcid": text(metadata.get("citation_pmcid")),
            "abstract": abstract, "pdf_url": pdf, "version": version,
            "scholarly": scholarly, "title": text(metadata.get("citation_title")),
            "has_article_body": soup.select_one("article, .article-body, .fulltext-view") is not None,
            "download_urls": list(dict.fromkeys(download_urls))[:20], "content": body}


class SourceReader:
    def __init__(self, manager, work_dir, *, session=None, reserve_request=None, max_seconds=180):
        self.manager, self.root = manager, Path(work_dir).resolve()
        self.session = session or requests.Session()
        self.reserve_request = reserve_request
        self.max_seconds = min(600, max(1, max_seconds))
        self.source_attempts = []

    def _get(self, url, *, started, request_limit, json_response=False):
        # Redirects count as real requests. No unbounded hidden redirect loop.
        for _ in range(4):
            remaining = self.max_seconds - (time.monotonic() - started)
            if remaining <= 0 or request_limit[0] <= 0 or (self.reserve_request and not self.reserve_request("http")):
                self.source_attempts.append({"url": url, "status": "budget_exhausted"})
                raise SourceRequestBudgetExceeded("Source acquisition request/time budget exhausted")
            request_limit[0] -= 1
            if self.reserve_request is None:
                from .adaptive_search import charge_acquisition_http
                try:
                    charge_acquisition_http()
                except RuntimeError:
                    self.source_attempts.append({"url": url, "status": "budget_exhausted"})
                    raise
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Invalid source URL")
            try:
                response = self.session.get(url, timeout=(min(5, remaining), min(20, remaining)),
                                            allow_redirects=False, stream=True,
                                            headers={"User-Agent": "QwenSci-SourceReader/1.0 (research source acquisition)"})
            except requests.RequestException:
                self.source_attempts.append({"url": url, "status": "network_error"})
                raise
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                status = ("access_denied" if response.status_code in {401, 403} else "not_found" if response.status_code == 404
                          else "rate_limited" if response.status_code == 429 else "http_error" if response.status_code >= 400 else "response")
                self.source_attempts.append({"url": url, "status": status, "http_status": response.status_code})
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if not json_response and "pdf" in content_type:
                    return {"url": url, "pdf_url": url}
                data = bytearray()
                try:
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > 4_000_000 or time.monotonic() - started > self.max_seconds:
                            self.source_attempts.append({"url": url, "status": "budget_exhausted"})
                            raise SourceRequestBudgetExceeded("Source page exceeds byte/time budget")
                except requests.RequestException:
                    self.source_attempts.append({"url": url, "status": "network_error"})
                    raise
                encoding = response.encoding or "utf-8"
                body = bytes(data).decode(encoding, errors="replace")
                return {"url": url, "body": json.loads(body) if json_response else body,
                        "content_type": content_type, "http_status": response.status_code}
            finally:
                response.close()
        raise ValueError("Source redirect limit reached")

    def _resolve_identity(self, paper, *, started, request_limit, issues):
        def fetch(url):
            return self._get(url, started=started, request_limit=request_limit, json_response=True)["body"]

        try:
            metadata = resolve_biomedical_metadata(paper, fetch)
            for key, value in metadata.items():
                if key in {"externalIds"}:
                    paper[key] = {**paper.get(key, {}), **value}
                elif key in {"identity_provenance", "openalex_oa_locations"}:
                    paper[key] = [*paper.get(key, []), *(entry for entry in value if entry not in paper.get(key, []))]
                elif value and (not paper.get(key) or key in {"title", "metadata_identity_status"}):
                    paper[key] = value
        except Exception as exc:
            issues.append({"step": "identifier_metadata", "error_type": type(exc).__name__})
            if isinstance(exc, ValueError) and str(exc).startswith("No metadata record matches"):
                self.source_attempts.append({"status": "identity_unresolved"})
            elif isinstance(exc, ValueError):
                self.source_attempts.append({"status": "invalid_metadata_response"})

    @staticmethod
    def _check_page_identity(paper, page, url):
        expected = biomedical_identity(paper)
        actual = biomedical_identity({"url": url, "doi": page["doi"], "pmid": page["pmid"], "pmcid": page["pmcid"]})
        if any(expected.get(key) and actual.get(key) and expected[key] != actual[key] for key in expected):
            raise ValueError("Source page identifiers conflict with the requested paper")
        if any(expected.values()) and not any(expected[key] and actual[key] for key in expected):
            raise ValueError("Source page does not confirm the requested scholarly identifiers")

    def _repository_content(self, paper, *, started, request_limit, issues):
        pmcid = source_identifiers(paper)["pmcid"]
        if pmcid:
            url = f"{EUROPE_PMC_API}/{pmcid}/fullTextXML"
            try:
                response = self._get(url, started=started, request_limit=request_limit)
                article = parse_repository_jats(response.get("body", ""), paper)
                raw_path = self.root / (str(paper["paperId"]) + ".jats.xml")
                raw_path.write_text(response["body"], encoding="utf-8")
                paper.update(raw_source_path=str(raw_path), raw_source_sha256=hashlib.sha256(response["body"].encode()).hexdigest())
                paper.setdefault("version", "open_access_repository")
                paper["source_article_type"] = article["article_type"]
                return article["content"], "fulltext_xml", response["url"]
            except Exception as exc:
                issues.append({"step": "repository_xml", "error_type": type(exc).__name__})
        urls = [paper["url"]] if paper.get("url") and public_repository_route(paper["url"]) else []
        if pmcid:
            urls.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/")
        for location in [*paper.get("oa_locations", []), *paper.get("openalex_oa_locations", [])]:
            if isinstance(location, Mapping):
                url = location.get("landing_url") or location.get("landing_page_url") or location.get("url")
                if url and public_repository_route(url) and url not in urls:
                    urls.append(url)
        seen = {attempt.get("url") for attempt in self.source_attempts}
        for url in [url for url in urls if url not in seen][:3]:
            try:
                response = self._get(url, started=started, request_limit=request_limit)
                if response.get("pdf_url"):
                    paper["openAccessPdf"] = {"url": response["pdf_url"]}
                    continue
                page = _page_metadata(response.get("body", ""), response["url"])
                self._check_page_identity(paper, page, response["url"])
                if not public_repository_route(response["url"]):
                    continue
                if page["pdf_url"]:
                    paper["openAccessPdf"] = {"url": page["pdf_url"]}
                if page["doi"] and not paper.get("doi"):
                    paper["doi"] = page["doi"]
                paper.setdefault("version", public_repository_route(response["url"])["version"])
                if page["scholarly"] and page["has_article_body"] and len(page["content"]) > max(2000, len(page["abstract"]) * 3):
                    return page["content"], "fulltext_html", response["url"]
            except Exception as exc:
                issues.append({"step": "repository_html", "error_type": type(exc).__name__})
        return "", "", ""

    def _cached_source(self, paper, checkpoint):
        try:
            current = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        requested_version = paper.get("version") or public_repository_route(paper.get("url", "")).get("version")
        if current.get("reading_status") == "completed":
            if not requested_version or requested_version == "unspecified" or current.get("version") == requested_version:
                return current
            current = {}
        expected = biomedical_identity(paper)
        if not any(expected.values()):
            return current
        for path in self.root.glob("*.source.json"):
            if path == checkpoint:
                continue
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if cached.get("reading_status") != "completed":
                continue
            actual = biomedical_identity(cached)
            shared = [key for key in expected if expected[key] and actual[key]]
            if requested_version and requested_version != "unspecified" and cached.get("version") != requested_version:
                continue
            if shared and all(expected[key] == actual[key] for key in shared):
                return {**cached, "reused_from": cached.get("paper_id")}
        return current

    def _probe_access(self, url, *, started, request_limit):
        """Verify a declared file endpoint without downloading a dataset."""
        for _ in range(3):
            remaining = self.max_seconds - (time.monotonic() - started)
            if remaining <= 0 or request_limit[0] <= 0 or (self.reserve_request and not self.reserve_request("http")):
                raise SourceRequestBudgetExceeded("Dataset access probe budget exhausted")
            request_limit[0] -= 1
            if self.reserve_request is None:
                from .adaptive_search import charge_acquisition_http
                charge_acquisition_http()
            response = self.session.get(url, timeout=(min(5, remaining), min(10, remaining)),
                                        stream=True, allow_redirects=False, headers={"Range": "bytes=0-1023"})
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                return {"url": url, "http_status": response.status_code, "content_type": content_type,
                        "status": "landing_page" if "text/html" in content_type else "accessible",
                        "content_length": response.headers.get("Content-Length", "")}
            finally:
                response.close()
        return {"url": url, "status": "redirect_limit"}

    def read(self, paper, *, prefer_fulltext=True, allow_abstract_fallback=True, max_source_chars=60000):
        paper = dict(paper)
        pid = str(paper.get("paperId") or paper.get("paper_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", pid):
            pid = "SRC" + hashlib.sha256(json.dumps(paper, sort_keys=True).encode()).hexdigest()[:24]
        self.root.mkdir(parents=True, exist_ok=True)
        checkpoint = self.root / (pid + ".source.json")
        access_context = source_access_context(self.manager)
        fingerprint = source_route_fingerprint(paper)
        self.source_attempts = []
        try:
            cached = self._cached_source(paper, checkpoint)
            if cached.get("reading_status") == "unavailable" and not source_retry_allowed(paper, cached, access_context):
                return {**cached, "retry_skipped": True}
            source = Path(cached.get("source_path", ""))
            if cached.get("reading_status") == "completed" and source.is_file() and source.resolve().is_relative_to(self.root):
                content = source.read_text(encoding="utf-8")
                if hashlib.sha256(content.encode()).hexdigest() == cached.get("content_sha256"):
                    used = content[:max(1000, max_source_chars)]
                    mode = cached.get("reading_mode", "").removesuffix("_excerpt")
                    if self.manager is not None:
                        self.manager.register_discovered_papers([{**paper,
                            **{key: cached[key] for key in ("doi", "pmid", "pmcid", "externalIds", "title", "authors", "year", "venue",
                                                          "identity_provenance", "version", "repository_id", "source_type", "access_urls", "access_status") if key in cached},
                            **({"abstract": content} if mode == "abstract" else {}),
                            "verified_source_path": str(source), "verified_source_sha256": cached["content_sha256"],
                            "verified_reading_mode": mode}])
                    result = {**cached, "paper_id": pid, "node_id": pid, "keynote": used, "used_chars": len(used),
                            "reading_mode": mode + ("_excerpt" if len(used) < len(content) else ""),
                            "reading_range": {"start": 0, "end": len(used), "total_chars": len(content)}}
                    if cached.get("reused_from"):
                        write_json_atomic(checkpoint, {key: value for key, value in result.items() if key != "keynote"})
                    return result
        except (OSError, ValueError, TypeError):
            pass
        issues, content, mode = [], "", ""
        source_url = text(paper.get("url"))
        source_type = paper.get("source_type") or "paper"
        started, request_limit = time.monotonic(), [6]
        ids = source_identifiers(paper)
        page = {}
        doi = normalize_doi(paper.get("doi") or (paper.get("externalIds") or {}).get("DOI"))
        api = getattr(self.manager, "openalex_api", None)
        if source_type in {"paper", "preprint"} and doi and api is not None and not paper.get("abstract"):
            try:
                resolved = api.get_paper_details("https://doi.org/" + doi)
                if isinstance(resolved, Mapping) and normalize_doi(resolved.get("doi") or (resolved.get("externalIds") or {}).get("DOI")) == doi:
                    for key in ("abstract", "authors", "year", "venue", "openAccessPdf", "openalex_oa_locations"):
                        if resolved.get(key) and not paper.get(key):
                            paper[key] = resolved[key]
                    paper["externalIds"] = {**resolved.get("externalIds", {}), **paper.get("externalIds", {})}
                    paper["metadata_identity_status"] = "doi_exact_match"
            except Exception as exc:
                issues.append({"step": "identity_metadata", "error_type": type(exc).__name__})
        if source_url and (source_type not in {"paper", "preprint"} or (str(pid).startswith("AS") and not paper.get("doi"))):
            try:
                host = (urlsplit(source_url).hostname or "").lower()
                if host == "github.com" and ids["repository"]:
                    repo = ids["repository"].removeprefix("github.com/")
                    response = self._get("https://api.github.com/repos/" + repo, started=started, request_limit=request_limit, json_response=True)
                    metadata = response["body"]
                    requested = text(paper.get("version"))
                    branch = requested if requested and requested != "unspecified" else text(metadata.get("default_branch"))
                    commit = self._get(f"https://api.github.com/repos/{repo}/commits/{branch}", started=started, request_limit=request_limit, json_response=True)["body"]
                    version = text(commit.get("sha"))
                    if not version:
                        raise ValueError("Repository commit identity missing")
                    readme = self._get(f"https://raw.githubusercontent.com/{repo}/{version}/README.md", started=started, request_limit=request_limit)
                    paper.update(version=version, repository_id="github.com/" + repo,
                                 access_urls=[f"https://github.com/{repo}/archive/{version}.zip"], access_status="repository_verified")
                    content, mode, source_url = readme.get("body", ""), "repository_readme", readme["url"]
                else:
                    response = self._get(source_url, started=started, request_limit=request_limit)
                    source_url = response["url"]
                    if response.get("pdf_url"):
                        paper["openAccessPdf"] = {"url": response["pdf_url"]}
                    elif "html" in response.get("content_type", "") or "<html" in response.get("body", "")[:1000].lower():
                        page = _page_metadata(response["body"], source_url)
                        self._check_page_identity(paper, page, source_url)
                        if page["title"]:
                            paper["title"] = page["title"]
                        if page["doi"] and not paper.get("doi"):
                            paper["doi"] = page["doi"]
                        if page["abstract"] and (page["scholarly"] or ids["pmcid"]):
                            paper["abstract"] = page["abstract"]
                        if page["pdf_url"]:
                            paper["openAccessPdf"] = {"url": page["pdf_url"]}
                        if not paper.get("version") or paper["version"] == "unspecified":
                            paper["version"] = page["version"] or public_repository_route(source_url).get("version", "")
                        if source_type in {"dataset", "code"}:
                            if not (ids["repository"] or paper.get("doi")):
                                raise ValueError("Dataset/software repository identity could not be verified")
                            paper.update(repository_id=ids["repository"] or paper["doi"], access_urls=page["download_urls"],
                                         access_status="download_links_declared" if page["download_urls"] else "landing_only")
                            access_checks = []
                            for access_url in page["download_urls"][:2]:
                                try:
                                    access_checks.append(self._probe_access(access_url, started=started, request_limit=request_limit))
                                except Exception as exc:
                                    access_checks.append({"url": access_url, "status": "unavailable", "error_type": type(exc).__name__})
                            paper["access_checks"] = access_checks
                            if any(check.get("status") == "accessible" for check in access_checks):
                                paper["access_status"] = "download_verified"
                            content, mode = page["content"], "repository_metadata"
                        elif source_type in {"policy", "standard", "documentation", "statistics"}:
                            content, mode = page["content"], "source_page"
                        elif (prefer_fulltext and urlsplit(source_url).hostname != "pubmed.ncbi.nlm.nih.gov" and page["has_article_body"]
                              and (ids["pmcid"] or page["scholarly"]) and len(page["content"]) > max(2000, len(page["abstract"]) * 3)):
                            content, mode = page["content"], "fulltext_html"
            except Exception as exc:
                issues.append({"step": "source_metadata", "error_type": type(exc).__name__})
        if (source_type in {"paper", "preprint"} and (ids["pmid"] or ids["pmcid"])
                and (not paper.get("doi") or not ids["pmcid"])):
            self._resolve_identity(paper, started=started, request_limit=request_limit, issues=issues)
        if not content and prefer_fulltext and source_type in {"paper", "preprint"}:
            paper["paperId"] = pid
            content, mode, repository_url = self._repository_content(paper, started=started, request_limit=request_limit, issues=issues)
            source_url = repository_url or source_url
        resolved_ids = source_identifiers(paper)
        paper["externalIds"] = {**paper.get("externalIds", {}),
                                **({"DOI": paper["doi"]} if paper.get("doi") else {}),
                                **({"PubMed": resolved_ids["pmid"]} if resolved_ids["pmid"] else {}),
                                **({"PMCID": resolved_ids["pmcid"]} if resolved_ids["pmcid"] else {})}
        if self.manager is not None:
            self.manager.register_discovered_papers([paper])
        if not content and prefer_fulltext and (source_type in {"paper", "preprint"} or paper.get("openAccessPdf")) and self.manager is not None:
            try:
                # PDF download and MinerU parsing retain their existing bounded
                # timeouts/retries and caches. A source-level request scope is
                # supplied by the shared runtime for exact HTTP accounting.
                content = self.manager.get_paper_raw_markdown(paper).strip()
                if content:
                    mode = "fulltext"
            except Exception as exc:
                issues.append({"step": "fulltext", "error_type": type(exc).__name__})
                report_loader = getattr(self.manager, "get_fulltext_acquisition_report", None)
                report = report_loader(pid) if callable(report_loader) else {}
                if isinstance(report, Mapping):
                    self.source_attempts.extend(report.get("attempts", []))
        if not content and allow_abstract_fallback and source_type in {"paper", "preprint"}:
            content = text(paper.get("abstract"))
            if not content and self.manager is not None:
                try:
                    _, content = self.manager.get_paper_title_abstract(pid)
                except Exception as exc:
                    issues.append({"step": "abstract", "error_type": type(exc).__name__})
            if content:
                mode = "abstract"
        base = {"paper_id": pid, "node_id": pid, "title": text(paper.get("title")),
                "doi": paper.get("doi", ""), "url": source_url, "authors": paper.get("authors", []),
                "year": paper.get("year"), "venue": paper.get("venue", ""),
                "source": paper.get("provider", "anysearch"), "source_type": source_type,
                "metadata_identity_status": paper.get("metadata_identity_status", "source_identifier" if any(ids.values()) else "source_page"),
                "externalIds": {**paper.get("externalIds", {}), **({"DOI": paper["doi"]} if paper.get("doi") else {})},
                "pmid": source_identifiers(paper)["pmid"], "pmcid": source_identifiers(paper)["pmcid"],
                "version": paper.get("version", "") or "unspecified",
                "repository_id": paper.get("repository_id", ""), "access_urls": paper.get("access_urls", []),
                "access_checks": paper.get("access_checks", []),
                "access_status": paper.get("access_status", "source_read" if content else "unavailable"),
                "fetched_at": datetime.now(timezone.utc).isoformat(), "reading_issues": issues,
                "discovery_provenance": paper.get("discovery_provenance", []),
                "identity_provenance": paper.get("identity_provenance", []), "source_attempts": self.source_attempts,
                **{key: paper[key] for key in ("raw_source_path", "raw_source_sha256", "source_article_type") if key in paper}}
        if not text(content):
            statuses = {attempt.get("status") for attempt in self.source_attempts} - {"response"}
            blocked = {"access_denied", "authentication_required", "not_found", "no_declared_pdf", "non_pdf",
                       "landing_recovery_not_permitted", "identity_unresolved"}
            retry = {"policy": "when_source_changes" if statuses and statuses <= blocked else "retry",
                     "route_fingerprint": fingerprint, "access_context_generation": access_context,
                     "reader_revision": SOURCE_READER_REVISION, "reasons": sorted(status for status in statuses if status)}
            result = {**base, "reading_status": "unavailable", "retry": retry}
        else:
            source_path = self.root / (pid + ".md")
            source_path.write_text(content, encoding="utf-8")
            used = content[:max(1000, int(max_source_chars))]
            result = {**base, "reading_status": "completed", "reading_mode": mode + ("_excerpt" if len(used) < len(content) else ""),
                      "source_path": str(source_path), "source_chars": len(content), "used_chars": len(used),
                      "reading_range": {"start": 0, "end": len(used), "total_chars": len(content)},
                      "content_sha256": hashlib.sha256(content.encode()).hexdigest()}
            if self.manager is not None:
                self.manager.register_discovered_papers([{**paper, "verified_source_path": str(source_path),
                    "verified_source_sha256": result["content_sha256"], "verified_reading_mode": mode}])
        write_json_atomic(checkpoint, result)
        return {**result, **({"keynote": used} if result["reading_status"] == "completed" else {})}
