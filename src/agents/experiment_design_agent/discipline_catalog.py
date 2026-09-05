"""Internal discipline scope and execution policy for ExperimentDesign Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable


CATALOG_SCHEMA_VERSION = "experiment_design_discipline_catalog_v1"
CATALOG_SOURCE = "paperseek_openalex_fields"
DESIGN_ONLY = "DESIGN_ONLY"
DIGITAL_EXECUTION_ELIGIBLE = "DIGITAL_EXECUTION_ELIGIBLE"


@dataclass(frozen=True)
class DisciplineCatalogEntry:
    """One OpenAlex field and its ExperimentDesign eligibility."""

    id: str
    label: str
    domain: str
    allowed: bool
    template_family: str
    baseline_risk: str

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


_ENTRIES: tuple[DisciplineCatalogEntry, ...] = (
    DisciplineCatalogEntry("11", "Agricultural and Biological Sciences", "Life Sciences", True, "earth_environment_agro", "medium"),
    DisciplineCatalogEntry("12", "Arts and Humanities", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("13", "Biochemistry, Genetics and Molecular Biology", "Life Sciences", True, "life_veterinary", "high"),
    DisciplineCatalogEntry("14", "Business, Management and Accounting", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("15", "Chemical Engineering", "Physical Sciences", True, "materials_chemical", "medium"),
    DisciplineCatalogEntry("16", "Chemistry", "Physical Sciences", True, "materials_chemical", "medium"),
    DisciplineCatalogEntry("17", "Computer Science", "Physical Sciences", True, "computational", "medium"),
    DisciplineCatalogEntry("18", "Decision Sciences", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("19", "Earth and Planetary Sciences", "Physical Sciences", True, "earth_environment_agro", "medium"),
    DisciplineCatalogEntry("20", "Economics, Econometrics and Finance", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("21", "Energy", "Physical Sciences", True, "energy_engineering", "medium"),
    DisciplineCatalogEntry("22", "Engineering", "Physical Sciences", True, "energy_engineering", "medium"),
    DisciplineCatalogEntry("23", "Environmental Science", "Physical Sciences", True, "earth_environment_agro", "medium"),
    DisciplineCatalogEntry("24", "Immunology and Microbiology", "Life Sciences", True, "life_veterinary", "high"),
    DisciplineCatalogEntry("25", "Materials Science", "Physical Sciences", True, "materials_chemical", "medium"),
    DisciplineCatalogEntry("26", "Mathematics", "Physical Sciences", True, "mathematics_theory", "low"),
    DisciplineCatalogEntry("27", "Medicine", "Health Sciences", True, "clinical_health", "critical"),
    DisciplineCatalogEntry("28", "Neuroscience", "Life Sciences", True, "life_veterinary", "high"),
    DisciplineCatalogEntry("29", "Nursing", "Health Sciences", True, "clinical_health", "critical"),
    DisciplineCatalogEntry("30", "Pharmacology, Toxicology and Pharmaceutics", "Life Sciences", True, "life_veterinary", "high"),
    DisciplineCatalogEntry("31", "Physics and Astronomy", "Physical Sciences", True, "mathematics_or_engineering", "medium"),
    DisciplineCatalogEntry("32", "Psychology", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("33", "Social Sciences", "Social Sciences", False, "excluded", "out_of_scope"),
    DisciplineCatalogEntry("34", "Veterinary", "Health Sciences", True, "life_veterinary", "high"),
    DisciplineCatalogEntry("35", "Dentistry", "Health Sciences", True, "clinical_health", "critical"),
    DisciplineCatalogEntry("36", "Health Professions", "Health Sciences", True, "clinical_health", "critical"),
)

_BY_ID = {entry.id: entry for entry in _ENTRIES}


def _alias_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower().replace("&", " and "))


_INTERNAL_KEY_TO_FIELD_ID = {
    "agricultural_biological_sciences": "11",
    "biochemistry_genetics_molecular_biology": "13",
    "chemical_engineering": "15",
    "chemistry": "16",
    "computer_science": "17",
    "earth_planetary_science": "19",
    "energy": "21",
    "engineering": "22",
    "environmental_science": "23",
    "immunology_microbiology": "24",
    "materials_science": "25",
    "mathematics": "26",
    "medicine": "27",
    "neuroscience": "28",
    "nursing": "29",
    "pharmacology_toxicology_pharmaceutics": "30",
    "physics_astronomy": "31",
    "veterinary": "34",
    "dentistry": "35",
    "health_professions": "36",
    "electrical_engineering_systems": "22",
    "quantitative_biology": "13",
    "statistics": "26",
    "astrobiology": "19",
    "astrophysics": "31",
    "astronomy": "31",
}


_ALIASES = {
    _alias_key(alias): entry.id
    for entry in _ENTRIES
    for alias in (entry.id, entry.label, f"fields/{entry.id}", f"https://openalex.org/fields/{entry.id}")
}
_ALIASES.update({
    _alias_key(key): field_id
    for key, field_id in _INTERNAL_KEY_TO_FIELD_ID.items()
})

PERMITTED_DISCIPLINE_IDS = frozenset(entry.id for entry in _ENTRIES if entry.allowed)
EXCLUDED_DISCIPLINE_IDS = frozenset(entry.id for entry in _ENTRIES if not entry.allowed)


def _iter_values(values: object) -> Iterable[object]:
    if values is None:
        return ()
    if isinstance(values, str):
        return tuple(item.strip() for item in re.split(r"[|;,\n]+", values) if item.strip())
    if isinstance(values, Iterable):
        return values
    return (values,)


def normalize_discipline_ids(values: object) -> tuple[str, ...]:
    """Resolve supported IDs, labels, and OpenAlex field URLs in input order."""

    resolved: list[str] = []
    for value in _iter_values(values):
        identifier = _ALIASES.get(_alias_key(value))
        if identifier and identifier not in resolved:
            resolved.append(identifier)
    return tuple(resolved)


def list_discipline_catalog(*, include_excluded: bool = True) -> list[dict[str, str | bool]]:
    """Return the internal catalog without importing the external PaperSeek project."""

    return [
        entry.to_dict()
        for entry in _ENTRIES
        if include_excluded or entry.allowed
    ]


def get_discipline_entries(values: object) -> tuple[DisciplineCatalogEntry, ...]:
    return tuple(_BY_ID[identifier] for identifier in normalize_discipline_ids(values))


def resolve_design_scope(values: object) -> dict[str, Any]:
    """Decide whether all requested fields belong to the supported design scope."""

    identifiers = normalize_discipline_ids(values)
    unresolved = [str(value).strip() for value in _iter_values(values) if _alias_key(value) not in _ALIASES]
    excluded = [identifier for identifier in identifiers if identifier in EXCLUDED_DISCIPLINE_IDS]
    allowed = [identifier for identifier in identifiers if identifier in PERMITTED_DISCIPLINE_IDS]
    if not identifiers:
        status = "REQUIRES_SCOPE_CLARIFICATION"
        reason = "No recognized PaperSeek/OpenAlex discipline field was supplied."
    elif unresolved:
        status = "REQUIRES_SCOPE_CLARIFICATION"
        reason = "At least one requested discipline field is not in the internal catalog."
    elif excluded:
        status = "BLOCKED_BY_SCOPE"
        reason = "The requested scope contains an explicitly excluded humanities or social-science field."
    else:
        status = "IN_SCOPE"
        reason = "All requested discipline fields are in the ExperimentDesign scientific scope."
    return {
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "catalog_source": CATALOG_SOURCE,
        "status": status,
        "reason": reason,
        "discipline_ids": list(identifiers),
        "allowed_discipline_ids": allowed,
        "excluded_discipline_ids": excluded,
        "unresolved_disciplines": unresolved,
        "template_families": sorted({entry.template_family for entry in get_discipline_entries(identifiers) if entry.allowed}),
        "baseline_risk_levels": sorted({entry.baseline_risk for entry in get_discipline_entries(identifiers) if entry.allowed}),
    }


def resolve_execution_policy(
    values: object,
    *,
    allow_digital_execution: bool = False,
) -> dict[str, Any]:
    """Return a design-first policy that never enables non-CS execution."""

    scope = resolve_design_scope(values)
    identifiers = set(scope["discipline_ids"])
    computer_science_only = identifiers == {"17"}
    eligible = (
        scope["status"] == "IN_SCOPE"
        and computer_science_only
        and bool(allow_digital_execution)
    )
    if eligible:
        mode = DIGITAL_EXECUTION_ELIGIBLE
        reason = "Digital execution was explicitly enabled for a Computer Science-only design."
    elif scope["status"] != "IN_SCOPE":
        mode = DESIGN_ONLY
        reason = "Execution is unavailable because the requested design scope is not eligible."
    elif not bool(allow_digital_execution):
        mode = DESIGN_ONLY
        reason = "Digital execution is disabled by the ExperimentDesign configuration."
    else:
        mode = DESIGN_ONLY
        reason = "Digital execution is limited to Computer Science-only designs."
    return {
        "mode": mode,
        "allow_digital_execution": bool(allow_digital_execution),
        "computer_science_only": computer_science_only,
        "reason": reason,
        "scope": scope,
    }
