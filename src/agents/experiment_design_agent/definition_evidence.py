"""Local, bounded evidence retrieval for mathematical definition tasks."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping

from .llm_json import json_prompt_payload


def terms(value):
    if isinstance(value, Mapping):
        return set().union(*(terms(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(terms(item) for item in value)) if value else set()
    text = str(value or "")
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*|[\u4e00-\u9fff]", text.casefold())
    stop = {"the", "and", "for", "with", "from", "that", "this", "variable", "definition", "unknown", "value", "status"}
    return set(token for token in tokens if token not in stop)


class DefinitionEvidenceIndex:
    def __init__(self, cards):
        self.cards = list(cards)
        self.documents = [terms(" ".join(str(card.get(field, "")) for field in (
            "statement", "support_statement", "claim_slot", "evidence_excerpt", "design_implication", "limitations", "does_not_establish",
        ))) for card in self.cards]
        frequency = Counter(token for document in self.documents for token in document)
        self.weights = {token: math.log(1 + len(cards) / count) for token, count in frequency.items()}

    def select(self, query, *, limit=20, max_chars=80000, excluded=()):
        query_terms = terms(query)
        excluded = set(excluded)
        ranked = []
        for position, (card, document) in enumerate(zip(self.cards, self.documents)):
            if card.get("card_id") in excluded:
                continue
            overlap = query_terms & document
            score = sum(self.weights[token] for token in overlap)
            if score <= 0:
                continue
            if re.search(r"=|\\frac|definition|defined|定义", str(card.get("evidence_excerpt", "")), re.I):
                score *= 1.15
            ranked.append((score, position, card))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        selected, sources, seen = [], Counter(), set()
        used = 0
        while ranked and len(selected) < min(40, limit):
            best = max(range(len(ranked)), key=lambda index: ranked[index][0] / (1 + sources[str(ranked[index][2].get("source_id", ""))]))
            _, _, card = ranked.pop(best)
            card_id = card.get("card_id")
            size = len(json_prompt_payload(card))
            if card_id in seen or used + size > max_chars:
                continue
            selected.append(card)
            seen.add(card_id)
            used += size
            sources[str(card.get("source_id", ""))] += 1
        return selected

    def catalog(self):
        return [{"card_id": card.get("card_id"), "source_id": card.get("source_id"),
                 "evidence_level": card.get("evidence_level"),
                 "statement": str(card.get("statement", ""))[:240]} for card in self.cards]


def variable_groups(variables, group_size=4):
    pending = list(variables)
    groups = []
    while pending:
        group = [pending.pop(0)]
        while pending and len(group) < group_size:
            links = {link for variable in group for link in variable.get("claim_links", [])}
            identifiers = {variable.get("variable_id") for variable in group}
            vocabulary = set().union(*(terms({key: variable.get(key, "") for key in ("name", "construct", "symbol")}) for variable in group))

            def relevance(variable):
                dependencies = set(variable.get("depends_on", []))
                reverse = any(variable.get("variable_id") in member.get("depends_on", []) for member in group)
                return 10 * (len(dependencies & identifiers) + reverse) + 3 * len(links & set(variable.get("claim_links", []))) + len(vocabulary & terms({key: variable.get(key, "") for key in ("name", "construct", "symbol")}))

            best = max(range(len(pending)), key=lambda position: relevance(pending[position]))
            if relevance(pending[best]) == 0:
                break
            group.append(pending.pop(best))
        groups.append(group)
    return groups or [[]]


def bounded_formal_evidence(bundle, query, *, card_limit=40, catalog_limit=80):
    cards = [card for card in bundle.get("evidence_cards", []) if isinstance(card, Mapping)]
    index = DefinitionEvidenceIndex(cards)
    selected = index.select(query, limit=max(1, min(40, int(card_limit))))
    selected_ids = {str(card.get("card_id")) for card in selected}
    catalog = [item for item in index.catalog() if str(item.get("card_id")) in selected_ids]
    catalog = catalog[:max(1, min(80, int(catalog_limit)))]
    return {"evidence_cards": selected,
            "evidence_catalog": catalog, "total_card_count": len(cards),
            "selection_policy": "Relevant excerpts only; absence from this selection is not absence of evidence."}


def bounded_prompt_evidence(payload, query):
    cards = {}

    def collect(value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key == "evidence_cards" and isinstance(item, list):
                    cards.update({card["card_id"]: dict(card) for card in item if isinstance(card, Mapping) and card.get("card_id")})
                elif key == "evidence_cards_by_id" and isinstance(item, Mapping):
                    cards.update({identifier: {**card, "card_id": identifier} for identifier, card in item.items() if isinstance(card, Mapping)})
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    if len(cards) <= 40:
        return payload
    index = DefinitionEvidenceIndex(list(cards.values()))
    selected = index.select(query, limit=40)

    def replace(value):
        if isinstance(value, Mapping):
            return {key: ([{"card_id": card.get("card_id")} for card in item if isinstance(card, Mapping)] if key == "evidence_cards" and isinstance(item, list)
                         else {identifier: {"card_id": identifier} for identifier in item} if key == "evidence_cards_by_id" and isinstance(item, Mapping)
                         else replace(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    result = replace(payload)
    result["retrieved_evidence_cards"] = selected
    result["evidence_selection_notice"] = "Only retrieved_evidence_cards contains selected card content. Other card IDs are an index, not evidence for a claim. Missing content is not negative evidence; preserve upstream gaps."
    return result
