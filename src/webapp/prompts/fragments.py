"""Deterministic task-axis rules frozen into each document Job input."""

from typing import Any, Mapping

from ..jobs.store import canonical_hash


SECTION_RULES = {
    "abstract": "Preserve the objective, methods, key numerical results, and conclusion relationships.",
    "introduction": "Keep the established evidence, research gap, and study objective distinct.",
    "results": "Report supplied observations and statistics without adding mechanisms or interpretations.",
    "discussion": "Retain limitations, uncertainty, alternatives, and the distinction between association and causation.",
    "conclusion": "Keep the conclusion within the supplied results; add no generalization or new evidence.",
    "methods": "Preserve all experimental conditions, ordered steps, parameters, units, and reproducibility details.",
    "title": "State the supplied study scope precisely without adding causal or priority claims.",
}
STYLE_RULES = {
    "clear": "Use direct sentences and one main point per paragraph.",
    "concise": "Remove repetition while retaining every factual proposition and necessary qualification.",
    "formal": "Use precise academic register without inflated vocabulary or promotional claims.",
    "native_academic": "Use idiomatic academic phrasing while retaining the author's argument and evidence strength.",
}


def compile_rules(kind: str, request: Mapping[str, Any]) -> dict[str, Any]:
    rules = []
    language = request.get("target_language")
    if language:
        rules.append(f"Write the candidate text in {'Simplified Chinese' if language == 'zh-CN' else 'English'}.")
    if kind == "polish":
        rules.extend(SECTION_RULES[section] for section in request.get("section", []) if section in SECTION_RULES)
        rules.append(STYLE_RULES.get(request.get("style_profile"), STYLE_RULES["clear"]))
        if request.get("paper_type") == "proposal":
            rules.append("Describe proposed work as planned work; do not convert expected outcomes into completed findings.")
        elif request.get("paper_type") == "review":
            rules.append("Attribute findings to their supplied sources and distinguish synthesis from original experiments.")
    if kind == "translation":
        rules.append("Translate all supplied prose without summarizing, omitting, or adding scientific content.")
        rules.append("Copy every LOCK marker exactly once. Introduce no new numerical values or scientific identifiers.")
    if str(request.get("target_journal", "")).casefold().startswith("nature"):
        rules.append("Use concise Nature-family academic wording while preserving the actual study design and evidence strength.")
    snapshot = {"version": "1.0.0", "rules": rules}
    return {**snapshot, "sha256": canonical_hash(snapshot)}


def apply_rules(messages: list[dict[str, object]], snapshot: Mapping[str, Any]) -> list[dict[str, object]]:
    value = {"version": snapshot.get("version"), "rules": snapshot.get("rules")}
    if snapshot.get("sha256") != canonical_hash(value):
        raise ValueError("Frozen task-axis rules no longer match their hash.")
    system = str(messages[0]["content"]) + "\n\nTask-specific rules:\n" + "\n".join(value["rules"])
    return [{**messages[0], "content": system}, *messages[1:]]
