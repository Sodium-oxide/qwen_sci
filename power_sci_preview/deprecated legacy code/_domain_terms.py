from __future__ import annotations

from collections import defaultdict
from typing import Any


DOMAIN_TERM_PROBABILITY: dict[str, dict[str, float]] = {
    "battery": {"chemistry": 0.9, "physics": 0.35, "electrical_engineering": 0.3},
    "electrolyte": {"chemistry": 0.9, "physics": 0.3, "biology": 0.2},
    "neural network": {"computer_science": 0.95, "biology": 0.25, "physics": 0.15},
    "machine learning": {"computer_science": 0.95, "physics": 0.35, "chemistry": 0.35, "biology": 0.35},
    "algorithm": {"computer_science": 0.95, "mathematics": 0.7, "statistics": 0.35},
    "crystal": {"chemistry": 0.8, "physics": 0.8},
    "polymer": {"chemistry": 0.9, "physics": 0.35, "biology": 0.2},
    "catalysis": {"chemistry": 0.95, "biology": 0.25, "physics": 0.25},
    "protein": {"biology": 0.95, "chemistry": 0.7, "medicine": 0.55},
    "genome": {"biology": 0.95, "medicine": 0.6, "quantitative_biology": 0.55},
    "clinical": {"medicine": 0.95, "biology": 0.45, "statistics": 0.2},
    "patient": {"medicine": 0.95, "biology": 0.35, "statistics": 0.2},
    "neuron": {"biology": 0.9, "computer_science": 0.45, "medicine": 0.3},
    "galaxy": {"physics": 0.95, "mathematics": 0.2},
    "gravitational wave": {"physics": 0.95, "mathematics": 0.35, "computer_science": 0.2},
    "superheavy": {"physics": 0.95, "chemistry": 0.35},
    "nuclear": {"physics": 0.9, "chemistry": 0.3, "medicine": 0.15},
    "quantum": {"physics": 0.9, "computer_science": 0.45, "chemistry": 0.3, "mathematics": 0.3},
    "topological": {"physics": 0.65, "mathematics": 0.65, "computer_science": 0.25},
    "theorem": {"mathematics": 0.95, "computer_science": 0.35, "physics": 0.2},
    "partial differential equation": {"mathematics": 0.95, "physics": 0.45, "engineering": 0.25},
    "climate": {"physics": 0.4, "economics": 0.3, "biology": 0.25},
    "robot": {"computer_science": 0.8, "electrical_engineering": 0.7, "physics": 0.2},
}


def compute_domain_probability_profile(text: str) -> dict[str, float]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    normalized = normalize_space(text).lower()
    scores: dict[str, float] = defaultdict(float)
    for term, domain_scores in DOMAIN_TERM_PROBABILITY.items():
        if term not in normalized:
            continue
        for domain, probability in domain_scores.items():
            scores[domain] += float(probability)
    return normalize_domain_probability_profile(scores)


def field_domain_probability(field: str) -> str:
    try:
        from ._models import research_domain_for_field
    except ImportError:
        from _models import research_domain_for_field
    normalized = str(field or "general").strip().lower()
    mapped = str(research_domain_for_field(normalized) or "general").strip().lower()
    aliases = {
        "materials": "chemistry",
        "materials_energy": "chemistry",
        "electrochemistry": "chemistry",
        "nuclear_physics": "physics",
        "astrophysics": "physics",
        "high_energy_physics": "physics",
        "quantitative_biology": "quantitative_biology",
        "biomedical": "biology",
        "biophysics": "biology",
        "digital_medicine": "medicine",
    }
    return aliases.get(mapped, aliases.get(normalized, mapped))


def domain_probability_alignment(
    target_text: str,
    paper_text: str,
    target_field: str = "",
    result_field: str = "",
) -> dict[str, Any]:
    target_profile = compute_domain_probability_profile(target_text)
    result_profile = compute_domain_probability_profile(paper_text)
    target_domain = field_domain_probability(target_field)
    result_domain = field_domain_probability(result_field)
    if target_domain not in {"", "general", "multidisciplinary"}:
        target_profile[target_domain] = target_profile.get(target_domain, 0.0) + 0.9
    if result_domain not in {"", "general", "multidisciplinary"}:
        result_profile[result_domain] = result_profile.get(result_domain, 0.0) + 0.9
    target_profile = normalize_domain_probability_profile(target_profile)
    result_profile = normalize_domain_probability_profile(result_profile)
    overlap = sum(min(target_profile.get(domain, 0.0), result_profile.get(domain, 0.0)) for domain in set(target_profile) | set(result_profile))
    return {
        "target_profile": target_profile,
        "paper_profile": result_profile,
        "overlap": round(min(1.0, overlap), 4),
        "target_domain": target_domain,
        "result_domain": result_domain,
    }


def normalize_domain_probability_profile(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in scores.values())
    if total <= 0:
        return {}
    return {
        str(domain): round(max(0.0, float(value)) / total, 4)
        for domain, value in scores.items()
        if float(value) > 0
    }
