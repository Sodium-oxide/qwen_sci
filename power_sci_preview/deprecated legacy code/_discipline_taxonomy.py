"""Natural-science taxonomy for provider-native literature discovery filters.

This registry deliberately sits before PaperGraph.  Its filters constrain a
provider's *candidate discovery* pool only; they never classify evidence,
source roles, directness, independence, gaps, or hypotheses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re
from typing import Any, Iterable, Mapping, Sequence


_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_DISCIPLINE_TEXT_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_SUPPORTED_PROVIDERS = frozenset({"openalex", "arxiv", "pubmed", "semantic_scholar"})


@dataclass(frozen=True)
class DisciplineTaxonomyEntry:
    """One canonical natural-science discovery discipline.

    ``coverage`` expresses the fidelity of mapping from the internal research
    catalogue to the external taxonomy.  Only ``exact`` mappings may narrow a
    provider request.  ``parent_only`` entries stay auditable hints so a broad
    or interdisciplinary question is never silently reduced to one parent
    category.
    """

    key: str
    label: str
    family: str
    aliases: tuple[str, ...]
    internal_domains: tuple[str, ...]
    openalex_field_ids: tuple[str, ...]
    wos_categories: tuple[str, ...]
    arxiv_categories: tuple[str, ...]
    semantic_scholar_fields: tuple[str, ...]
    pubmed_mesh_terms: tuple[str, ...]
    provider_applicability: tuple[str, ...]
    coverage: str = "exact"
    adjacent: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["openalex_filter"] = (
            "primary_topic.field.id:" + "|".join(self.openalex_field_ids)
            if self.openalex_field_ids
            else ""
        )
        return payload


# The OpenAlex field identifiers and broad labels follow OpenAlex's public
# field taxonomy.  WoS values are context/audit labels, not a claim that every
# connector can dispatch a WoS ``WC=`` query.
NATURAL_SCIENCE_DISCIPLINE_REGISTRY: dict[str, DisciplineTaxonomyEntry] = {
    "agricultural_biological_sciences": DisciplineTaxonomyEntry(
        key="agricultural_biological_sciences",
        label="Agricultural and Biological Sciences",
        family="life_sciences",
        aliases=("agricultural science", "agriculture", "agronomy", "ecology", "plant science", "zoology", "biological science", "biology"),
        internal_domains=("agriculture", "biology"),
        openalex_field_ids=("11",),
        wos_categories=("Agriculture, Multidisciplinary", "Biology", "Ecology", "Plant Sciences", "Zoology"),
        arxiv_categories=(),
        semantic_scholar_fields=("Biology", "Agricultural and Food Sciences"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "biorxiv"),
        adjacent=("biochemistry_genetics_molecular_biology", "environmental_science", "veterinary"),
    ),
    "biochemistry_genetics_molecular_biology": DisciplineTaxonomyEntry(
        key="biochemistry_genetics_molecular_biology",
        label="Biochemistry, Genetics and Molecular Biology",
        family="life_sciences",
        aliases=("biochemistry", "molecular biology", "genetics", "genomics", "proteomics", "cell biology", "molecular genetics"),
        internal_domains=("biology", "quantitative_biology"),
        openalex_field_ids=("13",),
        wos_categories=("Biochemistry & Molecular Biology", "Cell Biology", "Genetics & Heredity", "Developmental Biology"),
        arxiv_categories=("q-bio.BM", "q-bio.GN"),
        semantic_scholar_fields=("Biology",),
        pubmed_mesh_terms=("Biochemistry", "Genetics", "Molecular Biology"),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv", "biorxiv"),
        adjacent=("immunology_microbiology", "neuroscience", "quantitative_biology"),
    ),
    "chemical_engineering": DisciplineTaxonomyEntry(
        key="chemical_engineering",
        label="Chemical Engineering",
        family="physical_sciences_engineering",
        aliases=("chemical engineering", "reaction engineering", "reactor design", "unit operation", "separation process", "process systems engineering", "process intensification", "industrial catalysis"),
        internal_domains=("chemistry", "engineering", "materials_science"),
        openalex_field_ids=("15",),
        wos_categories=("Engineering, Chemical", "Chemistry, Applied", "Thermodynamics", "Polymer Science"),
        arxiv_categories=(),
        semantic_scholar_fields=("Engineering", "Chemistry"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "chemrxiv"),
        adjacent=("chemistry", "engineering", "energy"),
    ),
    "chemistry": DisciplineTaxonomyEntry(
        key="chemistry",
        label="Chemistry",
        family="physical_sciences",
        aliases=("chemistry", "chemical synthesis", "organic chemistry", "inorganic chemistry", "analytical chemistry", "physical chemistry", "electrochemistry", "catalysis"),
        internal_domains=("chemistry",),
        openalex_field_ids=("16",),
        wos_categories=("Chemistry, Analytical", "Chemistry, Inorganic & Nuclear", "Chemistry, Organic", "Chemistry, Physical", "Electrochemistry"),
        arxiv_categories=(),
        semantic_scholar_fields=("Chemistry",),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "chemrxiv"),
        adjacent=("chemical_engineering", "materials_science", "pharmacology_toxicology_pharmaceutics"),
    ),
    "computer_science": DisciplineTaxonomyEntry(
        key="computer_science",
        label="Computer Science",
        family="formal_computational_sciences",
        aliases=("computer science", "computing", "machine learning", "artificial intelligence", "software engineering", "information retrieval", "computer vision", "cybersecurity"),
        internal_domains=("computer_science",),
        openalex_field_ids=("17",),
        wos_categories=("Computer Science, Artificial Intelligence", "Computer Science, Information Systems", "Computer Science, Software Engineering", "Computer Science, Theory & Methods"),
        arxiv_categories=("cs.AI", "cs.LG", "cs.IR"),
        semantic_scholar_fields=("Computer Science",),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        adjacent=("mathematics", "statistics", "electrical_engineering_systems"),
    ),
    "earth_planetary_science": DisciplineTaxonomyEntry(
        key="earth_planetary_science",
        label="Earth and Planetary Sciences",
        family="earth_space_sciences",
        aliases=("earth and planetary sciences", "earth science", "earth sciences", "planetary science", "geology", "geophysics", "geochemistry", "oceanography", "meteorology", "geoscience"),
        internal_domains=("earth_environmental_science", "astrobiology", "physics"),
        openalex_field_ids=("19",),
        wos_categories=("Geochemistry & Geophysics", "Geology", "Geosciences, Multidisciplinary", "Meteorology & Atmospheric Sciences", "Oceanography"),
        arxiv_categories=("physics.geo-ph", "astro-ph.EP"),
        semantic_scholar_fields=("Geology", "Environmental Science", "Physics"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        adjacent=("environmental_science", "physics_astronomy", "astrobiology"),
    ),
    "energy": DisciplineTaxonomyEntry(
        key="energy",
        label="Energy",
        family="physical_sciences_engineering",
        aliases=("energy", "renewable energy", "power system", "hydrogen energy", "nuclear energy", "solar energy", "wind energy", "thermal energy", "energy system"),
        internal_domains=("engineering", "electrical_engineering", "chemistry", "materials_science", "earth_environmental_science"),
        openalex_field_ids=("21",),
        wos_categories=("Energy & Fuels", "Engineering, Petroleum", "Nuclear Science & Technology", "Green & Sustainable Science & Technology"),
        arxiv_categories=("physics.app-ph", "eess.SY"),
        semantic_scholar_fields=("Engineering", "Environmental Science", "Physics"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv", "chemrxiv"),
        adjacent=("engineering", "materials_science", "environmental_science"),
    ),
    "engineering": DisciplineTaxonomyEntry(
        key="engineering",
        label="Engineering",
        family="engineering",
        aliases=("engineering", "mechanical engineering", "civil engineering", "aerospace engineering", "manufacturing engineering", "marine engineering", "petroleum engineering", "geological engineering"),
        internal_domains=("engineering",),
        openalex_field_ids=("22",),
        wos_categories=("Engineering, Multidisciplinary", "Engineering, Mechanical", "Engineering, Civil", "Engineering, Aerospace", "Engineering, Manufacturing"),
        arxiv_categories=("eess.SY",),
        semantic_scholar_fields=("Engineering",),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        adjacent=("chemical_engineering", "electrical_engineering_systems", "energy"),
    ),
    "environmental_science": DisciplineTaxonomyEntry(
        key="environmental_science",
        label="Environmental Science",
        family="earth_environmental_sciences",
        aliases=("environmental science", "environmental pollution", "water quality", "water treatment", "ecotoxicology", "contamination", "environmental exposure", "waste management"),
        internal_domains=("earth_environmental_science", "agriculture", "chemistry"),
        openalex_field_ids=("23",),
        wos_categories=("Environmental Sciences", "Environmental Studies", "Water Resources", "Limnology", "Green & Sustainable Science & Technology"),
        arxiv_categories=("physics.ao-ph",),
        semantic_scholar_fields=("Environmental Science",),
        pubmed_mesh_terms=("Environmental Exposure", "Environmental Pollution"),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv"),
        adjacent=("earth_planetary_science", "agricultural_biological_sciences", "energy"),
    ),
    "immunology_microbiology": DisciplineTaxonomyEntry(
        key="immunology_microbiology",
        label="Immunology and Microbiology",
        family="life_health_sciences",
        aliases=("immunology", "microbiology", "infectious disease", "virology", "mycology", "parasitology", "immune response", "pathogen"),
        internal_domains=("biology", "medicine", "quantitative_biology"),
        openalex_field_ids=("24",),
        wos_categories=("Immunology", "Microbiology", "Infectious Diseases", "Virology", "Parasitology"),
        arxiv_categories=("q-bio.BM",),
        semantic_scholar_fields=("Biology", "Medicine"),
        pubmed_mesh_terms=("Immunology", "Microbiology"),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv", "biorxiv", "medrxiv"),
        adjacent=("biochemistry_genetics_molecular_biology", "medicine", "neuroscience"),
    ),
    "materials_science": DisciplineTaxonomyEntry(
        key="materials_science",
        label="Materials Science",
        family="physical_sciences_engineering",
        aliases=("materials science", "material science", "biomaterials", "ceramics", "composites", "metallurgy", "nanomaterials", "polymer materials", "functional material"),
        internal_domains=("materials_science", "chemistry", "engineering"),
        openalex_field_ids=("25",),
        wos_categories=("Materials Science, Multidisciplinary", "Materials Science, Ceramics", "Materials Science, Composites", "Metallurgy & Metallurgical Engineering", "Nanoscience & Nanotechnology"),
        arxiv_categories=("cond-mat.mtrl-sci",),
        semantic_scholar_fields=("Materials Science", "Chemistry", "Engineering"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv", "chemrxiv"),
        adjacent=("chemistry", "chemical_engineering", "energy"),
    ),
    "mathematics": DisciplineTaxonomyEntry(
        key="mathematics",
        label="Mathematics",
        family="formal_computational_sciences",
        aliases=("mathematics", "mathematical", "algebra", "topology", "number theory", "partial differential equation", "optimization", "control theory"),
        internal_domains=("mathematics",),
        openalex_field_ids=("26",),
        wos_categories=("Mathematics", "Mathematics, Applied", "Mathematics, Interdisciplinary Applications", "Logic"),
        arxiv_categories=("math.OC", "math.ST"),
        semantic_scholar_fields=("Mathematics",),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        adjacent=("statistics", "computer_science", "physics_astronomy"),
    ),
    "medicine": DisciplineTaxonomyEntry(
        key="medicine",
        label="Medicine",
        family="health_sciences",
        aliases=("medicine", "medical", "clinical", "patient", "hospital", "diagnosis", "therapy", "treatment", "epidemiology", "public health"),
        internal_domains=("medicine",),
        openalex_field_ids=("27",),
        wos_categories=("Medicine, General & Internal", "Medicine, Research & Experimental", "Public, Environmental & Occupational Health", "Oncology", "Clinical Neurology"),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine",),
        pubmed_mesh_terms=("Medicine",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "medrxiv", "biorxiv"),
        adjacent=("pharmacology_toxicology_pharmaceutics", "neuroscience", "nursing"),
    ),
    "neuroscience": DisciplineTaxonomyEntry(
        key="neuroscience",
        label="Neuroscience",
        family="life_health_sciences",
        aliases=("neuroscience", "neurobiology", "neurology", "neural circuit", "brain", "neurodegenerative", "neuroimaging"),
        internal_domains=("biology", "medicine", "quantitative_biology"),
        openalex_field_ids=("28",),
        wos_categories=("Neurosciences", "Clinical Neurology", "Neuroimaging", "Behavioral Sciences"),
        arxiv_categories=("q-bio.NC",),
        semantic_scholar_fields=("Biology", "Medicine", "Psychology"),
        pubmed_mesh_terms=("Neurosciences",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv", "biorxiv", "medrxiv"),
        adjacent=("medicine", "biochemistry_genetics_molecular_biology", "immunology_microbiology"),
    ),
    "nursing": DisciplineTaxonomyEntry(
        key="nursing",
        label="Nursing",
        family="health_sciences",
        aliases=("nursing", "nurse-led", "primary health care", "nursing care"),
        internal_domains=("medicine",),
        openalex_field_ids=("29",),
        wos_categories=("Nursing", "Health Care Sciences & Services", "Primary Health Care"),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine",),
        pubmed_mesh_terms=("Nursing",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "medrxiv"),
        adjacent=("health_professions", "medicine"),
    ),
    "pharmacology_toxicology_pharmaceutics": DisciplineTaxonomyEntry(
        key="pharmacology_toxicology_pharmaceutics",
        label="Pharmacology, Toxicology and Pharmaceutics",
        family="life_health_sciences",
        aliases=("pharmacology", "toxicology", "pharmaceutics", "drug discovery", "drug metabolism", "medicinal chemistry", "toxicant"),
        internal_domains=("medicine", "biology", "chemistry"),
        openalex_field_ids=("30",),
        wos_categories=("Pharmacology & Pharmacy", "Toxicology", "Chemistry, Medicinal"),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine", "Chemistry", "Biology"),
        pubmed_mesh_terms=("Pharmacology", "Toxicology"),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "biorxiv", "medrxiv", "chemrxiv"),
        adjacent=("medicine", "chemistry", "biochemistry_genetics_molecular_biology"),
    ),
    "physics_astronomy": DisciplineTaxonomyEntry(
        key="physics_astronomy",
        label="Physics and Astronomy",
        family="physical_sciences",
        aliases=("physics", "astronomy", "astrophysics", "quantum physics", "particle physics", "condensed matter", "plasma physics", "optics"),
        internal_domains=("physics", "astrobiology"),
        openalex_field_ids=("31",),
        wos_categories=("Physics, Multidisciplinary", "Physics, Applied", "Astronomy & Astrophysics", "Physics, Condensed Matter", "Optics"),
        arxiv_categories=("physics.gen-ph", "astro-ph.GA", "cond-mat.mtrl-sci"),
        semantic_scholar_fields=("Physics",),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        adjacent=("mathematics", "earth_planetary_science", "materials_science"),
    ),
    "veterinary": DisciplineTaxonomyEntry(
        key="veterinary",
        label="Veterinary",
        family="health_sciences",
        aliases=("veterinary", "veterinarian", "animal health", "animal medicine", "veterinary medicine"),
        internal_domains=("agriculture", "biology", "medicine"),
        openalex_field_ids=("34",),
        wos_categories=("Veterinary Sciences",),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine", "Biology"),
        pubmed_mesh_terms=("Veterinary Medicine",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "biorxiv", "medrxiv"),
        adjacent=("agricultural_biological_sciences", "medicine", "immunology_microbiology"),
    ),
    "dentistry": DisciplineTaxonomyEntry(
        key="dentistry",
        label="Dentistry",
        family="health_sciences",
        aliases=("dentistry", "dental", "oral health", "oral surgery", "periodontal"),
        internal_domains=("medicine",),
        openalex_field_ids=("35",),
        wos_categories=("Dentistry, Oral Surgery & Medicine",),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine",),
        pubmed_mesh_terms=("Dentistry",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "medrxiv"),
        adjacent=("medicine", "health_professions"),
    ),
    "health_professions": DisciplineTaxonomyEntry(
        key="health_professions",
        label="Health Professions",
        family="health_sciences",
        aliases=("health professions", "allied health", "rehabilitation", "occupational therapy", "physical therapy", "healthcare profession"),
        internal_domains=("medicine",),
        openalex_field_ids=("36",),
        wos_categories=("Health Care Sciences & Services", "Health Policy & Services", "Rehabilitation", "Sport Sciences"),
        arxiv_categories=(),
        semantic_scholar_fields=("Medicine",),
        pubmed_mesh_terms=("Allied Health Occupations", "Rehabilitation"),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "medrxiv"),
        adjacent=("nursing", "medicine"),
    ),
    "electrical_engineering_systems": DisciplineTaxonomyEntry(
        key="electrical_engineering_systems",
        label="Electrical Engineering and Systems",
        family="engineering",
        aliases=("electrical engineering", "power electronics", "telecommunications", "communication systems", "circuit design", "semiconductor device", "signal processing", "control systems"),
        internal_domains=("electrical_engineering",),
        openalex_field_ids=("22",),
        wos_categories=("Engineering, Electrical & Electronic", "Telecommunications", "Automation & Control Systems", "Instruments & Instrumentation"),
        arxiv_categories=("eess.SP", "eess.SY"),
        semantic_scholar_fields=("Engineering", "Computer Science"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        coverage="parent_only",
        adjacent=("engineering", "computer_science", "energy"),
    ),
    "quantitative_biology": DisciplineTaxonomyEntry(
        key="quantitative_biology",
        label="Quantitative Biology",
        family="life_sciences",
        aliases=("quantitative biology", "computational biology", "systems biology", "bioinformatics", "biophysics", "biological modeling"),
        internal_domains=("quantitative_biology",),
        openalex_field_ids=("13",),
        wos_categories=("Mathematical & Computational Biology", "Biophysics", "Biochemistry & Molecular Biology"),
        arxiv_categories=("q-bio.QM", "q-bio.GN", "q-bio.BM"),
        semantic_scholar_fields=("Biology", "Mathematics"),
        pubmed_mesh_terms=("Computational Biology",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv", "biorxiv"),
        coverage="parent_only",
        adjacent=("biochemistry_genetics_molecular_biology", "statistics", "computer_science"),
    ),
    "statistics": DisciplineTaxonomyEntry(
        key="statistics",
        label="Statistics",
        family="formal_computational_sciences",
        aliases=("statistics", "statistical inference", "experimental design", "bayesian", "probability theory", "causal inference", "uncertainty quantification"),
        internal_domains=("statistics",),
        openalex_field_ids=("26",),
        wos_categories=("Statistics & Probability", "Mathematics, Applied"),
        arxiv_categories=("stat.ML", "stat.AP", "math.ST"),
        semantic_scholar_fields=("Mathematics",),
        pubmed_mesh_terms=("Statistics as Topic",),
        provider_applicability=("openalex", "semantic_scholar", "pubmed", "arxiv"),
        coverage="parent_only",
        adjacent=("mathematics", "computer_science", "quantitative_biology"),
    ),
    "astrobiology": DisciplineTaxonomyEntry(
        key="astrobiology",
        label="Astrobiology",
        family="earth_space_life_sciences",
        aliases=("astrobiology", "life detection", "exoplanet habitability", "biosignature", "planetary habitability"),
        internal_domains=("astrobiology",),
        openalex_field_ids=("19", "31", "13"),
        wos_categories=("Astronomy & Astrophysics", "Geology", "Biochemistry & Molecular Biology"),
        arxiv_categories=("astro-ph.EP", "physics.geo-ph"),
        semantic_scholar_fields=("Physics", "Geology", "Biology"),
        pubmed_mesh_terms=(),
        provider_applicability=("openalex", "semantic_scholar", "arxiv"),
        coverage="parent_only",
        adjacent=("earth_planetary_science", "physics_astronomy", "biochemistry_genetics_molecular_biology"),
    ),
}


def _normalized_text(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(
        " ",
        _DISCIPLINE_TEXT_SEPARATOR_PATTERN.sub(" ", str(value or "").lower()),
    ).strip()


def _normal_key(value: Any) -> str:
    return _NORMALIZE_PATTERN.sub("_", _normalized_text(value)).strip("_")


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {_normalized_text(phrase)} " in f" {text} "


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _extend_taxonomy_entry(
    key: str,
    *,
    aliases: Iterable[str] = (),
    wos_categories: Iterable[str] = (),
    arxiv_categories: Iterable[str] = (),
    semantic_scholar_fields: Iterable[str] = (),
    pubmed_mesh_terms: Iterable[str] = (),
    provider_applicability: Iterable[str] = (),
    adjacent: Iterable[str] = (),
) -> None:
    """Merge PaperSeek's non-HSS discipline directions into one entry.

    The imported PaperSeek list includes Humanities/Social Sciences fields.
    This supplement is intentionally scoped to natural sciences, engineering,
    agriculture, medicine, and allied health discovery.  It updates provider
    routing hints only; it does not classify evidence strength or hypothesis
    validity.
    """

    entry = NATURAL_SCIENCE_DISCIPLINE_REGISTRY.get(key)
    if entry is None:
        return
    NATURAL_SCIENCE_DISCIPLINE_REGISTRY[key] = replace(
        entry,
        aliases=tuple(_unique((*entry.aliases, *aliases))),
        wos_categories=tuple(_unique((*entry.wos_categories, *wos_categories))),
        arxiv_categories=tuple(_unique((*entry.arxiv_categories, *arxiv_categories))),
        semantic_scholar_fields=tuple(
            _unique((*entry.semantic_scholar_fields, *semantic_scholar_fields))
        ),
        pubmed_mesh_terms=tuple(_unique((*entry.pubmed_mesh_terms, *pubmed_mesh_terms))),
        provider_applicability=tuple(
            _unique((*entry.provider_applicability, *provider_applicability))
        ),
        adjacent=tuple(_unique((*entry.adjacent, *adjacent))),
    )


def _apply_paperseek_natural_science_supplement() -> None:
    """Apply PaperSeek discipline directions, excluding HSS fields.

    Omitted OpenAlex fields from PaperSeek: Arts/Humanities, Business,
    Decision Sciences, Economics/Finance, Psychology, and Social Sciences.
    Omitted provider categories include q-fin, econ, psychology, sociology,
    political science, art, history, philosophy, linguistics, law, education,
    and other humanities/social-science options.
    """

    _extend_taxonomy_entry(
        "agricultural_biological_sciences",
        aliases=(
            "agricultural engineering", "dairy science", "animal science", "biodiversity conservation",
            "entomology", "fisheries", "food science", "food science and technology", "forestry",
            "horticulture", "marine biology", "freshwater biology", "soil science",
        ),
        wos_categories=(
            "Agricultural Engineering", "Agriculture, Dairy & Animal Science", "Agronomy",
            "Biodiversity Conservation", "Entomology", "Fisheries", "Food Science & Technology",
            "Forestry", "Horticulture", "Marine & Freshwater Biology", "Soil Science",
        ),
    )
    _extend_taxonomy_entry(
        "biochemistry_genetics_molecular_biology",
        aliases=(
            "biochemical research methods", "biotechnology", "applied microbiology",
            "developmental biology", "heredity", "reproductive biology", "physiology",
        ),
        wos_categories=(
            "Biochemical Research Methods", "Biotechnology & Applied Microbiology",
            "Developmental Biology", "Mathematical & Computational Biology", "Physiology",
            "Reproductive Biology",
        ),
        arxiv_categories=("q-bio.BM", "q-bio.GN"),
    )
    _extend_taxonomy_entry(
        "chemical_engineering",
        aliases=("chemical process", "polymer engineering", "thermodynamics", "energy and fuels"),
        wos_categories=("Energy & Fuels",),
    )
    _extend_taxonomy_entry(
        "chemistry",
        aliases=(
            "applied chemistry", "medicinal chemistry", "nuclear chemistry", "crystallography",
            "spectroscopy", "inorganic nuclear chemistry",
        ),
        wos_categories=(
            "Chemistry, Applied", "Chemistry, Medicinal", "Chemistry, Multidisciplinary",
            "Crystallography", "Spectroscopy",
        ),
    )
    _extend_taxonomy_entry(
        "computer_science",
        aliases=(
            "cybernetics", "hardware architecture", "information systems", "interdisciplinary applications",
            "neural computing", "evolutionary computing", "database systems", "human computer interaction",
        ),
        wos_categories=(
            "Computer Science, Cybernetics", "Computer Science, Hardware & Architecture",
            "Computer Science, Interdisciplinary Applications", "Robotics", "Telecommunications",
        ),
        arxiv_categories=(
            "cs.CL", "cs.CV", "cs.DB", "cs.DC", "cs.HC", "cs.NE", "cs.RO", "cs.SE",
        ),
    )
    _extend_taxonomy_entry(
        "earth_planetary_science",
        aliases=("physical geography", "mineralogy", "paleontology", "remote sensing", "planetary geology"),
        wos_categories=(
            "Astronomy & Astrophysics", "Geography, Physical", "Mineralogy", "Paleontology",
            "Remote Sensing",
        ),
    )
    _extend_taxonomy_entry(
        "energy",
        aliases=(
            "energy and fuels", "green sustainable science", "nuclear science", "petroleum engineering",
            "power engineering", "fuel science",
        ),
        wos_categories=("Environmental Sciences",),
    )
    _extend_taxonomy_entry(
        "engineering",
        aliases=(
            "automation control systems", "construction technology", "biomedical engineering",
            "electrical engineering", "environmental engineering", "geological engineering",
            "industrial engineering", "marine engineering", "ocean engineering", "petroleum engineering",
            "instrumentation", "transportation technology",
        ),
        wos_categories=(
            "Automation & Control Systems", "Construction & Building Technology", "Engineering, Biomedical",
            "Engineering, Electrical & Electronic", "Engineering, Environmental", "Engineering, Geological",
            "Engineering, Industrial", "Engineering, Marine", "Engineering, Ocean", "Engineering, Petroleum",
            "Instruments & Instrumentation", "Mechanics", "Robotics", "Transportation Science & Technology",
        ),
    )
    _extend_taxonomy_entry(
        "environmental_science",
        aliases=(
            "biodiversity conservation", "environmental studies", "limnology", "water resources",
            "sustainable science", "remote sensing environment",
        ),
        wos_categories=("Biodiversity Conservation", "Ecology", "Remote Sensing"),
    )
    _extend_taxonomy_entry(
        "immunology_microbiology",
        aliases=("mycology", "parasitology", "infectious diseases", "applied microbiology"),
        wos_categories=("Mycology",),
    )
    _extend_taxonomy_entry(
        "materials_science",
        aliases=(
            "biomaterials", "ceramic materials", "materials characterization", "coatings",
            "films", "paper materials", "wood materials", "textile materials",
        ),
        wos_categories=(
            "Materials Science, Biomaterials", "Materials Science, Characterization & Testing",
            "Materials Science, Coatings & Films", "Materials Science, Paper & Wood",
            "Materials Science, Textiles", "Polymer Science",
        ),
    )
    _extend_taxonomy_entry(
        "mathematics",
        aliases=("statistics and probability", "applied mathematics", "computational mathematics"),
        wos_categories=("Statistics & Probability",),
    )
    _extend_taxonomy_entry(
        "medicine",
        aliases=(
            "allergy", "anatomy morphology", "andrology", "anesthesiology", "cardiovascular medicine",
            "critical care", "dermatology", "emergency medicine", "endocrinology", "gastroenterology",
            "hematology", "oncology", "ophthalmology", "orthopedics", "pathology", "pediatrics",
            "radiology", "respiratory system", "urology nephrology", "tropical medicine",
        ),
        wos_categories=(
            "Allergy", "Anatomy & Morphology", "Andrology", "Anesthesiology",
            "Cardiac & Cardiovascular Systems", "Critical Care Medicine", "Dermatology",
            "Emergency Medicine", "Endocrinology & Metabolism", "Gastroenterology & Hepatology",
            "Geriatrics & Gerontology", "Hematology", "Ophthalmology", "Orthopedics",
            "Pediatrics", "Radiology, Nuclear Medicine & Medical Imaging", "Respiratory System",
            "Surgery", "Urology & Nephrology",
        ),
        pubmed_mesh_terms=(
            "Allergy and Immunology", "Anesthesiology", "Cardiology", "Dermatology",
            "Emergency Medicine", "Endocrinology", "Gastroenterology", "Hematology",
            "Nephrology", "Oncology", "Ophthalmology", "Orthopedics", "Pediatrics",
            "Radiology", "Respiratory Tract Diseases", "Surgery", "Urology",
        ),
    )
    _extend_taxonomy_entry(
        "neuroscience",
        aliases=("behavioral neuroscience", "neuroimaging", "neurosciences", "biological psychology"),
        wos_categories=("Psychology, Biological",),
    )
    _extend_taxonomy_entry(
        "nursing",
        aliases=("health care sciences", "primary health care", "nursing science"),
        wos_categories=("Public, Environmental & Occupational Health",),
    )
    _extend_taxonomy_entry(
        "pharmacology_toxicology_pharmaceutics",
        aliases=("pharmacy", "pharmaceutical sciences", "medicinal chemistry", "pharmacology pharmacy"),
        wos_categories=("Pharmacology & Pharmacy",),
        pubmed_mesh_terms=("Pharmacy", "Drug Discovery", "Pharmaceutical Preparations"),
    )
    _extend_taxonomy_entry(
        "physics_astronomy",
        aliases=(
            "acoustics", "atomic molecular chemical physics", "fluids and plasmas",
            "mathematical physics", "nuclear physics", "particles and fields",
            "quantum science technology",
        ),
        wos_categories=(
            "Acoustics", "Physics, Atomic, Molecular & Chemical", "Physics, Fluids & Plasmas",
            "Physics, Mathematical", "Physics, Nuclear", "Physics, Particles & Fields",
            "Quantum Science & Technology",
        ),
        arxiv_categories=("astro-ph.HE", "astro-ph.IM", "astro-ph.SR", "gr-qc", "hep-ex", "hep-lat", "hep-ph", "hep-th", "nucl-ex", "nucl-th", "quant-ph"),
    )
    _extend_taxonomy_entry(
        "veterinary",
        aliases=("veterinary sciences", "veterinary epidemiology", "animal disease"),
        wos_categories=("Zoology",),
    )
    _extend_taxonomy_entry(
        "health_professions",
        aliases=("medical informatics", "rehabilitation", "sport sciences", "allied health"),
        wos_categories=("Medical Informatics",),
        pubmed_mesh_terms=("Medical Informatics", "Physical Therapy Modalities", "Sports Medicine"),
    )


_apply_paperseek_natural_science_supplement()


def _entry_payload(entry: DisciplineTaxonomyEntry, score: int = 0, matches: Sequence[str] = ()) -> dict[str, Any]:
    payload = entry.to_dict()
    payload["score"] = int(score)
    payload["matched_aliases"] = list(matches)
    return payload


def list_natural_science_disciplines() -> list[dict[str, Any]]:
    """Return the supported natural-science discovery taxonomy, without HSS."""

    return [NATURAL_SCIENCE_DISCIPLINE_REGISTRY[key].to_dict() for key in sorted(NATURAL_SCIENCE_DISCIPLINE_REGISTRY)]


def get_natural_science_discipline(key: Any) -> DisciplineTaxonomyEntry | None:
    return NATURAL_SCIENCE_DISCIPLINE_REGISTRY.get(_normal_key(key))


def _provider_audit(
    provider: str,
    primary: DisciplineTaxonomyEntry | None,
    adjacent: Sequence[DisciplineTaxonomyEntry],
    *,
    resolution_reason: str,
) -> dict[str, Any]:
    selected = str(provider or "").strip().lower()
    if selected not in _SUPPORTED_PROVIDERS:
        return {
            "provider": selected,
            "mode": "unsupported_provider",
            "policy": "post_filter_only",
            "applied": False,
            "reason": "No natural-science native-filter compiler is registered for this provider.",
        }
    if primary is None:
        return {
            "provider": selected,
            "mode": "not_applied",
            "policy": "post_filter_only",
            "applied": False,
            "coverage": "unsupported",
            "reason": resolution_reason or "No confident natural-science discipline was resolved.",
        }
    adjacent_keys = [item.key for item in adjacent[:2]]
    if selected == "openalex":
        if primary.coverage != "exact" or not primary.openalex_field_ids:
            return {
                "provider": selected,
                "mode": "native_filter_withheld",
                "policy": "post_filter_only",
                "applied": False,
                "coverage": primary.coverage,
                "primary_discipline": primary.key,
                "soft_expansion_disciplines": adjacent_keys,
                "reason": "The resolved discipline maps only to a parent or mixed external field; no hard OpenAlex filter was emitted.",
            }
        filter_text = "primary_topic.field.id:" + "|".join(primary.openalex_field_ids)
        return {
            "provider": selected,
            "mode": "native_filter",
            "policy": "hard_filter",
            "applied": True,
            "coverage": primary.coverage,
            "primary_discipline": primary.key,
            "resolved_field_ids": list(primary.openalex_field_ids),
            "filter": filter_text,
            "soft_expansion_disciplines": adjacent_keys,
            "reason": "One exact primary field constrains discovery; adjacent disciplines remain audit-only soft expansion hints.",
        }
    if selected == "arxiv":
        if primary.coverage != "exact" or not primary.arxiv_categories:
            return {
                "provider": selected,
                "mode": "native_filter_withheld",
                "policy": "post_filter_only",
                "applied": False,
                "coverage": primary.coverage,
                "primary_discipline": primary.key,
                "soft_expansion_disciplines": adjacent_keys,
                "reason": "No exact arXiv category mapping is available for this resolved discipline.",
            }
        categories = list(primary.arxiv_categories[:3])
        return {
            "provider": selected,
            "mode": "native_filter",
            "policy": "hard_filter",
            "applied": True,
            "coverage": primary.coverage,
            "primary_discipline": primary.key,
            "categories": categories,
            "category_expression": "(" + " OR ".join(f"cat:{item}" for item in categories) + ")",
            "soft_expansion_disciplines": adjacent_keys,
            "reason": "One exact primary taxonomy maps to bounded arXiv categories; adjacent disciplines are not hard-constrained.",
        }
    if selected == "pubmed":
        if not primary.pubmed_mesh_terms or "pubmed" not in primary.provider_applicability:
            return {
                "provider": selected,
                "mode": "controlled_hint_only",
                "policy": "post_filter_only",
                "applied": False,
                "coverage": primary.coverage,
                "primary_discipline": primary.key,
                "reason": "No controlled PubMed MeSH restriction is registered for this discipline.",
            }
        terms = list(primary.pubmed_mesh_terms)
        return {
            "provider": selected,
            "mode": "controlled_mesh_filter",
            "policy": "hard_filter" if primary.coverage == "exact" else "post_filter_only",
            "applied": primary.coverage == "exact",
            "coverage": primary.coverage,
            "primary_discipline": primary.key,
            "mesh_terms": terms,
            "mesh_clause": "(" + " OR ".join(f'\"{term}\"[MeSH Terms]' for term in terms) + ")",
            "reason": "A controlled MeSH conjunction is appended after query compilation and cannot remove causal anchors.",
        }
    return {
        "provider": selected,
        "mode": "field_hint",
        "policy": "soft_boost",
        "applied": False,
        "coverage": primary.coverage,
        "primary_discipline": primary.key,
        "field_hints": list(primary.semantic_scholar_fields),
        "reason": "The current Semantic Scholar connector records field hints but does not dispatch a hard field filter.",
    }


def resolve_discipline_taxonomy(
    domain_or_text: Any,
    *,
    query: Any = "",
    internal_domains: Iterable[Any] = (),
    max_adjacent: int = 2,
) -> dict[str, Any]:
    """Resolve a conservative natural-science discovery taxonomy.

    Textual aliases identify a primary discipline.  Internal domains can add
    support but never force an exact provider filter by themselves: one parent
    domain such as ``biology`` legitimately spans multiple external fields.
    """

    domain_text = _normalized_text(domain_or_text)
    query_text = _normalized_text(query)
    active_domains = {_normal_key(value) for value in internal_domains if _normal_key(value)}
    ranked: list[tuple[int, DisciplineTaxonomyEntry, list[str]]] = []
    for entry in NATURAL_SCIENCE_DISCIPLINE_REGISTRY.values():
        score = 0
        matches: list[str] = []
        for alias in entry.aliases:
            if _contains_phrase(domain_text, alias):
                score += 12 + min(len(alias.split()), 3)
                matches.append(alias)
            elif _contains_phrase(query_text, alias):
                score += 7 + min(len(alias.split()), 3)
                matches.append(alias)
        domain_support = len(active_domains.intersection(entry.internal_domains))
        score += domain_support * 3
        if score:
            ranked.append((score, entry, _unique(matches)))
    ranked.sort(key=lambda item: (-item[0], item[1].key))
    primary_score, primary, primary_matches = ranked[0] if ranked else (0, None, [])
    # A weak single keyword is a discovery hint, not enough confidence to
    # narrow a provider.  The taxonomy remains observable and post-filter-only.
    primary_confident = bool(primary and (primary_score >= 10 or len(primary_matches) >= 2))
    if not primary_confident:
        primary = None
        primary_matches = []
        primary_score = 0

    adjacent_entries: list[DisciplineTaxonomyEntry] = []
    if primary is not None:
        for key in primary.adjacent:
            entry = NATURAL_SCIENCE_DISCIPLINE_REGISTRY.get(key)
            if entry is not None and entry not in adjacent_entries:
                adjacent_entries.append(entry)
            if len(adjacent_entries) >= max(0, min(int(max_adjacent), 2)):
                break
    reason = (
        "No confident natural-science discipline was resolved; provider-native filtering is withheld."
        if primary is None
        else "Resolved from declared domain/query aliases and retained as candidate-discovery metadata only."
    )
    provider_filters = {
        provider: _provider_audit(provider, primary, adjacent_entries, resolution_reason=reason)
        for provider in ("openalex", "arxiv", "pubmed", "semantic_scholar")
    }
    return {
        "schema_version": "natural_science_discipline_taxonomy_v1",
        "scope": "natural_science_health_engineering_only",
        "primary": _entry_payload(primary, primary_score, primary_matches) if primary is not None else None,
        "adjacent": [_entry_payload(entry) for entry in adjacent_entries],
        "resolved_discipline_ids": [primary.key] if primary is not None else [],
        "coverage": primary.coverage if primary is not None else "unsupported",
        "policy": provider_filters["openalex"].get("policy", "post_filter_only"),
        "provider_filters": provider_filters,
        "reason": reason,
        "evidence_boundary": "candidate_discovery_only; L0-L4 classification, causal alignment, source roles, directness, and independence remain downstream gates",
    }


def compile_provider_discipline_filter(provider: Any, resolution: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a provider's auditable native-filter payload from a resolution."""

    selected = str(provider or "").strip().lower()
    source = resolution if isinstance(resolution, Mapping) else {}
    filters = source.get("provider_filters") if isinstance(source.get("provider_filters"), Mapping) else {}
    payload = filters.get(selected) if isinstance(filters, Mapping) else None
    if isinstance(payload, Mapping):
        return dict(payload)
    return _provider_audit(selected, None, (), resolution_reason="No taxonomy resolution was supplied.")


def apply_pubmed_mesh_filter(query: Any, provider_filter: Mapping[str, Any] | None) -> str:
    """Append a controlled MeSH conjunction without editing the source query."""

    base_query = str(query or "").strip()
    payload = provider_filter if isinstance(provider_filter, Mapping) else {}
    clause = str(payload.get("mesh_clause") or "").strip()
    if not base_query or not bool(payload.get("applied")) or not clause:
        return base_query
    return f"({base_query}) AND {clause}"


def arxiv_category_expression(provider_filter: Mapping[str, Any] | None) -> str:
    payload = provider_filter if isinstance(provider_filter, Mapping) else {}
    if not bool(payload.get("applied")):
        return ""
    return str(payload.get("category_expression") or "").strip()


def taxonomy_allows_pubmed(domain_or_text: Any, *, query: Any = "", internal_domains: Iterable[Any] = ()) -> bool:
    """Whether an explicit health/life taxonomy safely supports PubMed discovery."""

    resolution = resolve_discipline_taxonomy(
        domain_or_text,
        query=query,
        internal_domains=internal_domains,
    )
    return bool(compile_provider_discipline_filter("pubmed", resolution).get("applied"))
