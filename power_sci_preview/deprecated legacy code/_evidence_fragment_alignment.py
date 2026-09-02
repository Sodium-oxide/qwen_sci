"""Source-bound evidence-fragment alignment.

The current V2 path aligns bounded spans to the evidence slots declared by a
``ResearchQuestionContractV2``.  The historical causal-triad helpers remain
below only for quarantined V1 callers; a V2 contract never enters their
object/process/outcome scoring path.  This keeps measurement, theory,
boundary, data, benchmark, and translation questions from being coerced into
a causal edge merely because they are represented by source text.
"""
from __future__ import annotations

from hashlib import sha256
from threading import Lock
from typing import Any
import json
import re


EVIDENCE_FRAGMENT_ALIGNMENT_VERSION = "evidence_fragment_alignment_v5"
RESEARCH_QUESTION_SLOT_ALIGNMENT_VERSION = "research_question_slot_alignment_v2"
FOCAL_VARIABLE_SYNONYM_DICTIONARY_VERSION = "focal_variable_synonym_dictionary_v1"
_FOCAL_VARIABLE_SYNONYM_DICTIONARY_MAX_ENTRIES = 8

INPUT_OR_CONDITION_EVIDENCE = "INPUT_OR_CONDITION_EVIDENCE"
MECHANISM_LINK_EVIDENCE = "MECHANISM_LINK_EVIDENCE"
OUTCOME_EVIDENCE = "OUTCOME_EVIDENCE"
DIRECT_TRIADIC_EVIDENCE = "DIRECT_TRIADIC_EVIDENCE"
BOUNDARY_OR_NEGATIVE_EVIDENCE = "BOUNDARY_OR_NEGATIVE_EVIDENCE"
ADVERSE_OR_REVERSAL_EVIDENCE = "ADVERSE_OR_REVERSAL_EVIDENCE"
FOUNDATIONAL_BRIDGE = "FOUNDATIONAL_BRIDGE"
BACKGROUND_REVIEW = "BACKGROUND_REVIEW"

CAUSAL_EDGE_EVIDENCE_LANES = frozenset({
    INPUT_OR_CONDITION_EVIDENCE,
    MECHANISM_LINK_EVIDENCE,
    OUTCOME_EVIDENCE,
    DIRECT_TRIADIC_EVIDENCE,
    BOUNDARY_OR_NEGATIVE_EVIDENCE,
    ADVERSE_OR_REVERSAL_EVIDENCE,
})

_TOKEN_RE = re.compile(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{2,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?。；;])\s+")

# These are research-role words, not a domain blacklist.  They remain valid
# process, method, or outcome terms when the source also identifies a concrete
# object and causal relation.
_NON_DISCRIMINATIVE_OBJECT_TERMS = {
    "analysis", "approach", "data", "detector", "energy", "evidence", "experiment",
    "measurement", "method", "model", "monitoring", "observation", "performance",
    "prediction", "research", "result", "results", "science", "signal", "simulation",
    "study", "studies", "system", "technology", "yield",
    # These can be central scientific objects, but alone they are far too
    # portable across biology/computation to identify a sub-hypothesis.  They
    # remain usable when accompanied by a second project-specific anchor.
    "differentiation", "editing", "genome", "modeling",
}

# Field provenance is stricter than paper/object alignment.  These are
# grammatical glue and generic research-role labels: they may appear in a
# valid scientific phrase, but a single occurrence cannot prove that a
# particular causal field came from a source unit.  This list is deliberately
# discipline-neutral.  For example, ``thermal`` remains a useful modifier in
# an exact phrase, but the word alone cannot bind "thermal camera sensitivity"
# to an unrelated sentence about thermal transport.
_FIELD_MATCH_NON_DISCRIMINATIVE_TERMS = _NON_DISCRIMINATIVE_OBJECT_TERMS | {
    "a", "an", "and", "as", "at", "by", "change", "changes", "changing",
    "for", "from", "in", "into", "of", "on", "or", "the", "to", "under",
    "using", "via", "with", "within", "thermal",
}
_OPERATION_PREFIX_RE = re.compile(
    r"^(?:controlled\s+(?:variation|change)\s+of|parameter\s+sweep\s+of|"
    r"perturbation\s+of|manipulation\s+of|replacement\s+of)\s+",
    re.IGNORECASE,
)
_MANIPULATION_MARKERS = (
    "ablation", "altered", "changed", "controlled", "modified", "perturb", "replaced",
    "substituted", "sweep", "swept", "varied", "variation", "vary",
)
_CAUSAL_RELATION_MARKERS = (
    "affect", "alter", "associate", "cause", "control", "depend", "determine",
    "drive", "enhance", "increase", "inhibit", "lead to", "link", "mediate",
    "measure", "measured", "modulate", "predict", "quantif", "reduce", "regulate", "result in", "suppress",
    "vary", "varied",
    "was varied", "were varied", "under", "versus", "compared with",
)
_BOUNDARY_OR_NEGATIVE_MARKERS = (
    "boundary", "cannot", "did not", "fails", "failure", "limit", "limited",
    "negative result", "no effect", "not observed", "outside", "threshold",
    "unchanged", "uncertain", "unknown", "unresolved",
)
_ADVERSE_OR_REVERSAL_MARKERS = (
    "adverse", "harm", "harmful", "toxicity", "toxic", "rebound",
    "substitution effect", "substitution burden", "burden shifting",
    "trade-off", "tradeoff", "unintended consequence", "resource competition",
    "failure mode", "implementation failure", "policy failure", "worse",
    "reduced effectiveness", "resistance", "off-target", "off target",
    "distribution shift", "robustness failure", "fairness degradation",
)
_ADVERSE_OR_REVERSAL_ROLE_MARKERS = (
    "adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound",
    "burden", "negative_evidence", "adverse_or_reversal",
    "ADVERSE_OR_REVERSAL_EVIDENCE".lower(),
)
# Direct-core evidence must be grounded in source content supplied by the
# paper itself.  Provider metadata, generated scenarios/benchmarks, and a
# clipped limitation field can remain useful discovery context but cannot
# manufacture a focal-variable intervention or result.
_PRIMARY_CONTENT_SOURCE_FIELDS = frozenset({
    "title", "abstract", "conclusion", "method", "results", "result", "discussion",
    "full_text_excerpt", "figure_caption", "table_caption",
})
_CORE_AXIS_GENERIC_TERMS = _NON_DISCRIMINATIVE_OBJECT_TERMS | {
    "absence", "activity", "activities", "background", "cell", "cellular", "chemical", "chemistry",
    "complex", "composition", "condition", "conditions", "context", "contexts", "effect", "effects",
    "efficiency", "emergence",
    "formation", "function", "functional", "general", "interaction", "interactions", "life", "living",
    "integrity", "molecular", "molecule", "molecules", "necessity", "normal", "normally", "organic",
    "outcome", "outcomes", "performance", "polarity", "presence", "process", "processes", "rate",
    "reaction", "reactions", "requirement", "result", "results", "specific", "stability", "structure",
    "system", "systems", "transfer", "variable", "change", "changes",
}
# A focal-variable equivalence may capture a field-specific operational name,
# but never a generic research topic.  These words are intentionally rejected
# even when an LLM proposes them as part of a phrase: they do not identify the
# same intervention/property with enough precision to relax direct-core
# provenance.
_FOCAL_VARIABLE_SYNONYM_GENERIC_TERMS = _CORE_AXIS_GENERIC_TERMS | {
    "asymmetry", "biochemistry", "evolution", "handedness", "origin",
    "selection", "symmetry",
}
_FOCAL_VARIABLE_SYNONYM_RELATIONS = frozenset({
    "mechanistic_semantic_equivalent",
    "operational_semantic_equivalent",
    "operational_or_mechanistic_semantic_equivalent",
})
_FOCAL_VARIABLE_SYNONYM_DICTIONARY_LOCK = Lock()
_FOCAL_VARIABLE_SYNONYM_DICTIONARY_CACHE: dict[str, dict[str, Any]] = {}
_COMPARISON_OR_PERTURBATION_MARKERS = (
    "ablation", "altered", "compared", "comparison", "control group", "controlled", "dose", "gradient",
    "knockout", "manipulated", "modified", "mutant", "perturb", "placebo", "randomized", "regime",
    "replaced", "sham", "strata", "titration", "treated", "untreated", "varied", "variation",
    "versus", " vs ", "wild type", "without",
)
_COMPARISON_GROUP_PATTERN = re.compile(
    r"\b(?:across|between|among)\s+(?:[a-z0-9+./-]+\s+){0,3}"
    r"(?:groups?|cohorts?|conditions?|treatments?|strata|plots?|sites?|populations?)\b",
    re.IGNORECASE,
)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normal(value: Any) -> str:
    return _compact(value).lower()


def _tokens(value: Any) -> list[str]:
    return [item.lower() for item in _TOKEN_RE.findall(_normal(value)) if item]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _compact(value)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _field_candidate_phrase(value: Any) -> str:
    """Return the source-facing phrase behind an operational wrapper."""
    return _compact(_OPERATION_PREFIX_RE.sub("", _compact(value)))


def _discriminative_field_terms(value: Any) -> list[str]:
    terms: list[str] = []
    for token in _tokens(_field_candidate_phrase(value)):
        if token not in _FIELD_MATCH_NON_DISCRIMINATIVE_TERMS:
            terms.append(token)
        # Formulae and hyphenated identifiers are kept whole by the scientific
        # tokenizer, but a compound such as ``beta-decay-rate`` carries three
        # discriminatory concepts.  Expose those components for the two-core-
        # term rule without changing tokenization elsewhere.
        terms.extend(
            part for part in re.split(r"[+\-./_]+", token)
            if len(part) >= 3 and part not in _FIELD_MATCH_NON_DISCRIMINATIVE_TERMS
        )
    return _unique(terms)


def _expanded_source_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for token in _tokens(value):
        tokens.add(token)
        tokens.update(part for part in re.split(r"[+\-./_]+", token) if len(part) >= 3)
    return tokens


def _source_constrained_semantic_equivalence(
    item: dict[str, Any],
    *,
    field: str,
    candidate: str,
) -> tuple[bool, list[str]]:
    """Accept only a provenance-checked paraphrase mapping.

    The optional LLM fragment parser may map a verbatim source phrase to an
    anchor already present in the sub-hypothesis contract.  It may not invent
    either side.  Reusing that verified mapping is the only semantic-equivalent
    path through the field provenance gate.
    """
    normalized_field = _normal(field)
    if "mediator" in normalized_field or "mechanism" in normalized_field:
        normalized_field = "mediator"
    elif "outcome" in normalized_field or "observable" in normalized_field or "calculable" in normalized_field:
        normalized_field = "outcome"
    elif "input" in normalized_field or "intervention" in normalized_field:
        normalized_field = "input"
    axis_name = {
        "input": "object_alignment",
        "intervention": "object_alignment",
        "mediator": "process_alignment",
        "outcome": "outcome_alignment",
    }.get(normalized_field, "")
    axis = item.get(axis_name) if axis_name and isinstance(item.get(axis_name), dict) else {}
    candidate_normal = _normal(_field_candidate_phrase(candidate))
    anchors = [_normal(value) for value in (axis.get("matched_anchors") or []) if _compact(value)]
    source_phrases = [
        _compact(value) for value in (axis.get("source_phrases") or [])
        if _compact(value) and _normal(value) in _normal(item.get("excerpt"))
    ]
    return bool(candidate_normal and candidate_normal in anchors and source_phrases), source_phrases


def _field_source_match(
    item: dict[str, Any],
    *,
    field: str,
    value: str,
) -> dict[str, Any]:
    """Apply the discriminatory phrase gate to one bounded source unit."""
    candidate = _field_candidate_phrase(value)
    candidate_normal = _normal(candidate)
    excerpt_normal = _normal(item.get("excerpt"))
    terms = _discriminative_field_terms(candidate)
    excerpt_tokens = _expanded_source_tokens(excerpt_normal)
    hits = [term for term in terms if term in excerpt_tokens]
    # A complete phrase (including a one-token scientific identifier such as
    # pH or CO2) is source evidence.  Otherwise require two core terms.  This
    # prevents 'of' or a lone 'model/measurement/thermal' from binding fields.
    candidate_tokens = _tokens(candidate_normal)
    if len(candidate_tokens) == 1:
        exact_phrase = candidate_tokens[0] in _expanded_source_tokens(excerpt_normal)
    elif re.search(r"[\u4e00-\u9fff]", candidate_normal):
        exact_phrase = candidate_normal in excerpt_normal
    else:
        exact_phrase = bool(re.search(
            rf"(?<![A-Za-z0-9]){re.escape(candidate_normal)}(?![A-Za-z0-9])",
            excerpt_normal,
        ))
    two_core_terms = len(set(hits)) >= 2
    semantic_equivalent, source_phrases = _source_constrained_semantic_equivalence(
        item,
        field=field,
        candidate=candidate,
    )
    return {
        "passes": bool(exact_phrase or two_core_terms or semantic_equivalent),
        "match_type": (
            "exact_phrase" if exact_phrase
            else "two_discriminative_terms" if two_core_terms
            else "source_constrained_semantic_equivalence" if semantic_equivalent
            else "no_discriminatory_match"
        ),
        "matched_terms": hits,
        "source_phrases": source_phrases,
    }


def _text_sections(record: dict[str, Any]) -> dict[str, str]:
    payload = record.get("papergraph_input") if isinstance(record.get("papergraph_input"), dict) else {}
    sections: dict[str, str] = {}
    for key in (
        "title", "abstract", "conclusion", "method", "scenario", "benchmark",
        "contribution", "limitation", "results", "result", "discussion",
        "full_text_excerpt", "figure_caption", "table_caption",
    ):
        text = _compact(record.get(key) or payload.get(key) or "")
        if text:
            sections[key] = text
    # Imported records do not use one stable schema for captions.  Treat each
    # caption/table note as a section-local unit rather than concatenating it
    # with an unrelated part of the paper.
    for plural_key, section_prefix in (("figure_captions", "figure_caption"), ("table_captions", "table_caption")):
        values = record.get(plural_key) or payload.get(plural_key) or []
        if not isinstance(values, list):
            values = [values]
        for index, value in enumerate(values, start=1):
            text = _compact(value)
            if text:
                sections[f"{section_prefix}_{index}"] = text
    return sections


def _sentences(text: str) -> list[str]:
    return [sentence for sentence in (_compact(item) for item in _SENTENCE_RE.split(_compact(text))) if sentence]


def _phrase_or_token_hits(text: str, anchors: list[str]) -> list[str]:
    lowered = _normal(text)
    hits: list[str] = []
    for anchor in anchors:
        candidate = _normal(anchor)
        if not candidate:
            continue
        if " " in candidate:
            if candidate in lowered:
                hits.append(candidate)
            continue
        if candidate in _tokens(lowered):
            hits.append(candidate)
    return _unique(hits)


def _discriminative_object_anchors(contract: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return phrase and token anchors that can identify the scientific object.

    A phrase is always preferred.  Single-token object identity is accepted
    only when at least two distinct project-local terms co-occur in a source
    unit.  This preserves projects whose object is genuinely a single word
    while preventing a broad method/property word from becoming an object.
    """
    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    policy_phrases = [
        item for item in (
            list(policy.get("strong_anchor_phrases") or [])
            + [
                anchor
                for anchor in (policy.get("object_group") or [])
                if len(_tokens(anchor)) >= 2
            ]
        )
        if len(_tokens(item)) >= 2
    ]
    policy_tokens = [
        item for item in (policy.get("strong_anchor_terms") or [])
        if _normal(item) and _normal(item) not in _NON_DISCRIMINATIVE_OBJECT_TERMS
    ]
    if policy_phrases or policy_tokens:
        return _unique(policy_phrases)[:32], _unique(policy_tokens)[:24]
    return [], []


def _subhypothesis_object_anchors(contract: dict[str, Any]) -> tuple[list[str], list[str]]:
    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    policy_phrases = [
        item for item in (
            list(policy.get("strong_anchor_phrases") or [])
            + [
                anchor
                for anchor in (policy.get("object_group") or [])
                if len(_tokens(anchor)) >= 2
            ]
        )
        if len(_tokens(item)) >= 2
    ]
    policy_tokens = [
        item for item in (policy.get("strong_anchor_terms") or [])
        if _normal(item) and _normal(item) not in _NON_DISCRIMINATIVE_OBJECT_TERMS
    ]
    if policy_phrases or policy_tokens:
        return _unique(policy_phrases)[:32], _unique(policy_tokens)[:24]
    return [], []


def _axis_anchors(contract: dict[str, Any], field: str) -> list[str]:
    terms, phrases = _policy_axis_values(contract, field=field)
    return _unique(list(phrases) + list(terms))


def _policy_axis_values(
    contract: dict[str, Any],
    *,
    field: str,
) -> tuple[list[str], list[str]]:
    """Get direct-core anchors from canonical core_axis_policy only."""
    policy = contract.get("core_axis_policy") if isinstance(contract.get("core_axis_policy"), dict) else None
    if policy is not None:
        # The external causal-field name is ``process`` while contracts name
        # that axis ``mechanism``.  Keep this mapping explicit rather than
        # falling through to a nonexistent ``process_terms`` key: an empty
        # mechanism axis would otherwise demote every otherwise-valid direct
        # experiment to auxiliary evidence.
        key = {
            "input": "focal_variable",
            "process": "mechanism",
            "outcome": "outcome",
        }[field]
        terms = [
            _normal(value) for value in (policy.get(f"{key}_terms") or [])
            if _normal(value) and _normal(value) not in _CORE_AXIS_GENERIC_TERMS
        ]
        phrases = [
            _normal(value) for value in (policy.get(f"{key}_phrases") or [])
            if _normal(value)
        ]
        return _unique(terms), _unique(phrases)

    return [], []


def _focal_variable_synonym_policy(contract: dict[str, Any]) -> dict[str, Any]:
    policy = contract.get("core_axis_policy")
    return policy if isinstance(policy, dict) else contract


def _mechanism_outcome_synonym_entries(
    contract: dict[str, Any],
    *,
    axis: str,
) -> list[dict[str, Any]]:
    policy = contract.get("core_axis_policy") if isinstance(contract.get("core_axis_policy"), dict) else {}
    dictionary = (
        policy.get("mechanism_outcome_synonym_dictionary")
        if isinstance(policy.get("mechanism_outcome_synonym_dictionary"), dict)
        else contract.get("mechanism_outcome_synonym_dictionary")
        if isinstance(contract.get("mechanism_outcome_synonym_dictionary"), dict)
        else {}
    )
    if str(dictionary.get("status") or "") != "ready":
        return []
    normalized_axis = _normal(axis)
    return [
        dict(entry)
        for entry in (dictionary.get("entries") or [])
        if isinstance(entry, dict) and _normal(entry.get("axis")) == normalized_axis
    ]


def _focal_variable_synonym_dictionary_input(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Return the immutable input used to cache one SH focal dictionary."""

    policy = _focal_variable_synonym_policy(contract)
    focal_variable = _compact(
        policy.get("focal_variable") or contract.get("focal_variable") or ""
    )
    focal_terms, focal_phrases = _policy_axis_values(contract, field="input")
    material = {
        "version": FOCAL_VARIABLE_SYNONYM_DICTIONARY_VERSION,
        "contract_hash": _alignment_contract_hash(contract),
        "focal_variable": _normal(focal_variable),
        "focal_variable_terms": _unique([_normal(value) for value in focal_terms]),
        "focal_variable_phrases": _unique([_normal(value) for value in focal_phrases]),
    }
    material["input_hash"] = sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return material


def _focal_variable_synonym_dictionary_summary(
    dictionary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose the dictionary audit without treating an alias as a conclusion."""

    value = dictionary if isinstance(dictionary, dict) else {}
    entries = value.get("entries") if isinstance(value.get("entries"), list) else []
    return {
        "version": str(value.get("version") or FOCAL_VARIABLE_SYNONYM_DICTIONARY_VERSION),
        "status": str(value.get("status") or "uninitialized"),
        "input_hash": str(value.get("input_hash") or ""),
        "focal_variable": str(value.get("focal_variable") or ""),
        "entry_count": len(entries),
        "entries": [
            {
                "source_phrase": str(entry.get("source_phrase") or ""),
                "canonical_focal_variable": str(entry.get("canonical_focal_variable") or ""),
                "relation": str(entry.get("relation") or ""),
                "status": str(entry.get("status") or ""),
            }
            for entry in entries
            if isinstance(entry, dict)
        ][: _FOCAL_VARIABLE_SYNONYM_DICTIONARY_MAX_ENTRIES],
        "rejected_entry_count": int(value.get("rejected_entry_count") or 0),
    }


def _validated_focal_variable_synonym_entries(
    entries: Any,
    *,
    focal_variable: str,
) -> tuple[list[dict[str, str]], int]:
    """Keep only source-matchable, conservative LLM dictionary proposals."""

    canonical = _normal(focal_variable)
    accepted: list[dict[str, str]] = []
    seen: set[str] = set()
    rejected = 0
    for raw in entries if isinstance(entries, list) else []:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        source_phrase = _compact(raw.get("source_phrase"))
        source_normal = _normal(source_phrase)
        proposed_canonical = _normal(raw.get("canonical_focal_variable"))
        relation = _normal(raw.get("relation"))
        source_tokens = _tokens(source_normal)
        specific_tokens = [
            token for token in source_tokens
            if token not in _FOCAL_VARIABLE_SYNONYM_GENERIC_TERMS
        ]
        valid = bool(
            source_normal
            and canonical
            and proposed_canonical == canonical
            and relation in _FOCAL_VARIABLE_SYNONYM_RELATIONS
            and source_normal != canonical
            and len(source_phrase) <= 120
            and len(source_tokens) >= 2
            and len(source_tokens) <= 8
            and len(specific_tokens) >= 2
            and not re.search(r"(?:https?://|www\\.)", source_normal)
        )
        if not valid or source_normal in seen:
            rejected += 1
            continue
        seen.add(source_normal)
        accepted.append({
            "source_phrase": source_phrase,
            "canonical_focal_variable": _compact(focal_variable),
            "relation": relation,
            "status": "llm_candidate_validated",
        })
        if len(accepted) >= _FOCAL_VARIABLE_SYNONYM_DICTIONARY_MAX_ENTRIES:
            break
    return accepted, rejected


def resolve_focal_variable_synonym_dictionary(
    contract: dict[str, Any],
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Resolve one auditable focal-variable alias dictionary per contract.

    This is deliberately a contract-level operation rather than a paper-level
    classifier.  An accepted entry still has no effect until its exact source
    phrase occurs in a bounded paper excerpt and every other direct-core
    condition passes.
    """

    policy = _focal_variable_synonym_policy(contract)
    dictionary_input = _focal_variable_synonym_dictionary_input(contract)
    input_hash = str(dictionary_input["input_hash"])
    focal_variable = str(dictionary_input["focal_variable"])
    existing = policy.get("focal_variable_synonym_dictionary")
    if isinstance(existing, dict) and str(existing.get("input_hash") or "") == input_hash:
        status = str(existing.get("status") or "")
        if status == "ready":
            entries, rejected = _validated_focal_variable_synonym_entries(
                existing.get("entries"), focal_variable=focal_variable,
            )
            if entries:
                resolved = {
                    **existing,
                    "entries": entries,
                    "rejected_entry_count": int(existing.get("rejected_entry_count") or 0) + rejected,
                }
                policy["focal_variable_synonym_dictionary"] = resolved
                return resolved
        if status in {"rejected", "unavailable", "not_applicable"}:
            return dict(existing)

    if not use_llm:
        return {
            **dictionary_input,
            "status": "uninitialized",
            "entries": [],
            "rejected_entry_count": 0,
        }

    with _FOCAL_VARIABLE_SYNONYM_DICTIONARY_LOCK:
        existing = policy.get("focal_variable_synonym_dictionary")
        if isinstance(existing, dict) and str(existing.get("input_hash") or "") == input_hash:
            status = str(existing.get("status") or "")
            if status in {"ready", "rejected", "unavailable", "not_applicable"}:
                return dict(existing)
        cached = _FOCAL_VARIABLE_SYNONYM_DICTIONARY_CACHE.get(input_hash)
        if isinstance(cached, dict):
            policy["focal_variable_synonym_dictionary"] = dict(cached)
            return dict(cached)

        if not focal_variable:
            resolved = {
                **dictionary_input,
                "status": "not_applicable",
                "entries": [],
                "rejected_entry_count": 0,
            }
            _FOCAL_VARIABLE_SYNONYM_DICTIONARY_CACHE[input_hash] = dict(resolved)
            policy["focal_variable_synonym_dictionary"] = resolved
            return dict(resolved)

        try:
            try:
                from ._llm import call_llm_json
            except ImportError:
                from _llm import call_llm_json
            context = {
                "focus": _compact(contract.get("focus"))[:600],
                "scientific_object": _compact(contract.get("scientific_object"))[:400],
                "causal_chain": [
                    _compact(value) for value in (contract.get("causal_chain") or [])
                    if _compact(value)
                ][:5],
                "mechanism_anchors": list(policy.get("mechanism_phrases") or [])[:6],
                "outcome_anchors": list(policy.get("outcome_phrases") or [])[:6],
            }
            payload = call_llm_json(
                system=(
                    "You build a conservative source-bound synonym dictionary for one scientific focal variable. "
                    "This dictionary is only a retrieval/alignment hypothesis, not evidence or a scientific conclusion. "
                    "Return JSON only. Do not create papers, results, claims, variables, or broad related topics."
                ),
                prompt=(
                    "Return up to 8 short phrases that may occur verbatim in a paper and can operationally or "
                    "mechanistically name the exact focal variable below. Each phrase must be specific enough to "
                    "distinguish the focal variable from broad context. Do not return generic words or phrases such as "
                    "asymmetry, chirality, handedness, selection, life, chemistry, reaction, stability, or evolution. "
                    "Every canonical_focal_variable must copy the supplied focal variable exactly. "
                    "Use relation exactly 'operational_or_mechanistic_semantic_equivalent'.\n\n"
                    f"Focal variable: {focal_variable}\n"
                    f"Contract context: {json.dumps(context, ensure_ascii=False)}\n\n"
                    "Return exactly: {\"entries\":[{\"source_phrase\":\"...\","
                    "\"canonical_focal_variable\":\"...\","
                    "\"relation\":\"operational_or_mechanistic_semantic_equivalent\"}]}"
                ),
                max_tokens=700,
                fallback_list_key="entries",
            )
            entries, rejected = _validated_focal_variable_synonym_entries(
                payload.get("entries"), focal_variable=focal_variable,
            )
            resolved = {
                **dictionary_input,
                "status": "ready" if entries else "rejected",
                "entries": entries,
                "rejected_entry_count": rejected,
            }
        except Exception as exc:
            resolved = {
                **dictionary_input,
                "status": "unavailable",
                "entries": [],
                "rejected_entry_count": 0,
                "error_type": type(exc).__name__,
            }
        _FOCAL_VARIABLE_SYNONYM_DICTIONARY_CACHE[input_hash] = dict(resolved)
        policy["focal_variable_synonym_dictionary"] = resolved
        return dict(resolved)


def _source_contains_exact_phrase(source: str, phrase: str) -> bool:
    """Match a validated dictionary phrase without widening it to a token bag."""

    normalized_source = _normal(source)
    normalized_phrase = _normal(phrase)
    if not normalized_source or not normalized_phrase:
        return False
    if re.search(r"[\u0370-\u03ff\u4e00-\u9fff+\-./]", normalized_phrase):
        return normalized_phrase in normalized_source
    return bool(re.search(
        rf"(?<![a-z0-9_]){re.escape(normalized_phrase)}(?![a-z0-9_])",
        normalized_source,
    ))


def _core_axis_support(
    excerpt: Any,
    *,
    terms: list[str],
    phrases: list[str],
    semantic_equivalents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require a phrase, one precise identifier, or two specific tokens."""
    normalized = _normal(excerpt)
    source_tokens = _expanded_source_tokens(normalized)
    phrase_hits = [phrase for phrase in phrases if phrase and phrase in normalized]
    term_hits: list[str] = []
    for term in terms:
        normalized_term = _normal(term)
        if not normalized_term:
            continue
        components = [
            part for part in re.split(r"[+\-./_]", normalized_term)
            if len(part) >= 2 and part not in _CORE_AXIS_GENERIC_TERMS
        ]
        if normalized_term in source_tokens or (len(components) >= 2 and all(part in source_tokens for part in components)):
            term_hits.append(normalized_term)
    term_hits = _unique(term_hits)
    lexical_passes = bool(
        phrase_hits
        or (len(terms) == 1 and term_hits)
        or len(term_hits) >= 2
    )
    semantic_hits: list[dict[str, str]] = []
    if not lexical_passes:
        for entry in semantic_equivalents or []:
            if not isinstance(entry, dict):
                continue
            source_phrase = _compact(entry.get("source_phrase"))
            if not _source_contains_exact_phrase(normalized, source_phrase):
                continue
            semantic_hits.append({
                "source_phrase": source_phrase,
                "canonical_focal_variable": _compact(entry.get("canonical_focal_variable")),
                "relation": _compact(entry.get("relation")),
                "status": _compact(entry.get("status")),
            })
    passes = bool(lexical_passes or semantic_hits)
    return {
        "passes": passes,
        "matched_terms": term_hits[:12],
        "matched_phrases": phrase_hits[:8],
        "matched_semantic_equivalents": semantic_hits[:4],
        "required_terms": terms[:16],
        "required_phrases": phrases[:12],
        "match_policy": (
            "exact_phrase_or_single_precise_identifier_or_two_axis_specific_terms"
            "_or_validated_dictionary_source_phrase"
        ),
    }


def _primary_content_source(source_field: Any) -> bool:
    field = re.sub(r"_\d+$", "", _normal(source_field))
    return field in _PRIMARY_CONTENT_SOURCE_FIELDS


def _explicit_comparison_or_perturbation(excerpt: Any) -> list[str]:
    normalized = _normal(excerpt)
    hits = [marker for marker in _COMPARISON_OR_PERTURBATION_MARKERS if marker in normalized]
    # Field and observational studies can contribute direct evidence when the
    # source explicitly names the comparison units.  A bare effect direction
    # ("increased", "higher", "different") is deliberately not enough.
    if _COMPARISON_GROUP_PATTERN.search(normalized):
        hits.append("explicit_comparison_groups")
    return _unique(hits)


def _direct_core_fragment_qualification(
    item: dict[str, Any],
    contract: dict[str, Any],
    *,
    fields: set[str],
    relation_signal: bool,
    focal_variable_synonym_dictionary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the additional hard requirements for direct-core evidence.

    Causal-edge import remains useful for a well-aligned partial paper.  It
    becomes CORE only when a bounded primary-source unit actually names the
    focal variable, shows a comparison or perturbation, and reaches a
    non-generic endpoint with an explicit relation.  The result is returned
    even for blocked fragments so the caller can route them as auxiliary
    context/bridge evidence rather than mistaking a domain keyword for a
    scientific result.
    """
    excerpt = str(item.get("excerpt") or "")
    focal_terms, focal_phrases = _policy_axis_values(contract, field="input")
    mechanism_terms, mechanism_phrases = _policy_axis_values(contract, field="process")
    outcome_terms, outcome_phrases = _policy_axis_values(contract, field="outcome")
    dictionary_entries = (
        focal_variable_synonym_dictionary.get("entries")
        if isinstance(focal_variable_synonym_dictionary, dict)
        and str(focal_variable_synonym_dictionary.get("status") or "") == "ready"
        and isinstance(focal_variable_synonym_dictionary.get("entries"), list)
        else []
    )
    focal = _core_axis_support(
        excerpt,
        terms=focal_terms,
        phrases=focal_phrases,
        semantic_equivalents=dictionary_entries,
    )
    mechanism = _core_axis_support(
        excerpt,
        terms=mechanism_terms,
        phrases=mechanism_phrases,
        semantic_equivalents=_mechanism_outcome_synonym_entries(contract, axis="mechanism"),
    )
    outcome = _core_axis_support(
        excerpt,
        terms=outcome_terms,
        phrases=outcome_phrases,
        semantic_equivalents=_mechanism_outcome_synonym_entries(contract, axis="outcome"),
    )
    comparison_hits = _explicit_comparison_or_perturbation(excerpt)
    content_source = _primary_content_source(item.get("source_field"))
    endpoint_supported = bool(
        ("mediator" in fields and mechanism.get("passes"))
        or ("outcome" in fields and outcome.get("passes"))
    )
    # The policy builder has removed upstream terms from downstream core
    # anchors.  This explicit check is retained for old persisted contracts,
    # where a shared generic token should never establish two causal roles.
    # Older persisted contracts commonly store a whole scientific anchor as a
    # multi-token term (for example ``mapping ambiguity``).  Such an anchor
    # is intentionally accepted by the exact-phrase rule above, so include
    # phrase identities here as well.  Looking only at token hits would make
    # every old-contract phrase appear empty and falsely report a circular
    # causal axis.
    focal_hits = (
        set(focal.get("matched_terms") or [])
        | set(focal.get("matched_phrases") or [])
        | {
            _normal(semantic_item.get("source_phrase"))
            for semantic_item in (focal.get("matched_semantic_equivalents") or [])
            if isinstance(semantic_item, dict) and _normal(semantic_item.get("source_phrase"))
        }
    )
    endpoint_hits = (
        set(mechanism.get("matched_terms") or [])
        | set(mechanism.get("matched_phrases") or [])
        | {
            _normal(semantic_item.get("source_phrase"))
            for semantic_item in (mechanism.get("matched_semantic_equivalents") or [])
            if isinstance(semantic_item, dict) and _normal(semantic_item.get("source_phrase"))
        }
        | set(outcome.get("matched_terms") or [])
        | set(outcome.get("matched_phrases") or [])
        | {
            _normal(semantic_item.get("source_phrase"))
            for semantic_item in (outcome.get("matched_semantic_equivalents") or [])
            if isinstance(semantic_item, dict) and _normal(semantic_item.get("source_phrase"))
        }
    )
    non_circular_axes = bool(endpoint_hits - focal_hits)
    missing: list[str] = []
    if not content_source:
        missing.append("support_not_from_title_abstract_or_body")
    if not focal.get("passes"):
        missing.append("focal_variable_not_supported")
    if not comparison_hits:
        missing.append("explicit_comparison_or_perturbation_not_supported")
    if not endpoint_supported:
        missing.append("specific_non_generic_endpoint_not_supported")
    if endpoint_supported and not non_circular_axes:
        missing.append("causal_axes_reuse_same_terms")
    if not relation_signal:
        missing.append("explicit_relation_not_supported")
    passes = not missing
    return {
        "passes": passes,
        "source_unit_id": str(item.get("source_unit_id") or ""),
        "source_field": str(item.get("source_field") or ""),
        "content_source_supported": content_source,
        "focal_variable_supported": bool(focal.get("passes")),
        "focal_variable": focal,
        "focal_variable_synonym_dictionary": _focal_variable_synonym_dictionary_summary(
            focal_variable_synonym_dictionary,
        ),
        "explicit_comparison_or_perturbation_supported": bool(comparison_hits),
        "comparison_or_perturbation_hits": comparison_hits[:12],
        "specific_endpoint_supported": endpoint_supported,
        "mechanism_endpoint": mechanism,
        "outcome_endpoint": outcome,
        "non_circular_axes_supported": non_circular_axes,
        "explicit_relation_supported": relation_signal,
        "missing_requirements": missing,
    }


def evidence_units(record: dict[str, Any], *, window_size: int = 3) -> list[dict[str, Any]]:
    """Produce small, stable section-local sentence windows.

    A primary claim may use a single sentence or an adjacent sentence window;
    it may not use arbitrary statements scattered across a paper.  The window
    id includes a content hash so later audits can detect source drift.
    """
    result: list[dict[str, Any]] = []
    paper_id = str(record.get("paper_id") or record.get("doi") or "").strip()
    if not paper_id:
        title = _compact(record.get("title"))
        paper_id = f"paper_anon_{sha256(title.encode('utf-8')).hexdigest()[:16]}"
    for section, text in _text_sections(record).items():
        sentences = _sentences(text)
        for start in range(len(sentences)):
            for width in range(1, min(max(1, int(window_size)), len(sentences) - start) + 1):
                excerpt = _compact(" ".join(sentences[start:start + width]))
                if not excerpt:
                    continue
                material = f"{paper_id}|{section}|{start}|{start + width - 1}|{excerpt}"
                excerpt_hash = sha256(excerpt.encode("utf-8")).hexdigest()
                source_locator = f"{section}:sentences:{start + 1}-{start + width}"
                result.append({
                    "paper_id": paper_id,
                    "source_field": section,
                    "sentence_start": start,
                    "sentence_end": start + width - 1,
                    "excerpt": excerpt[:1200],
                    "excerpt_hash": excerpt_hash,
                    "source_locator": source_locator,
                    # A locator such as ``abstract:sentences:1-2`` is local to
                    # one paper and is therefore not a valid global foreign
                    # key.  Bind every causal provenance id to both objects.
                    "source_unit_id": f"{paper_id}:{source_locator}:{sha256(material.encode('utf-8')).hexdigest()[:16]}",
                })
    return result


# Keep the public name used by the state-architecture design document.  The
# older ``evidence_units`` name remains a small, backwards-compatible alias.
def build_evidence_units(record: dict[str, Any], *, window_size: int = 3) -> list[dict[str, Any]]:
    """Split imported paper text into bounded, source-addressable units."""
    return evidence_units(record, window_size=window_size)


def _alignment_contract_hash(contract: dict[str, Any]) -> str:
    if _is_research_question_contract_v2(contract):
        stable = {
            "contract_id": contract.get("contract_id"),
            "contract_revision": contract.get("contract_revision") or contract.get("declaration_hash"),
            "question": contract.get("research_question"),
            "scope": contract.get("scientific_scope"),
            "evidence_contract": contract.get("evidence_contract"),
        }
        return sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]
    explicit = _compact(contract.get("contract_hash") or contract.get("alignment_card_hash"))
    if explicit:
        return explicit
    stable = {
        key: contract.get(key)
        for key in (
            "sub_hypothesis_id", "focus", "project_context_phrases",
            "project_context_anchor_terms", "scientific_object_phrases", "scientific_object_terms",
            "scientific_object_anchor_policy", "multi_entity_panel_policy", "object_auxiliary_terms",
            "input_terms", "mechanism_terms", "focus_terms", "outcome_terms", "causal_chain",
        )
    }
    return sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _is_research_question_contract_v2(contract: dict[str, Any] | None) -> bool:
    value = contract if isinstance(contract, dict) else {}
    return str(value.get("schema_version") or "") == "research_question_contract_v2"


def _v2_slot_coverage_alignment(
    record: dict[str, Any],
    contract: dict[str, Any],
    *,
    window_size: int,
    use_llm: bool,
) -> list[dict[str, Any]]:
    """Align V2 documents to declared evidence slots, never causal axes.

    The generic explicit-assertion extractor supplies source quotes, offsets,
    assertion kinds, and type-directed slot hits.  This adapter only groups
    those already-grounded assertions by span and evaluates coverage; it does
    not infer entities, relations, or a causal chain from neighbouring text.
    """
    del window_size
    try:
        try:
            from ._evidence_assertions import build_source_spans, extract_explicit_assertions
        except ImportError:
            from _evidence_assertions import build_source_spans, extract_explicit_assertions
    except Exception:
        return []

    source_spans = build_source_spans(record)
    assertions = extract_explicit_assertions(
        record,
        contract,
        source_spans=source_spans,
        use_llm=use_llm,
    )
    assertions_by_span: dict[str, list[dict[str, Any]]] = {}
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        for span_id in assertion.get("source_span_ids") or []:
            key = str(span_id or "")
            if key:
                assertions_by_span.setdefault(key, []).append(assertion)

    evidence_contract = (
        contract.get("evidence_contract")
        if isinstance(contract.get("evidence_contract"), dict)
        else {}
    )
    required_slots = [str(slot) for slot in evidence_contract.get("required_slots") or [] if str(slot)]
    optional_slots = [str(slot) for slot in evidence_contract.get("optional_slots") or [] if str(slot)]
    required_scope_axes = [
        str(axis)
        for axis in evidence_contract.get("required_comparability_axes") or []
        if str(axis)
    ]
    declared_scope = (
        contract.get("scientific_scope")
        if isinstance(contract.get("scientific_scope"), dict)
        else {}
    )
    paper_genre = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
    review_like = bool(paper_genre.get("is_review")) or "review" in _normal(record.get("publication_type"))
    candidate_only = _candidate_only_document(record)
    alignment_hash = _alignment_contract_hash(contract)
    output: list[dict[str, Any]] = []

    for span in source_spans:
        if not isinstance(span, dict):
            continue
        span_id = str(span.get("source_span_id") or "")
        span_assertions = assertions_by_span.get(span_id, [])
        supported_slots = {
            str(support.get("slot_id") or "")
            for assertion in span_assertions
            for support in assertion.get("slot_support", [])
            if isinstance(support, dict)
            and str(support.get("support_status") or "") == "VERIFIED_NONCOUNTING"
            and str(support.get("slot_id") or "")
            in set(str(item) for item in assertion.get("admitted_slot_ids_v4") or [])
            and str(support.get("slot_id") or "")
        }
        slot_coverage = {
            slot: "SUPPORTED" if slot in supported_slots else "MISSING"
            for slot in required_slots
        }
        slot_coverage.update(
            {
                slot: "SUPPORTED" if slot in supported_slots else "UNASSESSED"
                for slot in optional_slots
                if slot not in slot_coverage
            }
        )
        scope_coverage = {
            axis: "SUPPORTED"
            if any(
                str((assertion.get("scope_tuple") or {}).get(axis) or "").strip()
                for assertion in span_assertions
            )
            else "UNASSESSED"
            for axis in required_scope_axes
            if str(declared_scope.get(axis) or "").strip()
        }
        all_required_supported = bool(required_slots) and all(
            slot_coverage.get(slot) == "SUPPORTED" for slot in required_slots
        )
        any_required_supported = any(
            slot_coverage.get(slot) == "SUPPORTED" for slot in required_slots
        )
        if candidate_only or review_like:
            alignment_status = "BACKGROUND" if span_assertions else "OUT_OF_SCOPE"
        elif all_required_supported:
            alignment_status = "CORE"
        elif any_required_supported:
            alignment_status = "COMPONENT_BRIDGE"
        elif span_assertions:
            alignment_status = "BACKGROUND"
        else:
            alignment_status = "OUT_OF_SCOPE"
        source_type = _normal(span.get("source_type"))
        source_is_primary_kind = source_type not in {"abstract", "metadata", "review"}
        primary_slot_eligible = bool(
            source_is_primary_kind
            and not candidate_only
            and not review_like
            and alignment_status in {"CORE", "COMPONENT_BRIDGE"}
        )
        scope_status = (
            "SOURCE_BOUND"
            if not scope_coverage or all(value == "SUPPORTED" for value in scope_coverage.values())
            else "INSUFFICIENT_SCOPE_INFORMATION"
        )
        assertion_kinds = sorted(
            {
                str(kind)
                for assertion in span_assertions
                for kind in assertion.get("assertion_kinds", [])
                if str(kind)
            }
        )
        output.append(
            {
                "version": RESEARCH_QUESTION_SLOT_ALIGNMENT_VERSION,
                "alignment_contract_hash": alignment_hash,
                "research_question_contract_id": str(contract.get("contract_id") or ""),
                "research_question_contract_revision": str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                ),
                **span,
                # SourceSpan keeps its own immutable schema identifier in the
                # embedded source object.  The enclosing alignment must retain
                # the V2 pipeline schema so consumers do not mistake it for a
                # bare span after dictionary expansion.
                "source_span_schema_version": str(span.get("schema_version") or ""),
                "schema_version": "research_question_evidence_v2",
                "evidence_pipeline_schema": "research_question_evidence_v2",
                "alignment_status": alignment_status,
                "semantic_verdict": f"SLOT_COVERAGE_{alignment_status}",
                "source_role": {
                    "CORE": "direct",
                    "COMPONENT_BRIDGE": "component_bridge",
                    "BACKGROUND": "rationale_only",
                    "OUT_OF_SCOPE": "out_of_scope",
                }[alignment_status],
                # This is a span-local diagnostic projection for display and
                # explanation only.  V2 admission and retrieval scheduling
                # must read the contract-bound assertion ``slot_support``
                # records materialised in gap_source_admissions_v4 instead.
                "projection_kind": "display_only",
                "admission_authority": "gap_source_admission_v3.slot_support",
                "not_valid_for_scheduler_or_provider_skip": True,
                "slot_coverage": slot_coverage,
                "required_slots": list(required_slots),
                "optional_slots": list(optional_slots),
                "scope_slot_coverage": scope_coverage,
                "scope_compatibility": scope_status,
                "evidence_assertion_ids": [
                    str(assertion.get("assertion_id") or "")
                    for assertion in span_assertions
                    if str(assertion.get("assertion_id") or "")
                ],
                "assertion_kinds": assertion_kinds,
                "evidence_link_role": "QUESTION_SLOT_EVIDENCE" if span_assertions else "NONE",
                "source_admission": {
                    "primary_slot_eligible": primary_slot_eligible,
                    "primary_eligible": bool(primary_slot_eligible and all_required_supported),
                    "diagnostic_only": True,
                    "not_valid_for_v2_admission": True,
                    "admission_authority": "gap_source_admission_v3.slot_support",
                    "reason": (
                        "all_required_evidence_slots_are_explicitly_source_bound"
                        if primary_slot_eligible and all_required_supported
                        else "source_span_contributes_only_a_subset_of_the_question_contract"
                        if primary_slot_eligible
                        else "source_type_or_document_quality_cannot_anchor_primary_slot_evidence"
                    ),
                },
                "rejection_reasons": [
                    reason
                    for reason, applies in (
                        ("candidate_only_document", candidate_only),
                        ("review_or_background_cannot_anchor_primary_evidence", review_like),
                        ("required_slots_not_fully_covered", bool(required_slots) and not all_required_supported),
                    )
                    if applies
                ],
                "assessment_method": "explicit_assertion_slot_coverage_display_projection_v2",
                "confidence": round(
                    len(supported_slots & set(required_slots)) / max(1, len(required_slots)),
                    2,
                ),
                "cache_hit": False,
            }
        )
    return output


def assess_evidence_fragment_alignment(
    record: dict[str, Any],
    contract: dict[str, Any],
    *,
    window_size: int = 3,
    use_llm: bool = False,
    llm_max_units: int = 24,
) -> list[dict[str, Any]]:
    """Classify source units against the active evidence contract.

    V2 question contracts use explicit slot coverage.  Historical contracts
    take the legacy causal-triad branch below only so quarantined callers can
    receive their former diagnostic shape; no V2 caller is permitted to enter
    that branch.
    """
    if _is_research_question_contract_v2(contract):
        return _v2_slot_coverage_alignment(
            record,
            contract,
            window_size=window_size,
            use_llm=use_llm,
        )
    if _candidate_only_document(record):
        # OCR and supplemental-document text remains searchable in PaperGraph,
        # but cannot manufacture automatic causal support before review.
        return []
    object_phrases, object_tokens = _discriminative_object_anchors(contract)
    sh_object_phrases, sh_object_tokens = _subhypothesis_object_anchors(contract)
    input_anchors = _axis_anchors(contract, "input")
    process_anchors = _axis_anchors(contract, "process")
    outcome_anchors = _axis_anchors(contract, "outcome")
    paper_genre = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
    review_like = bool(paper_genre.get("is_review")) or "review" in _normal(record.get("publication_type"))
    contract_hash = _alignment_contract_hash(contract)
    current_genre = str(paper_genre.get("genre") or "")
    cached_by_unit = {
        str(item.get("source_unit_id") or ""): item
        for item in (record.get("evidence_fragment_alignments") or [])
        if isinstance(item, dict)
        and str(item.get("alignment_contract_hash") or "") == contract_hash
        and str(item.get("evidence_genre") or "") == current_genre
    }
    aligned: list[dict[str, Any]] = []
    for unit in evidence_units(record, window_size=window_size):
        cached = cached_by_unit.get(str(unit.get("source_unit_id") or ""))
        if isinstance(cached, dict) and str(cached.get("excerpt_hash") or "") == str(unit.get("excerpt_hash") or ""):
            aligned.append({**cached, "cache_hit": True})
            continue
        excerpt = str(unit["excerpt"])
        phrase_hits = _phrase_or_token_hits(excerpt, object_phrases)
        token_hits = _phrase_or_token_hits(excerpt, object_tokens)
        sh_phrase_hits = _phrase_or_token_hits(excerpt, sh_object_phrases)
        sh_token_hits = _phrase_or_token_hits(excerpt, sh_object_tokens)
        sh_object_passes = bool(sh_phrase_hits or len(sh_token_hits) >= 2)
        object_passes = (
            sh_object_passes
            if sh_object_phrases or sh_object_tokens
            else bool(phrase_hits or len(token_hits) >= 2)
        )
        input_hits = _phrase_or_token_hits(excerpt, input_anchors)
        process_hits = _phrase_or_token_hits(excerpt, process_anchors)
        outcome_hits = _phrase_or_token_hits(excerpt, outcome_anchors)
        input_passes = bool(input_hits)
        process_passes = bool(process_hits)
        outcome_passes = bool(outcome_hits)
        if review_like:
            verdict = "BACKGROUND_RATIONALE"
            source_role = "rationale_only"
        elif object_passes and process_passes and outcome_passes:
            verdict = "ALIGNED_TRIADIC_EVIDENCE"
            source_role = "direct"
        elif object_passes and (process_passes or outcome_passes):
            verdict = "ALIGNED_PARTIAL_EVIDENCE"
            source_role = "partial"
        elif object_passes:
            verdict = "BACKGROUND_RATIONALE"
            source_role = "rationale_only"
        else:
            verdict = "OUT_OF_SCOPE"
            source_role = "out_of_scope"
        causal_fields_supported: list[str] = []
        if input_passes:
            causal_fields_supported.append("input")
        if process_passes:
            causal_fields_supported.append("mediator")
        if outcome_passes:
            causal_fields_supported.append("outcome")
        evidence_kind = str(
            paper_genre.get("genre")
            or record.get("evidence_kind")
            or record.get("publication_type")
            or "unclassified"
        )
        rejection_reasons: list[str] = []
        if review_like:
            rejection_reasons.append("review_or_background_cannot_anchor_primary_causal_evidence")
        if not object_passes:
            rejection_reasons.append("project_object_not_supported_in_source_unit")
        if not process_passes:
            rejection_reasons.append("causal_process_not_supported_in_source_unit")
        if not outcome_passes:
            rejection_reasons.append("target_outcome_not_supported_in_source_unit")
        confidence = round((int(object_passes) + int(process_passes) + int(outcome_passes)) / 3, 2)
        aligned.append({
            "version": EVIDENCE_FRAGMENT_ALIGNMENT_VERSION,
            **unit,
            "alignment_contract_hash": contract_hash,
            "evidence_genre": str(paper_genre.get("genre") or ""),
            "evidence_kind": evidence_kind,
            "evidence_role": (
                "DIRECT_CAUSAL_EVIDENCE" if verdict == "ALIGNED_TRIADIC_EVIDENCE"
                else "PARTIAL_CAUSAL_EVIDENCE" if verdict == "ALIGNED_PARTIAL_EVIDENCE"
                else "BACKGROUND_OR_OUT_OF_SCOPE"
            ),
            "object_alignment": {
                "passes": object_passes,
                "matched_anchors": phrase_hits[:8] + token_hits[:12],
                "anchor_type": "project_object",
                "phrase_hits": phrase_hits[:8],
                "token_hits": token_hits[:12],
                "subhypothesis_object_passes": sh_object_passes,
                "subhypothesis_phrase_hits": sh_phrase_hits[:8],
                "subhypothesis_token_hits": sh_token_hits[:12],
            },
            "input_alignment": {
                "passes": input_passes, "matched_anchors": input_hits[:12],
                "anchor_type": "causal_input_or_condition", "hits": input_hits[:12],
            },
            "process_alignment": {
                "passes": process_passes, "matched_anchors": process_hits[:12],
                "anchor_type": "causal_process", "hits": process_hits[:12],
            },
            "outcome_alignment": {
                "passes": outcome_passes, "matched_anchors": outcome_hits[:12],
                "anchor_type": "target_outcome", "hits": outcome_hits[:12],
            },
            "causal_fields_supported": causal_fields_supported,
            "semantic_verdict": verdict,
            "source_role": source_role,
            "rejection_reasons": rejection_reasons,
            "assessment_method": "deterministic_source_bound_contract",
            "confidence": confidence,
            "cache_hit": False,
        })
    # Deterministic matches are sufficient whenever they produce a triadic
    # unit.  The optional LLM path exists for cross-domain paraphrases, runs as
    # one bounded batch, and may only map exact source phrases to anchors that
    # already exist in the alignment contract.  It cannot invent an entity,
    # mechanism, outcome, or source offset.
    if use_llm and not review_like and not any(item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE" for item in aligned):
        aligned = _apply_source_constrained_llm_alignment(
            aligned,
            contract,
            max_units=max(1, int(llm_max_units)),
        )
    return aligned


def _paper_is_foundational_bridge(record: dict[str, Any]) -> bool:
    assessment = (
        record.get("foundational_bridge_assessment")
        if isinstance(record.get("foundational_bridge_assessment"), dict)
        else {}
    )
    import_context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    return bool(
        str(record.get("research_role") or "").upper() == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or assessment.get("research_role") == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or str(record.get("stratified_layer") or import_context.get("stratified_layer") or "") == "L1_milestone"
    )


def _candidate_only_document(record: dict[str, Any]) -> bool:
    enrichment = record.get("full_text_enrichment")
    if not isinstance(enrichment, dict):
        return False
    admission = enrichment.get("evidence_admission")
    return bool(
        isinstance(admission, dict)
        and admission
        and not admission.get("allows_direct_evidence")
    )


def reanchor_gap_predicate_context(
    record: dict[str, Any],
    contract: dict[str, Any],
    predicate_text: Any,
    *,
    adjacent_sentences: int = 2,
) -> dict[str, Any]:
    """Relocate a gap predicate and select its minimum sufficient context.

    The predicate fragment remains a separate immutable source object.  The
    surrounding window may establish object identity or causal roles, but it
    is returned as contextual evidence rather than silently changing the
    predicate fragment's own verdict.
    """
    predicate = _compact(predicate_text)
    predicate_normal = _normal(predicate)
    predicate_terms = set(_discriminative_field_terms(predicate))
    single_units = evidence_units(record, window_size=1)
    if not single_units:
        return {
            "status": "SOURCE_TEXT_UNRESOLVED",
            "gap_predicate_fragment_ref": "",
            "object_context_fragment_refs": [],
            "causal_role_fragment_refs": [],
            "contextual_source_evidence_units": [],
            "contextual_object_confirmed": False,
        }

    def predicate_score(unit: dict[str, Any]) -> tuple[float, int]:
        excerpt = _normal(unit.get("excerpt"))
        if predicate_normal and predicate_normal in excerpt:
            return 3.0 + len(predicate_normal) / max(1, len(excerpt)), -len(excerpt)
        excerpt_terms = set(_discriminative_field_terms(excerpt))
        overlap = predicate_terms & excerpt_terms
        return len(overlap) / max(1, len(predicate_terms | excerpt_terms)), -len(excerpt)

    predicate_unit = max(single_units, key=predicate_score)
    best_score = predicate_score(predicate_unit)[0]
    exact = bool(predicate_normal and predicate_normal in _normal(predicate_unit.get("excerpt")))
    visibly_truncated = bool(
        not exact
        or re.match(r"^(?:\.{2,}|\)|\]|[a-z]{1,10}\))", predicate_normal)
        or predicate_normal.endswith(("...", "[truncated]"))
    )
    if best_score < 0.18:
        return {
            "status": "SOURCE_TEXT_UNRESOLVED",
            "gap_predicate_fragment_ref": "",
            "object_context_fragment_refs": [],
            "causal_role_fragment_refs": [],
            "contextual_source_evidence_units": [],
            "contextual_object_confirmed": False,
        }

    section = str(predicate_unit.get("source_field") or "")
    anchor_start = int(predicate_unit.get("sentence_start") or 0)
    all_context_windows = evidence_units(record, window_size=1 + 2 * max(0, int(adjacent_sentences)))
    candidates = [
        unit for unit in all_context_windows
        if str(unit.get("source_field") or "") == section
        and int(unit.get("sentence_start") or 0) <= anchor_start
        and int(unit.get("sentence_end") or 0) >= anchor_start
        and anchor_start - int(unit.get("sentence_start") or 0) <= adjacent_sentences
        and int(unit.get("sentence_end") or 0) - anchor_start <= adjacent_sentences
    ]
    if visibly_truncated:
        # A clipped PDF field may start in the middle of a taxon, formula, or
        # phrase while the abstract/conclusion contains the complete sentence.
        # Search the other canonical sections by discriminatory overlap, but
        # keep the result in the contextual set rather than rewriting the
        # predicate fragment itself.
        for unit in all_context_windows:
            excerpt_terms = set(_discriminative_field_terms(unit.get("excerpt")))
            overlap = len(predicate_terms & excerpt_terms) / max(1, len(predicate_terms))
            if overlap >= 0.2 and str(unit.get("source_unit_id") or "") not in {
                str(existing.get("source_unit_id") or "") for existing in candidates
            }:
                candidates.append(unit)
    assessed = assess_evidence_fragment_alignment(
        {
            **record,
            # Do not reuse cached alignments from a different window size.
            "evidence_fragment_alignments": [],
        },
        contract,
        window_size=1 + 2 * max(0, int(adjacent_sentences)),
        use_llm=False,
    )
    assessed_by_id = {str(item.get("source_unit_id") or ""): item for item in assessed}

    def sufficiency(unit: dict[str, Any]) -> tuple[int, int, float, int, float]:
        alignment = assessed_by_id.get(str(unit.get("source_unit_id") or ""), {})
        object_pass = bool((alignment.get("object_alignment") or {}).get("passes"))
        role_count = len(alignment.get("causal_fields_supported") or [])
        width = int(unit.get("sentence_end") or 0) - int(unit.get("sentence_start") or 0) + 1
        unit_terms = set(_discriminative_field_terms(unit.get("excerpt")))
        predicate_overlap = len(predicate_terms & unit_terms) / max(1, len(predicate_terms))
        # Prefer an object-confirming causal window, then the minimum sufficient
        # number of sentences, then the strongest deterministic alignment.
        return (
            int(object_pass and role_count > 0),
            role_count,
            predicate_overlap,
            -width,
            float(alignment.get("confidence") or 0.0),
        )

    context_unit = max(candidates or [predicate_unit], key=sufficiency)
    context_alignment = assessed_by_id.get(str(context_unit.get("source_unit_id") or ""), {})
    contextual_units: list[dict[str, Any]] = []
    for unit in (predicate_unit, context_unit):
        if str(unit.get("source_unit_id") or "") not in {
            str(existing.get("source_unit_id") or "") for existing in contextual_units
        }:
            contextual_units.append({**unit, "binding_status": "SOURCE_UNIT_VERIFIED"})
    object_refs = (
        [str(context_unit.get("source_unit_id") or "")]
        if bool((context_alignment.get("object_alignment") or {}).get("passes"))
        else []
    )
    causal_refs = (
        [str(context_unit.get("source_unit_id") or "")]
        if context_alignment.get("causal_fields_supported")
        else []
    )
    return {
        "version": "gap_predicate_context_anchor_v1",
        "status": "SOURCE_TEXT_TRUNCATED" if visibly_truncated else "SOURCE_TEXT_VERIFIED",
        "gap_predicate_fragment_ref": str(predicate_unit.get("source_unit_id") or ""),
        "gap_predicate_fragment": {**predicate_unit, "binding_status": "SOURCE_UNIT_VERIFIED"},
        "minimum_sufficient_context_fragment_ref": str(context_unit.get("source_unit_id") or ""),
        "object_context_fragment_refs": object_refs,
        "causal_role_fragment_refs": causal_refs,
        "contextual_source_evidence_units": contextual_units,
        "contextual_object_confirmed": bool(object_refs),
        "predicate_match": {
            "exact": exact,
            "score": round(float(best_score), 4),
            "requested_text": predicate[:600],
        },
    }


def _apply_source_constrained_llm_alignment(
    alignments: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    max_units: int,
) -> list[dict[str, Any]]:
    """Map paraphrases with an LLM, then deterministically verify provenance."""
    try:
        try:
            from ._llm import call_llm_json
        except ImportError:
            from _llm import call_llm_json
        object_phrases, object_tokens = _discriminative_object_anchors(contract)
        allowed = {
            "object": _unique(object_phrases + object_tokens),
            "process": _axis_anchors(contract, "process"),
            "outcome": _axis_anchors(contract, "outcome"),
        }
        units = [
            {
                "source_unit_id": str(item.get("source_unit_id") or ""),
                "excerpt": str(item.get("excerpt") or "")[:1200],
            }
            for item in alignments
            if isinstance(item, dict) and str(item.get("excerpt") or "")
        ][:max_units]
        if not units or any(not values for values in allowed.values()):
            return alignments
        payload = call_llm_json(
            system=(
                "You align bounded scientific source excerpts to an existing research contract. "
                "Never add scientific entities or claims. Every source_phrase must be copied verbatim from its excerpt, "
                "and every contract_anchor must be copied exactly from the supplied anchor list. Return JSON only."
            ),
            prompt=(
                "For each source unit, identify at most one object, process/mechanism, and outcome mapping. "
                "Omit an axis when the excerpt does not support it. Return {\"alignments\":[{\"source_unit_id\":...,"
                "\"object\":{\"source_phrase\":...,\"contract_anchor\":...},"
                "\"process\":{...},\"outcome\":{...}}]}.\n"
                f"Allowed anchors: {json.dumps(allowed, ensure_ascii=False)}\n"
                f"Source units: {json.dumps(units, ensure_ascii=False)}"
            ),
            max_tokens=2400,
            fallback_list_key="alignments",
        )
    except Exception:
        return alignments

    suggestions = payload.get("alignments") if isinstance(payload.get("alignments"), list) else []
    suggestions_by_id = {
        str(item.get("source_unit_id") or ""): item
        for item in suggestions if isinstance(item, dict) and str(item.get("source_unit_id") or "")
    }
    validated: list[dict[str, Any]] = []
    for item in alignments:
        unit_id = str(item.get("source_unit_id") or "")
        suggestion = suggestions_by_id.get(unit_id, {})
        excerpt = _normal(item.get("excerpt"))
        axis_results: dict[str, dict[str, Any]] = {}
        for axis in ("object", "process", "outcome"):
            proposed = suggestion.get(axis) if isinstance(suggestion.get(axis), dict) else {}
            source_phrase = _compact(proposed.get("source_phrase"))
            contract_anchor = _compact(proposed.get("contract_anchor"))
            anchor_allowed = any(_normal(contract_anchor) == _normal(value) for value in allowed[axis])
            source_located = bool(source_phrase and _normal(source_phrase) in excerpt)
            axis_results[axis] = {
                "passes": bool(anchor_allowed and source_located),
                "matched_anchors": [contract_anchor] if anchor_allowed and source_located else [],
                "source_phrases": [source_phrase] if anchor_allowed and source_located else [],
                "anchor_type": {
                    "object": "project_object", "process": "causal_process", "outcome": "target_outcome",
                }[axis],
            }
        passes = all(result["passes"] for result in axis_results.values())
        if passes:
            validated.append({
                **item,
                "object_alignment": axis_results["object"],
                "process_alignment": axis_results["process"],
                "outcome_alignment": axis_results["outcome"],
                "causal_fields_supported": ["input", "mediator", "outcome"],
                "semantic_verdict": "ALIGNED_TRIADIC_EVIDENCE",
                "source_role": "direct",
                "evidence_role": "DIRECT_CAUSAL_EVIDENCE",
                "rejection_reasons": [],
                "assessment_method": "llm_fragment_parser_then_deterministic_validator",
                "confidence": 0.9,
                "cache_hit": False,
            })
        else:
            validated.append(item)
    return validated


def persist_evidence_fragment_alignments(
    record: dict[str, Any],
    alignments: list[dict[str, Any]],
    *,
    max_entries_per_contract: int = 128,
) -> None:
    """Persist reusable fragment assessments on the PaperGraph record.

    The gap bundle retains its own immutable audit snapshot, while this cache
    lets a later gap from the same subhypothesis reuse the exact paper/source
    assessment without reinterpreting arbitrary full text.  Entries are
    partitioned by alignment-contract hash and bounded deliberately.
    """
    if not isinstance(record, dict):
        return
    existing = record.get("evidence_fragment_alignments")
    existing = existing if isinstance(existing, list) else []
    incoming = [item for item in alignments if isinstance(item, dict)]
    if not incoming:
        return
    contract_hash = str(incoming[0].get("alignment_contract_hash") or "")
    retained = [
        item for item in existing
        if isinstance(item, dict) and str(item.get("alignment_contract_hash") or "") != contract_hash
    ]
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in incoming:
        unit_id = str(item.get("source_unit_id") or "")
        if not unit_id or unit_id in seen:
            continue
        seen.add(unit_id)
        deduplicated.append(item)
        if len(deduplicated) >= max(1, int(max_entries_per_contract)):
            break
    record["evidence_fragment_alignments"] = retained + deduplicated


def primary_source_span_gate(fragment_alignments: list[dict[str, Any]]) -> dict[str, Any]:
    """Require either one triadic unit or a compatible set of causal edges."""
    direct = [
        item for item in fragment_alignments
        if isinstance(item, dict) and item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
    ]
    partial = [
        item for item in fragment_alignments
        if isinstance(item, dict) and item.get("semantic_verdict") == "ALIGNED_PARTIAL_EVIDENCE"
    ]
    background = [
        item for item in fragment_alignments
        if isinstance(item, dict) and item.get("source_role") == "rationale_only"
    ]
    edge_fragments = [
        item for item in (direct + partial)
        if bool((item.get("object_alignment") or {}).get("passes"))
        and len(set(item.get("causal_fields_supported") or [])) >= 2
    ]
    composite_fields = {
        str(field)
        for item in edge_fragments
        for field in (item.get("causal_fields_supported") or [])
        if str(field)
    }
    composite_passes = {"input", "mediator", "outcome"}.issubset(composite_fields)
    passes = bool(direct or composite_passes)
    missing_axes = [
        field for field in ("input", "mediator", "outcome")
        if field not in composite_fields and not direct
    ]
    return {
        "version": EVIDENCE_FRAGMENT_ALIGNMENT_VERSION,
        "status": "PASSED" if passes else "BLOCKED",
        "passes": passes,
        "gate_mode": "DIRECT_TRIADIC" if direct else "COMPOSITE_CAUSAL_EDGES" if composite_passes else "BLOCKED",
        "required_axes": ["object", "input", "process", "outcome"],
        "triadic_fragment_ids": [str(item.get("source_unit_id") or "") for item in direct[:8]],
        "partial_fragment_ids": [str(item.get("source_unit_id") or "") for item in partial[:8]],
        "composite_edge_fragment_ids": [
            str(item.get("source_unit_id") or "") for item in edge_fragments[:9]
        ],
        "rationale_fragment_ids": [str(item.get("source_unit_id") or "") for item in background[:8]],
        "rejected_fragment_ids": [
            str(item.get("source_unit_id") or "")
            for item in fragment_alignments
            if isinstance(item, dict) and item.get("semantic_verdict") in {"OUT_OF_SCOPE", "BACKGROUND_RATIONALE"}
        ][:16],
        "missing_axes": missing_axes,
        "reason": (
            "At least one bounded direct source unit jointly supports the project object, causal process, and target outcome."
            if direct else
            "A source-bound set of causal-edge fragments jointly supports input, mediator, and outcome for one aligned object."
            if composite_passes else
            "Neither a triadic source unit nor a complete source-bound causal-edge set supports input, mediator, and outcome."
        ),
    }


def source_bound_field_support(
    fragment_alignments: list[dict[str, Any]],
    *,
    field: str,
    value: str,
) -> list[dict[str, Any]]:
    """Return source-bound causal-edge units containing the requested field."""
    if not _field_candidate_phrase(value):
        return []
    supported: list[dict[str, Any]] = []
    for item in fragment_alignments:
        if (
            not isinstance(item, dict)
            or item.get("semantic_verdict") not in {"ALIGNED_TRIADIC_EVIDENCE", "ALIGNED_PARTIAL_EVIDENCE"}
            or (
                item.get("semantic_verdict") != "ALIGNED_TRIADIC_EVIDENCE"
                and (
                    not bool((item.get("object_alignment") or {}).get("passes"))
                    or field not in set(item.get("causal_fields_supported") or [])
                )
            )
        ):
            continue
        match = _field_source_match(item, field=field, value=value)
        if not match["passes"]:
            continue
        supported.append({
            "field": field,
            "paper_id": str(item.get("paper_id") or ""),
            "citation": "",
            "evidence_genre": str(item.get("evidence_genre") or ""),
            "source_field": str(item.get("source_field") or ""),
            "excerpt": str(item.get("excerpt") or "")[:500],
            "source_unit_id": str(item.get("source_unit_id") or ""),
            "matched_terms": list(match.get("matched_terms") or [])[:8],
            "field_match_type": str(match.get("match_type") or ""),
            "matched_source_phrases": list(match.get("source_phrases") or [])[:4],
            "source_role": str(item.get("source_role") or "partial"),
        })
    return supported[:6]


def source_bound_intervention_value(
    raw_value: str,
    fragment_alignments: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Normalize a variable to an operation only when a direct source says so."""
    candidate = _compact(raw_value)
    if not candidate:
        return "", []
    for item in fragment_alignments:
        if (
            not isinstance(item, dict)
            or item.get("semantic_verdict") not in {"ALIGNED_TRIADIC_EVIDENCE", "ALIGNED_PARTIAL_EVIDENCE"}
            or (
                item.get("semantic_verdict") != "ALIGNED_TRIADIC_EVIDENCE"
                and "input" not in set(item.get("causal_fields_supported") or [])
            )
        ):
            continue
        excerpt = _normal(item.get("excerpt"))
        match = _field_source_match(item, field="input", value=candidate)
        if not match["passes"]:
            continue
        if any(marker in excerpt for marker in _MANIPULATION_MARKERS):
            if any(marker in excerpt for marker in (
                "simulation", "numerical", "in silico", "algorithm", "model", "parameter sweep", "ablation",
            )):
                return f"parameter sweep of {candidate}", [str(item.get("source_unit_id") or "")]
            return f"controlled variation of {candidate}", [str(item.get("source_unit_id") or "")]
    return "", []


def normalize_causal_field_from_evidence(
    raw_value: str,
    fragments: list[dict[str, Any]],
    *,
    expected_role: str,
) -> dict[str, Any]:
    """Return a field only when the requested causal role is source-supported.

    This is intentionally conservative.  It does not turn a noun such as a
    material parameter into an operation merely because that operation would
    sound plausible.  The caller may use the returned ``candidate`` for a
    secondary research opportunity, but only ``normalized_value`` may enter a
    primary causal bundle.
    """
    candidate = _compact(raw_value)
    if not candidate:
        return {
            "value": "", "candidate": "", "normalized_value": "",
            "source_status": "UNRESOLVED", "source_unit_ids": [],
            "reason": "No candidate causal field was supplied.",
        }
    role = _normal(expected_role)
    direct = [
        item for item in fragments
        if isinstance(item, dict)
        and item.get("semantic_verdict") in {"ALIGNED_TRIADIC_EVIDENCE", "ALIGNED_PARTIAL_EVIDENCE"}
        and (
            item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
            or bool((item.get("object_alignment") or {}).get("passes"))
        )
        and (
            item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
            or role not in {"input", "intervention", "mediator", "specific_causal_mediator", "outcome", "observable_or_calculable_outcome"}
            or (
                "input" if role in {"input", "intervention"}
                else "mediator" if role in {"mediator", "specific_causal_mediator"}
                else "outcome"
            ) in set(item.get("causal_fields_supported") or [])
        )
    ]
    matching = [
        item for item in direct
        if _field_source_match(item, field=expected_role, value=candidate)["passes"]
    ]
    if not matching:
        return {
            "value": candidate, "candidate": candidate, "normalized_value": "",
            "source_status": "CANDIDATE_UNSUPPORTED", "source_unit_ids": [],
            "reason": "No aligned source fragment supports this candidate causal field.",
        }
    ids = [str(item.get("source_unit_id") or "") for item in matching if str(item.get("source_unit_id") or "")]
    # ``input`` is an epistemic-design-neutral condition.  It may later be
    # interpreted as a controlled operation, a natural regime, a model
    # family, a formal premise, or an instrument configuration.  Only an
    # explicitly requested intervention role requires a manipulation verb at
    # this source-provenance layer.
    if role == "input":
        return {
            "value": candidate, "candidate": candidate, "normalized_value": candidate,
            "source_status": "DIRECT_SOURCE_SUPPORTED", "source_unit_ids": ids,
            "reason": "An aligned source fragment directly supports the input condition; its legal role is decided by research mode.",
        }
    if role in {"intervention", "parameterized_computational_intervention"}:
        normalized, normalized_ids = source_bound_intervention_value(candidate, matching)
        if normalized:
            return {
                "value": candidate, "candidate": candidate, "normalized_value": normalized,
                "source_status": "DIRECT_SOURCE_SUPPORTED", "source_unit_ids": normalized_ids,
                "reason": "A direct source fragment establishes a parameterized operation or transformation.",
            }
        return {
            "value": candidate, "candidate": candidate, "normalized_value": "",
            "source_status": "CANDIDATE_UNSUPPORTED", "source_unit_ids": ids,
            "reason": "Aligned evidence mentions the value but does not establish it as an operation or parameterized transformation.",
        }
    return {
        "value": candidate, "candidate": candidate, "normalized_value": candidate,
        "source_status": "DIRECT_SOURCE_SUPPORTED", "source_unit_ids": ids,
        "reason": "Aligned source fragments directly support the requested causal role.",
    }


# Evidence-first causal facts are deliberately field-neutral.  They provide a
# small, auditable bridge between the literal text of a source unit and the
# I/M/O readiness gate.  The patterns below identify grammatical relations,
# not superconductivity (or any other discipline) vocabulary.
_EXPLICIT_CAUSAL_VERB_RE = re.compile(
    r"\b(?:increase(?:s|d)?|decrease(?:s|d)?|reduce(?:s|d)?|enhance(?:s|d)?|"
    r"suppress(?:es|ed)?|inhibit(?:s|ed)?|affect(?:s|ed)?|alter(?:s|ed)?|"
    r"change(?:s|d)?|modulate(?:s|d)?|regulate(?:s|d)?|control(?:s|led)?|"
    r"drive(?:s|n)?|determine(?:s|d)?|predict(?:s|ed)?|cause(?:s|d)?)\b",
    re.IGNORECASE,
)
_EXPLICIT_MEDIATION_RE = re.compile(r"\b(?:via|through|mediated\s+by|by\s+way\s+of)\b", re.IGNORECASE)
_CAUSAL_FACT_VERSION = "source_causal_fact_v1"


def _compact_source_phrase(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:.()[]{}")
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    return text[:180]


def _source_role_values(fragment: dict[str, Any], role: str) -> list[str]:
    """Read explicitly extracted source values without inventing aliases.

    Different ingestion paths have historically used either a compact
    ``causal_roles`` mapping or flat named fields.  This helper only reads
    those stored source-facing values; it never falls back to a subhypothesis
    or a generated gap draft.
    """
    canonical = "input" if role == "input" else "mediator" if role == "mediator" else "outcome"
    aliases = {
        "input": ("input", "intervention", "condition", "exposure", "parameter"),
        "mediator": ("mediator", "mechanism", "process", "intermediate"),
        "outcome": ("outcome", "output", "readout", "endpoint", "response"),
    }[canonical]
    values: list[str] = []
    for container_key in ("causal_roles", "extracted_causal_roles", "causal_fields"):
        container = fragment.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in aliases:
            value = container.get(key)
            if isinstance(value, dict):
                value = value.get("value") or value.get("candidate") or value.get("text")
            if isinstance(value, list):
                values.extend(_compact_source_phrase(item) for item in value)
            else:
                values.append(_compact_source_phrase(value))
    for key in aliases:
        value = fragment.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("candidate") or value.get("text")
        if isinstance(value, list):
            values.extend(_compact_source_phrase(item) for item in value)
        else:
            values.append(_compact_source_phrase(value))
    return list(dict.fromkeys(value for value in values if value))


def _source_sentences(excerpt: str) -> list[str]:
    return [
        _compact_source_phrase(sentence)
        for sentence in _SENTENCE_RE.split(str(excerpt or ""))
        if _compact_source_phrase(sentence)
    ]


def _explicit_relation_facts(fragment: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only bounded, explicit relation facts from a source excerpt.

    A binary relation contributes input/outcome candidates but deliberately
    does *not* manufacture a mediator.  A triadic fact is emitted only when a
    sentence contains both a causal verb and an explicit mediation connector.
    This conservative rule is usable across experimental, observational,
    computational, theoretical, and measurement research.
    """
    source_unit_id = str(fragment.get("source_unit_id") or "")
    paper_id = str(fragment.get("paper_id") or "")
    if not source_unit_id or not paper_id:
        return []
    facts: list[dict[str, Any]] = []
    for sentence in _source_sentences(str(fragment.get("excerpt") or "")):
        verb = _EXPLICIT_CAUSAL_VERB_RE.search(sentence)
        if not verb:
            continue
        left = _compact_source_phrase(sentence[:verb.start()])
        right = _compact_source_phrase(sentence[verb.end():])
        if not left or not right:
            continue
        mediation = _EXPLICIT_MEDIATION_RE.search(right)
        outcome = _compact_source_phrase(right[:mediation.start()] if mediation else right)
        mediator = _compact_source_phrase(right[mediation.end():]) if mediation else ""
        # Clause-sized spans, generic verbs, and pure assertions are too weak
        # to become scientific variables.  Ontologies apply an additional
        # role-specific check later.
        if len(left.split()) > 18 or len(outcome.split()) > 18:
            continue
        relation = str(verb.group(0)).lower()
        common = {
            "version": _CAUSAL_FACT_VERSION,
            "paper_id": paper_id,
            "source_unit_id": source_unit_id,
            "verbatim_span": sentence[:600],
            "relation": relation,
            "epistemic_status": "EXPLICIT_SOURCE_RELATION",
            "support_level": "EXPLICIT_TEXT_PATTERN",
        }
        facts.extend([
            {**common, "role": "input", "value": left},
            {**common, "role": "outcome", "value": outcome},
        ])
        if mediator and len(mediator.split()) <= 18:
            facts.append({**common, "role": "mediator", "value": mediator, "relation": "explicit_mediation"})
    return facts


def extract_source_causal_evidence_facts(
    fragments: list[dict[str, Any]],
    *,
    declared_candidates: dict[str, list[Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build source-anchored causal role candidates before gap-level routing.

    ``declared_candidates`` can preserve a candidate supplied by an earlier
    stage, but the candidate is included only after
    :func:`normalize_causal_field_from_evidence` proves it against a bounded
    source fragment.  In parallel, the extractor retains explicit source role
    fields and conservative grammar-derived relation facts.  It therefore
    prevents a generated gap or subhypothesis from becoming evidence merely by
    being present in the project state.
    """
    usable = [
        dict(fragment) for fragment in fragments
        if isinstance(fragment, dict)
        and str(fragment.get("paper_id") or "")
        and str(fragment.get("source_unit_id") or "")
        and str(fragment.get("excerpt") or "")
        and str(fragment.get("source_role") or "") in {"direct", "partial"}
    ]
    facts: list[dict[str, Any]] = []
    for fragment in usable:
        common = {
            "version": _CAUSAL_FACT_VERSION,
            "paper_id": str(fragment.get("paper_id") or ""),
            "source_unit_id": str(fragment.get("source_unit_id") or ""),
            "verbatim_span": str(fragment.get("excerpt") or "")[:600],
            "epistemic_status": "EXPLICIT_SOURCE_ROLE_FIELD",
            "support_level": "SOURCE_ROLE_FIELD",
        }
        for role in ("input", "mediator", "outcome"):
            for value in _source_role_values(fragment, role):
                facts.append({**common, "role": role, "value": value, "relation": "source_role_field"})
        facts.extend(_explicit_relation_facts(fragment))

    for role, values in (declared_candidates or {}).items():
        canonical_role = "input" if role == "input" else "mediator" if role == "mediator" else "outcome"
        expected_role = {
            "input": "input",
            "mediator": "specific_causal_mediator",
            "outcome": "observable_or_calculable_outcome",
        }[canonical_role]
        for raw_value in values if isinstance(values, list) else [values]:
            normalized = normalize_causal_field_from_evidence(
                _compact_source_phrase(raw_value), usable, expected_role=expected_role,
            )
            value = _compact_source_phrase(normalized.get("normalized_value"))
            source_ids = [str(item) for item in (normalized.get("source_unit_ids") or []) if str(item)]
            if not value or not source_ids:
                continue
            for source_id in source_ids:
                fragment = next((item for item in usable if str(item.get("source_unit_id") or "") == source_id), {})
                facts.append({
                    "version": _CAUSAL_FACT_VERSION,
                    "paper_id": str(fragment.get("paper_id") or ""),
                    "source_unit_id": source_id,
                    "verbatim_span": str(fragment.get("excerpt") or "")[:600],
                    "role": canonical_role,
                    "value": value,
                    "relation": "declared_candidate_source_verified",
                    "epistemic_status": "DIRECT_SOURCE_SUPPORTED",
                    "support_level": "SOURCE_VERIFIED_CANDIDATE",
                })

    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        key = (
            str(fact.get("source_unit_id") or ""),
            str(fact.get("role") or ""),
            _normal(str(fact.get("value") or "")),
        )
        if not all(key) or key in seen:
            continue
        seen.add(key)
        deduplicated.append(fact)
    return deduplicated
