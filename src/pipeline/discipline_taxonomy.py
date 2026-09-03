"""Natural-science and engineering taxonomy shared by Idea and Survey flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Mapping, Sequence


_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_HSS_SCOPE_TERMS = (
    "arts and humanities",
    "business",
    "economics",
    "economic policy",
    "finance",
    "history",
    "historical",
    "law",
    "legal studies",
    "education",
    "sociology",
    "social science",
    "political science",
    "politics",
    "philosophy",
    "literature",
    "linguistics",
    "marketing",
    "management",
    "anthropology",
)
_SUPPORTED_PROVIDERS = frozenset({"openalex", "arxiv", "semantic_scholar"})
_COVERAGE_VALUES = frozenset({"exact", "parent_only", "unsupported"})
_LEGACY_ROOT_DOMAIN_ALIASES = {
    "cs.AI": "computer_science",
    "cs.CL": "computer_science",
    "cs.CR": "computer_science",
    "cs.CV": "computer_science",
    "cs.DS": "computer_science",
    "cs.GT": "computer_science",
    "cs.LG": "computer_science",
    "cs.NE": "computer_science",
    "cs.RO": "computer_science",
    "cs.SI": "computer_science",
    "stat.ML": "statistics",
}


@dataclass(frozen=True)
class DisciplineTaxonomyEntry:
    """One allowlisted natural-science or engineering root discipline."""

    key: str
    label: str
    family: str
    aliases: tuple[str, ...]
    internal_domains: tuple[str, ...]
    openalex_field_ids: tuple[str, ...]
    arxiv_categories: tuple[str, ...]
    semantic_scholar_fields: tuple[str, ...]
    provider_applicability: tuple[str, ...]
    coverage: str = "exact"
    adjacent: tuple[str, ...] = ()
    wos_categories: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _entry(
    key: str,
    label: str,
    family: str,
    aliases: Sequence[str],
    openalex_field_id: str,
    *,
    arxiv_categories: Sequence[str] = (),
    semantic_scholar_fields: Sequence[str] = (),
    internal_domains: Sequence[str] = (),
    coverage: str = "exact",
    adjacent: Sequence[str] = (),
    wos_categories: Sequence[str] = (),
) -> DisciplineTaxonomyEntry:
    if coverage not in _COVERAGE_VALUES:
        raise ValueError(f"Unsupported taxonomy coverage: {coverage}")
    provider_applicability = ["openalex", "semantic_scholar"]
    if arxiv_categories:
        provider_applicability.append("arxiv")
    return DisciplineTaxonomyEntry(
        key=key,
        label=label,
        family=family,
        aliases=tuple(aliases),
        internal_domains=tuple(internal_domains),
        openalex_field_ids=(str(openalex_field_id),) if openalex_field_id else (),
        arxiv_categories=tuple(arxiv_categories),
        semantic_scholar_fields=tuple(semantic_scholar_fields),
        provider_applicability=tuple(provider_applicability),
        coverage=coverage,
        adjacent=tuple(adjacent),
        wos_categories=tuple(wos_categories),
    )


NATURAL_SCIENCE_ENGINEERING_TAXONOMY: dict[str, DisciplineTaxonomyEntry] = {
    "agricultural_biological_sciences": _entry(
        "agricultural_biological_sciences",
        "Agricultural and Biological Sciences",
        "life_sciences",
        ("agriculture", "agricultural science", "agronomy", "crop", "crop science", "plant science", "soil", "soil science", "ecology", "biology", "zoology"),
        "11",
        semantic_scholar_fields=("Biology", "Agricultural and Food Sciences"),
        internal_domains=("agriculture", "biology"),
        adjacent=("biochemistry_genetics_molecular_biology", "environmental_science", "veterinary"),
    ),
    "biochemistry_genetics_molecular_biology": _entry(
        "biochemistry_genetics_molecular_biology",
        "Biochemistry, Genetics and Molecular Biology",
        "life_sciences",
        ("biochemistry", "molecular biology", "genetics", "genomics", "proteomics", "cell biology", "molecular genetics"),
        "13",
        arxiv_categories=("q-bio.BM", "q-bio.GN"),
        semantic_scholar_fields=("Biology",),
        internal_domains=("biology", "quantitative_biology"),
        adjacent=("immunology_microbiology", "neuroscience", "quantitative_biology"),
    ),
    "chemical_engineering": _entry(
        "chemical_engineering",
        "Chemical Engineering",
        "physical_sciences_engineering",
        ("chemical engineering", "reaction engineering", "reactor design", "separation process", "process systems engineering", "process intensification"),
        "15",
        semantic_scholar_fields=("Engineering", "Chemistry"),
        internal_domains=("chemistry", "engineering", "materials_science"),
        adjacent=("chemistry", "engineering", "energy"),
    ),
    "chemistry": _entry(
        "chemistry",
        "Chemistry",
        "physical_sciences",
        (
            "chemistry",
            "chemical synthesis",
            "organic chemistry",
            "inorganic chemistry",
            "analytical chemistry",
            "physical chemistry",
            "electrochemistry",
            "electrochemical",
            "electrochemical impedance spectroscopy",
            "catalysis",
        ),
        "16",
        semantic_scholar_fields=("Chemistry",),
        internal_domains=("chemistry",),
        adjacent=("chemical_engineering", "materials_science", "pharmacology_toxicology_pharmaceutics"),
    ),
    "computer_science": _entry(
        "computer_science",
        "Computer Science",
        "formal_computational_sciences",
        ("computer science", "computing", "machine learning", "deep learning", "artificial intelligence", "software engineering", "information retrieval", "computer vision", "cybersecurity", "natural language processing", "robotics"),
        "17",
        arxiv_categories=("cs.AI", "cs.LG", "cs.IR"),
        semantic_scholar_fields=("Computer Science",),
        internal_domains=("computer_science",),
        adjacent=("mathematics", "statistics", "electrical_engineering_systems"),
    ),
    "earth_planetary_science": _entry(
        "earth_planetary_science",
        "Earth and Planetary Sciences",
        "earth_space_sciences",
        ("earth science", "earth sciences", "planetary science", "geology", "geophysics", "geochemistry", "oceanography", "meteorology", "climate science"),
        "19",
        arxiv_categories=("physics.geo-ph", "astro-ph.EP"),
        semantic_scholar_fields=("Environmental Science", "Physics"),
        internal_domains=("earth_environmental_science", "astrobiology", "physics"),
        adjacent=("environmental_science", "physics_astronomy", "agricultural_biological_sciences"),
    ),
    "energy": _entry(
        "energy",
        "Energy",
        "physical_sciences_engineering",
        ("energy storage", "battery", "renewable energy", "power system", "hydrogen energy", "solar energy", "wind energy", "energy system", "fuel cell"),
        "21",
        arxiv_categories=("physics.app-ph", "eess.SY"),
        semantic_scholar_fields=("Engineering", "Environmental Science", "Physics"),
        internal_domains=("engineering", "electrical_engineering", "chemistry", "materials_science"),
        adjacent=("materials_science", "engineering", "environmental_science"),
    ),
    "engineering": _entry(
        "engineering",
        "Engineering",
        "engineering",
        ("engineering", "mechanical engineering", "civil engineering", "aerospace engineering", "manufacturing engineering", "structural engineering", "control engineering"),
        "22",
        arxiv_categories=("eess.SY",),
        semantic_scholar_fields=("Engineering",),
        internal_domains=("engineering",),
        adjacent=("electrical_engineering_systems", "materials_science", "energy"),
    ),
    "environmental_science": _entry(
        "environmental_science",
        "Environmental Science",
        "earth_environmental_sciences",
        ("environmental science", "environmental pollution", "water quality", "water treatment", "ecotoxicology", "contamination", "environmental exposure", "waste management", "air pollution"),
        "23",
        arxiv_categories=("physics.ao-ph",),
        semantic_scholar_fields=("Environmental Science",),
        internal_domains=("earth_environmental_science", "agriculture", "chemistry"),
        adjacent=("earth_planetary_science", "agricultural_biological_sciences", "energy"),
    ),
    "immunology_microbiology": _entry(
        "immunology_microbiology",
        "Immunology and Microbiology",
        "life_health_sciences",
        ("immunology", "microbiology", "infectious disease", "virology", "immune response", "pathogen", "microbiome"),
        "24",
        arxiv_categories=("q-bio.BM",),
        semantic_scholar_fields=("Biology", "Medicine"),
        internal_domains=("biology", "medicine", "quantitative_biology"),
        adjacent=("biochemistry_genetics_molecular_biology", "medicine", "neuroscience"),
    ),
    "materials_science": _entry(
        "materials_science",
        "Materials Science",
        "physical_sciences_engineering",
        ("materials science", "material science", "biomaterials", "ceramics", "composites", "metallurgy", "nanomaterials", "polymer materials", "functional material", "solid electrolyte", "solid state electrolyte", "electrolyte", "electrode material"),
        "25",
        arxiv_categories=("cond-mat.mtrl-sci",),
        semantic_scholar_fields=("Materials Science", "Chemistry", "Engineering"),
        internal_domains=("materials_science", "chemistry", "engineering"),
        adjacent=("chemistry", "chemical_engineering", "energy"),
    ),
    "mathematics": _entry(
        "mathematics",
        "Mathematics",
        "formal_computational_sciences",
        ("mathematics", "algebra", "topology", "number theory", "partial differential equation", "differential equations", "mathematical proof", "dynamical systems"),
        "26",
        arxiv_categories=("math.OC", "math.ST"),
        semantic_scholar_fields=("Mathematics",),
        internal_domains=("mathematics",),
        adjacent=("statistics", "computer_science", "physics_astronomy"),
    ),
    "medicine": _entry(
        "medicine",
        "Medicine",
        "health_sciences",
        ("medicine", "medical", "clinical", "patient", "hospital", "diagnosis", "therapy", "treatment", "epidemiology", "public health"),
        "27",
        semantic_scholar_fields=("Medicine",),
        internal_domains=("medicine",),
        adjacent=("pharmacology_toxicology_pharmaceutics", "neuroscience", "nursing"),
    ),
    "neuroscience": _entry(
        "neuroscience",
        "Neuroscience",
        "life_health_sciences",
        ("neuroscience", "neurobiology", "neurology", "neural circuit", "brain", "neurodegenerative", "neuroimaging"),
        "28",
        arxiv_categories=("q-bio.NC",),
        semantic_scholar_fields=("Biology", "Medicine"),
        internal_domains=("biology", "medicine", "quantitative_biology"),
        adjacent=("medicine", "biochemistry_genetics_molecular_biology", "immunology_microbiology"),
    ),
    "nursing": _entry(
        "nursing",
        "Nursing",
        "health_sciences",
        ("nursing", "nurse led", "nursing care", "primary health care"),
        "29",
        semantic_scholar_fields=("Medicine",),
        internal_domains=("medicine",),
        adjacent=("medicine", "health_professions"),
    ),
    "pharmacology_toxicology_pharmaceutics": _entry(
        "pharmacology_toxicology_pharmaceutics",
        "Pharmacology, Toxicology and Pharmaceutics",
        "health_sciences",
        ("pharmacology", "toxicology", "pharmaceutics", "drug discovery", "drug delivery", "adverse drug", "medicinal chemistry"),
        "30",
        semantic_scholar_fields=("Medicine", "Chemistry"),
        internal_domains=("medicine", "chemistry"),
        adjacent=("medicine", "chemistry", "biochemistry_genetics_molecular_biology"),
    ),
    "physics_astronomy": _entry(
        "physics_astronomy",
        "Physics and Astronomy",
        "physical_sciences",
        ("physics", "astronomy", "astrophysics", "quantum physics", "quantum mechanics", "particle physics", "condensed matter", "plasma physics", "optics"),
        "31",
        arxiv_categories=("physics.gen-ph", "astro-ph.GA", "cond-mat.mtrl-sci"),
        semantic_scholar_fields=("Physics",),
        internal_domains=("physics", "astrobiology"),
        adjacent=("mathematics", "earth_planetary_science", "materials_science"),
    ),
    "veterinary": _entry(
        "veterinary",
        "Veterinary",
        "health_sciences",
        ("veterinary", "veterinarian", "animal health", "animal medicine", "veterinary medicine"),
        "34",
        semantic_scholar_fields=("Medicine", "Biology"),
        internal_domains=("agriculture", "biology", "medicine"),
        adjacent=("agricultural_biological_sciences", "medicine"),
    ),
    "dentistry": _entry(
        "dentistry",
        "Dentistry",
        "health_sciences",
        ("dentistry", "dental", "oral health", "periodontology", "orthodontics"),
        "35",
        semantic_scholar_fields=("Medicine",),
        internal_domains=("medicine",),
        adjacent=("medicine", "materials_science"),
    ),
    "health_professions": _entry(
        "health_professions",
        "Health Professions",
        "health_sciences",
        ("health professions", "medical informatics", "rehabilitation", "physical therapy", "allied health", "sport science"),
        "36",
        semantic_scholar_fields=("Medicine",),
        internal_domains=("medicine",),
        adjacent=("medicine", "nursing"),
    ),
    "electrical_engineering_systems": _entry(
        "electrical_engineering_systems",
        "Electrical Engineering and Systems",
        "engineering",
        ("electrical engineering", "power electronics", "telecommunications", "communication systems", "circuit design", "semiconductor device", "signal processing", "control systems"),
        "22",
        arxiv_categories=("eess.SP", "eess.SY"),
        semantic_scholar_fields=("Engineering", "Computer Science"),
        internal_domains=("electrical_engineering",),
        coverage="parent_only",
        adjacent=("engineering", "computer_science", "energy"),
    ),
    "quantitative_biology": _entry(
        "quantitative_biology",
        "Quantitative Biology",
        "life_sciences",
        ("quantitative biology", "computational biology", "systems biology", "bioinformatics", "biophysics", "biological modeling"),
        "13",
        arxiv_categories=("q-bio.QM", "q-bio.GN", "q-bio.BM"),
        semantic_scholar_fields=("Biology", "Mathematics"),
        internal_domains=("quantitative_biology",),
        coverage="parent_only",
        adjacent=("biochemistry_genetics_molecular_biology", "statistics", "computer_science"),
    ),
    "statistics": _entry(
        "statistics",
        "Statistics",
        "formal_computational_sciences",
        ("statistics", "statistical inference", "experimental design", "bayesian inference", "probability theory", "causal inference", "uncertainty quantification"),
        "26",
        arxiv_categories=("stat.ML", "stat.AP", "math.ST"),
        semantic_scholar_fields=("Mathematics",),
        internal_domains=("statistics",),
        coverage="parent_only",
        adjacent=("mathematics", "computer_science", "quantitative_biology"),
    ),
    "astrobiology": _entry(
        "astrobiology",
        "Astrobiology",
        "earth_space_life_sciences",
        ("astrobiology", "life detection", "exoplanet habitability", "biosignature", "planetary habitability"),
        "19",
        arxiv_categories=("astro-ph.EP",),
        semantic_scholar_fields=("Biology", "Physics"),
        internal_domains=("astrobiology",),
        coverage="parent_only",
        adjacent=("earth_planetary_science", "physics_astronomy", "biochemistry_genetics_molecular_biology"),
    ),
}


def _normal_key(value: Any) -> str:
    return _NORMALIZE_PATTERN.sub("", str(value or "").strip().lower().replace("&", " and "))


def _normalized_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return " ".join(_NORMALIZE_PATTERN.sub(" ", text.lower()).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalized_text(phrase)
    if not normalized_phrase:
        return False
    normalized_text = f" {text} "
    phrase_variants = (normalized_phrase, f"{normalized_phrase}s")
    return any(f" {candidate} " in normalized_text for candidate in phrase_variants)


def _unique(values: Iterable[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


_ALIAS_INDEX: dict[str, str] = {}
for _taxonomy_entry in NATURAL_SCIENCE_ENGINEERING_TAXONOMY.values():
    for _alias in (_taxonomy_entry.key, _taxonomy_entry.label, *_taxonomy_entry.aliases):
        _ALIAS_INDEX[_normal_key(_alias)] = _taxonomy_entry.key
for _legacy_alias, _canonical_key in _LEGACY_ROOT_DOMAIN_ALIASES.items():
    _ALIAS_INDEX[_normal_key(_legacy_alias)] = _canonical_key


def canonicalize_discipline_key(value: Any) -> str:
    """Normalize canonical, human-readable, and legacy root-domain values."""

    return _ALIAS_INDEX.get(_normal_key(value), "")


def get_discipline_entry(value: Any) -> DisciplineTaxonomyEntry | None:
    return NATURAL_SCIENCE_ENGINEERING_TAXONOMY.get(canonicalize_discipline_key(value))


def list_allowlisted_disciplines() -> list[dict[str, Any]]:
    return [
        NATURAL_SCIENCE_ENGINEERING_TAXONOMY[key].to_dict()
        for key in sorted(NATURAL_SCIENCE_ENGINEERING_TAXONOMY)
    ]


def taxonomy_catalog_labels() -> dict[str, str]:
    return {
        key: entry.label
        for key, entry in NATURAL_SCIENCE_ENGINEERING_TAXONOMY.items()
    }


def format_taxonomy_catalog_for_prompt() -> str:
    """Render canonical keys with provider-native categories for an LLM prompt."""

    lines = []
    for key in sorted(NATURAL_SCIENCE_ENGINEERING_TAXONOMY):
        entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY[key]
        openalex_category = ", ".join(entry.openalex_field_ids) or "none"
        arxiv_category = ", ".join(entry.arxiv_categories) or "no exact category"
        lines.append(
            f"- {entry.key}: {entry.label} | OpenAlex field: {openalex_category} | arXiv: {arxiv_category}"
        )
    return "\n".join(lines)


def _entry_score(entry: DisciplineTaxonomyEntry, domain_text: str, query_text: str, active_domains: set[str]) -> tuple[int, list[str]]:
    score = 0
    matches: list[str] = []
    for alias in entry.aliases:
        words = len(_normalized_text(alias).split())
        if _contains_phrase(domain_text, alias):
            score += 12 + min(words, 3)
            matches.append(alias)
        elif _contains_phrase(query_text, alias):
            score += 7 + min(words, 3)
            matches.append(alias)
    score += 3 * len(active_domains.intersection(entry.internal_domains))
    return score, _unique(matches)


def _provider_filter(entry: DisciplineTaxonomyEntry | None, provider: str, *, reason: str, adjacent: Sequence[str]) -> dict[str, Any]:
    selected_provider = str(provider or "").strip().lower()
    if selected_provider not in _SUPPORTED_PROVIDERS:
        return {
            "provider": selected_provider,
            "mode": "unsupported_provider",
            "policy": "post_filter_only",
            "applied": False,
            "coverage": "unsupported",
            "reason": "No native taxonomy formatter is registered for this provider.",
        }
    if entry is None:
        return {
            "provider": selected_provider,
            "mode": "not_applied",
            "policy": "post_filter_only",
            "applied": False,
            "coverage": "unsupported",
            "reason": reason,
        }
    base = {
        "provider": selected_provider,
        "primary_discipline": entry.key,
        "coverage": entry.coverage,
        "soft_expansion_disciplines": list(adjacent[:2]),
    }
    if selected_provider == "openalex":
        if entry.coverage != "exact" or not entry.openalex_field_ids:
            return {
                **base,
                "mode": "native_filter_withheld",
                "policy": "post_filter_only",
                "applied": False,
                "reason": "The taxonomy is parent-only or mixed, so no hard OpenAlex field filter was emitted.",
            }
        return {
            **base,
            "mode": "native_filter",
            "policy": "hard_filter",
            "applied": True,
            "resolved_field_ids": list(entry.openalex_field_ids),
            "filter": "primary_topic.field.id:" + "|".join(entry.openalex_field_ids),
            "reason": "An exact OpenAlex field mapping is available for candidate-discovery metadata.",
        }
    if selected_provider == "arxiv":
        if entry.coverage != "exact" or not entry.arxiv_categories:
            return {
                **base,
                "mode": "native_filter_withheld",
                "policy": "post_filter_only",
                "applied": False,
                "reason": "No exact arXiv category mapping is available for this taxonomy entry.",
            }
        categories = list(entry.arxiv_categories[:3])
        return {
            **base,
            "mode": "native_filter",
            "policy": "hard_filter",
            "applied": True,
            "categories": categories,
            "category_expression": "(" + " OR ".join(f"cat:{category}" for category in categories) + ")",
            "reason": "An exact bounded arXiv category expression is available for candidate-discovery metadata.",
        }
    return {
        **base,
        "mode": "field_hint",
        "policy": "soft_boost",
        "applied": False,
        "field_hints": list(entry.semantic_scholar_fields),
        "reason": "Semantic Scholar field values are recorded as soft hints; no hard field filter is claimed.",
    }


def compile_provider_discipline_filter(provider: Any, resolution: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return an auditable OpenAlex/arXiv/Semantic Scholar metadata payload."""

    selected_provider = str(provider or "").strip().lower()
    payload = resolution if isinstance(resolution, Mapping) else {}
    provider_filters = payload.get("provider_filters")
    if isinstance(provider_filters, Mapping) and isinstance(provider_filters.get(selected_provider), Mapping):
        return dict(provider_filters[selected_provider])
    return _provider_filter(None, selected_provider, reason="No taxonomy resolution was supplied.", adjacent=())


def _subhypothesis_taxonomy_text(subhypothesis: Mapping[str, Any] | None) -> str:
    """Extract the SH text that may legitimately refine a discovery filter."""

    payload = subhypothesis if isinstance(subhypothesis, Mapping) else {}
    scope = payload.get("scientific_scope")
    definitions = payload.get("slot_definitions")
    parts: list[Any] = [payload.get("title"), payload.get("question")]
    if isinstance(scope, Mapping):
        parts.extend(scope.values())
    if isinstance(definitions, Mapping):
        for definition in definitions.values():
            if not isinstance(definition, Mapping):
                continue
            parts.extend(
                [
                    definition.get("meaning"),
                    definition.get("retrieval_concepts"),
                    definition.get("retrieval_query_variants"),
                ]
            )

    def _flatten(value: Any) -> Iterable[str]:
        if isinstance(value, Mapping):
            for nested in value.values():
                yield from _flatten(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                yield from _flatten(nested)
        elif str(value or "").strip():
            yield str(value)

    return _normalized_text(" ".join(item for value in parts for item in _flatten(value)))


def resolve_subhypothesis_discipline_taxonomy(
    project_resolution: Mapping[str, Any] | None,
    subhypothesis: Mapping[str, Any] | None,
    *,
    max_openalex_disciplines: int = 3,
) -> dict[str, Any]:
    """Refine an exact project OpenAlex filter from one validated SH.

    The project-level taxonomy remains the authority for the primary discipline.
    This helper only widens its *OpenAlex candidate-discovery* field filter with
    exact taxonomy entries directly indicated by the SH question, scope, or slot
    concepts.  It deliberately does not infer paper relevance or evidence role.
    """

    inherited = dict(project_resolution) if isinstance(project_resolution, Mapping) else {}
    inherited_filters = inherited.get("provider_filters")
    provider_filters = (
        {
            str(provider): dict(provider_filter)
            for provider, provider_filter in inherited_filters.items()
            if isinstance(provider_filter, Mapping)
        }
        if isinstance(inherited_filters, Mapping)
        else {}
    )
    project_openalex = provider_filters.get("openalex", {})
    if not isinstance(project_openalex, Mapping):
        project_openalex = {}
    has_exact_project_filter = bool(
        project_openalex.get("applied")
        and project_openalex.get("coverage") == "exact"
        and project_openalex.get("policy") == "hard_filter"
    )
    sh_text = _subhypothesis_taxonomy_text(subhypothesis)
    if not has_exact_project_filter or not sh_text:
        return {
            **inherited,
            "provider_filters": provider_filters,
            "subhypothesis_taxonomy": {
                "source": "project_domain_only",
                "expanded": False,
                "reason": (
                    "The project taxonomy did not supply an exact OpenAlex filter."
                    if not has_exact_project_filter
                    else "The sub-hypothesis did not contain taxonomy text that could refine the filter."
                ),
                "matched_disciplines": [],
            },
        }

    max_entries = max(1, min(int(max_openalex_disciplines or 1), 4))
    selected_keys: list[str] = []
    for key in [
        inherited.get("primary_discipline"),
        *(inherited.get("discipline_ids") or []),
    ]:
        canonical = canonicalize_discipline_key(key)
        entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY.get(canonical or "")
        if (
            entry
            and entry.coverage == "exact"
            and entry.openalex_field_ids
            and entry.key not in selected_keys
        ):
            selected_keys.append(entry.key)

    ranked_matches: list[tuple[int, DisciplineTaxonomyEntry, list[str]]] = []
    for entry in NATURAL_SCIENCE_ENGINEERING_TAXONOMY.values():
        score, matches = _entry_score(entry, "", sh_text, set())
        if score and matches and entry.coverage == "exact" and entry.openalex_field_ids:
            ranked_matches.append((score, entry, matches))
    ranked_matches.sort(key=lambda item: (-item[0], item[1].key))

    matched_disciplines: list[dict[str, Any]] = []
    for score, entry, matches in ranked_matches:
        matched_disciplines.append(
            {"discipline": entry.key, "score": score, "matched_terms": matches}
        )
        if entry.key not in selected_keys and len(selected_keys) < max_entries:
            selected_keys.append(entry.key)

    field_ids: list[str] = []
    for key in selected_keys[:max_entries]:
        entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY[key]
        for field_id in entry.openalex_field_ids:
            if field_id not in field_ids:
                field_ids.append(field_id)

    primary_discipline = canonicalize_discipline_key(inherited.get("primary_discipline"))
    expanded = field_ids != list(project_openalex.get("resolved_field_ids") or [])
    provider_filters["openalex"] = {
        **dict(project_openalex),
        "primary_discipline": primary_discipline or project_openalex.get("primary_discipline"),
        "resolved_discipline_ids": selected_keys[:max_entries],
        "resolved_field_ids": field_ids,
        "filter": "primary_topic.field.id:" + "|".join(field_ids),
        "source": "project_domain_plus_subhypothesis",
        "reason": (
            "The exact project field was combined with exact taxonomy fields whose aliases "
            "matched this sub-hypothesis question, scope, or slot concepts."
            if expanded
            else "No additional exact taxonomy field was indicated by this sub-hypothesis."
        ),
    }
    return {
        **inherited,
        "provider_filters": provider_filters,
        "subhypothesis_taxonomy": {
            "source": "project_domain_plus_subhypothesis",
            "expanded": expanded,
            "max_openalex_disciplines": max_entries,
            "matched_disciplines": matched_disciplines,
            "selected_disciplines": selected_keys[:max_entries],
            "selected_openalex_field_ids": field_ids,
            "source_text_fields": ["title", "question", "scientific_scope", "slot_definitions"],
        },
    }


def resolve_query_variant_discipline_taxonomy(
    project_resolution: Mapping[str, Any] | None,
    subhypothesis_resolution: Mapping[str, Any] | None,
    preferred_disciplines: Iterable[Any] = (),
    *,
    max_openalex_disciplines: int = 3,
) -> dict[str, Any]:
    """Compile a bounded precision filter for one alternative slot query.

    A variant can prefer a material, chemistry, safety, or method-adjacent
    field without changing the project's primary discipline.  The returned
    filter is intentionally a *precision lane* supplement: callers must keep
    a broad, unfiltered lane for the same query variant.
    """

    project = dict(project_resolution) if isinstance(project_resolution, Mapping) else {}
    effective = (
        dict(subhypothesis_resolution)
        if isinstance(subhypothesis_resolution, Mapping)
        else project
    )
    project_filters = project.get("provider_filters")
    base_openalex = (
        dict(project_filters.get("openalex"))
        if isinstance(project_filters, Mapping)
        and isinstance(project_filters.get("openalex"), Mapping)
        else {}
    )
    exact_project_filter = bool(
        base_openalex.get("applied")
        and base_openalex.get("coverage") == "exact"
        and base_openalex.get("policy") == "hard_filter"
    )
    if not exact_project_filter:
        return {}

    max_entries = max(1, min(int(max_openalex_disciplines or 1), 4))
    selected_keys: list[str] = []
    project_primary = canonicalize_discipline_key(project.get("primary_discipline"))
    if project_primary:
        primary_entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY.get(project_primary)
        if primary_entry and primary_entry.coverage == "exact" and primary_entry.openalex_field_ids:
            selected_keys.append(primary_entry.key)

    normalized_preferences: list[str] = []
    preferences = (
        preferred_disciplines
        if not isinstance(preferred_disciplines, (str, bytes))
        else [preferred_disciplines]
    )
    for value in preferences:
        key = canonicalize_discipline_key(value)
        entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY.get(key or "")
        if (
            entry
            and entry.coverage == "exact"
            and entry.openalex_field_ids
            and entry.key not in normalized_preferences
        ):
            normalized_preferences.append(entry.key)

    if normalized_preferences:
        candidate_keys = normalized_preferences
        selection_source = "query_variant_preferred_disciplines"
    else:
        effective_filters = effective.get("provider_filters")
        effective_openalex = (
            effective_filters.get("openalex")
            if isinstance(effective_filters, Mapping)
            and isinstance(effective_filters.get("openalex"), Mapping)
            else {}
        )
        candidate_keys = list(effective_openalex.get("resolved_discipline_ids") or [])
        selection_source = "subhypothesis_taxonomy"

    for value in candidate_keys:
        key = canonicalize_discipline_key(value)
        entry = NATURAL_SCIENCE_ENGINEERING_TAXONOMY.get(key or "")
        if (
            entry
            and entry.coverage == "exact"
            and entry.openalex_field_ids
            and entry.key not in selected_keys
            and len(selected_keys) < max_entries
        ):
            selected_keys.append(entry.key)

    field_ids: list[str] = []
    for key in selected_keys[:max_entries]:
        for field_id in NATURAL_SCIENCE_ENGINEERING_TAXONOMY[key].openalex_field_ids:
            if field_id not in field_ids:
                field_ids.append(field_id)
    if not field_ids:
        return {}
    return {
        **base_openalex,
        "primary_discipline": project_primary or base_openalex.get("primary_discipline"),
        "resolved_discipline_ids": selected_keys[:max_entries],
        "resolved_field_ids": field_ids,
        "filter": "primary_topic.field.id:" + "|".join(field_ids),
        "source": "project_domain_plus_query_variant",
        "selection_source": selection_source,
        "preferred_disciplines": normalized_preferences,
        "reason": (
            "This exact field filter is an optional precision lane for one SH query "
            "variant; broad candidate discovery remains unfiltered."
        ),
    }


def arxiv_category_expression(provider_filter: Mapping[str, Any] | None) -> str:
    payload = provider_filter if isinstance(provider_filter, Mapping) else {}
    return str(payload.get("category_expression") or "") if payload.get("applied") else ""


def resolve_discipline_taxonomy(
    domain_or_text: Any,
    *,
    query: Any = "",
    internal_domains: Iterable[Any] = (),
    max_disciplines: int = 2,
) -> dict[str, Any]:
    """Resolve a conservative allowlisted discipline without changing provider calls."""

    domain_text = _normalized_text(domain_or_text)
    query_text = _normalized_text(query)
    active_domains = {
        canonicalize_discipline_key(value) or _normal_key(value)
        for value in internal_domains
        if str(value or "").strip()
    }
    explicit_key = canonicalize_discipline_key(domain_or_text)
    ranked: list[tuple[int, DisciplineTaxonomyEntry, list[str]]] = []
    for entry in NATURAL_SCIENCE_ENGINEERING_TAXONOMY.values():
        score, matches = _entry_score(entry, domain_text, query_text, active_domains)
        if entry.key == explicit_key:
            score += 100
            matches = _unique([entry.key, *matches])
        if score:
            ranked.append((score, entry, matches))
    ranked.sort(key=lambda item: (-item[0], item[1].key))

    hss_matches = [term for term in _HSS_SCOPE_TERMS if _contains_phrase(f"{domain_text} {query_text}", term)]
    if not ranked:
        status = "out_of_scope" if hss_matches else "unresolved"
        reason = (
            "The topic matches excluded humanities or social-science terms without a natural-science or engineering anchor."
            if status == "out_of_scope"
            else "No allowlisted natural-science or engineering discipline was resolved with sufficient evidence."
        )
        provider_filters = {
            provider: _provider_filter(None, provider, reason=reason, adjacent=())
            for provider in sorted(_SUPPORTED_PROVIDERS)
        }
        return {
            "schema_version": "discipline_taxonomy_v1",
            "scope": "natural_science_engineering_only",
            "status": status,
            "primary_discipline": None,
            "discipline_ids": [],
            "adjacent_disciplines": [],
            "coverage": "unsupported",
            "matched_terms": [],
            "out_of_scope_terms": hss_matches,
            "mixed": False,
            "provider_filters": provider_filters,
            "reason": reason,
        }

    primary_score, primary, primary_matches = ranked[0]
    close_entries = [
        (score, entry, matches)
        for score, entry, matches in ranked[1:]
        if score >= max(8, int(primary_score * 0.8))
    ]
    status = "ambiguous" if close_entries else "resolved"
    selected_entries = [primary]
    if close_entries and max_disciplines > 1:
        selected_entries.append(close_entries[0][1])
    adjacent = _unique(
        [entry.key for _, entry, _ in close_entries]
        + list(primary.adjacent)
    )
    adjacent = [key for key in adjacent if key not in {entry.key for entry in selected_entries}][:2]
    mixed = bool(hss_matches)
    reason = (
        "Resolved to one allowlisted discipline; humanities or social-science language is retained as mixed-topic context."
        if mixed
        else "Resolved conservatively from allowlisted aliases; provider-native filters remain metadata until a provider route consumes them."
    )
    provider_filters = {
        provider: _provider_filter(primary, provider, reason=reason, adjacent=adjacent)
        for provider in sorted(_SUPPORTED_PROVIDERS)
    }
    return {
        "schema_version": "discipline_taxonomy_v1",
        "scope": "natural_science_engineering_only",
        "status": status,
        "primary_discipline": primary.key,
        "discipline_ids": [entry.key for entry in selected_entries[:max(1, min(max_disciplines, 2))]],
        "adjacent_disciplines": adjacent,
        "coverage": primary.coverage,
        "matched_terms": primary_matches,
        "out_of_scope_terms": hss_matches,
        "mixed": mixed,
        "primary": primary.to_dict(),
        "provider_filters": provider_filters,
        "reason": reason,
    }
