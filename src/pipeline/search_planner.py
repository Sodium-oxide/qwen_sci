"""Scientific information needs and executable, capability-checked search plans."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any

from .anysearch import identity_keys, text
from .search_capabilities import validate_route


SCIENTIFIC_FIELDS = ("original_request", "topic", "research_object", "objective", "research_objective",
                     "normalized_objective", "research_brief", "current_subproblem", "sub_hypothesis",
                     "research_question", "question", "title", "target_system", "scientific_scope", "scientific_constraints",
                     "statement", "description", "mechanism", "conditions", "outcomes", "data_context",
                     "evidence_gaps", "open_questions", "missing_information", "core_entities", "synonyms")
CANDIDATE_FIELDS = ("title", "central_hypothesis", "hypothesis", "mechanism", "mechanism_or_relation",
                    "candidate_mechanism", "expected_mechanism", "evidence_gaps", "open_questions")
NEED_KINDS = {"overview", "mechanism", "method_transfer", "data_code", "citation", "official", "latest"}
SOURCE_TYPES = {"paper", "preprint", "dataset", "code", "policy", "standard", "documentation", "statistics"}
STOPWORDS = set("a an the of to in on for and or with by from as is are was were be been being this that these those it its our we you your study research investigate identify understand important how what which into may can could should using use explore investigate including has have effects interest several such new approach based topic request please need there their".split())


def _strings(value, *, depth=0):
    if depth > 3:
        return []
    if isinstance(value, str):
        return [value.strip()[:3000]] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [s for item in value[:16] for s in _strings(item, depth=depth + 1)]
    if isinstance(value, Mapping):
        # Explicitly named scientific fields only; never serialize arbitrary
        # evaluator, rubric, scoring or adjudication dictionaries.
        return [s for key in (*SCIENTIFIC_FIELDS, "name", "label", "entity", "term") if key in value
                for s in _strings(value[key], depth=depth + 1)]
    return []


def scientific_input(task: Mapping, *, topic="", project_context=None, candidates=(), known_references=()) -> dict:
    task = task if isinstance(task, Mapping) else {}
    context = project_context if isinstance(project_context, Mapping) else {}
    result = {key: _strings(task[key]) for key in SCIENTIFIC_FIELDS if key in task}
    result["topic"] = text(topic)[:10000]
    result["context"] = {key: _strings(context[key]) for key in SCIENTIFIC_FIELDS if key in context}
    identity = context.get("research_identity")
    if isinstance(identity, Mapping):
        for key in SCIENTIFIC_FIELDS:
            if key in identity and not result["context"].get(key):
                result["context"][key] = _strings(identity[key])
    taxonomy = context.get("discovery_taxonomy")
    taxonomy = taxonomy if isinstance(taxonomy, Mapping) else {}
    result["disciplines"] = list(dict.fromkeys([
        *_strings(context.get("research_domains", [])),
        *(value for key in ("declared_domain", "domain", "primary_discipline", "secondary_disciplines")
          for value in _strings(context.get(key, []))),
        *(value for key in ("primary_discipline", "secondary_disciplines") for value in _strings(taxonomy.get(key, []))),
    ]))
    result["candidates"] = [
        {key: _strings(item[key]) for key in CANDIDATE_FIELDS if key in item}
        for item in candidates if isinstance(item, Mapping)
        and item.get("maturity_status") != "rejected" and item.get("independence_status") != "collapsed_duplicate"
    ][:8]
    result["known_literature"] = [
        {key: item[key][:2000] if isinstance(item[key], str) else item[key]
         for key in ("paper_id", "paperId", "title", "doi", "abstract", "summary", "insight", "reading_mode")
         if key in item and isinstance(item[key], (str, int))}
        for item in known_references if isinstance(item, Mapping)
    ][:30]
    return result


def compact_query(value: str, *, max_words=16, max_chars=180) -> str:
    value = " ".join(text(value).split())
    tokens = re.findall(r"[\wα-ωΑ-Ω]+(?:[-+./][\wα-ωΑ-Ω]+)*", value, re.U)
    meaningful = [token for token in tokens if token.casefold() not in STOPWORDS]
    if re.search(r"[\u4e00-\u9fff]", value):
        meaningful = [re.sub(r"^(?:请|研究课题[：:]|课题[：:])", "", token) for token in meaningful]
    return " ".join(dict.fromkeys(meaningful))[:max_chars] if len(meaningful) <= max_words else " ".join(dict.fromkeys(meaningful[:max_words]))[:max_chars]


def _catalog_view(catalog):
    return {tag: {"description": item.get("description", ""),
                  "params": {key: {k: v for k, v in spec.items() if k in {"description", "required", "type", "enum"}}
                             for key, spec in item.get("params", {}).items() if isinstance(spec, Mapping)}}
            for tag, item in catalog.get("channels", {}).items()}


def json_object(raw: Any) -> dict:
    if isinstance(raw, Mapping):
        return dict(raw)
    value = text(raw)
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value)
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


def request_key(route: Mapping) -> str:
    return hashlib.sha256(json.dumps({key: route.get(key, {} if key == "params" else "")
                                     for key in ("provider", "tag", "params", "query", "result_limit")},
                                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def normalize_route(raw: Mapping, catalog: Mapping, *, default_query="") -> dict:
    provider = text(raw.get("provider")) or "anysearch"
    query = text(raw.get("query") or default_query)
    if not query or len(query) > 240 or len(query.split()) > 24:
        raise ValueError("Queries must contain a short object/relation/method/condition phrase")
    if provider == "openalex":
        if raw.get("params"):
            raise ValueError("Shared OpenAlex route accepts only a keyword query")
        return {"provider": provider, "query": query, "params": {}, "tag": "", "reason": text(raw.get("reason"))}
    if provider != "anysearch":
        raise ValueError("Unsupported search provider")
    tag, params = text(raw.get("tag")) or "academic.search", raw.get("params", {})
    validate_route(catalog, tag, params)
    return {"provider": provider, "query": query, "tag": tag, "params": dict(params), "reason": text(raw.get("reason"))}


class ScientificSearchPlanner:
    def __init__(self, catalog, *, llm=None, max_needs=5, repair_attempts=1, budget=None, save_raw=None):
        self.catalog, self.llm, self.budget, self.save_raw = catalog, llm, budget, save_raw
        self.max_needs = min(8, max(1, max_needs))
        self.repair_attempts = min(2, max(0, repair_attempts))
        self.issues = []

    def call(self, prompt, *, label):
        if not callable(self.llm) or (self.budget and not self.budget("model")):
            raise RuntimeError("Planner model unavailable or budget exhausted")
        raw = self.llm(prompt)
        if self.save_raw:
            self.save_raw(label, raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))
        return json_object(raw)

    def plan(self, inputs, *, phase="initial"):
        prompt = (
            "You plan scientific information acquisition. Read only the scientific task and literature below. "
            "Decompose it into concrete information needs; a task may span several disciplines. Keep the original research object. "
            "Separate overview, mechanism, transfer of methods from adjacent disciplines, datasets/code, citations, latest work, and official sources as relevant. "
            "Use only real channels and parameters from the capability catalog. OpenAlex keyword search is also available. "
            "For each need choose 1-2 initial probe routes, short executable queries (object + relation/method + condition, <=16 words), "
            "and 1-3 alternative synonym/relaxed/adjacent-discipline queries as separate strings. Never paste a long task description into a query. "
            "Citation routes require a real persistent identifier from the literature. Unknown disciplines start with general academic probes. "
            "Save a scientific reason, target subproblem, expected source types, and per-need request/reading budgets. "
            "Discovery snippets cannot support scientific claims. Return only JSON matching this example: "
            '{"needs":[{"id":"N1","kind":"mechanism","purpose":"find experimental mechanism evidence",'
            '"target_subproblem":"scientific question","disciplines":["domain"],"expected_source_types":["paper"],'
            '"object_terms":["specific object"],"coverage_terms":["condition or comparison"],'
            '"queries":["short query","alternative query"],"budget":{"requests":4,"successful_reads":2},'
            '"routes":[{"provider":"anysearch","tag":"academic.search","params":{},"query":"short query",'
            '"reason":"scientific selection reason"}]}]}\n'
            + "Scientific task=" + json.dumps(inputs, ensure_ascii=False)
            + "\nCapabilities=" + json.dumps(_catalog_view(self.catalog), ensure_ascii=False)
        )
        error = ""
        for attempt in range(self.repair_attempts + 1):
            try:
                payload = self.call(prompt if not attempt else prompt + "\nPrevious plan failed validation: " + error + ". Return corrected JSON.", label=f"plan-{attempt}")
                needs = self.validate_plan(payload)
                return {"schema_version": 2, "source": "model", "phase": phase, "needs": needs, "issues": self.issues}
            except Exception as exc:
                error = str(exc)[:500] if isinstance(exc, ValueError) else type(exc).__name__
                self.issues.append({"step": "plan", "attempt": attempt + 1, "reason": error})
                if not callable(self.llm):
                    break
        return {"schema_version": 2, "source": "deterministic_fallback", "phase": phase,
                "needs": self.fallback(inputs), "issues": self.issues}

    def validate_plan(self, payload):
        rows = payload.get("needs")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Plan needs a nonempty needs array")
        needs, seen = [], set()
        for i, raw in enumerate(rows[:self.max_needs]):
            if not isinstance(raw, Mapping) or raw.get("kind") not in NEED_KINDS:
                raise ValueError("Invalid information need kind")
            types = raw.get("expected_source_types")
            if not isinstance(types, list) or not types or any(t not in SOURCE_TYPES for t in types):
                raise ValueError("Invalid expected source types")
            purpose = text(raw.get("purpose"))
            question = text(raw.get("target_subproblem"))
            if not purpose or not question:
                raise ValueError("Each need requires a purpose and target subproblem")
            routes = [normalize_route(route, self.catalog) for route in raw.get("routes", [])[:2] if isinstance(route, Mapping)]
            if not routes:
                raise ValueError("Each need requires an executable route")
            queries = [text(q) for q in raw.get("queries", []) if isinstance(q, str) and text(q)]
            if any(len(q) > 240 or len(q.split()) > 24 for q in queries):
                raise ValueError("Alternative queries must be short")
            number = str(raw.get("id") or f"N{i + 1}")
            if number in seen:
                raise ValueError("Duplicate information need id")
            seen.add(number)
            limits = raw.get("budget") if isinstance(raw.get("budget"), Mapping) else {}
            needs.append({"id": number, "kind": raw["kind"], "purpose": purpose[:1000], "target_subproblem": question[:2000],
                          "disciplines": _strings(raw.get("disciplines", [])), "expected_source_types": types,
                          "object_terms": _strings(raw.get("object_terms", [])), "coverage_terms": _strings(raw.get("coverage_terms", [])),
                          "queries": list(dict.fromkeys([*(route["query"] for route in routes), *queries]))[:6], "routes": routes,
                          "budget": {"requests": min(12, max(1, int(limits.get("requests", 4)))),
                                     "successful_reads": min(8, max(1, int(limits.get("successful_reads", 2))))}})
        return needs

    def fallback(self, inputs):
        context = inputs.get("context", {})
        entities = context.get("core_entities", []) or inputs.get("core_entities", [])
        subject = compact_query(" ".join(entities), max_words=8) or compact_query(inputs.get("topic", ""), max_words=10)
        request = " ".join(inputs.get("original_request", []))
        subject = subject or compact_query(request, max_words=10)
        specifications = []
        candidates = inputs.get("candidates", [])
        if candidates:
            for candidate in candidates:
                words = [s for key in CANDIDATE_FIELDS for s in candidate.get(key, [])]
                if words:
                    specifications.append(("mechanism", compact_query(" ".join(words)), ["paper"], words))
        else:
            specifications.append(("overview", subject, ["paper"], []))
            for discipline in inputs.get("disciplines", [])[:3]:
                specifications.append(("method_transfer", compact_query(subject + " " + discipline + " methods"), ["paper"], [discipline]))
            gaps = inputs.get("missing_information", []) + inputs.get("evidence_gaps", []) + context.get("evidence_gaps", [])
            gaps += inputs.get("current_subproblem", [])
            for gap in gaps[:3]:
                specifications.append(("mechanism", compact_query(subject + " " + gap), ["paper"], [gap]))
            if re.search(r"dataset|benchmark|code|reproduc|数据集|代码|复现", request + inputs.get("topic", ""), re.I):
                specifications.append(("data_code", compact_query(subject + " dataset"), ["dataset", "code"], ["dataset"]))
        needs = []
        for i, (kind, query, types, terms) in enumerate(specifications[:self.max_needs]):
            if not query:
                continue
            tag = "academic.dataset" if kind == "data_code" and "academic.dataset" in self.catalog.get("channels", {}) else "academic.search"
            if tag not in self.catalog.get("channels", {}):
                routes = [{"provider": "openalex", "query": query, "params": {}, "tag": "", "reason": "Catalog unavailable; use configured scholarly provider"}]
            else:
                routes = [{"provider": "anysearch", "tag": tag, "params": {}, "query": query,
                           "reason": "Small general probe; use source themes to refine the next route"}]
            needs.append({"id": f"N{i + 1}", "kind": kind, "purpose": kind.replace("_", " "),
                          "target_subproblem": " ".join(terms) or subject, "disciplines": inputs.get("disciplines", []),
                          "expected_source_types": types, "object_terms": entities or [subject], "coverage_terms": terms,
                          "queries": list(dict.fromkeys([query, compact_query(subject + " " + (terms[0] if terms else "mechanism evidence"))])),
                          "routes": routes, "budget": {"requests": 4, "successful_reads": 2}})
        return needs

    def assess(self, need, papers):
        """Assess discovery relevance; this result is never scientific evidence."""
        rows = [{"id": p["paperId"], "title": p.get("title", ""), "url": p.get("url", ""),
                 "abstract": text(p.get("abstract"))[:2000], "discovery_snippet": text(p.get("discovery_snippet"))[:1000],
                 "source_type": p.get("source_type", "")} for p in papers[:10]]
        try:
            payload = self.call(
                "Assess DISCOVERY relevance to this scientific information need. Snippets are unverified navigation aids. "
                "Detect wrong same-name entities, off-topic pages, popular pages vs research, and covered question facets. "
                'Return only JSON {"items":[{"id":"provided id","relevant":true,"source_type":"paper|preprint|dataset|code|policy|standard|documentation|statistics|other",'
                '"covered_terms":["facet"],"reason":"why"}]}.\nNeed=' + json.dumps(need, ensure_ascii=False)
                + "\nCandidates=" + json.dumps(rows, ensure_ascii=False), label="assessment")
            values = payload.get("items")
            if not isinstance(values, list):
                raise ValueError("Missing assessment items")
            results = {v["id"]: v for v in values if isinstance(v, dict) and isinstance(v.get("relevant"), bool)
                       and v.get("source_type") in SOURCE_TYPES | {"other"} and v.get("id") in {p["paperId"] for p in papers}}
        except Exception:
            results = {}
        for paper in papers:
            pid = paper["paperId"]
            if pid in results:
                results[pid]["assessment_source"] = "model"
                continue
            title = text(paper.get("title")).casefold()
            haystack = title + " " + text(paper.get("abstract")).casefold() + " " + text(paper.get("discovery_snippet")).casefold()
            terms = [compact_query(t, max_words=6).casefold() for t in need.get("object_terms", [])]
            tokens = [word for term in terms for word in term.split() if len(word) > 2]
            relevant = not tokens or any(word in haystack for word in tokens)
            source_type = paper.get("source_type")
            if source_type not in SOURCE_TYPES:
                ids = paper.get("externalIds") or {}
                url = text(paper.get("url")).casefold()
                if any(h in url for h in ("github.com/", "gitlab.com/")):
                    source_type = "code"
                elif any(h in url for h in ("zenodo.org/", "figshare.com/", "datadryad.org/")):
                    source_type = "dataset"
                elif paper.get("doi") or paper.get("abstract") or ids.get("PMCID") or ids.get("ArXiv") or url.endswith(".pdf"):
                    source_type = "paper"
                elif re.search(r"blog|youtube|about.cbd|health.harvard|news/", url):
                    source_type = "other"
                else:
                    # A source page may expose scholarly citation metadata
                    # during acquisition. Unknown is allowed for one probe.
                    source_type = "paper" if "paper" in need["expected_source_types"] else "other"
            results[pid] = {"id": pid, "relevant": relevant, "source_type": source_type,
                            "covered_terms": [term for term in need.get("coverage_terms", []) if term.casefold() in haystack],
                            "assessment_source": "lexical_fallback", "reason": "Object terms and source identity metadata"}
        return results

    def adjust(self, need, metrics, previous, *, round_index):
        prompt = ("Choose ONE next small search probe for this scientific information need using actual probe outcomes. "
                  "Prioritize NEW relevant READABLE sources and uncovered question facets. HTTP success and result count alone are not progress. "
                  "For popular/wrong-entity pages clarify entity and restrict scholarly type; for few results replace synonyms, "
                  "relax conditions then year constraints or try adjacent discipline channels; for duplicates follow citations with real ids or change method. "
                  "For reading failure seek repositories/open access. Choose only real catalog tags and valid parameters. "
                  'Return JSON {"done":false,"reason":"specific adjustment reason","route":{"provider":"anysearch",'
                  '"tag":"academic.search","params":{},"query":"short query"}}, or {"done":true,"reason":"sufficient evidence"}.\n'
                  + "Need=" + json.dumps(need, ensure_ascii=False) + "\nOutcomes=" + json.dumps(metrics, ensure_ascii=False)
                  + "\nPrevious=" + json.dumps(previous, ensure_ascii=False)
                  + "\nCapabilities=" + json.dumps(_catalog_view(self.catalog), ensure_ascii=False))
        try:
            payload = self.call(prompt, label=f"adjust-{round_index}")
            if payload.get("done") is True:
                return None, text(payload.get("reason")) or "Planner found sufficient coverage"
            route = normalize_route(payload.get("route", {}), self.catalog)
            return route, text(payload.get("reason")) or "Adapt based on probe outcomes"
        except Exception:
            pass
        queries = need.get("queries", [])
        used_queries = {r.get("query") for r in previous}
        base = dict(need["routes"][0])
        query = next((q for q in queries if q not in used_queries), "")
        params = dict(base.get("params", {}))
        reason = "Try an alternative synonym or adjacent-method query"
        if metrics.get("new_relevant", 0) == 0 and metrics.get("duplicates", 0) and "academic.citation" in self.catalog.get("channels", {}):
            doi = next((p.get("doi") for r in previous for p in r.get("papers", []) if p.get("doi")), "")
            if doi:
                return {"provider": "anysearch", "tag": "academic.citation", "params": {"id": doi, "id_type": "doi", "op": "references" if round_index % 2 else "citations"},
                        "query": doi, "reason": "Trace a verified paper identity because discovery repeated existing records"}, "Trace citations after duplicates"
        if not query and any(key in params for key in ("year_from", "year_to")):
            params = {k: v for k, v in params.items() if k not in {"year_from", "year_to"}}
            query, reason = base["query"], "Broaden publication years after low evidence yield"
        if not query and metrics.get("read_successes", 0) == 0 and base.get("provider") == "anysearch":
            spec = self.catalog.get("channels", {}).get(base.get("tag"), {}).get("params", {})
            if "open_access" in spec and params.get("open_access") is not True:
                params["open_access"] = True
                query, reason = base["query"], "Seek accessible sources after acquisition failures"
        if not query:
            return None, "No unused validated alternative; preserve existing evidence"
        return {**base, "query": query, "params": params, "reason": reason}, reason
