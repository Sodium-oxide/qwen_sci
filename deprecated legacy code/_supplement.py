from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any
import ast
import json
import re
import time



def zhizhi_auto_supplement_blind_spots(
    *,
    project_id: str,
    coverage_diagnostic: dict[str, Any],
    providers: list[str],
    domain: str,
    use_llm: bool,
    max_branches: int = 3,
    per_branch_imports: int = 2,
) -> dict[str, Any]:
    try:
        from ._literature_import import extract_paper_keynote, import_literature_search_result, select_zhizhi_import_results
        from ._literature_search import search_literature_stratified
        from ._project import load_project
        from ._utils import clamp_int, normalize_space
    except ImportError:
        from _literature_import import extract_paper_keynote, import_literature_search_result, select_zhizhi_import_results
        from _literature_search import search_literature_stratified
        from _project import load_project
        from _utils import clamp_int, normalize_space
    blind_spots = coverage_diagnostic.get("blind_spots", [])
    selected: list[dict[str, Any]] = []
    for spot in blind_spots:
        if not isinstance(spot, dict):
            continue
        probe = spot.get("live_probe") if isinstance(spot.get("live_probe"), dict) else {}
        if int(probe.get("total_results") or 0) <= 0:
            continue
        query = normalize_space(str(spot.get("suggested_query") or spot.get("topic") or ""))
        if not query:
            continue
        selected.append({"topic": spot.get("topic"), "query": query, "live_probe_total": probe.get("total_results")})
        if len(selected) >= clamp_int(max_branches, 1, 8):
            break
    if not selected:
        return {"attempted": False, "reason": "no live-confirmed blind spots"}

    # Build set of existing PaperGraph titles for pre-filtering duplicates
    project = load_project(project_id)
    existing_titles: set[str] = set()
    for record in project.get("papergraph", []):
        if isinstance(record, dict):
            title = str(record.get("title") or "").strip().lower()
            if title and title != "unknown":
                existing_titles.add(title)

    imports: list[dict[str, Any]] = []
    branch_reports: list[dict[str, Any]] = []
    for branch in selected:
        query = str(branch.get("query") or "")
        try:
            payload = json.loads(
                search_literature_stratified(
                    query=query,
                    providers=providers,
                    max_results=max(6, per_branch_imports * 4),
                    domain=domain,
                    focus_branches=[query],
                    use_llm=use_llm,
                )
            )
            search_id = str(payload.get("search_id") or "")
            results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
            selected_results = select_zhizhi_import_results(results, per_branch_imports)[0]
            branch_imports: list[dict[str, Any]] = []
            for result in selected_results[:per_branch_imports]:
                # Pre-filter: skip if title already exists in PaperGraph
                result_title = str(result.get("title") or "").strip().lower()
                if result_title and result_title in existing_titles:
                    branch_imports.append(
                        {
                            "result_index": result.get("result_index"),
                            "title": result.get("title"),
                            "status": "pre_filtered_duplicate",
                        }
                    )
                    continue
                try:
                    imported = json.loads(
                        import_literature_search_result(
                            project_id,
                            search_id,
                            int(result.get("result_index") or 0),
                            use_llm=use_llm,
                        )
                    )
                    record = imported.get("record") or imported.get("existing_record") or {}
                    # Track newly imported title to avoid re-import within this loop
                    new_title = str(record.get("title") or "").strip().lower()
                    if new_title:
                        existing_titles.add(new_title)
                    branch_imports.append(
                        {
                            "result_index": result.get("result_index"),
                            "paper_id": record.get("paper_id"),
                            "title": record.get("title"),
                            "status": imported.get("status"),
                        }
                    )
                    if record.get("paper_id"):
                        try:
                            extract_paper_keynote(project_id, paper_id=str(record.get("paper_id")), use_llm=use_llm)
                        except Exception:
                            pass
                except Exception as exc:
                    branch_imports.append({"result_index": result.get("result_index"), "status": "import_failed", "error": str(exc)})
            imports.extend(branch_imports)
            branch_reports.append(
                {
                    "topic": branch.get("topic"),
                    "query": query,
                    "search_id": search_id,
                    "total_results": payload.get("total_results"),
                    "imports": branch_imports,
                }
            )
        except Exception as exc:
            branch_reports.append({"topic": branch.get("topic"), "query": query, "status": "search_failed", "error": str(exc)})
    return {
        "attempted": True,
        "branches_attempted": len(selected),
        "imports": imports,
        "branches": branch_reports,
        "policy": "auto-supplement only live-confirmed blind spots; cap branches/imports to control API and token budget",
    }

def zhizhi_supplement_from_audit(
    *,
    project_id: str,
    audit_report: dict[str, Any],
    hypothesis_text: str,
    providers: list[str] | None = None,
    max_claims: int = 2,
    per_claim_imports: int = 1,
    use_llm: bool = True,
) -> dict[str, Any]:
    try:
        from ._literature_import import extract_paper_keynote, import_literature_search_result, select_zhizhi_import_results
        from ._literature_search import search_literature_stratified
        from ._project import default_literature_providers, load_project, save_project
        from ._utils import clamp_int, normalize_space
        from ._verification import yanzhen_unsupported_claims
    except ImportError:
        from _literature_import import extract_paper_keynote, import_literature_search_result, select_zhizhi_import_results
        from _literature_search import search_literature_stratified
        from _project import default_literature_providers, load_project, save_project
        from _utils import clamp_int, normalize_space
        from _verification import yanzhen_unsupported_claims
    claims = audit_report.get("unsupported_claims", []) if isinstance(audit_report.get("unsupported_claims"), list) else []
    if not claims:
        return {"attempted": False, "reason": "no unsupported claims from YanZhen"}
    project = load_project(project_id)
    domain = str(project.get("domain") or "")
    selected_providers = providers or default_literature_providers(query=f"{domain} {hypothesis_text}")
    selected_claims = [normalize_space(str(claim)) for claim in claims if normalize_space(str(claim))][: clamp_int(max_claims, 1, 5)]
    if not selected_claims:
        return {"attempted": False, "reason": "unsupported claims were empty after normalization"}
    imports: list[dict[str, Any]] = []
    claim_reports: list[dict[str, Any]] = []
    for claim in selected_claims:
        query = build_audit_supplement_query(domain, hypothesis_text, claim)
        try:
            payload = json.loads(
                search_literature_stratified(
                    query=query,
                    providers=selected_providers,
                    max_results=max(6, per_claim_imports * 5),
                    domain=domain,
                    focus_branches=[claim],
                    use_llm=use_llm,
                )
            )
            search_id = str(payload.get("search_id") or "")
            results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
            relevance_reports = [
                {
                    "result_index": item.get("result_index"),
                    "title": item.get("title"),
                    "relevance_gate": audit_supplement_candidate_relevance(item, claim, domain, hypothesis_text),
                }
                for item in results[:12]
                if isinstance(item, dict)
            ]
            gated_results = [
                item
                for item in results
                if isinstance(item, dict)
                and audit_supplement_candidate_relevance(item, claim, domain, hypothesis_text).get("pass")
            ]
            selected_results = select_zhizhi_import_results(gated_results, per_claim_imports)[0] if gated_results else []
            claim_imports: list[dict[str, Any]] = []
            for result in selected_results[:per_claim_imports]:
                try:
                    relevance_gate = audit_supplement_candidate_relevance(result, claim, domain, hypothesis_text)
                    imported = json.loads(
                        import_literature_search_result(
                            project_id,
                            search_id,
                            int(result.get("result_index") or 0),
                            use_llm=use_llm,
                        )
                    )
                    record = imported.get("record") or imported.get("existing_record") or {}
                    item = {
                        "claim": claim,
                        "query": query,
                        "result_index": result.get("result_index"),
                        "paper_id": record.get("paper_id"),
                        "title": record.get("title"),
                        "status": imported.get("status"),
                        "relevance_gate": relevance_gate,
                    }
                    claim_imports.append(item)
                    imports.append(item)
                    if record.get("paper_id"):
                        try:
                            extract_paper_keynote(project_id, paper_id=str(record.get("paper_id")), use_llm=use_llm)
                        except Exception:
                            pass
                except Exception as exc:
                    claim_imports.append({"claim": claim, "query": query, "status": "import_failed", "error": str(exc)})
            if not claim_imports:
                claim_imports.append(
                    {
                        "claim": claim,
                        "query": query,
                        "status": "no_relevance_pass",
                        "reason": "Search returned candidates, but none matched the unsupported causal link closely enough to import.",
                    }
                )
            claim_reports.append(
                {
                    "claim": claim,
                    "query": query,
                    "search_id": search_id,
                    "total_results": payload.get("total_results"),
                    "relevance_reports": relevance_reports,
                    "imports": claim_imports,
                }
            )
        except Exception as exc:
            claim_reports.append({"claim": claim, "query": query, "status": "search_failed", "error": str(exc)})
    report = {
        "attempted": True,
        "trigger": "yanzhen_unsupported_claims",
        "claims_attempted": len(selected_claims),
        "providers": selected_providers,
        "imports": imports,
        "claims": claim_reports,
        "policy": "targeted evidence completion only; capped by unsupported-claim count to avoid broad rescans",
    }
    project = load_project(project_id)
    project.setdefault("audit_triggered_literature_supplements", []).append(report)
    project["updatedAt"] = time.time()
    save_project(project)
    return report

def extract_academic_keyword(text: str, *, max_keywords: int = 8) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, unique_preserve_order
    """Extract meaningful academic keyword phrases from text for literature search.

    Unlike query_terms (single tokens), this captures compound technical phrases
    such as "structural equation modeling", "cathode electrolyte interphase",
    "co-precipitation", etc.  It strips causal connectors and generic verbs
    so the output is suitable as academic database search keywords.
    """
    lower = normalize_space(str(text or "")).lower()
    connector_pattern = r"\s*(?:->|→|leads?\s+to|causes?|drives?|because|therefore|results?\s+in|enables?|improves?|enhances?|affects?|influences?|promotes?|triggers?|yields?|produces?|generates?|facilitates?)\s*"
    segments = re.split(connector_pattern, lower, flags=re.IGNORECASE)
    stopword_set = {
        "a", "an", "and", "are", "as", "at", "by", "for", "from", "in", "into",
        "of", "on", "or", "the", "to", "with", "this", "that", "which", "where",
        "when", "while", "can", "may", "will", "should", "could", "would", "been",
        "be", "is", "was", "were", "has", "have", "had", "do", "does", "did",
        "not", "no", "but", "if", "then", "than", "so", "its", "it", "their",
        "we", "our", "these", "those", "also", "more", "most", "very", "such",
        # Template/hypothesis boilerplate that is NOT academic search content
        "retested", "retest", "matched", "under", "reveal", "exposes", "boundary",
        "claims", "claim", "predicted", "predict", "prediction", "hypothesis",
        "intervention", "mechanism", "causal", "link", "unsupported",
        "conditions", "condition", "scenarios", "scenario", "regime",
        "observed", "observable", "controllable", "validity", "stated",
        "detected", "unresolved", "contradiction", "migration",
    }
    keywords: list[str] = []
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        # Extract compound technical phrases (2-4 word sequences of substantive terms)
        words = [w for w in re.findall(r"[a-z][a-z0-9_-]{1,}", segment) if w not in stopword_set and len(w) > 2]
        # Add individual substantive words as single-keyword fallbacks
        for word in words:
            if len(word) > 3:
                keywords.append(word)
        # Add 2-word compound phrases when adjacent substantive words exist
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i + 1]}"
            if len(phrase) > 7:
                keywords.append(phrase)
    return unique_preserve_order(keywords)[:max_keywords]

def strip_audit_meta_language(text: str) -> str:
    """Remove internal audit/report labels that should never appear in academic search queries.

    YanZhen and DuZhi produce meta-labels like 'Unsupported causal link:', 'decisive prediction',
    'conflicting claims' etc.  These are pipeline-internal jargon, not research keywords.
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    clean = normalize_space(str(text or ""))
    # Strip common audit prefixes (case-insensitive)
    prefixes = [
        r"^unsupported causal link:\s*",
        r"^potential unresolved contradiction:\s*",
        r"^cross-domain migration detected:\s*",
        r"^no observable[,\s]+measurement[,\s]+benchmark[,\s]+or validation readout is stated\.?\s*",
        r"^no controllable\s*(?:variable|variables)?.*?stated\.?\s*",
        r"^no validity.*?stated\.?\s*",
        r"^no cited\s*(?:evidence|support|reference).*?:\s*",
        r"^low lexical overlap:\s*",
        r"^method family\s*'[^']*'\s*applied to scenario family\s*'[^']*'\s*without explicit bridging evidence[:.]?\s*",
    ]
    for pat in prefixes:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    # Remove inline audit labels that appear anywhere in the text
    inline_labels = [
        r"\bunsupported causal link\b",
        r"\bdecisive prediction\b",
        r"\bconflicting claims\b",
        r"\bcawm\s*(?:risk|detected|level)\b",
        r"\bmechanism[\s-]?stress intervention\b",
        r"\bregime\s*shift\b",
    ]
    for pat in inline_labels:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    return normalize_space(clean)


def build_audit_supplement_query(domain: str, hypothesis_text: str, unsupported_claim: str) -> str:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    """Build a keyword-driven academic search query for supplementing unsupported claims.

    Query structure (keyword priority):
      [domain_context] [causal_node_keywords] [method_keywords]
    No fixed boilerplate suffix — every term comes from the actual research content.
    Audit meta-language (e.g. 'unsupported causal link', 'conflicting claims') is stripped
    before keyword extraction so it never pollutes the search query.
    """
    # Strip audit meta-language from all inputs
    clean_claim = strip_audit_meta_language(unsupported_claim)
    clean_hypothesis = strip_audit_meta_language(hypothesis_text)
    # Layer 1: Domain context keywords (anchor the search to the right field)
    domain_kws = extract_academic_keyword(domain, max_keywords=3)
    # Layer 2: Causal-link node keywords (the key concepts at each end of the causal chain)
    causal_kws = extract_academic_keyword(clean_claim, max_keywords=5)
    # Layer 3: Method/mechanism keywords from the hypothesis (filter domain overlap)
    hypothesis_kws = extract_academic_keyword(clean_hypothesis, max_keywords=6)
    domain_set = set(domain_kws)
    hypothesis_kws = [kw for kw in hypothesis_kws if kw not in domain_set][:4]
    # Assemble: domain first (field anchor), then causal nodes, then method terms
    prioritized = unique_preserve_order(domain_kws + causal_kws + hypothesis_kws)
    query = " ".join(prioritized[:14])
    if not query:
        query = normalize_space(f"{domain} {clean_claim}")[:240]
    return normalize_space(query)

def causal_link_terms(text: str) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, unique_preserve_order
    clean = normalize_space(str(text or ""))
    clean = re.sub(r"^unsupported causal link:\s*", "", clean, flags=re.IGNORECASE)
    parts = re.split(r"\s*(?:->|→|leads to|causes|drives|because|therefore)\s*", clean, flags=re.IGNORECASE)
    terms: list[str] = []
    for part in parts:
        terms.extend(query_terms(part)[:6])
    return unique_preserve_order(terms)[:12]

def audit_supplement_candidate_relevance(result: dict[str, Any], claim: str, domain: str, hypothesis_text: str) -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, science_term_in_text
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, science_term_in_text
    text = normalize_space(
        " ".join(str(result.get(key) or "") for key in ("title", "abstract", "venue", "citation", "method", "scenario", "benchmark"))
    ).lower()
    # Single-token terms for broad matching
    claim_terms = set(query_terms(" ".join(causal_link_terms(claim)) or claim))
    domain_terms = set(query_terms(domain))
    hypothesis_terms = set(query_terms(hypothesis_text))
    # Compound academic keyword phrases for precise matching
    claim_keywords = set(extract_academic_keyword(claim, max_keywords=6))
    domain_keywords = set(extract_academic_keyword(domain, max_keywords=4))
    if not text:
        return {"pass": False, "score": 0.0, "reason": "candidate has no textual metadata"}
    claim_hits = {term for term in claim_terms if science_term_in_text(term, text)}
    domain_hits = {term for term in domain_terms if science_term_in_text(term, text)}
    hypothesis_hits = {term for term in hypothesis_terms if science_term_in_text(term, text)}
    # Compound phrase matches (higher signal than single tokens)
    claim_kw_hits = {kw for kw in claim_keywords if kw in text}
    domain_kw_hits = {kw for kw in domain_keywords if kw in text}
    score = 0.0
    # Token-level scoring (broad coverage)
    score += 0.40 * (len(claim_hits) / max(1, min(len(claim_terms), 6)))
    score += 0.20 * (len(domain_hits) / max(1, min(len(domain_terms), 5)))
    score += 0.15 * (len(hypothesis_hits) / max(1, min(len(hypothesis_terms), 8)))
    # Compound-keyword bonus (high-signal phrase matches)
    kw_bonus = 0.25 * min(1.0, (len(claim_kw_hits) + len(domain_kw_hits)) / max(1, min(len(claim_keywords), 4)))
    score += kw_bonus
    score = round(min(1.0, score), 3)
    # Pass: need at least one token-level OR keyword-level claim hit, plus minimum score
    has_claim_signal = bool(claim_hits) or bool(claim_kw_hits)
    has_domain_signal = bool(domain_hits) or bool(domain_kw_hits)
    passes = has_claim_signal and (score >= 0.15 or has_domain_signal)
    return {
        "pass": passes,
        "score": score,
        "claim_hits": sorted(claim_hits)[:8],
        "claim_keyword_hits": sorted(claim_kw_hits)[:6],
        "domain_hits": sorted(domain_hits)[:8],
        "domain_keyword_hits": sorted(domain_kw_hits)[:4],
        "hypothesis_hits": sorted(hypothesis_hits)[:8],
        "reason": "requires at least one causal-claim term or keyword hit plus domain/hypothesis support",
    }

