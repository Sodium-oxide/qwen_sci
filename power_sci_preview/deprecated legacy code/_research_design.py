"""Evidence-bounded full research-design report profile.

The traceability report in :mod:`_research_report` is intentionally compact.
This module adds a second, domain-neutral profile for projects that need a
paper-like research-design report.  It does *not* infer results from metadata
or manufacture equations and protocols.  Instead it turns frozen project
artifacts into four explicit contracts:

* evidence cards, including a source-unit identifier for every substantive
  literature statement and any reported quantitative anchor;
* a directed research argument graph from sources to SHs, gaps, hypotheses,
  formalizations, and planned tests;
* formalization and experiment-design contracts that distinguish recorded
  material from a proposed design;
* chapter-local writer/reviewer iterations that are auditable and have no
  access to unbounded workflow logs.

All helpers accept arbitrary scientific domains.  The profile deliberately
reports missing evidence, missing equations, and incomplete experimental
contracts as limitations rather than filling them with plausible prose.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
import json
import re

try:
    from ._research_report import (
        MAX_NARRATIVE_RETRIES,
        RESTRICTED_BRIDGE_DISCLAIMER,
        _CITATION_TOKEN_RE,
        _RESULT_OVERCLAIM_RE,
        _CJK_RE,
        _first,
        _items,
        _latex_cell,
        _latex_citations,
        _latex_escape,
        _mapping,
        _narrative_to_latex,
        _report_model_hash,
        _safe_identifier,
        _text,
        _unique,
        _contains_unsafe_validation_overclaim,
        audit_report_narrative,
    )
except ImportError:  # pragma: no cover - direct-module execution support
    from _research_report import (
        MAX_NARRATIVE_RETRIES,
        RESTRICTED_BRIDGE_DISCLAIMER,
        _CITATION_TOKEN_RE,
        _RESULT_OVERCLAIM_RE,
        _CJK_RE,
        _first,
        _items,
        _latex_cell,
        _latex_citations,
        _latex_escape,
        _mapping,
        _narrative_to_latex,
        _report_model_hash,
        _safe_identifier,
        _text,
        _unique,
        _contains_unsafe_validation_overclaim,
        audit_report_narrative,
    )


FULL_RESEARCH_DESIGN_PROFILE = "full_research_design"
FULL_RESEARCH_DESIGN_SCHEMA_VERSION = "research_design_report_v1"
MAX_DESIGN_REVIEW_ROUNDS = 2

_FRAGMENT_TEXT_KEYS = (
    "excerpt", "quote", "claim_text", "claim", "sentence", "text", "content",
    "finding", "observation", "result_summary", "evidence_text",
)
_LIMITATION_KEYS = (
    "limitations", "reported_limitations", "methodological_limitations", "caveats", "constraints",
)
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*[×x]\s*10\s*(?:\^\s*)?[+-]?\d+)?)"
    r"\s*(?P<unit>%|[A-Za-zµμ]+(?:\s*/\s*[A-Za-z0-9µμ^.-]+)?|°\s*[CFK])?"
)
_UNSAFE_LATEX_RE = re.compile(
    r"\\(?:input|include|write|openout|read|catcode|usepackage|documentclass|begin\s*\{document\}|end\s*\{document\})",
    flags=re.IGNORECASE,
)
_SYMBOL_RE = re.compile(r"(?<!\\)\b([A-Za-z](?:_[A-Za-z0-9]+)?)\b")
_NON_SUBSTANTIVE_CARD_ROLES = {"catalogue_record", "translation_pending_source_excerpt"}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in _items(value) if isinstance(item, dict)]


def _source_ids(value: Any) -> list[str]:
    """Collect only explicitly supplied source unit identifiers."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in {"source_unit_id", "source_unit_ids", "sourceunitid", "sourceunitids"}:
                found.extend(_items(nested))
            elif isinstance(nested, (dict, list, tuple)):
                found.extend(_source_ids(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_source_ids(nested))
    return _unique(found)


def _compact_text(value: Any, limit: int = 900) -> str:
    text = _text(value)
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _reference_record_index(model: dict[str, Any]) -> dict[str, str]:
    """Map raw paper/source identifiers to stable report citation keys."""
    result: dict[str, str] = {}
    for reference in _dict_items(model.get("references")):
        key = _text(reference.get("reference_key"))
        if not key:
            continue
        for raw_id in _items(reference.get("source_paper_ids")) + _items(reference.get("source_record_ids")):
            if _text(raw_id):
                result[_text(raw_id)] = key
    return result


def _record_reference_key(record: dict[str, Any], index: dict[str, str]) -> str:
    payload = _mapping(record.get("papergraph_input"))
    for candidate in (
        record.get("reference_key"), record.get("paper_id"), record.get("id"), record.get("unique_key"),
        payload.get("paper_id"), payload.get("id"), payload.get("unique_key"),
    ):
        value = _text(candidate)
        if value in index:
            return index[value]
    return _text(record.get("reference_key"))


def _extract_fragment_candidates(value: Any, inherited_units: list[str] | None = None) -> list[dict[str, Any]]:
    """Find local source excerpts without promoting arbitrary nested metadata.

    A candidate is only substantive if it contains both readable text and an
    explicit source unit id (either local or inherited from its source record).
    This prevents a bibliographic title from masquerading as a literature
    finding.
    """
    inherited_units = inherited_units or []
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        local_units = _unique(inherited_units + _source_ids({
            key: nested for key, nested in value.items()
            if str(key).lower() in {"source_unit_id", "source_unit_ids", "sourceunitid", "sourceunitids"}
        }))
        text = ""
        text_field = ""
        for key in _FRAGMENT_TEXT_KEYS:
            candidate = _text(value.get(key))
            if candidate and len(candidate) >= 24:
                text, text_field = candidate, key
                break
        if text:
            for unit in local_units:
                result.append({
                    "source_unit_id": unit,
                    "excerpt": _compact_text(text),
                    "source_field": text_field,
                    "fragment_id": _first(value.get("fragment_id"), value.get("evidence_id"), value.get("id")),
                    "evidence_role": _first(value.get("evidence_role"), value.get("source_role"), "source_excerpt"),
                })
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple)):
                result.extend(_extract_fragment_candidates(nested, local_units))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            result.extend(_extract_fragment_candidates(nested, inherited_units))
    return result


def _quantitative_anchors(text: str, *, source_unit_id: str, evidence_card_id: str) -> list[dict[str, Any]]:
    """Keep reported numbers local to their source excerpt and never generalize them."""
    anchors: list[dict[str, Any]] = []
    for ordinal, match in enumerate(_NUMBER_RE.finditer(text), start=1):
        value = _text(match.group("value"))
        unit = _text(match.group("unit"))
        # Years and bare one/two-digit section labels are not quantitative claims.
        if not unit and re.fullmatch(r"(?:19|20)\d{2}", value):
            continue
        before = text[max(0, match.start() - 80):match.start()].strip(" ,;:()")
        after = text[match.end():min(len(text), match.end() + 80)].strip(" ,;:()")
        context = _compact_text(f"{before} [{value}{(' ' + unit) if unit else ''}] {after}", 240)
        anchors.append({
            "quantitative_anchor_id": f"{evidence_card_id}:q{ordinal}",
            "evidence_card_id": evidence_card_id,
            "source_unit_id": source_unit_id,
            "metric_or_quantity": "reported numeric anchor; metric label must remain in source context",
            "value": value,
            "unit": unit or "not explicitly recorded",
            "condition": context,
            "reported_not_generalized": True,
        })
    return anchors[:12]


def _card_context(record: dict[str, Any]) -> dict[str, str]:
    payload = _mapping(record.get("papergraph_input"))
    return {
        "system": _first(record.get("scenario"), payload.get("scenario"), record.get("system"), payload.get("system")),
        "population_or_testbed": _first(record.get("testbed"), payload.get("testbed"), record.get("population"), payload.get("population")),
        "intervention_or_condition": _first(record.get("intervention"), payload.get("intervention"), record.get("condition"), payload.get("condition")),
        "comparator": _first(record.get("comparison"), payload.get("comparison"), record.get("comparator"), payload.get("comparator")),
    }


def build_evidence_cards(model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build source-unit-grounded evidence cards from the frozen PaperGraph.

    A record with only bibliography-level fields is still useful, but is marked
    ``catalogue_record`` and can only be used for catalogue/matrix statements.
    It is never rendered as an established scientific finding.
    """
    snapshot = _mapping(model.get("project_snapshot"))
    reference_index = _reference_record_index(model)
    raw_records = _dict_items(snapshot.get("papergraph"))
    records_by_key: dict[str, list[dict[str, Any]]] = {}
    for record in raw_records:
        key = _record_reference_key(record, reference_index)
        if key:
            records_by_key.setdefault(key, []).append(record)
    cards: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for reference in _dict_items(model.get("references")):
        key = _text(reference.get("reference_key"))
        records = records_by_key.get(key, [])
        fragments: list[dict[str, Any]] = []
        for record in records:
            fragments.extend(_extract_fragment_candidates(record, _source_ids(record)))
        for fragment in fragments:
            unit = _text(fragment.get("source_unit_id"))
            excerpt = _compact_text(fragment.get("excerpt"))
            marker = (key, unit, excerpt)
            if not unit or not excerpt or marker in seen:
                continue
            seen.add(marker)
            card_id = _safe_identifier(f"EC_{key}_{unit}_{len(cards)+1}", f"evidence_card_{len(cards)+1}")
            source_limitations = _unique(
                limitation for record in records for limitation in _items(record.get("limitations"))
            ) or _unique(_items(reference.get("limitations")))
            translation_pending = bool(_CJK_RE.search(excerpt))
            card = {
                "evidence_card_id": card_id,
                "reference_key": key,
                "source_unit_id": unit,
                "source_record_ids": _unique(_items(reference.get("source_record_ids"))),
                "sub_hypothesis_ids": _unique(
                    sid for record in records for sid in _items(record.get("sub_hypothesis_id")) + _items(record.get("sub_hypothesis_ids"))
                ),
                "evidence_role": "translation_pending_source_excerpt" if translation_pending else (_text(fragment.get("evidence_role")) or "source_excerpt"),
                "claim_type": "translation_pending_source_excerpt" if translation_pending else "source_excerpt",
                "claim_text": "English rendering pending source-grounded translation of this excerpt." if translation_pending else excerpt,
                "source_language_rendering_status": "TRANSLATION_PENDING" if translation_pending else "ENGLISH_READY",
                "study_context": _card_context(records[0]) if records else {},
                "source_stated_limitations": source_limitations,
                "allowed_report_uses": ["provenance_only", "evidence_matrix"] if translation_pending else ["literature_synthesis", "local_sh_review", "gap_context", "evidence_matrix"],
                "provenance_status": "SOURCE_UNIT_BOUND",
            }
            card["quantitative_anchors"] = [] if translation_pending else _quantitative_anchors(excerpt, source_unit_id=unit, evidence_card_id=card_id)
            anchors.extend(card["quantitative_anchors"])
            cards.append(card)
        if fragments:
            continue
        # Preserve a transparent bibliographic card if no source excerpt was
        # persisted.  This can substantiate only the existence of a catalogue
        # entry, not a substantive scientific assertion.
        units = _unique(_items(reference.get("source_unit_ids")))
        for unit in units or [""]:
            card_id = _safe_identifier(f"EC_{key}_{unit or 'missing'}_{len(cards)+1}", f"evidence_card_{len(cards)+1}")
            method = _text(reference.get("method"))
            scenario = _text(reference.get("scenario"))
            benchmark = _text(reference.get("benchmark"))
            catalogue_text = (
                f"The frozen catalogue records this study as method={method or 'not recorded'}, "
                f"scenario={scenario or 'not recorded'}, benchmark={benchmark or 'not recorded'}."
            )
            cards.append({
                "evidence_card_id": card_id,
                "reference_key": key,
                "source_unit_id": unit,
                "source_record_ids": _unique(_items(reference.get("source_record_ids"))),
                "sub_hypothesis_ids": _unique(
                    sid for record in records for sid in _items(record.get("sub_hypothesis_id")) + _items(record.get("sub_hypothesis_ids"))
                ),
                "evidence_role": "catalogue_record",
                "claim_type": "bibliographic_metadata",
                "claim_text": catalogue_text,
                "study_context": _card_context(records[0]) if records else {},
                "source_stated_limitations": _unique(_items(reference.get("limitations"))),
                "allowed_report_uses": ["bibliography", "literature_matrix", "catalogue_count"],
                "provenance_status": "SOURCE_UNIT_BOUND" if unit else "SOURCE_UNIT_MISSING",
                "quantitative_anchors": [],
            })
    return cards, anchors


def _node(node_id: str, node_type: str, label: str, **extra: Any) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, "label": _compact_text(label, 300), **extra}


def _edge(source: str, target: str, relation: str, **extra: Any) -> dict[str, Any]:
    return {"edge_id": _safe_identifier(f"{source}__{relation}__{target}", "edge"), "source": source, "target": target, "relation": relation, **extra}


def build_research_argument_graph(model: dict[str, Any]) -> dict[str, Any]:
    """Build a non-speculative source→claim→gap→test graph."""
    cards = _dict_items(model.get("evidence_cards"))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["node_id"] not in node_ids:
            node_ids.add(item["node_id"])
            nodes.append(item)

    for card in cards:
        card_node = f"evidence:{card.get('evidence_card_id')}"
        add(_node(card_node, "evidence_card", card.get("claim_text") or card.get("evidence_card_id"),
                  reference_key=card.get("reference_key"), source_unit_id=card.get("source_unit_id"),
                  evidence_role=card.get("evidence_role"), provenance_status=card.get("provenance_status")))
    for sh in _dict_items(model.get("sub_hypotheses")):
        sh_id = _text(sh.get("sub_hypothesis_id"))
        add(_node(f"sh:{sh_id}", "sub_hypothesis", sh.get("title") or sh_id, sub_hypothesis_id=sh_id))
    for gap in _dict_items(model.get("gaps")):
        gap_id = _text(gap.get("gap_id"))
        add(_node(f"gap:{gap_id}", "gap", gap.get("description") or gap_id, gap_id=gap_id,
                  availability=gap.get("availability"), restricted=gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE"))
    for combined in _dict_items(model.get("combined_gaps")):
        combined_id = _text(combined.get("combined_gap_id"))
        add(_node(f"combined:{combined_id}", "combined_gap", combined.get("description") or combined_id,
                  combined_gap_id=combined_id, status=combined.get("status")))
    for hypothesis in _dict_items(model.get("hypotheses")):
        hypothesis_id = _text(hypothesis.get("hypothesis_id"))
        add(_node(f"hypothesis:{hypothesis_id}", "hypothesis", hypothesis.get("statement") or hypothesis_id,
                  hypothesis_id=hypothesis_id, status=hypothesis.get("status"), disclaimer=hypothesis.get("disclaimer")))
    for formalization in _dict_items(model.get("formalizations")):
        formalization_id = _text(formalization.get("formalization_id"))
        add(_node(f"formalization:{formalization_id}", "formalization", formalization.get("equation_latex") or formalization_id,
                  formalization_id=formalization_id, status=formalization.get("status")))
    for experiment in _dict_items(model.get("experiment_designs")):
        experiment_id = _text(experiment.get("experiment_design_id"))
        add(_node(f"experiment:{experiment_id}", "experiment_design", experiment.get("summary") or experiment_id,
                  experiment_design_id=experiment_id, status=experiment.get("status")))

    for card in cards:
        if card.get("evidence_role") in _NON_SUBSTANTIVE_CARD_ROLES:
            continue
        source = f"evidence:{card.get('evidence_card_id')}"
        for sh_id in _items(card.get("sub_hypothesis_ids")):
            target = f"sh:{_text(sh_id)}"
            if target in node_ids:
                edges.append(_edge(source, target, "supports_local_scope", source_unit_ids=[card.get("source_unit_id")]))
    for gap in _dict_items(model.get("gaps")):
        source = f"sh:{_text(gap.get('sub_hypothesis_id'))}"
        target = f"gap:{_text(gap.get('gap_id'))}"
        if source in node_ids:
            relation = "requires_direct_validation" if gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" else "has_gap"
            edges.append(_edge(source, target, relation, source_unit_ids=_unique(_items(gap.get("source_unit_ids"))), disclaimer=gap.get("disclaimer")))
    for combined in _dict_items(model.get("combined_gaps")):
        target = f"combined:{_text(combined.get('combined_gap_id'))}"
        relation = "compatible_with" if combined.get("status") == "COMBINABLE" and combined.get("compatibility_gate_passed") else "cannot_be_combined_with"
        for gap_id in _items(combined.get("declared_gap_ids")):
            source = f"gap:{_text(gap_id)}"
            if source in node_ids:
                edges.append(_edge(source, target, relation, source_unit_ids=_unique(_items(combined.get("source_unit_ids")))))
    for hypothesis in _dict_items(model.get("hypotheses")):
        source = f"gap:{_text(hypothesis.get('gap_id'))}"
        target = f"hypothesis:{_text(hypothesis.get('hypothesis_id'))}"
        if source in node_ids:
            edges.append(_edge(source, target, "operationalizes", source_unit_ids=_unique(_items(hypothesis.get("source_unit_ids"))), disclaimer=hypothesis.get("disclaimer")))
    for formalization in _dict_items(model.get("formalizations")):
        target = f"formalization:{_text(formalization.get('formalization_id'))}"
        source = f"hypothesis:{_text(formalization.get('hypothesis_id'))}"
        if source in node_ids:
            edges.append(_edge(source, target, "formalizes", status=formalization.get("status")))
    for experiment in _dict_items(model.get("experiment_designs")):
        target = f"experiment:{_text(experiment.get('experiment_design_id'))}"
        source = f"hypothesis:{_text(experiment.get('hypothesis_id'))}"
        if source in node_ids:
            edges.append(_edge(source, target, "falsifies", status=experiment.get("status")))
    return {
        "graph_id": "research_argument_graph",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "scope": "A directed audit graph, not evidence of causal validation.",
    }


def _raw_formalizations(snapshot: dict[str, Any], hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for key in ("formalizations", "research_formalizations", "theory_formalizations", "models"):
        values.extend(_dict_items(snapshot.get(key)))
    for raw_hypothesis in _dict_items(snapshot.get("hypotheses")):
        raw = raw_hypothesis.get("formalization")
        if isinstance(raw, dict):
            values.append({
                **raw,
                "hypothesis_id": _first(raw.get("hypothesis_id"), raw_hypothesis.get("hypothesis_id"), raw_hypothesis.get("idea_id")),
            })
    for hypothesis in hypotheses:
        raw = hypothesis.get("formalization")
        if isinstance(raw, dict):
            values.append({**raw, "hypothesis_id": _first(raw.get("hypothesis_id"), hypothesis.get("hypothesis_id"))})
    return values


def _symbols(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _items(value):
        if isinstance(item, dict):
            symbol = _first(item.get("symbol"), item.get("name"), item.get("id"))
            meaning = _first(item.get("meaning"), item.get("description"), item.get("definition"))
            unit = _first(item.get("unit_or_domain"), item.get("unit"), item.get("domain"))
        else:
            symbol, meaning, unit = _text(item), "", ""
        if symbol:
            result.append({"symbol": symbol, "meaning": meaning, "unit_or_domain": unit})
    return result


def build_formalization_contracts(model: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = _mapping(model.get("project_snapshot"))
    hypotheses = _dict_items(model.get("hypotheses"))
    raw_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for record in _raw_formalizations(snapshot, hypotheses):
        hypothesis_id = _first(record.get("hypothesis_id"), record.get("supports_hypothesis_id"), record.get("idea_id"))
        if hypothesis_id:
            raw_by_hypothesis.setdefault(hypothesis_id, []).append(record)
    contracts: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        hypothesis_id = _text(hypothesis.get("hypothesis_id"))
        records = raw_by_hypothesis.get(hypothesis_id, [])
        if not records:
            contracts.append({
                "formalization_id": f"formalization_{hypothesis_id}", "hypothesis_id": hypothesis_id,
                "formalization_type": "not_provided", "equation_latex": "", "symbols": [], "assumptions": [],
                "measurable_outputs": [], "falsification_conditions": [], "reported_as": "proposal_not_result",
                "status": "NOT_PROVIDED", "validation": {"verdict": "INCOMPLETE", "errors": [{"code": "FORMALIZATION_NOT_PROVIDED", "detail": hypothesis_id}]},
            })
            continue
        for ordinal, record in enumerate(records, start=1):
            equation = _text(record.get("equation_latex"))
            if not equation:
                equation = _text(record.get("equation"))
            contract = {
                "formalization_id": _safe_identifier(_first(record.get("formalization_id"), record.get("id"), f"formalization_{hypothesis_id}_{ordinal}"), f"formalization_{hypothesis_id}_{ordinal}"),
                "hypothesis_id": hypothesis_id,
                "formalization_type": _first(record.get("type"), record.get("formalization_type"), "proposed_design"),
                "equation_latex": equation,
                "symbols": _symbols(record.get("symbols")),
                "assumptions": _unique(_items(record.get("assumptions"))),
                "measurable_outputs": _unique(_items(record.get("measurable_outputs"))),
                "falsification_conditions": _unique(_items(record.get("falsification_conditions")) + _items(record.get("falsification"))),
                "reported_as": "evidence_backed" if _text(record.get("reported_as")) == "evidence_backed" else "proposal_not_result",
                "source_unit_ids": _source_ids(record),
                "status": "RECORDED" if equation else "INCOMPLETE",
            }
            contract["validation"] = validate_formalization_contract(contract)
            contracts.append(contract)
    return contracts


def validate_formalization_contract(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    equation = _text(contract.get("equation_latex"))
    symbols = _dict_items(contract.get("symbols"))
    if contract.get("status") == "NOT_PROVIDED":
        return {"verdict": "INCOMPLETE", "errors": [{"code": "FORMALIZATION_NOT_PROVIDED", "detail": contract.get("hypothesis_id")}], "warnings": []}
    if not equation:
        errors.append({"code": "FORMALIZATION_EQUATION_MISSING", "detail": contract.get("formalization_id")})
    elif _UNSAFE_LATEX_RE.search(equation):
        errors.append({"code": "FORMALIZATION_UNSAFE_LATEX", "detail": contract.get("formalization_id")})
    declared = {_text(item.get("symbol")).lstrip("\\") for item in symbols if _text(item.get("symbol"))}
    used = {value for value in _SYMBOL_RE.findall(equation) if value.lower() not in {"mathrm", "text", "left", "right", "frac", "sum", "log", "exp", "sin", "cos", "min", "max"}}
    undeclared = sorted(value for value in used if value not in declared and value not in {"e", "i", "d"})
    if equation and not symbols:
        errors.append({"code": "FORMALIZATION_SYMBOLS_MISSING", "detail": contract.get("formalization_id")})
    elif undeclared:
        errors.append({"code": "FORMALIZATION_UNDECLARED_SYMBOL", "detail": undeclared})
    if not _items(contract.get("measurable_outputs")):
        errors.append({"code": "FORMALIZATION_OUTPUTS_MISSING", "detail": contract.get("formalization_id")})
    if not _items(contract.get("falsification_conditions")):
        errors.append({"code": "FORMALIZATION_FALSIFIER_MISSING", "detail": contract.get("formalization_id")})
    if contract.get("reported_as") == "evidence_backed" and not _unique(_items(contract.get("source_unit_ids"))):
        errors.append({"code": "FORMALIZATION_EVIDENCE_SOURCE_UNIT_MISSING", "detail": contract.get("formalization_id")})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": []}


def _protocol_value(protocol: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = protocol.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def build_experiment_design_contracts(model: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for hypothesis in _dict_items(model.get("hypotheses")):
        hypothesis_id = _text(hypothesis.get("hypothesis_id"))
        protocol = _mapping(hypothesis.get("experimental_protocol"))
        if not protocol:
            contracts.append({
                "experiment_design_id": f"experiment_{hypothesis_id}", "hypothesis_id": hypothesis_id,
                "design_type": "not_provided", "status": "NOT_PROVIDED", "summary": "No execution-level protocol was recorded.",
                "reported_as": "proposal_not_result", "validation": {"verdict": "INCOMPLETE", "errors": [{"code": "EXPERIMENT_PROTOCOL_NOT_PROVIDED", "detail": hypothesis_id}]},
            })
            continue
        intervention = _protocol_value(protocol, "intervention", "treatment", "exposure")
        comparator = _protocol_value(protocol, "comparators", "comparator", "controls", "control_arms")
        readouts = _protocol_value(protocol, "readouts", "outcomes", "measurements", "metrics")
        failure = _protocol_value(protocol, "failure_criteria", "falsification_criteria", "falsification", "rejection_rule")
        contract = {
            "experiment_design_id": _safe_identifier(_first(protocol.get("experiment_design_id"), protocol.get("protocol_id"), f"experiment_{hypothesis_id}"), f"experiment_{hypothesis_id}"),
            "hypothesis_id": hypothesis_id,
            "design_type": _first(protocol.get("design_type"), protocol.get("research_mode"), _mapping(model.get("project")).get("research_mode"), "proposed_experiment"),
            "testbed": _protocol_value(protocol, "model_system", "testbed", "population", "dataset", "system"),
            "intervention": intervention,
            "comparators": comparator,
            "readouts": readouts,
            "analysis_plan": _protocol_value(protocol, "analysis", "analysis_plan", "statistical_analysis"),
            "falsification_conditions": failure,
            "replication_and_bias_controls": _protocol_value(protocol, "replication", "replication_plan", "bias_controls"),
            "source_unit_ids": _source_ids(protocol),
            "reported_as": "proposal_not_result",
            "status": "RECORDED",
            "summary": _compact_text(_first(hypothesis.get("test_plan"), "Recorded execution-level protocol."), 500),
        }
        contract["validation"] = validate_experiment_design_contract(contract)
        contracts.append(contract)
    return contracts


def validate_experiment_design_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("status") == "NOT_PROVIDED":
        return {"verdict": "INCOMPLETE", "errors": [{"code": "EXPERIMENT_PROTOCOL_NOT_PROVIDED", "detail": contract.get("hypothesis_id")}], "warnings": []}
    errors: list[dict[str, Any]] = []
    for field in ("testbed", "intervention", "comparators", "readouts", "falsification_conditions"):
        if not _text(contract.get(field)) and not _items(contract.get(field)) and not _mapping(contract.get(field)):
            errors.append({"code": "EXPERIMENT_CONTRACT_FIELD_MISSING", "detail": field})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": []}


def _evidence_claim_entries(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for card in cards:
        if card.get("evidence_role") in _NON_SUBSTANTIVE_CARD_ROLES:
            continue
        result.append({
            "claim_id": f"evidence_card_{card.get('evidence_card_id')}",
            "claim_kind": "evidence_card",
            "certainty": "source excerpt; scope limited to recorded context",
            "claim_text": card.get("claim_text"),
            "reference_keys": [card.get("reference_key")] if card.get("reference_key") else [],
            "source_unit_ids": [card.get("source_unit_id")] if card.get("source_unit_id") else [],
            "source_record_ids": card.get("source_record_ids", []),
            "conclusion_scope": "source-local statement; not a final-object result",
        })
    return result


def _rubric(model: dict[str, Any]) -> dict[str, Any]:
    cards = _dict_items(model.get("evidence_cards"))
    substantive = [card for card in cards if card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES]
    quantified = _dict_items(model.get("quantitative_anchors"))
    gaps = _dict_items(model.get("gaps"))
    hypotheses = _dict_items(model.get("hypotheses"))
    formalizations = _dict_items(model.get("formalizations"))
    experiments = _dict_items(model.get("experiment_designs"))
    scores = {
        "evidence_traceability": 25 if substantive and all(card.get("source_unit_id") for card in substantive) else (12 if cards else 0),
        "gap_specificity": 25 if gaps and all(_text(gap.get("description")) for gap in gaps) else (10 if gaps else 0),
        "testability": 20 if hypotheses and any(item.get("validation", {}).get("verdict") == "PASS" for item in experiments) else (8 if hypotheses else 0),
        "cross_sh_synthesis": 10 if any(item.get("status") == "COMBINABLE" for item in _dict_items(model.get("combined_gaps"))) else 5,
        "quantitative_anchors": 10 if quantified else 0,
        "formalization": 5 if any(item.get("validation", {}).get("verdict") == "PASS" for item in formalizations) else 0,
        "auditability": 5 if cards and model.get("argument_graph") else 0,
    }
    total = sum(scores.values())
    return {
        "maximum_score": 100,
        "score": total,
        "dimensions": scores,
        "publication_readiness": "READY_FOR_DESIGN_REVIEW" if total >= 75 else "NEEDS_EVIDENCE_OR_METHOD_ENRICHMENT",
        "interpretation": "This is a report-quality rubric, not a measure of scientific truth or experimental success.",
    }


def validate_full_research_design_model(model: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    cards = _dict_items(model.get("evidence_cards"))
    for card in cards:
        if card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES and not _text(card.get("source_unit_id")):
            errors.append({"code": "EVIDENCE_CARD_SOURCE_UNIT_MISSING", "detail": card.get("evidence_card_id")})
        if not _text(card.get("reference_key")):
            errors.append({"code": "EVIDENCE_CARD_REFERENCE_MISSING", "detail": card.get("evidence_card_id")})
    if cards and not any(card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES for card in cards):
        warnings.append({"code": "NO_SOURCE_EXCERPT_EVIDENCE_CARDS", "detail": "Only catalogue records are available; deep literature claims remain intentionally limited."})
    graph = _mapping(model.get("argument_graph"))
    node_ids = {_text(node.get("node_id")) for node in _dict_items(graph.get("nodes"))}
    for edge in _dict_items(graph.get("edges")):
        if _text(edge.get("source")) not in node_ids or _text(edge.get("target")) not in node_ids:
            errors.append({"code": "ARGUMENT_GRAPH_DANGLING_EDGE", "detail": edge.get("edge_id")})
    for combined in _dict_items(model.get("combined_gaps")):
        if combined.get("status") == "COMBINABLE" and not combined.get("compatibility_gate_passed"):
            errors.append({"code": "FORCED_COMBINED_GAP", "detail": combined.get("combined_gap_id")})
    for formalization in _dict_items(model.get("formalizations")):
        validation = _mapping(formalization.get("validation"))
        if validation.get("verdict") == "REJECT":
            warnings.append({"code": "FORMALIZATION_CONTRACT_REJECTED", "detail": validation.get("errors")})
    for experiment in _dict_items(model.get("experiment_designs")):
        validation = _mapping(experiment.get("validation"))
        if validation.get("verdict") == "REJECT":
            warnings.append({"code": "EXPERIMENT_CONTRACT_REJECTED", "detail": validation.get("errors")})
    return {
        "verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": warnings,
        "checks": {
            "evidence_cards_source_unit_bound": not any(item["code"] == "EVIDENCE_CARD_SOURCE_UNIT_MISSING" for item in errors),
            "argument_graph_closed": not any(item["code"] == "ARGUMENT_GRAPH_DANGLING_EDGE" for item in errors),
            "combined_gap_gate_respected": not any(item["code"] == "FORCED_COMBINED_GAP" for item in errors),
            "predictions_not_results": True,
        },
    }


def build_full_research_design_model(base_model: dict[str, Any]) -> dict[str, Any]:
    """Enrich a frozen traceability model without mutating it or the project."""
    model = deepcopy(base_model)
    model["schema_version"] = FULL_RESEARCH_DESIGN_SCHEMA_VERSION
    model["report_profile"] = FULL_RESEARCH_DESIGN_PROFILE
    cards, anchors = build_evidence_cards(model)
    model["evidence_cards"] = cards
    model["quantitative_anchors"] = anchors
    model["formalizations"] = build_formalization_contracts(model)
    model["experiment_designs"] = build_experiment_design_contracts(model)
    model["argument_graph"] = build_research_argument_graph(model)
    model["claim_evidence_ledger"] = _dict_items(model.get("claim_evidence_ledger")) + _evidence_claim_entries(cards)
    model["quality_rubric"] = _rubric(model)
    model["design_validation"] = validate_full_research_design_model(model)
    model.pop("report_model_hash", None)
    model["report_model_hash"] = _report_model_hash(model)
    return model


def _table(caption: str, label: str, headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    # Keep the total column width below one text width even for the seven-column
    # experiment contract matrix.  This is deliberately calculated from the
    # schema rather than tuned for one research domain or one title length.
    width = min(0.45, max(0.10, 0.92 / max(1, len(headers))))
    columns = "|".join(f"p{{{width:.3f}\\textwidth}}" for _ in headers)
    header = " & ".join(f"\\textbf{{{_latex_escape(item)}}}" for item in headers) + r" \\ \hline"
    body = "\n".join(" & ".join(row) + r" \\ \hline" for row in rows)
    return (
        "\\begin{table*}[t]\n\\centering\n\\scriptsize\n"
        f"\\caption{{{_latex_escape(caption)}}}\n\\label{{{_safe_identifier(label, 'table')}}}\n"
        f"\\begin{{tabular}}{{|{columns}|}}\n\\hline\n{header}\n{body}\n"
        "\\end{tabular}\n\\end{table*}\n"
    )


def _metadata(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    title = _latex_escape(project.get("title") or "Evidence-Bounded Research Design Report")
    return (
        f"\\title{{{title}\\\\\n{{\\footnotesize Evidence-bounded full research-design report}}}}\n"
        "\\author{\\IEEEauthorblockN{Research Design Report}\\n"
        "\\IEEEauthorblockA{Generated from a frozen AI-for-Science project snapshot\\\\\n"
        "Claims, equations, and protocols remain scoped to their recorded evidence and planning status.}}\n"
        "\\maketitle\n"
    )


def _render_abstract(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    rubric = _mapping(model.get("quality_rubric"))
    counts = _mapping(model.get("source_project_fields"))
    return (
        "\\begin{abstract}\n"
        f"This report documents a frozen research-design process for {_latex_escape(project.get('objective'))}. "
        f"It audits {counts.get('sub_hypothesis_count', 0)} subhypotheses, {counts.get('papergraph_count', 0)} literature records, "
        f"{len(_items(model.get('evidence_cards')))} evidence cards, {len(_items(model.get('gaps')))} gaps, and "
        f"{len(_items(model.get('hypotheses')))} hypotheses. The report builds a source-to-test argument graph, separates established "
        "source-local statements from proposed mechanisms and tests, and retains missing evidence or incomplete methods as explicit limitations. "
        f"Its design-review readiness is {_latex_escape(rubric.get('publication_readiness'))}; this is not an experimental result or final-object validation.\n"
        "\\end{abstract}\n"
    )


def _render_status(model: dict[str, Any]) -> str:
    validation = _mapping(model.get("design_validation"))
    rubric = _mapping(model.get("quality_rubric"))
    rows = [
        ["Report profile", FULL_RESEARCH_DESIGN_PROFILE],
        ["Frozen snapshot", _latex_cell(model.get("project_snapshot_hash"), 250)],
        ["Traceability model audit", _latex_cell(_mapping(model.get("model_validation")).get("verdict"), 120)],
        ["Design-profile audit", _latex_cell(validation.get("verdict"), 120)],
        ["Quality score", f"{rubric.get('score', 0)}/{rubric.get('maximum_score', 100)}"],
        ["Research-result boundary", "All hypotheses, equations, expected observations, and protocols are proposals unless frozen evidence records otherwise."],
    ]
    return "\\section{Research Status, Scope, and Claims Boundary}\n" + _table(
        "Frozen project status and the boundary between research design and results.", "tab:design_status", ["Item", "Recorded status"], rows
    ) + (
        "A component or bridge evidence path may motivate a hypothesis and its subsequent Socratic enrichment, but it does not validate the final research object. "
        "Predicted observations are retained as falsifiable expectations, never rewritten as findings.\n"
    )


def _render_research_question(model: dict[str, Any]) -> str:
    project = _mapping(model.get("project"))
    sh_rows = [[_latex_cell(sh.get("sub_hypothesis_id"), 70), _latex_cell(sh.get("scientific_object"), 150), _latex_cell(sh.get("title"), 300)] for sh in _dict_items(model.get("sub_hypotheses"))]
    return (
        "\\section{Research Question and Scoped Decomposition}\n"
        f"\\textbf{{Research objective.}} {_latex_escape(project.get('objective'))}\n"
        "The question is decomposed into bounded subhypotheses so that source evidence, gaps, and proposed tests can be traced without asserting that their combination has been validated.\n"
        + _table("Subhypothesis overview.", "tab:design_sh_overview", ["SH", "Scientific object", "Scoped question"], sh_rows)
    )


def _render_evidence_matrix(model: dict[str, Any]) -> str:
    rows: list[list[str]] = []
    for card in _dict_items(model.get("evidence_cards")):
        rows.append([
            _latex_cell(card.get("evidence_card_id"), 150), _latex_cell(card.get("reference_key"), 130),
            _latex_cell(", ".join(_unique(_items(card.get("sub_hypothesis_ids")))) or "project-level", 100),
            _latex_cell(card.get("evidence_role"), 100), _latex_cell(card.get("claim_text"), 300),
            _latex_cell(card.get("source_unit_id") or "missing", 150),
        ])
    return "\\section{Literature Evidence Matrix}\n" + (
        "Each row is an Evidence Card. A source-excerpt card can support only its source-local statement; a catalogue-record card can support only bibliographic traceability and is not promoted into a finding.\n"
    ) + _table("Source-unit evidence-card matrix.", "tab:evidence_cards", ["Card", "Citation", "SH", "Role", "Recorded local statement", "Source unit"], rows)


def _render_gap_matrix(model: dict[str, Any]) -> str:
    rows: list[list[str]] = []
    for gap in _dict_items(model.get("gaps")):
        rows.append([
            _latex_cell(gap.get("gap_id"), 120), _latex_cell(gap.get("sub_hypothesis_id"), 80),
            _latex_cell(gap.get("availability"), 130), _latex_cell(gap.get("input") or "not resolved", 120),
            _latex_cell(gap.get("outcome") or "not resolved", 120), _latex_cell(gap.get("falsification") or "not resolved", 220),
            _latex_cell(gap.get("scope"), 150),
        ])
    return "\\section{Gap Matrix and Availability Conditions}\n" + (
        "The matrix reports the recorded causal slots and admissibility state. Empty or unresolved slots remain visible as limitations; the report does not derive a gap merely from topical similarity.\n"
    ) + _table("Per-SH gap matrix.", "tab:design_gap_matrix", ["Gap", "SH", "Availability", "Input", "Outcome", "Falsifier", "Scope"], rows)


def _render_iterative_synthesis(model: dict[str, Any]) -> str:
    rows = []
    for item in _dict_items(model.get("iterations")):
        rows.append([_latex_cell(item.get("stage"), 135), _latex_cell(item.get("identifier"), 100), _latex_cell(item.get("outcome"), 350), _latex_cell(item.get("timestamp"), 80)])
    return "\\section{Iterative Evidence Synthesis and Review Trail}\n" + (
        "This timeline is a workflow trace.  It records when a design artifact was created or reviewed; it does not establish the artifact as true.\n"
    ) + _table("Frozen research-process iteration trail.", "tab:design_iteration_trail", ["Stage", "Identifier", "Recorded outcome", "Time"], rows)


def _cards_for_sh(model: dict[str, Any], sh_id: str) -> list[dict[str, Any]]:
    cards = []
    reference_keys = {key for sh in _dict_items(model.get("sub_hypotheses")) if _text(sh.get("sub_hypothesis_id")) == sh_id for key in _items(sh.get("reference_keys"))}
    for card in _dict_items(model.get("evidence_cards")):
        if sh_id in _unique(_items(card.get("sub_hypothesis_ids"))) or _text(card.get("reference_key")) in reference_keys:
            cards.append(card)
    return cards


def _render_sh_deep_review(model: dict[str, Any], sh: dict[str, Any]) -> tuple[str, str]:
    sh_id = _text(sh.get("sub_hypothesis_id"))
    cards = _cards_for_sh(model, sh_id)
    gaps = [gap for gap in _dict_items(model.get("gaps")) if _text(gap.get("sub_hypothesis_id")) == sh_id]
    hypotheses = [hypothesis for hypothesis in _dict_items(model.get("hypotheses")) if _text(hypothesis.get("sub_hypothesis_id")) == sh_id]
    section = [f"\\section{{{_latex_escape(sh_id)}: Deep Evidence-to-Test Review}}\n"]
    section.append("\\subsection{What Is Established in the Frozen Record}\n")
    substantive = [card for card in cards if card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES]
    if substantive:
        section.append("\\begin{itemize}\n")
        for card in substantive[:12]:
            section.append(f"\\item {_latex_escape(card.get('claim_text'))}{_latex_citations([_text(card.get('reference_key'))])} "
                           f"[source unit: \\texttt{{{_latex_escape(card.get('source_unit_id'))}}}]\n")
        section.append("\\end{itemize}\n")
    else:
        section.append("No source excerpt was preserved for this SH. The bibliography is retained, but the report intentionally does not turn its metadata into an established scientific finding.\n")
    section.append("\\subsection{Precise Gap}\n")
    if gaps:
        for gap in gaps:
            section.append(f"\\textbf{{{_latex_escape(gap.get('gap_id'))}.}} {_latex_escape(gap.get('description'))}{_latex_citations(_unique(_items(gap.get('reference_keys'))))} "
                           f"Availability: \\texttt{{{_latex_escape(gap.get('availability'))}}}.\n")
            if _text(gap.get("disclaimer")):
                section.append(f"\\emph{{Scope limit: {_latex_escape(gap.get('disclaimer'))}}}\n")
    else:
        section.append("No gap was recorded for this SH in the frozen snapshot.\n")
    section.append("\\subsection{Researchable Claim}\n")
    if hypotheses:
        for hypothesis in hypotheses:
            section.append(f"\\textbf{{{_latex_escape(hypothesis.get('hypothesis_id'))}.}} {_latex_escape(hypothesis.get('statement'))}{_latex_citations(_unique(_items(hypothesis.get('reference_keys'))))}\n")
            if _text(hypothesis.get("disclaimer")):
                section.append(f"\\emph{{Scope limit: {_latex_escape(hypothesis.get('disclaimer'))}}}\n")
    else:
        section.append("No hypothesis has been recorded for this SH; no claim is proposed here.\n")
    section.append("\\subsection{Quantitative Test and Falsifier}\n")
    contracts = [item for item in _dict_items(model.get("experiment_designs")) if _text(item.get("hypothesis_id")) in {_text(h.get("hypothesis_id")) for h in hypotheses}]
    anchors = [anchor for anchor in _dict_items(model.get("quantitative_anchors")) if anchor.get("evidence_card_id") in {card.get("evidence_card_id") for card in cards}]
    if anchors:
        section.append("Reported numeric anchors below remain local to their cited source conditions and are not effect-size predictions.\n\\begin{itemize}\n")
        for anchor in anchors[:10]:
            section.append(f"\\item {_latex_escape(anchor.get('value'))} {_latex_escape(anchor.get('unit'))}: {_latex_escape(anchor.get('condition'))} "
                           f"[source unit: \\texttt{{{_latex_escape(anchor.get('source_unit_id'))}}}]\n")
        section.append("\\end{itemize}\n")
    for contract in contracts:
        validation = _mapping(contract.get("validation"))
        if validation.get("verdict") == "PASS":
            section.append(f"Proposed testbed: {_latex_escape(contract.get('testbed'))}; intervention: {_latex_escape(contract.get('intervention'))}; "
                           f"comparator: {_latex_escape(contract.get('comparators'))}; readouts: {_latex_escape(contract.get('readouts'))}; "
                           f"falsifier: {_latex_escape(contract.get('falsification_conditions'))}. This is a proposed design, not a result.\n")
        else:
            section.append(f"For {_latex_escape(contract.get('hypothesis_id'))}, the execution-level experiment contract is {_latex_escape(contract.get('status'))}; "
                           "a testbed, comparator, readout, or falsifier remains incomplete and is not fabricated.\n")
    key = f"sh_{_safe_identifier(sh_id, 'unknown')}_deep_review"
    return key, "".join(section)


def _render_cross_sh(model: dict[str, Any]) -> str:
    content = ["\\section{Cross-Subhypothesis Synthesis}\n"]
    combined = _dict_items(model.get("combined_gaps"))
    rows = []
    for item in combined:
        rows.append([
            _latex_cell(item.get("combined_gap_id"), 130), _latex_cell(", ".join(_unique(_items(item.get("declared_gap_ids")))), 140),
            _latex_cell(item.get("status"), 100), _latex_cell(item.get("compatibility_reason"), 360),
        ])
    content.append(_table("Compatibility assessment for proposed cross-SH synthesis.", "tab:cross_sh_compatibility", ["Combination", "Member gaps", "Status", "Recorded rationale"], rows))
    for item in combined:
        if item.get("status") != "COMBINABLE":
            content.append(f"\\textbf{{{_latex_escape(item.get('combined_gap_id'))}.}} The frozen record does not authorize a combined gap; its member gaps remain separate.\n")
        else:
            allowed = ", ".join(_unique(_items(item.get("allowed_scope")))) or "recorded local scope only"
            forbidden = ", ".join(_unique(_items(item.get("forbidden_scope")))) or "no unstated final-object conclusion"
            content.append(f"\\textbf{{{_latex_escape(item.get('combined_gap_id'))}.}} Combination is limited to { _latex_escape(allowed) }; forbidden scope: {_latex_escape(forbidden)}.\n")
    if not combined:
        content.append("No cross-SH combination was recorded. The report therefore does not infer one.\n")
    return "".join(content)


def _render_hypothesis_matrix(model: dict[str, Any]) -> str:
    rows = []
    for hypothesis in _dict_items(model.get("hypotheses")):
        rows.append([
            _latex_cell(hypothesis.get("hypothesis_id"), 110), _latex_cell(hypothesis.get("gap_id"), 110),
            _latex_cell(hypothesis.get("sub_hypothesis_id"), 80), _latex_cell(hypothesis.get("statement"), 310),
            _latex_cell(hypothesis.get("status"), 80),
        ])
    return "\\section{Generated Hypotheses and Claim Scope}\n" + _table(
        "Hypothesis matrix. Entries are proposed claims, not validated results.", "tab:design_hypotheses",
        ["Hypothesis", "Gap", "SH", "Proposed statement", "Workflow status"], rows
    ) + "Every hypothesis remains tied to the cited gap and its recorded limitations.\n"


def _render_formalizations(model: dict[str, Any]) -> str:
    content = ["\\section{Formalization Contracts}\n"]
    for item in _dict_items(model.get("formalizations")):
        validation = _mapping(item.get("validation"))
        content.append(f"\\subsection{{{_latex_escape(item.get('formalization_id'))} for {_latex_escape(item.get('hypothesis_id'))}}}\n")
        if validation.get("verdict") == "PASS" and _text(item.get("equation_latex")):
            content.append("The following expression is a recorded formalization or proposed design; it is not a fitted or experimentally confirmed result.\n")
            content.append("\\begin{equation}\n" + _text(item.get("equation_latex")) + "\n\\end{equation}\n")
            rows = [[_latex_cell(symbol.get("symbol"), 90), _latex_cell(symbol.get("meaning"), 280), _latex_cell(symbol.get("unit_or_domain"), 130)] for symbol in _dict_items(item.get("symbols"))]
            content.append(_table("Declared symbols for the formalization.", f"tab:{item.get('formalization_id')}", ["Symbol", "Meaning", "Unit/domain"], rows))
            content.append("Assumptions: " + _latex_escape("; ".join(_unique(_items(item.get("assumptions")))) or "not recorded") + ". Falsification conditions: " + _latex_escape("; ".join(_unique(_items(item.get("falsification_conditions")))) or "not recorded") + ".\n")
        else:
            content.append("No renderable, internally complete formalization contract is available. The report does not invent an equation, symbol definitions, or a falsifier.\n")
    return "".join(content)


def _render_experiments(model: dict[str, Any]) -> str:
    rows = []
    for item in _dict_items(model.get("experiment_designs")):
        validation = _mapping(item.get("validation"))
        rows.append([
            _latex_cell(item.get("hypothesis_id"), 100), _latex_cell(item.get("design_type"), 110), _latex_cell(item.get("testbed"), 150),
            _latex_cell(item.get("intervention"), 150), _latex_cell(item.get("comparators"), 150), _latex_cell(item.get("readouts"), 150),
            _latex_cell("ready" if validation.get("verdict") == "PASS" else item.get("status"), 100),
        ])
    return "\\section{Feasible Experiment Designs and Expected Discriminators}\n" + (
        "The following are design contracts. Their readouts and falsification conditions are expected discriminators, not observed results. "
        "An incomplete contract is a visible request for methodological completion rather than a silently filled protocol.\n"
    ) + _table("Experiment-design contract matrix.", "tab:design_experiments", ["Hypothesis", "Design", "Testbed", "Intervention", "Comparator", "Readout", "Contract state"], rows)


def _render_argument_graph(model: dict[str, Any]) -> str:
    graph = _mapping(model.get("argument_graph"))
    rows = []
    for edge in _dict_items(graph.get("edges")):
        rows.append([_latex_cell(edge.get("source"), 180), _latex_cell(edge.get("relation"), 130), _latex_cell(edge.get("target"), 180), _latex_cell(", ".join(_unique(_items(edge.get("source_unit_ids")))), 150)])
    return "\\section{Research Argument Graph}\n" + (
        "The graph makes the reasoning chain auditable: evidence cards may support a local SH scope; gaps require testing; hypotheses operationalize gaps; and test contracts can falsify hypotheses. "
        "No edge is an assertion of final-object validation.\n"
    ) + _table("Directed source-to-test argument edges.", "tab:argument_graph", ["Source", "Relation", "Target", "Source unit"], rows)


def _render_reproducibility(model: dict[str, Any]) -> str:
    cards = _dict_items(model.get("evidence_cards"))
    missing = [card for card in cards if card.get("provenance_status") != "SOURCE_UNIT_BOUND"]
    return (
        "\\section{Reproducibility, Audit Package, and Remaining Limitations}\n"
        "The deliverable preserves the frozen snapshot, normalized report model, claim--evidence ledger, evidence cards, quantitative-anchor registry, argument graph, section-level narrative review trail, and compilation/visual-QA reports. "
        f"There are {len(missing)} evidence card(s) without an explicit source-unit binding. Such cards are excluded from substantive literature synthesis. "
        "Reference citations identify bibliography records, while \\texttt{source\\_unit\\_id} identifies the local evidence location required to audit a substantive claim.\n"
    )


def _render_conclusion(model: dict[str, Any]) -> str:
    rubric = _mapping(model.get("quality_rubric"))
    return (
        "\\section{Conclusion and Next Review Action}\n"
        f"The frozen project is rendered as an evidence-bounded design report with an audit score of {rubric.get('score', 0)}/100. "
        "The appropriate next action is determined by its visible deficits: add source excerpts and source-local quantitative anchors where only catalogue metadata exists; complete comparators, readouts, and falsifiers for incomplete protocols; and supply declared-symbol formalizations only when justified by the project. "
        "After those additions, the same chapter-local writer/reviewer loop can be rerun. This document does not state that an object, mechanism, or prediction has been experimentally verified.\n"
    )


FULL_SECTION_ORDER = (
    "metadata", "abstract", "research_status", "research_question", "evidence_matrix", "gap_matrix", "iterative_synthesis",
)


def full_research_design_section_order(model: dict[str, Any]) -> list[str]:
    return list(FULL_SECTION_ORDER) + [
        f"sh_{_safe_identifier(sh.get('sub_hypothesis_id'), 'unknown')}_deep_review" for sh in _dict_items(model.get("sub_hypotheses"))
    ] + [
        "cross_sh_synthesis", "hypothesis_matrix", "formalization_contracts", "experiment_designs",
        "argument_graph", "reproducibility", "conclusion",
    ]


def _section_context(model: dict[str, Any], section_id: str) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    """Return only a chapter-local evidence package; never forward raw project logs."""
    ledger = _dict_items(model.get("claim_evidence_ledger"))
    cards = _dict_items(model.get("evidence_cards"))
    selected_cards: list[dict[str, Any]] = []
    if section_id.startswith("sh_") and section_id.endswith("_deep_review"):
        sh_id = section_id[len("sh_"):-len("_deep_review")]
        # Safe ids are normally the original SH IDs; use both to cope with punctuation.
        selected_cards = [card for card in cards if _safe_identifier(card.get("sub_hypothesis_ids", [""])[0] if _items(card.get("sub_hypothesis_ids")) else "", "") == sh_id]
        gaps = [item for item in _dict_items(model.get("gaps")) if _safe_identifier(item.get("sub_hypothesis_id"), "") == sh_id]
        hypotheses = [item for item in _dict_items(model.get("hypotheses")) if _safe_identifier(item.get("sub_hypothesis_id"), "") == sh_id]
        facts: dict[str, Any] = {"evidence_cards": selected_cards, "gaps": gaps, "hypotheses": hypotheses}
    elif section_id == "evidence_matrix":
        selected_cards = cards
        facts = {"evidence_cards": selected_cards, "quantitative_anchors": _dict_items(model.get("quantitative_anchors"))}
    elif section_id == "gap_matrix":
        gaps = _dict_items(model.get("gaps"))
        facts = {"gaps": gaps, "subhypotheses": _dict_items(model.get("sub_hypotheses"))}
        selected_cards = [card for card in cards if _text(card.get("reference_key")) in {
            key for gap in gaps for key in _items(gap.get("reference_keys"))
        }]
    elif section_id == "cross_sh_synthesis":
        gaps = _dict_items(model.get("gaps"))
        facts = {"combined_gaps": _dict_items(model.get("combined_gaps")), "gaps": gaps}
        selected_cards = [card for card in cards if _text(card.get("reference_key")) in {
            key for gap in gaps for key in _items(gap.get("reference_keys"))
        }]
    elif section_id == "hypothesis_matrix":
        hypotheses = _dict_items(model.get("hypotheses"))
        facts = {"hypotheses": hypotheses, "gaps": _dict_items(model.get("gaps"))}
        selected_cards = [card for card in cards if _text(card.get("reference_key")) in {
            key for hypothesis in hypotheses for key in _items(hypothesis.get("reference_keys"))
        }]
    elif section_id == "formalization_contracts":
        facts = {"formalizations": _dict_items(model.get("formalizations"))}
    elif section_id == "experiment_designs":
        facts = {"experiment_designs": _dict_items(model.get("experiment_designs")), "hypotheses": _dict_items(model.get("hypotheses"))}
    elif section_id == "argument_graph":
        facts = {"argument_graph": _mapping(model.get("argument_graph"))}
    elif section_id == "iterative_synthesis":
        facts = {"iterations": _dict_items(model.get("iterations"))[:60]}
    else:
        facts = {"project": _mapping(model.get("project")), "quality_rubric": _mapping(model.get("quality_rubric")), "counts": _mapping(model.get("source_project_fields"))}
    keys = _unique(card.get("reference_key") for card in selected_cards if card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES)
    if not keys and section_id in {"research_question", "iterative_synthesis", "hypothesis_matrix"}:
        keys = _unique(key for claim in ledger for key in _items(claim.get("reference_keys")))[:12]
    claims = [claim for claim in ledger if not keys or any(key in keys for key in _items(claim.get("reference_keys")))]
    claim_ids = _unique(claim.get("claim_id") for claim in claims)
    disclaimers = _unique(
        item.get("disclaimer") for item in _dict_items(model.get("gaps")) + _dict_items(model.get("hypotheses")) + _dict_items(model.get("combined_gaps"))
        if _text(item.get("disclaimer"))
    ) if section_id in {"cross_sh_synthesis", "experiment_designs", "hypothesis_matrix"} or section_id.startswith("sh_") else []
    return {"facts": facts, "admissible_claims": claims}, keys, claim_ids, disclaimers


def _call_writer(
    llm_callable: Callable[..., dict[str, Any]] | None, *, section_id: str, context: dict[str, Any], keys: list[str], claim_ids: list[str], disclaimers: list[str], feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    if llm_callable is None:
        try:
            from ._llm import call_llm_json
        except ImportError:  # pragma: no cover
            from _llm import call_llm_json
        llm_callable = call_llm_json
    response = llm_callable(
        system=(
            "Role: chapter writer. Write one English research-design paragraph using only the supplied local evidence package. "
            "Never introduce methods, numbers, results, causal conclusions, or references absent from it. A source-local factual statement must use [[CITE:key]]. "
            "Call every hypothesis, equation, and experiment a proposal unless the input explicitly says otherwise; no final-object validation claims. Return JSON only."
        ),
        prompt=(
            f"Write section '{section_id}'. Allowed citation keys: {keys}. Allowed claim IDs: {claim_ids}. "
            f"Required scope disclaimers (verbatim if listed): {disclaimers}. Prior reviewer feedback: {feedback[-8:]}.\n"
            f"LOCAL_EVIDENCE_PACKAGE:\n{json.dumps(context, ensure_ascii=False, default=str)[:22000]}\n"
            "Return exactly {\"section_id\":\"...\",\"text\":\"...\",\"citation_keys\":[...],\"claim_ids\":[...],\"self_critique\":\"...\"}."
        ),
        max_tokens=1200,
    )
    return response if isinstance(response, dict) else {}


def _call_reviewer(llm_callable: Callable[..., dict[str, Any]] | None, *, section_id: str, proposal: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if llm_callable is None:
        try:
            from ._llm import call_llm_json
        except ImportError:  # pragma: no cover
            from _llm import call_llm_json
        llm_callable = call_llm_json
    response = llm_callable(
        system=(
            "Role: independent evidence and methods reviewer. Review only the supplied local package and proposed paragraph. "
            "Reject unsupported factual claims, invented methods/numbers, result language, or scope expansion. Return JSON only; do not rewrite the chapter."
        ),
        prompt=(
            f"Review section '{section_id}'. LOCAL_EVIDENCE_PACKAGE:\n{json.dumps(context, ensure_ascii=False, default=str)[:18000]}\n"
            f"PROPOSED_PARAGRAPH:\n{json.dumps(proposal, ensure_ascii=False, default=str)[:8000]}\n"
            "Return exactly {\"section_id\":\"...\",\"verdict\":\"PASS|REVISE\",\"issues\":[{\"code\":\"...\",\"detail\":\"...\"}],\"revision_instructions\":\"...\",\"rubric\":{\"evidence\":0,\"methods\":0,\"scope\":0,\"clarity\":0}}."
        ),
        max_tokens=700,
    )
    return response if isinstance(response, dict) else {}


def _review_writer_proposal(proposal: dict[str, Any], *, section_id: str, allowed_keys: list[str], allowed_claim_ids: list[str], disclaimers: list[str], reviewer: dict[str, Any]) -> dict[str, Any]:
    audit = audit_report_narrative(proposal, section_id=section_id, allowed_keys=allowed_keys, allowed_claim_ids=allowed_claim_ids, required_scope_disclaimers=disclaimers)
    reviewer_verdict = _text(reviewer.get("verdict")).upper()
    reviewer_issues = _dict_items(reviewer.get("issues"))
    if reviewer and (_text(reviewer.get("section_id")) != section_id or reviewer_verdict not in {"PASS", "REVISE"}):
        reviewer_issues.append({"code": "REVIEWER_RESPONSE_INVALID", "detail": "Reviewer response did not follow the review contract."})
    rejected_by_reviewer = reviewer_verdict == "REVISE" or bool(reviewer_issues)
    failures = _dict_items(audit.get("failures")) + reviewer_issues
    return {
        "verdict": "PASS" if audit.get("hard_gate_passed") and not rejected_by_reviewer else "REVISE",
        "hard_gate_passed": bool(audit.get("hard_gate_passed") and not rejected_by_reviewer),
        "writer_audit": audit, "reviewer": reviewer,
        "failures": failures,
    }


def _refine_full_sections(model: dict[str, Any], sections: dict[str, str], *, llm_callable: Callable[..., dict[str, Any]] | None, max_retries: int, max_review_rounds: int) -> tuple[dict[str, str], dict[str, Any]]:
    audits: dict[str, Any] = {}
    retries = max(0, min(MAX_NARRATIVE_RETRIES, int(max_retries or 0)))
    review_rounds = max(1, min(MAX_DESIGN_REVIEW_ROUNDS, int(max_review_rounds or 1)))
    for section_id in full_research_design_section_order(model):
        if section_id == "metadata":
            continue
        context, keys, claim_ids, disclaimers = _section_context(model, section_id)
        # No literature keys are valid for pure status/reproducibility chapters;
        # their deterministic content remains the safe fallback.
        attempts: list[dict[str, Any]] = []
        feedback: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        total_attempts = retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                proposal = _call_writer(llm_callable, section_id=section_id, context=context, keys=keys, claim_ids=claim_ids, disclaimers=disclaimers, feedback=feedback)
                reviewer: dict[str, Any] = {}
                review_history: list[dict[str, Any]] = []
                for review_round in range(1, review_rounds + 1):
                    reviewer = _call_reviewer(llm_callable, section_id=section_id, proposal=proposal, context=context)
                    review_history.append({"round": review_round, "review": reviewer})
                    if _text(reviewer.get("verdict")).upper() == "PASS" and not _dict_items(reviewer.get("issues")):
                        break
                review = _review_writer_proposal(proposal, section_id=section_id, allowed_keys=keys, allowed_claim_ids=claim_ids, disclaimers=disclaimers, reviewer=reviewer)
                attempts.append({"attempt": attempt, "proposal": proposal, "review_history": review_history, "review": review})
                if review.get("hard_gate_passed"):
                    selected = attempts[-1]
                    sections[section_id] += "\\paragraph{Audited Chapter Refinement.} " + _narrative_to_latex(_text(proposal.get("text"))) + "\n"
                    break
                feedback = [{"code": item.get("code"), "detail": item.get("detail")} for item in _dict_items(review.get("failures"))]
            except Exception as exc:  # Do not fail the deterministic report because an LLM is unavailable.
                attempts.append({"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
                feedback = [{"code": "DESIGN_WRITER_OR_REVIEWER_FAILED", "detail": attempts[-1]["error"]}]
        audits[section_id] = {
            "status": "SELECTED" if selected else "DETERMINISTIC_FALLBACK",
            "writer_attempt_count": len(attempts), "max_review_rounds": review_rounds, "attempts": attempts,
        }
    return sections, {"status": "COMPLETED", "sections": audits, "process": "chapter_local_writer_reviewer_loop"}


def render_full_research_design_sections(model: dict[str, Any], *, use_llm: bool = False, llm_callable: Callable[..., dict[str, Any]] | None = None, max_narrative_retries: int = MAX_NARRATIVE_RETRIES, max_review_rounds: int = MAX_DESIGN_REVIEW_ROUNDS) -> tuple[dict[str, str], dict[str, Any]]:
    """Render deterministic full-profile chapters and optional audited refinements."""
    sections: dict[str, str] = {
        "metadata": _metadata(model), "abstract": _render_abstract(model), "research_status": _render_status(model),
        "research_question": _render_research_question(model), "evidence_matrix": _render_evidence_matrix(model),
        "gap_matrix": _render_gap_matrix(model), "iterative_synthesis": _render_iterative_synthesis(model),
    }
    for sh in _dict_items(model.get("sub_hypotheses")):
        key, body = _render_sh_deep_review(model, sh)
        sections[key] = body
    sections.update({
        "cross_sh_synthesis": _render_cross_sh(model), "hypothesis_matrix": _render_hypothesis_matrix(model),
        "formalization_contracts": _render_formalizations(model), "experiment_designs": _render_experiments(model),
        "argument_graph": _render_argument_graph(model), "reproducibility": _render_reproducibility(model), "conclusion": _render_conclusion(model),
    })
    audit: dict[str, Any] = {"status": "NOT_REQUESTED", "sections": {}}
    if use_llm:
        sections, audit = _refine_full_sections(model, sections, llm_callable=llm_callable, max_retries=max_narrative_retries, max_review_rounds=max_review_rounds)
    return sections, audit


def validate_full_research_design_render(model: dict[str, Any], sections: dict[str, str]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    text = "\n".join(sections.values())
    for required in full_research_design_section_order(model):
        if required not in sections or not _text(sections.get(required)):
            errors.append({"code": "FULL_REPORT_REQUIRED_SECTION_MISSING", "detail": required})
    if _CJK_RE.search(text):
        errors.append({"code": "FULL_REPORT_NOT_ENGLISH", "detail": "CJK characters detected."})
    if _contains_unsafe_validation_overclaim(text):
        errors.append({"code": "FULL_REPORT_OVERCLAIMS_VALIDATION", "detail": "Unsafe validation language."})
    if _RESULT_OVERCLAIM_RE.search(text):
        errors.append({"code": "FULL_REPORT_TREATS_PREDICTION_AS_RESULT", "detail": "Observed-result language."})
    keys = {_text(reference.get("reference_key")) for reference in _dict_items(model.get("references"))}
    cited = _unique(key for block in re.findall(r"\\cite\{([^}]+)\}", text) for key in block.split(","))
    unknown = [key for key in cited if key not in keys]
    if unknown:
        errors.append({"code": "FULL_REPORT_UNKNOWN_CITATION", "detail": unknown})
    for card in _dict_items(model.get("evidence_cards")):
        if card.get("evidence_role") not in _NON_SUBSTANTIVE_CARD_ROLES and _latex_escape(card.get("source_unit_id")) not in text:
            errors.append({"code": "FULL_REPORT_EVIDENCE_CARD_OMITTED", "detail": card.get("evidence_card_id")})
    for subhypothesis in _dict_items(model.get("sub_hypotheses")):
        if _latex_escape(subhypothesis.get("sub_hypothesis_id")) not in text:
            errors.append({"code": "FULL_REPORT_SUBHYPOTHESIS_OMITTED", "detail": subhypothesis.get("sub_hypothesis_id")})
    for gap in _dict_items(model.get("gaps")):
        if _latex_escape(gap.get("gap_id")) not in text:
            errors.append({"code": "FULL_REPORT_GAP_OMITTED", "detail": gap.get("gap_id")})
        if gap.get("availability") == "AVAILABLE_RESTRICTED_COMPONENT_BRIDGE" and _text(gap.get("disclaimer")) and _text(gap.get("disclaimer")) not in text:
            errors.append({"code": "FULL_REPORT_BRIDGE_DISCLAIMER_OMITTED", "detail": gap.get("gap_id")})
    for hypothesis in _dict_items(model.get("hypotheses")):
        if _latex_escape(hypothesis.get("hypothesis_id")) not in text:
            errors.append({"code": "FULL_REPORT_HYPOTHESIS_OMITTED", "detail": hypothesis.get("hypothesis_id")})
        if _text(hypothesis.get("disclaimer")) and _text(hypothesis.get("disclaimer")) not in text:
            errors.append({"code": "FULL_REPORT_HYPOTHESIS_DISCLAIMER_OMITTED", "detail": hypothesis.get("hypothesis_id")})
    if not _dict_items(model.get("quantitative_anchors")):
        warnings.append({"code": "FULL_REPORT_NO_QUANTITATIVE_ANCHORS", "detail": "No source-local numeric anchor was supplied."})
    if _mapping(model.get("design_validation")).get("verdict") != "PASS":
        errors.append({"code": "FULL_REPORT_MODEL_AUDIT_FAILED", "detail": _mapping(model.get("design_validation")).get("errors")})
    return {"verdict": "PASS" if not errors else "REJECT", "errors": errors, "warnings": warnings, "citation_keys": cited,
            "checks": {"chapter_contracts": True, "evidence_cards_checked": True, "argument_graph_checked": True, "prediction_result_boundary_checked": True,
                       "all_subhypotheses_rendered": not any(item.get("code") == "FULL_REPORT_SUBHYPOTHESIS_OMITTED" for item in errors)}}
