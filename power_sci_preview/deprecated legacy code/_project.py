from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable
import ast
import copy
import errno
import hashlib
import json
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

try:
    from .config import (
        SCIENCE_DIR,
        SCIENCE_SEMANTIC_SCHOLAR_PROBE_VARIANTS,
        SCIENCE_SUBSPACE_PROBE_MAX_CALLS_PER_PROVIDER,
    )
    from .log import log_event
    from ._utils import normalize_space
    from ._decomposition_coverage import (
        audit_selected_direction_coverage,
        build_candidate_direction_coverage_matrix,
        normalize_direction_axes,
        normalize_direction_coverage_claims,
    )
    from ._epistemic_profile import normalize_epistemic_profile
    from ._research_question_contract import (
        QUESTION_KIND_SPECS,
        RESEARCH_QUESTION_CONTRACT_VERSION,
        build_project_research_domain_contract,
        build_question_retrieval_plan,
        build_research_question_contract,
        validate_research_domain_contract,
        validate_research_question_contract,
    )
    from ._evidence_roles import (
        EVIDENCE_ROLE_REGISTRY,
        normalize_evidence_role_contract,
        role_evidence_path,
    )
except ImportError:
    from config import (
        SCIENCE_DIR,
        SCIENCE_SEMANTIC_SCHOLAR_PROBE_VARIANTS,
        SCIENCE_SUBSPACE_PROBE_MAX_CALLS_PER_PROVIDER,
    )
    from log import log_event
    from _utils import normalize_space
    from _decomposition_coverage import (
        audit_selected_direction_coverage,
        build_candidate_direction_coverage_matrix,
        normalize_direction_axes,
        normalize_direction_coverage_claims,
    )
    from _epistemic_profile import normalize_epistemic_profile
    from _research_question_contract import (
        QUESTION_KIND_SPECS,
        RESEARCH_QUESTION_CONTRACT_VERSION,
        build_project_research_domain_contract,
        build_question_retrieval_plan,
        build_research_question_contract,
        validate_research_domain_contract,
        validate_research_question_contract,
    )
    from _evidence_roles import (
        EVIDENCE_ROLE_REGISTRY,
        normalize_evidence_role_contract,
        role_evidence_path,
    )


_PROJECT_STORE_LOCK = threading.RLock()
_PROJECT_STORE_RETRY_DELAYS = (0.05, 0.15, 0.35, 0.75, 1.25)
_PROJECT_STORE_TRANSIENT_ERRNOS = {
    errno.EACCES,
    errno.EBUSY,
    errno.EINVAL,
    errno.ENOENT,
    errno.EPERM,
}
_PROJECT_STORE_TRANSIENT_WINERRORS = {5, 32, 33, 87}
_SCIENCE_STATE_MANAGER = None


# A decomposition is only useful as a retrieval plan when its variables can
# be tied to an observable comparison.  Keep this deliberately domain-neutral:
# it catches placeholder language without trying to decide whether a molecular,
# clinical, ecological, or formal mechanism is scientifically true.
SCIENTIFIC_OPERATIONALITY_PREFLIGHT_VERSION = "scientific_operationality_v6"
SCIENTIFIC_OBJECT_CONTRACT_PREFLIGHT_VERSION = "scientific_object_contract_v1"
# v3 makes object identity maturity authoritative for *local-edge* retrieval.
# Claim completeness remains a separate limit on whole-SH assertions; it must
# never route a mature, searchable object through component-bridge retrieval.
OBJECT_MATURITY_PREFLIGHT_VERSION = "object_maturity_anchorability_v3"
OBJECT_MATURITY_LLM_BATCH_SIZE = 2
OBJECT_MATURITY_LLM_MAX_TOKENS = 4_096
MATURE_OBJECT_CANDIDATE_PROMPT_VERSION = "mature_searchable_object_candidates_v1"

# A retrieval contract must keep a locally observable causal statement apart
# from a later transfer or decision interpretation.  These are generic claim
# roles, not a vocabulary for any particular scientific domain.
CAUSAL_INPUT_ROLE_TYPES = frozenset({
    "INTERVENTION", "EXPOSURE", "STRATIFICATION", "PARAMETER",
    "DESCRIPTIVE_STATE", "UNSPECIFIED",
})
CAUSAL_CLAIM_LAYERS = frozenset({
    "LOCAL_EMPIRICAL", "CROSS_SYSTEM_TRANSFER", "DECISION_INTERPRETATION",
})
_DESCRIPTIVE_STATE_INPUT_MARKERS = (
    "composition", "volume", "abundance", "distribution", "profile",
    "inventory", "prevalence", "overall state", "baseline state",
)
_PARAMETER_INPUT_MARKERS = (
    "dose", "concentration", "fraction", "ratio", "temperature",
    "pressure", "voltage", "frequency", "duration", "time interval",
)
_TRANSFER_OR_INTERPRETATION_MARKERS = (
    "potential for", "implications for", "significance for", "relevance for",
    "applicability to", "translation to", "decision", "policy", "feasibility",
    "resource value", "global impact", "clinical relevance",
)

# These are scientific object classes, not discipline vocabularies.  Keeping
# this small and typed makes the rewrite step portable across empirical and
# formal sciences without hard-coding a particular research field.
MATURE_SEARCHABLE_OBJECT_TYPES = frozenset({
    "material_family", "defined_material_system", "comparable_system",
    "model_system", "mechanism_subsystem", "defined_population",
    "device_architecture", "reaction_system",
    "ecological_system", "formal_model", "benchmark_dataset",
})
MIXED_PARENT_OBJECTIVE_PREFLIGHT_VERSION = "mixed_parent_objective_preflight_v1"
DECOMPOSITION_MIN_SUBHYPOTHESES = 1
DECOMPOSITION_MAX_SUBHYPOTHESES = 6
# The LLM returns the final high-value set directly.  There is deliberately no
# lower-bound fill: a short, source-grounded decomposition is preferable to
# heuristic SHs invented solely to reach an arbitrary count.
# DashScope/Qwen rejects output budgets above 8000 with InvalidParameter.
DECOMPOSITION_LLM_MAX_TOKENS = 8000
# Keep each LLM call cognitively bounded.  The final set is accumulated only
# from LLM-produced batches; these values do *not* create a minimum SH count
# or authorize heuristic replacement candidates.
DECOMPOSITION_LLM_BATCH_SIZE = 2
DECOMPOSITION_SH_MAX_PRIMARY_ENTITY_COUNT = 4
DECOMPOSITION_SH_MAX_EXCLUSIVE_OBJECTS = 4
DECOMPOSITION_SH_MAX_SUPPORTING_MEDIATORS = 4
DECOMPOSITION_SH_MAX_RETRIEVAL_QUERY_TERMS = 12
DECOMPOSITION_ENTITY_BREADTH_GATE_ENABLED = False
DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES = frozenset({
    "LLM_DECOMPOSITION_EMPTY",
    "LLM_DECOMPOSITION_RESPONSE_TRUNCATED",
    "LLM_DECOMPOSITION_ROOT_PROTOCOL_INVALID",
    "LLM_DECOMPOSITION_TIMEOUT",
    "LLM_DECOMPOSITION_INVOCATION_FAILED",
    "LLM_DECOMPOSITION_DISABLED",
    "DECOMPOSITION_CANDIDATE_REPAIR_REQUIRED",
    "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED",
})
_PREFLIGHT_PLACEHOLDERS = {
    "", "na", "n a", "none", "unknown", "unspecified", "tbd",
    "to be determined", "not specified", "not applicable",
}
_PREFLIGHT_GENERIC_INDEPENDENT_VARIABLES = {
    "independent variable",
    "manipulated variable",
    "variable",
    "intervention",
    "exposure",
    "function",
    "cellular function",
    "cellular process function",
    "cellular processes",
    "molecular interactions",
    "chemical reactions",
}
_PREFLIGHT_GENERIC_OUTCOMES = {
    "quantitative readout",
    "readout",
    "measurable readout",
    "observable outcome",
    "measurable outcome",
    "measurable endpoint",
    "functional outcome",
    "improved outcome",
    "function",
    "cellular function",
    "biological function",
    "normal function",
    "cellular process function",
    "cellular processes",
    "functional cellular processes",
    "process",
    "processes",
    "outcome",
    "result",
    "understanding",
    "visualization",
    "visualisation",
    "formation",
    "effect",
    "effects",
    "efficacy",
    "efficiency",
    "effectiveness",
    "feasibility",
    "performance",
    "model performance",
    "system performance",
    "quality",
    "robustness",
    "success",
    "sustainability",
    "impact",
    "impacts",
    "reliable results",
    "reproducible results",
    "reliable and reproducible results",
    "reliability",
    "reproducibility",
}
_SCIENTIFIC_OBJECT_RESEARCH_ACTION_RE = re.compile(
    r"^\s*(?:to\s+(?:quantitatively|qualitatively|systematically|experimentally|"
    r"computationally|statistically|formally|empirically)\s+|to\s+)?"
    r"(?:compare|evaluate|assess|determine|investigate|explore|"
    r"test|examine|measure|quantify|estimate|analy[sz]e|review|identify|"
    r"characteri[sz]e|optimi[sz]e|validate|verify|demonstrate|establish|"
    r"study)\b",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_OBJECT_BOUNDARY_PARAMETER_RE = re.compile(
    r"^\s*(?:using|use\s+of|by\s+using|under|within|across|over|during|for|"
    r"with|without|based\s+on|assuming|given|at)\b",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_OBJECT_TIME_HORIZON_RE = re.compile(
    r"^\s*(?:a|an|the)?\s*\d+(?:\.\d+)?\s*[- ]?"
    r"(?:year|month|day|week|hour|yr|y|h)s?\s+"
    r"(?:time\s+)?(?:horizon|window|period|timescale|timeframe)\b",
    flags=re.IGNORECASE,
)
_SCIENTIFIC_OBJECT_PARAMETER_MARKERS = frozenset({
    "time horizon",
    "assessment horizon",
    "evaluation horizon",
    "baseline scenario",
    "system boundary",
    "boundary condition",
    "discount rate",
    "time window",
    "temperature condition",
    "storage condition",
    "follow up period",
    "follow-up period",
})

_MIXED_PARENT_STOPWORDS = {
    "about", "across", "after", "also", "among", "and", "are", "because",
    "been", "being", "but", "can", "could", "does", "doing", "for", "from",
    "have", "how", "into", "its", "many", "may", "more", "onto", "our",
    "over", "recent", "recently", "reported", "should", "such", "than",
    "that", "the", "their", "these", "this", "through", "to", "using",
    "what", "when", "where", "which", "while", "with", "would", "years",
}
_MIXED_PARENT_GENERIC_TERMS = {
    "ability", "achieve", "advance", "advancement", "application",
    "applications", "approach", "approaches", "baseline", "benefit",
    "challenge", "challenges", "compare", "compared", "condition",
    "conditions", "effect", "effects", "evidence", "field", "framework",
    "future", "impact", "impacts", "implication", "implications", "level",
    "levels", "method", "methods", "model", "models", "potential",
    "process", "processes", "progress", "reality", "research", "result",
    "results", "science", "scientific", "scientists", "specific", "standard",
    "state", "study", "system", "systems", "team", "technique",
    "techniques", "technology", "testing", "using",
}
_PREFLIGHT_GENERIC_COMPARISONS = {
    "control",
    "controls",
    "baseline",
    "matched control",
    "matched control or confounder",
    "control group",
    "reference condition",
    "treated",
    "untreated",
    "treated group",
    "untreated group",
    "experimental group",
    "comparison group",
    "positive control",
    "negative control",
}
_PREFLIGHT_EXISTENTIAL_VARIABLE_RE = re.compile(
    r"^(?:presence|absence|existence|necessity)\s+of\s+(.+)$",
    re.IGNORECASE,
)
_PREFLIGHT_GENERIC_ENTITY_HEADS = frozenset({
    "category", "categories", "class", "classes", "component", "components",
    "condition", "conditions", "entity", "entities", "factor", "factors",
    "interaction", "interactions", "material", "materials", "molecule", "molecules",
    "object", "objects", "process", "processes", "reaction", "reactions",
    "system", "systems", "thing", "things",
})
_PREFLIGHT_NON_SPECIFYING_MODIFIERS = frozenset({
    "biological", "cellular", "chemical", "complex", "functional", "general",
    "generic", "molecular", "normal", "organic", "physical", "specific",
})
_PREFLIGHT_OPERATIONAL_VARIABLE_MARKERS = frozenset({
    "abundance", "allele", "composition", "concentration", "copy number", "dose",
    "duration", "enantiomeric", "exposure", "fraction", "frequency", "genotype",
    "gradient", "knockout", "level", "loading", "mutation", "overexpression",
    "parameter", "perturbation", "pressure", "proportion", "ratio", "replacement",
    "temperature", "threshold", "treatment", "variant",
})
_PREFLIGHT_VARIABLE_RESOLUTION_MARKERS = frozenset({
    "ablation", "addition", "allele", "architecture", "calibration", "charge",
    "concentration", "content", "copy number", "crosslink", "deletion", "density",
    "distribution shift", "dose", "duration", "exposure class", "feature set",
    "fraction", "frequency", "genotype", "gradient", "inhibition", "intensity",
    "knockout", "length", "level", "line of therapy", "loading", "mutation",
    "overexpression", "parameter", "ph", "pressure", "proportion", "ratio",
    "removal", "replacement", "residence time", "size", "substitution",
    "temperature", "threshold", "time", "variant",
})
_PREFLIGHT_LOW_RESOLUTION_INPUT_HEADS = frozenset({
    "approach", "approaches", "composition", "compositions", "condition", "conditions",
    "data quality", "design", "designs", "environment", "environments", "framework",
    "frameworks", "history", "management", "model", "models", "organization",
    "organisation", "organizations", "organisations", "platform", "platforms",
    "process", "processes", "program", "programs", "quality", "strategy",
    "strategies", "structure", "structures", "system", "systems", "treatment",
    "workflow", "workflows",
})
_PREFLIGHT_LOW_RESOLUTION_INPUT_PHRASES = (
    "composition change",
    "composition changes",
    "condition change",
    "condition changes",
    "environmental factor",
    "environmental factors",
    "management approach",
    "management strategy",
    "model design",
    "process condition",
    "process conditions",
    "strategy choice",
    "system design",
    "treatment history",
    "workflow design",
)
_PREFLIGHT_CONCRETE_READOUT_MARKERS = frozenset({
    # Domain-neutral measurement and statistics terms.
    "abundance", "accuracy", "activity", "auc", "auc roc", "c index",
    "calibration", "cmax", "coefficient", "concentration", "confidence interval",
    "correlation", "count", "coverage", "ec50", "effect size", "error",
    "f1 score", "false positive", "fidelity", "flux", "fraction", "half life", "half time",
    "half-life", "half-time", "hazard ratio", "ic50", "incidence", "index",
    "mae", "mass", "odds ratio", "precision", "p value", "p-value", "rate",
    "ratio", "readout", "recall", "rmse", "score", "sensitivity",
    "signal to noise", "signal-to-noise", "specificity", "threshold",
    # Biological, medical, environmental, engineering, materials, and formal
    # readout families.  These are measurement roles, not field patches.
    "capacity fade", "capacity retention", "capital cost",
    "classification error", "conductivity", "cost", "coulombic efficiency",
    "cycle life", "degradation rate", "diffusion coefficient", "elasticity",
    "abatement cost", "adverse event rate", "biodiversity index",
    "capture efficiency", "carbon removal rate", "carbon retention",
    "carbon stock change", "carbon footprint", "co2 capture efficiency", "co2 storage capacity",
    "cost per ton", "cost per tonne", "curtailment rate",
    "discharge duration", "ecosystem health", "ecosystem health index",
    "energy density", "energy efficiency", "expression",
    "failure rate", "firm capacity", "force", "fracture toughness",
    "greenhouse gas emissions", "incident rate", "leakage rate", "leakage rates",
    "levelized cost",
    "levelized cost of storage", "leakage mass", "localisation", "localization",
    "lcos", "loss of load probability", "maintenance cost",
    "maintenance costs", "metabolic activity", "mortality", "net co2 removal rate",
    "operating cost", "partition coefficient", "potency", "power density", "purity",
    "quality attribute", "resolution", "response rate",
    "round trip efficiency", "round-trip efficiency", "roundtrip efficiency",
    "specific capacity", "stability", "sterility", "stiffness", "storage capacity", "strength",
    "survival", "toxicity", "total cost of ownership", "transport rate",
    "turnaround time", "viability", "viscosity", "water usage", "yield",
    "assay signal", "growth inhibition",
    # Computational/mathematical model outputs.
    "bound", "calibration error", "convergence rate", "error bound",
    "regret bound", "sample complexity", "spectral gap",
})

# Retained only for backward-compatible state inspection.  Retrieval no longer
# imposes a minimum number of sub-hypotheses.
SCIENCE_MIN_RETRIEVAL_SUBHYPOTHESES = 0
_PREFLIGHT_BROAD_OUTCOME_TERMS = frozenset({
    "benefit", "benefits", "development", "effect", "effects",
    "effectiveness", "efficiency", "formation", "function", "functions",
    "impact", "impacts", "improvement", "maintenance", "organization",
    "organisation", "outcome", "outcomes", "performance", "process",
    "processes", "quality", "reliability", "reproducibility",
    "reproducible", "reliable", "result", "results", "success",
    "understanding", "usefulness", "validity", "visualisation",
    "visualization",
})
_PREFLIGHT_BROAD_OUTCOME_PHRASES = (
    "biological function",
    "cellular function",
    "clinical benefit",
    "environmental benefit",
    "formation and maintenance",
    "functional outcome",
    "improved outcome",
    "model performance",
    "model usefulness",
    "normal function",
    "orderly and effective",
    "reliable and reproducible",
    "reliable results",
    "reproducible results",
    "system behavior",
    "system behaviour",
    "system performance",
    "understanding of",
    "visualisation of",
    "visualization of",
)
_PREFLIGHT_COMPARISON_MARKERS = (
    " compared ", " comparison ", " versus ", " vs ", " against ",
    " baseline", " control", " counterfactual", " counterexample",
    " untreated", " sham", " placebo", " ablation", " knockout",
    " without ", " relative to ",
)


def _project_store_error_is_transient(exc: BaseException) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        # A legacy direct writer may have truncated the destination between
        # read_text() and json.loads(). Atomic writes prevent this for new
        # processes, while the retry keeps mixed-version runs recoverable.
        return True
    if not isinstance(exc, OSError):
        return False
    return (
        getattr(exc, "errno", None) in _PROJECT_STORE_TRANSIENT_ERRNOS
        or getattr(exc, "winerror", None) in _PROJECT_STORE_TRANSIENT_WINERRORS
    )


def _project_store_retry(
    operation: str,
    path: Path,
    attempt: int,
    exc: BaseException,
) -> None:
    delay = _PROJECT_STORE_RETRY_DELAYS[attempt]
    log_event(
        "WARN",
        "project_store_io_retry",
        operation=operation,
        path=str(path),
        attempt=attempt + 1,
        max_attempts=len(_PROJECT_STORE_RETRY_DELAYS) + 1,
        delay_seconds=delay,
        error_type=type(exc).__name__,
        errno=getattr(exc, "errno", None),
        winerror=getattr(exc, "winerror", None),
        error=str(exc)[:240],
    )
    time.sleep(delay)


def _read_json_store(path: Path, missing_error: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(missing_error)
    with _PROJECT_STORE_LOCK:
        for attempt in range(len(_PROJECT_STORE_RETRY_DELAYS) + 1):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if attempt:
                    log_event(
                        "SCIENCE",
                        "project_store_io_recovered",
                        operation="read",
                        path=str(path),
                        attempts=attempt + 1,
                    )
                return payload
            except (OSError, json.JSONDecodeError) as exc:
                if attempt >= len(_PROJECT_STORE_RETRY_DELAYS) or not _project_store_error_is_transient(exc):
                    raise
                _project_store_retry("read", path, attempt, exc)
    raise RuntimeError(f"Unreachable project-store read state: {path}")


def _write_json_store(path: Path, payload: Any) -> None:
    # Monolithic project snapshots are machine-managed state, and indentation
    # alone added roughly one third to large multi-paper files.  Searches and
    # small operator-facing JSON stay pretty-printed; project snapshots use a
    # lossless compact encoding after semantic persistence compaction.
    is_project_snapshot = bool(
        isinstance(payload, dict)
        and payload.get("project_id")
        and path.parent.name == "projects"
    )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=None if is_project_snapshot else 2,
        separators=(",", ":") if is_project_snapshot else None,
    )
    # Validate the exact serialized representation before it reaches either
    # the temporary file or the atomic replace boundary.  This is a focused
    # persistence-integrity check, not a repeated artifact hash gate.
    json.loads(serialized)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _PROJECT_STORE_LOCK:
        for attempt in range(len(_PROJECT_STORE_RETRY_DELAYS) + 1):
            temp_path = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
            )
            try:
                temp_path.write_text(serialized, encoding="utf-8")
                json.loads(temp_path.read_text(encoding="utf-8"))
                # The destination is never exposed as a partially written JSON
                # document. On Windows an antivirus/indexer may temporarily
                # reject replace(), so EINVAL/sharing errors use the same
                # bounded recovery policy as read_text().
                os.replace(temp_path, path)
                if attempt:
                    log_event(
                        "SCIENCE",
                        "project_store_io_recovered",
                        operation="write",
                        path=str(path),
                        attempts=attempt + 1,
                    )
                return
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt >= len(_PROJECT_STORE_RETRY_DELAYS) or not _project_store_error_is_transient(exc):
                    raise
                _project_store_retry("write", path, attempt, exc)
    raise RuntimeError(f"Unreachable project-store write state: {path}")



def create_research_project(
    title: str,
    domain: str,
    objective: str,
    strategic_need: str = "",
    research_brief: str = "",
    use_llm: bool = True,
) -> str:
    try:
        from ._models import (
            PHASES,
            resolve_project_research_identity,
            scientific_research_brief_for_domain_resolution,
        )
        from ._utils import new_id
    except ImportError:
        from _models import (
            PHASES,
            resolve_project_research_identity,
            scientific_research_brief_for_domain_resolution,
        )
        from _utils import new_id
    raw_research_brief = str(research_brief or objective)
    domain_research_brief = scientific_research_brief_for_domain_resolution(
        raw_research_brief
    )
    domain_resolution = resolve_project_research_identity(
        title=title,
        declared_domain=domain,
        objective=objective,
        research_brief=raw_research_brief,
        use_llm=use_llm,
    )
    resolved_domain = str(domain_resolution.get("primary_label") or "")
    project = {
        "project_id": new_id("sci"),
        "title": title,
        "domain": resolved_domain,
        "declared_domain": domain,
        "research_domains": domain_resolution.get("research_domains", []),
        "domain_resolution": domain_resolution,
        "research_identity": domain_resolution.get("research_identity", {}),
        "domain_taxonomy": domain_resolution.get("domain_taxonomy", {}),
        "discovery_taxonomy": domain_resolution.get("discovery_taxonomy", {}),
        "domain_context": domain_resolution.get("domain_context", {}),
        "objective": objective,
        "strategic_need": strategic_need,
        "research_brief": raw_research_brief,
        "research_brief_source": "verbatim_user_prompt" if research_brief else "objective_fallback",
        "domain_research_brief": domain_research_brief,
        "domain_research_brief_source": (
            "explicit_scientific_section"
            if domain_research_brief != raw_research_brief
            else "full_research_brief"
        ),
        "phase": PHASES[0],
        "workflow_mode": "V3_GROUPCHAT_ONLY",
        "orchestration_mode": "V3_GROUPCHAT_ONLY",
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "papergraph": [],
        "evidence": [],
        "coverage_matrix": {},
        "knowledge_gaps": [],
        "hypotheses": [],
        "keynotes": [],
        "sub_hypotheses": [],
        "objective_decomposition": {"status": "not_run", "sub_hypothesis_count": 0},
        "mechanism_reports": [],
    }
    try:
        save_project(project)
    except Exception as exc:
        # The legacy snapshot is committed before normalized V2 storage is
        # activated.  Preserve the durable identity when that second stage
        # fails so the caller can resume the same canonical GroupChat flow.
        legacy_snapshot_exists = project_path(project["project_id"]).is_file()
        if not legacy_snapshot_exists:
            raise
        initialization_result = {
            "status": "PROJECT_INITIALIZATION_FAILED",
            "terminal": False,
            "project_id": project["project_id"],
            "workflow_mode": "V3_GROUPCHAT_ONLY",
            "initialization_stage": "normalized_project_storage_activation",
            "reason_code": "NORMALIZED_V3_STATE_INITIALIZATION_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "allowed_next_stages": ["run_autogen_groupchat"],
            "next_tool": "run_autogen_groupchat",
        }
        log_event(
            "ERROR",
            "project_initialization_failed_after_legacy_snapshot",
            project_id=project["project_id"],
            initialization_stage=initialization_result["initialization_stage"],
            error_type=initialization_result["error_type"],
            error=initialization_result["error"],
        )
        return json.dumps(initialization_result, ensure_ascii=False, indent=2)
    log_event(
        "SCIENCE",
        "project_created",
        project_id=project["project_id"],
        declared_domain=domain,
        domain=resolved_domain,
        research_domains="|".join(item.get("label", "") for item in project["research_domains"]),
        domain_resolution_source=domain_resolution.get("resolution_source"),
        requires_human_confirmation=domain_resolution.get("requires_human_confirmation"),
    )
    return json.dumps(project, ensure_ascii=False, indent=2)


def project_research_domain_context(project: dict[str, Any]) -> str:
    try:
        from ._models import resolve_project_research_identity
        from ._utils import normalize_space
    except ImportError:
        from _models import resolve_project_research_identity
        from _utils import normalize_space
    resolution = project.get("domain_resolution")
    if not isinstance(resolution, dict) or not isinstance(resolution.get("research_domains"), list):
        # This path is only for legacy/incomplete persisted projects. Avoid a
        # surprise network call while reading context; explicit project create
        # and refresh own the LLM-first classification lifecycle.
        resolution = resolve_project_research_identity(
            title=project.get("title") or "",
            declared_domain=project.get("declared_domain") or project.get("domain") or "",
            objective=project.get("objective") or "",
            research_brief=project.get("research_brief") or "",
            use_llm=False,
        )
    labels = [
        str(item.get("label") or "")
        for item in resolution.get("research_domains", [])
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ]
    has_resolved_domains = bool(resolution.get("research_domains"))
    identity = resolution.get("research_identity") if isinstance(resolution.get("research_identity"), dict) else project.get("research_identity")
    primary = str(
        (identity or {}).get("label")
        or (resolution.get("primary_label") if has_resolved_domains else project.get("domain"))
        or project.get("domain")
        or ""
    )
    domain_context = resolution.get("domain_context") if isinstance(resolution.get("domain_context"), dict) else project.get("domain_context")
    secondary_labels = [
        str(item)
        for item in (domain_context or {}).get("secondary_labels", [])
        if str(item).strip()
    ]
    retrieval_terms = [
        str(item)
        for item in (domain_context or {}).get("retrieval_terms", [])
        if str(item).strip()
    ][:16]
    domain_text = " | ".join(dict.fromkeys([primary, *labels, *secondary_labels]))
    return normalize_space(
        " ".join(
            value
            for value in (
                f"Research identity: {primary}" if primary else "",
                f"Catalog taxonomy: {' | '.join(labels)}" if labels else "",
                f"Secondary research areas: {' | '.join(secondary_labels)}" if secondary_labels else "",
                f"Domain retrieval anchors: {' | '.join(retrieval_terms)}" if retrieval_terms else "",
                f"Research domains: {domain_text}" if domain_text else "",
                f"Objective: {project.get('objective') or ''}",
            )
            if value.strip()
        )
    )


def refresh_project_domain_resolution(project: dict[str, Any], use_llm: bool = True) -> dict[str, Any]:
    try:
        from ._models import (
            resolve_project_research_identity,
            scientific_research_brief_for_domain_resolution,
        )
    except ImportError:
        from _models import (
            resolve_project_research_identity,
            scientific_research_brief_for_domain_resolution,
        )
    raw_research_brief = str(project.get("research_brief") or "")
    domain_research_brief = scientific_research_brief_for_domain_resolution(
        raw_research_brief
    )
    resolution = resolve_project_research_identity(
        title=project.get("title") or "",
        declared_domain=project.get("declared_domain") or project.get("domain") or "",
        objective=project.get("objective") or "",
        research_brief=project.get("research_brief") or "",
        use_llm=use_llm,
    )
    project["domain_resolution"] = resolution
    project["research_domains"] = resolution.get("research_domains", [])
    project["research_identity"] = resolution.get("research_identity", {})
    project["domain_taxonomy"] = resolution.get("domain_taxonomy", {})
    project["discovery_taxonomy"] = resolution.get("discovery_taxonomy", {})
    project["domain_context"] = resolution.get("domain_context", {})
    project["domain_research_brief"] = domain_research_brief
    project["domain_research_brief_source"] = (
        "explicit_scientific_section"
        if domain_research_brief != raw_research_brief
        else "full_research_brief"
    )
    project["domain"] = str(resolution.get("primary_label") or "")
    return resolution


def build_research_question_contract_preflight_v3(
    sub_hypotheses: Any,
    *,
    decomposition_status: str = "",
) -> dict[str, Any]:
    invalid_contract_ids: list[str] = []
    all_sub_hypothesis_ids: list[str] = []
    for index, item in enumerate(
        sub_hypotheses if isinstance(sub_hypotheses, list) else []
    ):
        if not isinstance(item, dict):
            continue
        sub_id = str(
            item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}"
        )
        all_sub_hypothesis_ids.append(sub_id)
        try:
            contract = validate_research_question_contract(
                item.get("research_question_contract")
            )
            valid = bool(
                contract.get("contract_id")
                and (
                    contract.get("contract_revision")
                    or contract.get("declaration_hash")
                )
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            invalid_contract_ids.append(sub_id)
    if not all_sub_hypothesis_ids:
        status = (
            decomposition_status
            if decomposition_status in DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
            else "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        )
    elif invalid_contract_ids:
        status = "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
    else:
        status = "READY_FOR_SOURCE_BOUND_RETRIEVAL"
    return {
        "schema_version": "research_question_contract_preflight_v3",
        "status": status,
        "total": len(all_sub_hypothesis_ids),
        "ready_sub_hypothesis_ids": [
            sub_id
            for sub_id in all_sub_hypothesis_ids
            if sub_id not in invalid_contract_ids
        ],
        "invalid_sub_hypothesis_ids": invalid_contract_ids,
        "legacy_causal_preflight_used": False,
    }


def decompose_research_objective(
    project_id: str,
    max_subhypotheses: int = 6,
    use_llm: bool = True,
    coherence_recovery_context: dict[str, Any] | None = None,
) -> str:
    try:
        from ._subhypothesis_annotation import annotate_project_subhypotheses
    except ImportError:
        from _subhypothesis_annotation import annotate_project_subhypotheses
    project = load_project(project_id)
    limit = max(
        DECOMPOSITION_MIN_SUBHYPOTHESES,
        min(
            int(max_subhypotheses or DECOMPOSITION_MAX_SUBHYPOTHESES),
            DECOMPOSITION_MAX_SUBHYPOTHESES,
        ),
    )
    decomposition = build_objective_decomposition(
        objective=str(project.get("objective") or ""),
        domain=project_research_domain_context(project),
        research_brief=str(project.get("research_brief") or ""),
        max_subhypotheses=limit,
        use_llm=use_llm,
        coherence_recovery_context=coherence_recovery_context,
        research_domain_contract=build_project_research_domain_contract(project),
    )
    project["sub_hypotheses"] = decomposition["sub_hypotheses"]
    project["research_design_inventory"] = dict(
        decomposition.get("research_design_inventory") or {}
    )
    project["shared_knowledge_registry"] = dict(
        decomposition.get("shared_knowledge_registry") or {}
    )
    project["academic_reframing"] = decomposition.get("academic_reframing") or {
        "schema_version": "academic_reframing_v1",
        "applied": False,
        "original_objective": str(project.get("objective") or ""),
    }
    annotation_summary = annotate_project_subhypotheses(project)
    # Fresh decomposition yields only V3 research-question contracts.  The
    # former object-slot causal gate has no authority over them.
    object_contract_summary = {
        "schema_version": "research_question_scope_preflight_v3",
        "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
        "total": len(project.get("sub_hypotheses") or []),
    }
    contract_preflight = build_research_question_contract_preflight_v3(
        project.get("sub_hypotheses"),
        decomposition_status=str(decomposition.get("status") or ""),
    )
    project["research_question_contract_preflight"] = contract_preflight
    project["objective_decomposition"] = objective_decomposition_persistence_projection(
        decomposition,
        project["sub_hypotheses"],
    )
    project["updatedAt"] = time.time()
    save_project(project)
    reframing_for_log = (
        project.get("academic_reframing")
        if isinstance(project.get("academic_reframing"), dict)
        else decomposition.get("academic_reframing")
        if isinstance(decomposition.get("academic_reframing"), dict)
        else {}
    )
    dependent_variable_scope_audit = (
        decomposition.get("dependent_variable_scope_audit")
        if isinstance(decomposition.get("dependent_variable_scope_audit"), dict)
        else {}
    )
    if dependent_variable_scope_audit.get("applied"):
        log_event(
            "SCIENCE",
            "subhypothesis_dependent_variable_scope_repaired",
            project_id=project_id,
            changed_count=dependent_variable_scope_audit.get("changed_count"),
            round_trip_efficiency_present_count=dependent_variable_scope_audit.get(
                "round_trip_efficiency_present_count"
            ),
            shared_round_trip_overbroadcast_detected=dependent_variable_scope_audit.get(
                "shared_round_trip_overbroadcast_detected"
            ),
            changed=dependent_variable_scope_audit.get("changed"),
        )
    log_event(
        "SCIENCE",
        "objective_decomposed",
        project_id=project_id,
        count=len(decomposition["sub_hypotheses"]),
        extractor=decomposition.get("extractor"),
        design_inventory_basis_count=len(
            (decomposition.get("research_design_inventory") or {}).get("design_basis") or []
        ),
        rejected_design_basis_reference_count=(
            (decomposition.get("candidate_pool_policy") or {}).get(
                "rejected_design_basis_reference_count"
            )
        ),
        **_academic_reframing_log_fields(reframing_for_log),
        decomposition_objective=str(decomposition.get("decomposition_objective") or "")[:500],
        subhypothesis_annotation_total=annotation_summary.get("total"),
        subhypothesis_annotation_tiers=annotation_summary.get("by_priority_tier"),
        scientific_object_contract_valid=object_contract_summary.get("valid"),
        scientific_object_contract_invalid=object_contract_summary.get("invalid"),
        scientific_object_contract_invalid_ids=object_contract_summary.get("invalid_sub_hypothesis_ids"),
        scientific_object_contract_invalid_by_error=object_contract_summary.get("invalid_by_error"),
        research_question_contract_status=contract_preflight.get("status"),
        research_question_contract_ready_ids=contract_preflight.get("ready_sub_hypothesis_ids"),
        research_question_contract_invalid_ids=contract_preflight.get("invalid_sub_hypothesis_ids"),
        dependent_variable_scope_repair_applied=dependent_variable_scope_audit.get("applied"),
        dependent_variable_scope_repair_changed_count=dependent_variable_scope_audit.get("changed_count"),
        shared_round_trip_overbroadcast_detected=dependent_variable_scope_audit.get(
            "shared_round_trip_overbroadcast_detected"
        ),
    )
    subhypothesis_log_entries = v3_subhypothesis_decomposition_log_entries(
        project.get("sub_hypotheses")
    )
    log_event(
        "SCIENCE",
        (
            "v3_subhypothesis_decomposition_blocked"
            if contract_preflight.get("status")
            in DECOMPOSITION_TERMINAL_PROTOCOL_STATUSES
            else "v3_subhypothesis_decomposition_ready"
        ),
        project_id=project_id,
        status=str(contract_preflight.get("status") or ""),
        extractor=str(decomposition.get("extractor") or ""),
        sub_hypothesis_count=len(subhypothesis_log_entries),
        ready_sub_hypothesis_count=len(
            contract_preflight.get("ready_sub_hypothesis_ids") or []
        ),
        invalid_sub_hypothesis_ids=contract_preflight.get(
            "invalid_sub_hypothesis_ids"
        ) or [],
        design_inventory_basis_count=len(
            (decomposition.get("research_design_inventory") or {}).get("design_basis") or []
        ),
        validation_error_code_counts=dict(
            (decomposition.get("candidate_validation_audit") or {}).get(
                "validation_error_code_counts"
            )
            or {}
        ),
        candidate_repair_status=str(
            (decomposition.get("candidate_repair_audit") or {}).get("status")
            or ""
        ),
        legacy_causal_preflight_used=False,
    )
    for entry in subhypothesis_log_entries:
        log_event(
            "SCIENCE",
            "v3_subhypothesis_declared",
            project_id=project_id,
            **entry,
        )
    return json.dumps(decomposition, ensure_ascii=False, indent=2)


def _subhypothesis_log_text(value: Any, limit: int = 260) -> str:
    return normalize_space(str(value or ""))[:limit]


def v3_subhypothesis_decomposition_log_entries(
    sub_hypotheses: Any,
) -> list[dict[str, Any]]:
    """Build concise, human-facing declarations from persisted V3 contracts."""
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(sub_hypotheses or [], start=1):
        if not isinstance(item, dict):
            continue
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        question = (
            contract.get("research_question")
            if isinstance(contract.get("research_question"), dict)
            else {}
        )
        scope = (
            contract.get("scientific_scope")
            if isinstance(contract.get("scientific_scope"), dict)
            else {}
        )
        claim_target = (
            contract.get("claim_target")
            if isinstance(contract.get("claim_target"), dict)
            else {}
        )
        evidence_contract = (
            contract.get("evidence_contract")
            if isinstance(contract.get("evidence_contract"), dict)
            else {}
        )
        independence = (
            contract.get("independence_contract")
            if isinstance(contract.get("independence_contract"), dict)
            else {}
        )
        boundary = (
            contract.get("boundary_contract")
            if isinstance(contract.get("boundary_contract"), dict)
            else {}
        )
        mapping = (
            contract.get("measurement_mapping")
            if isinstance(contract.get("measurement_mapping"), dict)
            else {}
        )
        threshold = (
            contract.get("threshold_governance")
            if isinstance(contract.get("threshold_governance"), dict)
            else {}
        )
        retrieval_plan = (
            item.get("research_question_retrieval_plan")
            if isinstance(item.get("research_question_retrieval_plan"), dict)
            else {}
        )
        required_slots = [
            str(slot).strip()
            for slot in evidence_contract.get("required_slots") or []
            if str(slot).strip()
        ]
        scope_summary = "; ".join(
            f"{label}={_subhypothesis_log_text(value, 120)}"
            for label, value in (
                ("object", scope.get("research_object")),
                ("construct", claim_target.get("target_construct")),
                ("condition", scope.get("condition_or_regime")),
                ("outcome", scope.get("outcome_definition")),
            )
            if _subhypothesis_log_text(value, 120)
        )
        entries.append(
            {
                "sub_hypothesis_id": str(
                    item.get("id") or item.get("sub_hypothesis_id") or f"SH{index}"
                ),
                "question_kind": str(question.get("question_kind") or "UNRESOLVED"),
                "question": _subhypothesis_log_text(
                    question.get("question_text") or item.get("focus")
                ),
                "scope": scope_summary or "scope=unresolved",
                "claim_kind": str(claim_target.get("claim_kind") or ""),
                "required_slots": "|".join(required_slots),
                "research_role": str(contract.get("research_role") or ""),
                "design_basis_ids": "|".join(
                    str(value) for value in contract.get("design_basis_ids") or []
                    if str(value).strip()
                ),
                "independent_target": _subhypothesis_log_text(
                    independence.get("independent_falsification_target"), 160
                ),
                "shared_context_keys": "|".join(
                    str(value) for value in independence.get("shared_context_keys") or []
                    if str(value).strip()
                ),
                "boundary": _subhypothesis_log_text(
                    " vs ".join(
                        value for value in (
                            str(boundary.get("condition_a") or "").strip(),
                            str(boundary.get("condition_b") or "").strip(),
                        ) if value
                    ),
                    180,
                ),
                "mapping_status": str(mapping.get("status") or ""),
                "threshold_source": str(threshold.get("threshold_source") or ""),
                "retrieval_task_count": len(
                    [
                        task
                        for task in retrieval_plan.get("tasks") or []
                        if isinstance(task, dict)
                    ]
                ),
            }
        )
    return entries


def academic_reframing_for_objective(
    *,
    objective: str,
    domain: str = "",
    research_brief: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run the public-framing audit and optional academic rewrite.

    The rewrite is advisory and scoped: it never mutates the user's stored
    objective.  Decomposition may use ``academic_objective`` as a better parent
    question while preserving ``original_objective`` for rollback.
    """

    try:
        from ._llm import (
            academic_reframe_project_objective,
            detect_public_or_solution_list_framing,
        )
    except ImportError:
        from _llm import (
            academic_reframe_project_objective,
            detect_public_or_solution_list_framing,
        )
    mixed_parent_preflight = audit_mixed_parent_objective(
        objective=str(objective or ""),
        domain=domain,
        research_brief=research_brief,
    )
    audit = detect_public_or_solution_list_framing(
        objective,
        domain=domain,
        research_brief=research_brief,
        use_llm=use_llm,
    )
    action = str(audit.get("recommended_action") or "").strip()
    public_or_solution_reframe_required = bool(
        action in {"academic_reframing", "academic_reframing_required"}
        and (audit.get("is_public_framing") or audit.get("is_solution_list_like"))
        and int(audit.get("failure_count") or 0) > 3
    )
    academic_operationalization_required = bool(
        (
            action == "academic_operationalization"
            or audit.get("is_review_or_field_intro_like")
            or audit.get("is_under_operationalized_academic_framing")
        )
        and (
            audit.get("missing_measurable_endpoint")
            or audit.get("missing_variable_resolution")
            or audit.get("missing_comparison")
            or audit.get("missing_falsification")
        )
    )
    should_reframe = public_or_solution_reframe_required or academic_operationalization_required
    if not should_reframe:
        return {
            "schema_version": "academic_reframing_v1",
            "applied": False,
            "reframing_type": "",
            "original_objective": str(objective or ""),
            "academic_objective": "",
            "academic_rewrite": "",
            "rewrite_reason": "",
            "scope_preservation": "Original objective was used directly for decomposition.",
            "reframing_axes": [],
            "baseline_requirements": [],
            "adversarial_requirements": [],
            "original_objective_preserved": str(objective or ""),
            "framing_audit": audit,
            "mixed_parent_objective_preflight": mixed_parent_preflight,
            "extractor": str(audit.get("extractor") or ""),
        }
    reframing = academic_reframe_project_objective(
        original_objective=str(objective or ""),
        domain=domain,
        detected_weaknesses=list(audit.get("detected_weaknesses") or []),
        framing_audit=audit,
        research_brief=research_brief,
        use_llm=use_llm,
    )
    if isinstance(reframing, dict):
        reframing["mixed_parent_objective_preflight"] = mixed_parent_preflight
        if mixed_parent_preflight.get("mixed_parent_objective"):
            reframing["scope_warning"] = (
                "mixed_parent_objective_detected_before_academic_reframing; "
                "decomposition should split or isolate parent threads instead "
                "of merging their retrieval anchors"
            )
    return reframing


def apply_project_academic_reframing_preflight(
    project: dict[str, Any],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Persist the framing audit/rewrite on a project without redecomposing."""

    existing = project.get("academic_reframing")
    if (
        isinstance(existing, dict)
        and existing.get("schema_version") == "academic_reframing_v1"
        and isinstance(existing.get("mixed_parent_objective_preflight"), dict)
    ):
        return existing
    reframing = academic_reframing_for_objective(
        objective=str(project.get("objective") or ""),
        domain=project_research_domain_context(project),
        research_brief=str(project.get("research_brief") or ""),
        use_llm=use_llm,
    )
    project["academic_reframing"] = reframing
    return reframing


def _academic_reframing_log_fields(reframing: Any) -> dict[str, Any]:
    """Compact, explicit fields for logs that need to explain SH framing."""

    data = reframing if isinstance(reframing, dict) else {}
    audit = data.get("framing_audit") if isinstance(data.get("framing_audit"), dict) else {}
    mixed = (
        data.get("mixed_parent_objective_preflight")
        if isinstance(data.get("mixed_parent_objective_preflight"), dict)
        else {}
    )
    return {
        "academic_reframing_applied": bool(data.get("applied")),
        "reframing_type": str(data.get("reframing_type") or "")[:80],
        "academic_objective": str(data.get("academic_objective") or "")[:500],
        "reframing_axes": [
            str(item)[:180]
            for item in (data.get("reframing_axes") or [])
            if str(item).strip()
        ][:8],
        "adversarial_requirements": [
            str(item)[:180]
            for item in (data.get("adversarial_requirements") or [])
            if str(item).strip()
        ][:8],
        "baseline_requirements": [
            str(item)[:180]
            for item in (data.get("baseline_requirements") or [])
            if str(item).strip()
        ][:8],
        "public_framing_detected": bool(audit.get("is_public_framing")),
        "solution_list_like": bool(audit.get("is_solution_list_like")),
        "review_or_field_intro_like": bool(audit.get("is_review_or_field_intro_like")),
        "under_operationalized_academic_framing": bool(
            audit.get("is_under_operationalized_academic_framing")
        ),
        "missing_measurable_endpoint": bool(audit.get("missing_measurable_endpoint")),
        "missing_variable_resolution": bool(audit.get("missing_variable_resolution")),
        "missing_adverse_or_reversal_path": bool(
            audit.get("missing_adverse_or_reversal_path")
        ),
        "mixed_parent_objective_detected": bool(mixed.get("mixed_parent_objective")),
        "mixed_parent_objective_unsafe_to_merge": bool(mixed.get("unsafe_to_merge")),
        "mixed_parent_thread_count": int(
            (mixed.get("diagnostics") or {}).get("thread_count") or 0
        ) if isinstance(mixed.get("diagnostics"), dict) else 0,
        "mixed_parent_recommended_action": str(
            mixed.get("recommended_action") or ""
        )[:80],
    }


def _subhypothesis_restart_summary(project: dict[str, Any]) -> dict[str, Any]:
    """Capture only audit-scale state before beginning a clean SH generation."""

    return {
        "sub_hypotheses": [
            {
                "id": str(item.get("id") or ""),
                "focus": str(item.get("focus") or ""),
                "scientific_object": str(item.get("scientific_object") or ""),
                "status": str(item.get("status") or ""),
                "retrieval_status": str(
                    (item.get("retrieval") or {}).get("status")
                    if isinstance(item.get("retrieval"), dict)
                    else ""
                ),
            }
            for item in (project.get("sub_hypotheses") or [])
            if isinstance(item, dict)
        ],
        "retrieval_run_count": len(
            [item for item in (project.get("sub_hypothesis_retrieval_runs") or []) if isinstance(item, dict)]
        ),
        "papergraph_count": len(
            [item for item in (project.get("papergraph") or []) if isinstance(item, dict)]
        ),
    }


def _archive_and_clear_subhypothesis_bindings(project: dict[str, Any], generation: int) -> int:
    """Keep canonical papers/full texts but remove stale SH-specific evidence."""

    cleared = 0
    binding_keys = (
        "subhypothesis_bindings",
        "sub_hypothesis_id",
        "retrieval_branch",
        "alignment_assessment",
        "alignment_override",
        "import_context",
        "evidence_kind",
        "foundational_bridge_assessment",
    )
    for record in project.get("papergraph", []):
        if not isinstance(record, dict):
            continue
        archived = {
            key: record.pop(key)
            for key in binding_keys
            if key in record
        }
        if not archived:
            continue
        history = record.get("superseded_subhypothesis_contexts")
        history = [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []
        history.append({
            "generation": generation,
            "superseded_at": time.time(),
            "context": archived,
        })
        record["superseded_subhypothesis_contexts"] = history[-3:]
        cleared += 1
    return cleared


def _mixed_parent_objective_segments(text: str) -> list[str]:
    source = normalize_space(str(text or ""))
    if not source:
        return []
    # Public/science-writing snippets are often pasted without a space after
    # punctuation ("...?But ...").  Insert the missing boundary before
    # sentence splitting so independent parent questions do not get merged.
    source = re.sub(r"([?？.!。；;])(?=\S)", r"\1 ", source)
    raw_segments = re.split(r"(?<=[?？.!。；;])\s+|\n+", source)
    segments: list[str] = []
    for raw in raw_segments:
        clean = normalize_space(raw).strip(" -–—:;；")
        if len(clean) < 18:
            continue
        if clean.lower() in {item.lower() for item in segments}:
            continue
        segments.append(clean[:700])
    return segments[:18]


def _mixed_parent_objective_terms(text: str) -> list[str]:
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+\-./]{2,}", str(text or ""))
    ]
    output: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = token.strip("-_./")
        if (
            len(normalized) < 3
            or normalized in _MIXED_PARENT_STOPWORDS
            or normalized in _MIXED_PARENT_GENERIC_TERMS
            or normalized in seen
        ):
            continue
        seen.add(normalized)
        output.append(normalized)
    return output[:18]


def _mixed_parent_jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def audit_mixed_parent_objective(
    *,
    objective: str,
    domain: str = "",
    research_brief: str = "",
) -> dict[str, Any]:
    """Detect pasted objectives that actually contain multiple parent topics.

    This is intentionally a pre-reframing, domain-neutral scope audit.  It
    does not decide that either thread is scientifically invalid; it records
    when an academic rewrite would be unsafe if it fused independent questions
    into one parent objective.  The decomposition/retrieval stack can then
    isolate SH-local context instead of letting terms from one thread pollute
    another.
    """

    source = normalize_space(" ".join(
        part for part in (objective, research_brief) if str(part or "").strip()
    ))
    segments = _mixed_parent_objective_segments(source)
    question_count = len(re.findall(r"[?？]", source))
    if not segments:
        return {
            "schema_version": MIXED_PARENT_OBJECTIVE_PREFLIGHT_VERSION,
            "mixed_parent_objective": False,
            "unsafe_to_merge": False,
            "recommended_action": "single_parent_objective",
            "detected_threads": [],
            "diagnostics": {
                "segment_count": 0,
                "question_count": question_count,
                "domain": str(domain or ""),
            },
        }

    clusters: list[dict[str, Any]] = []
    for segment in segments:
        terms = _mixed_parent_objective_terms(segment)
        if not terms:
            continue
        term_set = set(terms)
        best_index = -1
        best_score = 0.0
        for index, cluster in enumerate(clusters):
            score = _mixed_parent_jaccard(term_set, set(cluster.get("term_set") or set()))
            # A repeated core token, such as "addiction" in a later definition
            # sentence, should rejoin the same thread even when surrounding
            # vocabulary differs.
            if not score and term_set & set(cluster.get("core_terms") or []):
                score = 0.2
            if score > best_score:
                best_index, best_score = index, score
        if best_index >= 0 and best_score >= 0.18:
            cluster = clusters[best_index]
            cluster["segments"].append(segment)
            merged = list(dict.fromkeys(list(cluster.get("core_terms") or []) + terms))
            cluster["core_terms"] = merged[:18]
            cluster["term_set"] = set(merged)
            continue
        clusters.append({
            "segments": [segment],
            "core_terms": terms[:18],
            "term_set": set(terms),
        })

    detected_threads: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters):
        core_terms = [
            term for term in (cluster.get("core_terms") or [])
            if term not in _MIXED_PARENT_GENERIC_TERMS
        ][:12]
        if not core_terms:
            continue
        label_terms = core_terms[:4]
        detected_threads.append({
            "thread_id": f"T{len(detected_threads) + 1}",
            "label": " ".join(label_terms),
            "core_terms": core_terms,
            "query_forbidden_terms_if_other_thread": core_terms,
            "evidence_spans": [str(item)[:260] for item in (cluster.get("segments") or [])[:3]],
        })

    overlap_scores: list[float] = []
    for left_index, left in enumerate(detected_threads):
        for right in detected_threads[left_index + 1:]:
            overlap_scores.append(_mixed_parent_jaccard(
                set(left.get("core_terms") or []),
                set(right.get("core_terms") or []),
            ))
    max_overlap = max(overlap_scores) if overlap_scores else 0.0
    independent_threads = len(detected_threads) >= 2 and max_overlap <= 0.28
    has_mixed_question_shape = bool(
        question_count >= 2
        or re.search(
            r"\b(?:what\s+is|how\s+does|how\s+close|can\s+we|whether|to\s+what\s+extent)\b",
            source,
            flags=re.IGNORECASE,
        )
        and len(detected_threads) >= 2
    )
    mixed = bool(independent_threads and has_mixed_question_shape)
    return {
        "schema_version": MIXED_PARENT_OBJECTIVE_PREFLIGHT_VERSION,
        "mixed_parent_objective": mixed,
        "unsafe_to_merge": mixed,
        "recommended_action": (
            "split_project_or_choose_primary_thread"
            if mixed
            else "single_parent_objective"
        ),
        "detected_threads": detected_threads[:6],
        "diagnostics": {
            "segment_count": len(segments),
            "question_count": question_count,
            "thread_count": len(detected_threads),
            "max_inter_thread_overlap": round(max_overlap, 3),
            "domain": str(domain or ""),
            "source": "heuristic_pre_academic_reframing",
        },
    }


def restart_project_from_subhypothesis_decomposition(
    project_id: str,
    *,
    reason: str = "scientific_model_redecomposition",
) -> str:
    """Start a new six-SH retrieval generation without reusing stale bindings.

    Paper identities and acquired full texts remain project-level reusable
    assets.  SH-specific alignment, reserve, gap, and failure state is
    archived or reset, so a new SH1 cannot inherit the prior SH1's evidence
    count merely because the display identifier is reused.
    """

    try:
        from ._models import PHASES
    except ImportError:
        from _models import PHASES

    project = load_project(project_id)
    previous_generation = int(project.get("subhypothesis_retrieval_generation") or 0)
    next_generation = previous_generation + 1
    archive = _subhypothesis_restart_summary(project)
    archive.update({
        "generation": previous_generation,
        "archived_at": time.time(),
        "reason": normalize_space(reason) or "scientific_model_redecomposition",
    })
    history = project.get("subhypothesis_retrieval_archives")
    history = [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []
    history.append(archive)
    project["subhypothesis_retrieval_archives"] = history[-12:]

    cleared_paper_contexts = _archive_and_clear_subhypothesis_bindings(
        project, previous_generation
    )
    # Derived material is scoped to the old causal decomposition.  Preserve
    # only project-level canonical papers/full texts and the compact archive.
    for field_name, empty_value in {
        "sub_hypothesis_count": 0,
        "research_design_inventory": {},
        "shared_knowledge_registry": {},
        "research_contract_coherence_audits_v3": {},
        "subhypothesis_scientific_operationality_preflight": {},
        "sub_hypothesis_retrieval_runs": [],
        "subhypothesis_evidence_reserve": {},
        "subhypothesis_serial_retrieval_loops": {},
        "subhypothesis_alignment_contracts": {},
        "foundational_mechanism_contracts": {},
        "research_alignment_card": {},
        "research_question_card": {},
        "coverage_matrix": {},
        "evidence": [],
        "knowledge_gaps": [],
        "primary_scientific_gaps": [],
        "secondary_scientific_gaps": [],
        "tanxi_gap_analysis": {},
        "socrates_mechanism_contracts": {},
        "socrates_reports": [],
        "mechanism_reports": [],
        "hypotheses": [],
        "mingli_draft_ideas": [],
        "mingli_finalized_ideas": [],
        "mingli_hypothesis_evolution_runs": [],
        "socratic_debates": [],
        "hypothesis_revisions": [],
        "mingli_debate_iterations": [],
        "verification_reports": [],
        "yanzhen_reports": [],
    }.items():
        project[field_name] = empty_value
    # A causal graph is a historical derived artefact, not part of a fresh V3
    # project state.  Do not create an empty replacement: retain only a stale
    # audit marker if an old run had one, so it cannot later be mistaken for
    # V3 input.
    if "causal_evidence_graph" in project:
        project["causal_evidence_graph_status"] = "STALE_SCHEMA"
        project.pop("causal_evidence_graph", None)
    project["objective_decomposition"] = {
        "status": "not_run",
        "objective": str(project.get("objective") or ""),
        "domain": project_research_domain_context(project),
        "research_brief": str(project.get("research_brief") or ""),
        "research_brief_source": "verbatim_project_brief",
        "sub_hypotheses": [],
        "restart_generation": next_generation,
        "restart_reason": archive["reason"],
    }
    project["subhypothesis_retrieval_generation"] = next_generation
    project["phase"] = PHASES[0]
    project["updatedAt"] = time.time()
    save_project(project)
    result = {
        "project_id": project_id,
        "status": "ready_for_fresh_subhypothesis_decomposition",
        "previous_generation": previous_generation,
        "generation": next_generation,
        "cleared_paper_subhypothesis_contexts": cleared_paper_contexts,
        "preserved_project_papergraph_records": archive["papergraph_count"],
        "objective": str(project.get("objective") or ""),
    }
    log_event("SCIENCE", "subhypothesis_decomposition_restart_prepared", **result)
    return json.dumps(result, ensure_ascii=False, indent=2)


def set_research_brief(
    project_id: str,
    research_brief: str,
    redecompose: bool = False,
    use_llm: bool = True,
) -> str:
    raw_research_brief = str(research_brief or "")
    if not raw_research_brief.strip():
        raise ValueError("research_brief must contain the complete original task instructions.")
    project = load_project(project_id)
    project["research_brief"] = raw_research_brief
    project["research_brief_source"] = "verbatim_user_prompt"
    refresh_project_domain_resolution(project)
    project["updatedAt"] = time.time()
    save_project(project)
    result: dict[str, Any] = {
        "project_id": project_id,
        "research_brief_chars": len(raw_research_brief),
        "research_brief_source": "verbatim_user_prompt",
        "redecomposed": False,
    }
    if redecompose:
        decomposition = json.loads(decompose_research_objective(project_id, use_llm=use_llm))
        result["redecomposed"] = True
        result["objective_decomposition"] = decomposition
    log_event("SCIENCE", "research_brief_saved", project_id=project_id, chars=len(raw_research_brief), redecompose=redecompose)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _question_kind_discriminated_schema_v3(
    question_kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Describe only the fields valid for each research-question kind."""

    selected_kinds = {
        normalize_space(str(value))
        for value in (question_kinds or [])
        if normalize_space(str(value))
    }
    variants: dict[str, Any] = {}
    slot_definition_template = {
        "meaning": "SH-specific meaning of this slot",
        "retrieval_concepts": ["field terms and source-visible synonyms"],
        "minimum_evidence": "minimum source-bound evidence needed",
        "admission_rule": "when this slot may be considered covered",
    }
    for kind, spec in QUESTION_KIND_SPECS.items():
        if selected_kinds and kind.value not in selected_kinds:
            continue
        required_slots = list(spec.required_slots)
        variant_fields: dict[str, Any] = {
            "evidence_contract": {
                "required_slots": required_slots,
                "optional_slots": [],
                "disqualifying_conditions": [],
                "required_comparability_axes": [],
                "negative_evidence_requirements": [],
            },
            "slot_definitions": {
                slot: {
                    **slot_definition_template,
                    "meaning": f"what {slot} means for this SH",
                }
                for slot in required_slots
            },
        }
        if kind.value in {"CAUSAL_IDENTIFICATION", "MECHANISM_COMPETITION"}:
            variant_fields["causal_model"] = {
                "exposure": "source-grounded exposure or candidate cause",
                "outcome": "scope-compatible outcome",
                "mediators": [],
                "moderators": [],
                "confounders": [],
                "alternative_explanations": [],
                "target_estimand": "explicit estimand or mechanism contrast",
                "identification_strategy": "design capable of resolving the declared relation",
            }
        if kind.value == "BENCHMARK_COMPARISON":
            variant_fields["comparison_contract_v4"] = {
                "schema_version": "comparison_contract_v4",
                "comparison_kind": "METHOD_VS_METHOD | MODEL_VS_MODEL | SYSTEM_VS_SYSTEM",
                "primary_arm": {
                    "arm_id": "stable_lower_snake_case",
                    "canonical_label": "specific scientifically meaningful primary arm",
                    "accepted_surface_forms": ["retrievable source form for that named arm"],
                },
                "comparator_arms": [
                    {
                        "arm_id": "stable_lower_snake_case",
                        "canonical_label": "specific scientifically meaningful comparator arm",
                        "accepted_surface_forms": ["retrievable source form for that named arm"],
                    }
                ],
                "target_comparison_pairs": [["primary_arm_id", "comparator_arm_id"]],
                "evidence_acquisition_mode": "ARM_FIRST",
                "cross_source_synthesis_mode": "COMPARABILITY_GATED",
                "required_metric_families": ["declared quantitative or qualitative endpoint family"],
                "comparability_axes": [
                    "research_object",
                    "population_or_system",
                    "condition_or_regime",
                    "measurement_definition",
                    "outcome_definition",
                ],
                "direct_pair_evidence_preferred": True,
            }
        if kind.value == "BOUNDARY_HETEROGENEITY":
            variant_fields["boundary_contract"] = {
                "boundary_variable": "one declared boundary variable",
                "condition_a": "one concrete state",
                "condition_b": "a distinct concrete state",
                "controlled_variables": ["variables held comparable"],
                "comparable_endpoint": "same endpoint measured under A and B",
            }
        if kind.value == "MEASUREMENT_VALIDITY":
            variant_fields["measurement_mapping"] = {
                "status": "ESTABLISHED_CALIBRATION | STANDARD_DEFINED | EMPIRICALLY_ESTIMATED | CONTESTED | UNMAPPED | PROJECT_DEFINED",
                "construct": "declared construct",
                "proxy_measure": "observable proxy",
                "target_measure": "reference or target measurement",
                "mapping_basis": "calibration, standard, theory, or empirical basis",
                "required_source_roles": ["allowed evidence source roles"],
            }
        variants[kind.value] = {
            "question_kind": kind.value,
            "variant_fields": variant_fields,
        }
    return {
        "discriminator_path": "sub_hypotheses[].research_question.question_kind",
        "merge_target": "sub_hypotheses[].research_question",
        "selection_rule": (
            "Select exactly one question_kind variant and merge only that variant_fields "
            "object into the research_question. Do not copy fields from any other variant."
        ),
        "variants": variants,
    }


def _research_role_discriminated_schema_v3() -> dict[str, Any]:
    return {
        "discriminator_path": "sub_hypotheses[].research_question.research_role",
        "merge_target": "sub_hypotheses[].research_question",
        "variants": {
            "PRIMARY_QUESTION": {"variant_fields": {}},
            "BASELINE_ENABLER": {"variant_fields": {}},
            "BOUNDARY_TEST": {"variant_fields": {}},
            "FOUNDATIONAL_CONTEXT": {"variant_fields": {}},
            "FALSIFICATION_RULE": {
                "variant_fields": {
                    "threshold_governance": {
                        "threshold_source": "METROLOGY_CALIBRATION | TASK_OR_ENGINEERING_REQUIREMENT | STANDARD_OR_GUIDELINE | EMPIRICAL_LITERATURE | PROJECT_DEFINED",
                        "threshold_definition": "source-bound or explicitly project-defined threshold",
                        "allowed_claim": "scope-bounded conclusion supported by this threshold",
                        "required_source_roles": ["allowed evidence source roles"],
                    }
                }
            },
        },
    }


def _research_question_candidate_manifest_schema_v3() -> dict[str, Any]:
    return {
        "schema_version": "research_question_candidate_manifest_v3",
        "direction_axes": [
            {
                "id": "AX1",
                "label": "source-grounded research direction",
                "description": "distinct knowledge question or scope constraint",
                "axis_type": "one supported direction type",
                "source_excerpt": "brief phrase grounding this direction",
            }
        ],
        "sub_hypotheses": [
            {
                "candidate_id": "C1",
                "focus": "short label",
                "question_text": "one independently answerable scientific question",
                "question_kind": "one exact ontology value",
                "research_role": "PRIMARY_QUESTION | BASELINE_ENABLER | BOUNDARY_TEST | FALSIFICATION_RULE | FOUNDATIONAL_CONTEXT",
                "primary_field": "most specific field",
                "adjacent_fields": [],
                "design_basis_ids": ["DB1"],
                "direction_coverage": [
                    {
                        "axis_id": "AX1",
                        "coverage_strength": "full | partial | none",
                        "rationale": "why the candidate covers the direction",
                    }
                ],
            }
        ],
    }


def _research_question_contract_batch_schema_v3(
    manifests: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Compile concrete candidate templates instead of exposing meta discriminators."""

    templates: list[dict[str, Any]] = []
    role_variants = _research_role_discriminated_schema_v3()["variants"]
    for index, manifest in enumerate(manifests):
        source = manifest if isinstance(manifest, dict) else {}
        candidate_id = normalize_space(
            str(source.get("candidate_id") or f"C{index + 1}")
        )
        question = (
            source.get("research_question")
            if isinstance(source.get("research_question"), dict)
            else {}
        )
        question_kind = normalize_space(
            str(source.get("question_kind") or question.get("question_kind") or "")
        )
        research_role = normalize_space(
            str(source.get("research_role") or question.get("research_role") or "")
        )
        question_text = normalize_space(
            str(source.get("question_text") or question.get("question_text") or "")
        )
        design_basis_ids = list(
            source.get("design_basis_ids")
            or question.get("design_basis_ids")
            or []
        )
        kind_schema = _question_kind_discriminated_schema_v3([question_kind])
        kind_variant = (
            (kind_schema.get("variants") or {}).get(question_kind)
            if question_kind
            else None
        )
        if not isinstance(kind_variant, dict):
            raise ValueError(
                f"Cannot compile concrete V3 contract schema for question_kind={question_kind or '<missing>'}"
            )
        research_question_template: dict[str, Any] = {
            "question_text": question_text,
            "question_kind": question_kind,
            "research_role": research_role,
            "target_knowledge_need": "necessary unknown or uncertainty",
            "expected_gap_type_priors": ["type priors for retrieval, never a verdict"],
            "scientific_scope": {
                "research_object": "", "population_or_system": "", "sample_or_model": "",
                "condition_or_regime": "", "intervention_or_exposure": "", "time_window": "",
                "spatial_scale": "", "temporal_scale": "", "method_or_design": "",
                "measurement_definition": "", "outcome_definition": "", "dataset_or_corpus": "",
            },
            "object_components": [
                {
                    "task_id": "RQ-OBJECT-1",
                    "research_object": "one internally comparable object class",
                    "population_or_system": "",
                    "prediction_horizon": "",
                    "measurement_definition": "",
                    "outcome_definition": "",
                    "data_quality_dimension": "",
                    "data_quantity_dimension": "",
                }
            ],
            "claim_target": {
                "claim_kind": "", "target_construct": "", "target_relation": "",
                "allowed_claim_strength_ceiling": "descriptive_scope_bound_claim",
            },
            "routing_contract": {
                "allowed_package_kinds": [],
                "can_compete_for_primary_research_package": True,
                "can_compete_for_primary_mechanism_package": False,
            },
            "operationalization": {
                "unit_of_analysis": "the entity, system, dataset, study, or task compared",
                "primary_construct": "one construct this SH resolves",
                "operational_measure": "observable quantity, statistic, or formal criterion",
                "comparison_unit": "matched task, reference, baseline, or explicitly not applicable",
                "decision_rule": "what result permits a scope-bounded conclusion",
            },
            "independence_contract": {
                "independent_falsification_target": "the distinct claim or decision this SH can falsify",
                "overlap_justification": "why any overlap with sibling SHs is necessary, or empty",
                "depends_on_candidate_ids": [],
                "shared_context_keys": [],
            },
            "design_basis_ids": design_basis_ids,
            **copy.deepcopy(kind_variant.get("variant_fields") or {}),
            **copy.deepcopy(
                ((role_variants.get(research_role) or {}).get("variant_fields") or {})
            ),
        }
        templates.append({
            "candidate_id": candidate_id,
            "repair_of_candidate_id": normalize_space(
                str(source.get("repair_of_candidate_id") or "")
            ),
            "focus": normalize_space(str(source.get("focus") or question_text)),
            "primary_field": normalize_space(
                str(source.get("primary_field") or "most specific scientific field")
            ),
            "adjacent_fields": list(source.get("adjacent_fields") or []),
            "priority_rationale": {
                "impact": "why resolving the question matters",
                "feasibility": "why source evidence is obtainable or difficult",
                "novelty": "why resolution remains uncertain",
                "strategic_alignment": "connection to the parent objective",
            },
            "epistemic_profile": {
                "primary_mode": "one epistemic mode compatible with the question",
                "claim_types": ["claim types compatible with the question"],
            },
            "research_question": research_question_template,
            "direction_coverage": copy.deepcopy(
                source.get("direction_coverage") or []
            ),
        })
    return {
        "schema_version": "research_question_contract_batch_v3",
        "sub_hypotheses": templates,
    }


def _research_design_inventory_schema_v3() -> dict[str, Any]:
    """Return the project-level inventory consumed by V3 decomposition."""

    return {
        "schema_version": "research_design_inventory_v1",
        "design_basis": [
            {
                "id": "DB1",
                "kind": "research_object | construct | measure | comparison | boundary | mapping | threshold | shared_context | source_role",
                "value": "one explicit project-level design element",
                "rationale": "why it constrains a later SH contract",
                "source_excerpt": "short phrase from the objective or brief",
            }
        ],
        "shared_context_keys": ["stable reusable background key"],
        "source_excerpt": "verbatim objective or brief excerpt used as the inventory basis",
    }


def extract_research_design_inventory_v3_with_llm(
    objective: str,
    domain: str,
    research_brief: str,
    academic_reframing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract an auditable design inventory before V3 SH decomposition.

    The inventory is a planning intermediate representation, not a hypothesis,
    retrieval result, or legacy causal model.  Later SHs must cite one or more
    IDs, allowing their operational choices to remain traceable to the source
    brief without inferring missing values from historic project artefacts.
    """

    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    result = call_llm_json(
        system=(
            "You extract a domain-independent scientific research-design inventory. "
            "Return only source-grounded constraints; do not create hypotheses, causal chains, "
            "papers, results, effect sizes, or ungrounded thresholds."
        ),
        prompt=(
            "Build a compact project-level design inventory before decomposing into research questions. "
            "Capture only explicit or clearly implied study-design elements: research objects, primary "
            "constructs, observable measures, comparison units, candidate boundary variables, measurement "
            "mapping bases, threshold-governance needs, shared background contexts, and permissible source roles. "
            "Use one stable DB identifier per element. Include a short source_excerpt for every element. "
            "Do not invent concrete conditions, calibration mappings, standards, or thresholds where the input "
            "does not state them; record the unresolved design need instead.\n\n"
            f"Domain: {domain}\nObjective: {objective}\n\n"
            f"Academic reframing context: {json.dumps(academic_reframing or {}, ensure_ascii=False)}\n\n"
            f"Raw task brief: {research_brief}\n\n"
            f"Return JSON only, following this schema:\n"
            f"{json.dumps(_research_design_inventory_schema_v3(), ensure_ascii=False, indent=2)}"
        ),
        max_tokens=min(4_000, DECOMPOSITION_LLM_MAX_TOKENS),
        fallback_list_key="design_basis",
    )
    payload = result if isinstance(result, dict) else {}
    raw_basis = payload.get("design_basis") if isinstance(payload.get("design_basis"), list) else []
    design_basis: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_basis, start=1):
        if not isinstance(raw, dict):
            continue
        basis_id = normalize_space(str(raw.get("id") or f"DB{index}"))
        value = normalize_space(str(raw.get("value") or ""))
        rationale = normalize_space(str(raw.get("rationale") or ""))
        source_excerpt = normalize_space(str(raw.get("source_excerpt") or ""))
        kind = normalize_space(str(raw.get("kind") or ""))
        if not basis_id or basis_id in seen_ids or not value or not source_excerpt:
            continue
        seen_ids.add(basis_id)
        design_basis.append({
            "id": basis_id,
            "kind": kind,
            "value": value,
            "rationale": rationale,
            "source_excerpt": source_excerpt,
        })
    if not design_basis:
        raise ValueError("V3 design inventory requires at least one source-grounded design_basis entry")
    shared_context_keys = [
        normalize_space(str(value))
        for value in (payload.get("shared_context_keys") or [])
        if normalize_space(str(value))
    ]
    return {
        "schema_version": "research_design_inventory_v1",
        "design_basis": design_basis,
        "shared_context_keys": list(dict.fromkeys(shared_context_keys)),
        "source_excerpt": normalize_space(str(payload.get("source_excerpt") or "")),
        "extraction_source": "llm_v3_design_inventory",
    }


def _validated_research_question_manifests_v3(
    payload: dict[str, Any],
    *,
    valid_design_basis_ids: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed_kinds = {kind.value for kind in QUESTION_KIND_SPECS}
    allowed_roles = {
        "PRIMARY_QUESTION",
        "BASELINE_ENABLER",
        "BOUNDARY_TEST",
        "FALSIFICATION_RULE",
        "FOUNDATIONAL_CONTEXT",
    }
    accepted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    raw_items = payload.get("sub_hypotheses")
    if not isinstance(raw_items, list):
        return [], [{"error_code": "ROOT_SUB_HYPOTHESES_NOT_ARRAY"}]
    for index, raw in enumerate(raw_items[:limit]):
        if not isinstance(raw, dict):
            errors.append({"index": index, "error_code": "MANIFEST_NOT_OBJECT"})
            continue
        candidate_id = normalize_space(str(raw.get("candidate_id") or ""))
        question_text = normalize_space(str(raw.get("question_text") or ""))
        question_kind = normalize_space(str(raw.get("question_kind") or ""))
        research_role = normalize_space(str(raw.get("research_role") or ""))
        design_basis_ids = [
            normalize_space(str(value))
            for value in (raw.get("design_basis_ids") or [])
            if normalize_space(str(value))
        ]
        error_code = ""
        if not candidate_id or candidate_id in seen_ids:
            error_code = "MANIFEST_CANDIDATE_ID_INVALID"
        elif not question_text:
            error_code = "MANIFEST_QUESTION_TEXT_REQUIRED"
        elif question_kind not in allowed_kinds:
            error_code = "MANIFEST_QUESTION_KIND_INVALID"
        elif research_role not in allowed_roles:
            error_code = "MANIFEST_RESEARCH_ROLE_INVALID"
        elif not design_basis_ids or not set(design_basis_ids).issubset(
            valid_design_basis_ids
        ):
            error_code = "MANIFEST_DESIGN_BASIS_INVALID"
        if error_code:
            errors.append({
                "candidate_id": candidate_id,
                "index": index,
                "error_code": error_code,
            })
            continue
        seen_ids.add(candidate_id)
        accepted.append({
            "candidate_id": candidate_id,
            "focus": normalize_space(str(raw.get("focus") or question_text))[:240],
            "question_text": question_text,
            "question_kind": question_kind,
            "research_role": research_role,
            "primary_field": normalize_space(str(raw.get("primary_field") or "")),
            "adjacent_fields": [
                normalize_space(str(value))
                for value in (raw.get("adjacent_fields") or [])
                if normalize_space(str(value))
            ],
            "design_basis_ids": list(dict.fromkeys(design_basis_ids)),
            "direction_coverage": copy.deepcopy(raw.get("direction_coverage") or []),
        })
    return accepted, errors


def _validate_expanded_research_question_batch_v3(
    payload: dict[str, Any],
    manifests: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {
        str(item.get("candidate_id") or ""): item
        for item in manifests
    }
    returned: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("sub_hypotheses") or []):
        if not isinstance(raw, dict):
            errors.append({"index": index, "error_code": "EXPANDED_CANDIDATE_NOT_OBJECT"})
            continue
        candidate_id = normalize_space(str(raw.get("candidate_id") or ""))
        manifest = expected.get(candidate_id)
        question = raw.get("research_question") if isinstance(raw.get("research_question"), dict) else {}
        if not manifest:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_CANDIDATE_ID_UNEXPECTED",
            })
            continue
        if candidate_id in returned:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_CANDIDATE_ID_DUPLICATE",
            })
            continue
        if normalize_space(str(question.get("question_kind") or "")) != manifest["question_kind"]:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_QUESTION_KIND_CHANGED",
            })
            continue
        if normalize_space(str(question.get("research_role") or "")) != manifest["research_role"]:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_RESEARCH_ROLE_CHANGED",
            })
            continue
        if normalize_space(str(question.get("question_text") or "")) != manifest["question_text"]:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_QUESTION_TEXT_CHANGED",
            })
            continue
        returned_basis_ids = [
            normalize_space(str(value))
            for value in (question.get("design_basis_ids") or [])
            if normalize_space(str(value))
        ]
        if returned_basis_ids != list(manifest["design_basis_ids"]):
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_DESIGN_BASIS_CHANGED",
            })
            continue
        returned[candidate_id] = raw
    for candidate_id in expected:
        if candidate_id not in returned:
            errors.append({
                "candidate_id": candidate_id,
                "error_code": "EXPANDED_CANDIDATE_MISSING",
            })
    return [returned[item["candidate_id"]] for item in manifests if item["candidate_id"] in returned], errors


def _compile_question_kind_slots_v3(candidate: dict[str, Any]) -> dict[str, Any]:
    compiled = copy.deepcopy(candidate)
    question = (
        compiled.get("research_question")
        if isinstance(compiled.get("research_question"), dict)
        else {}
    )
    question_kind = normalize_space(str(question.get("question_kind") or ""))
    spec = next(
        (
            value
            for kind, value in QUESTION_KIND_SPECS.items()
            if kind.value == question_kind
        ),
        None,
    )
    if spec is None:
        return compiled
    evidence_contract = (
        dict(question.get("evidence_contract"))
        if isinstance(question.get("evidence_contract"), dict)
        else {}
    )
    evidence_contract["required_slots"] = list(spec.required_slots)
    evidence_contract.setdefault("optional_slots", [])
    evidence_contract.setdefault("disqualifying_conditions", [])
    evidence_contract.setdefault("required_comparability_axes", [])
    evidence_contract.setdefault("negative_evidence_requirements", [])
    question["evidence_contract"] = evidence_contract
    compiled["research_question"] = question
    return compiled


def _validate_complete_expanded_research_question_batch_v3(
    payload: dict[str, Any],
    manifests: list[dict[str, Any]],
    *,
    objective: str,
    domain: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    identity_valid, errors = _validate_expanded_research_question_batch_v3(
        payload,
        manifests,
    )
    compiled_candidates = [
        _compile_question_kind_slots_v3(candidate)
        for candidate in identity_valid
    ]
    contract_audit: list[dict[str, Any]] = []
    normalize_sub_hypotheses(
        compiled_candidates,
        objective=objective,
        domain=domain,
        max_subhypotheses=max(1, len(compiled_candidates)),
        research_domain_contract=None,
        validation_audit=contract_audit,
        validation_stage="typed_contract_batch",
    )
    accepted_ids = {
        str(item.get("candidate_id") or "")
        for item in contract_audit
        if item.get("status") == "ACCEPTED"
    }
    for item in contract_audit:
        if item.get("status") != "REJECTED":
            continue
        errors.append({
            "candidate_id": str(item.get("candidate_id") or ""),
            "error_code": str(
                item.get("validation_error_code")
                or "RESEARCH_QUESTION_CONTRACT_VALIDATION_FAILED"
            ),
            "error_message": str(item.get("validation_error_message") or ""),
        })
    return [
        candidate
        for candidate in compiled_candidates
        if str(candidate.get("candidate_id") or "") in accepted_ids
    ], errors


def _manifest_repair_items_v3(
    raw_candidates: list[Any],
    validation_errors: list[dict[str, Any]],
    *,
    reserved_candidate_ids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for error in validation_errors:
        index = error.get("index")
        if not isinstance(index, int) or not (0 <= index < len(raw_candidates)):
            continue
        if index in seen_indexes:
            continue
        seen_indexes.add(index)
        raw_candidate = raw_candidates[index]
        candidate_id = normalize_space(
            str(raw_candidate.get("candidate_id") or "")
        ) if isinstance(raw_candidate, dict) else ""
        replacement_candidate_id = (
            candidate_id
            if candidate_id and candidate_id not in reserved_candidate_ids
            else f"REPAIR_CANDIDATE_{index + 1}"
        )
        items.append({
            "replacement_candidate_id": replacement_candidate_id,
            "raw_candidate": copy.deepcopy(raw_candidate),
            "validation_errors": [
                copy.deepcopy(item)
                for item in validation_errors
                if item.get("index") == index
            ],
        })
    return items


def _latest_decomposition_diagnostics_v3(
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    generation = diagnostics.get("generation_diagnostics")
    if not isinstance(generation, dict):
        generation = diagnostics
    manifest_attempts = generation.get("manifest_attempts")
    manifest_repairs = generation.get("manifest_repairs")
    contract_batches = generation.get("contract_batches")
    attempts = [
        item
        for collection in (manifest_attempts, manifest_repairs, contract_batches)
        if isinstance(collection, list)
        for item in collection
        if isinstance(item, dict)
    ]
    latest = dict(attempts[-1]) if attempts else dict(generation)
    validation_errors = latest.get("validation_errors")
    error_counts: dict[str, int] = {}
    if isinstance(validation_errors, list):
        for item in validation_errors:
            if not isinstance(item, dict):
                continue
            code = normalize_space(str(item.get("error_code") or ""))
            if code:
                error_counts[code] = error_counts.get(code, 0) + 1
    latest["attempt_count"] = len(attempts)
    latest["validation_error_code_counts"] = error_counts
    return latest


def decompose_research_questions_v3_with_llm(
    objective: str,
    domain: str,
    research_brief: str,
    max_subhypotheses: int,
    academic_reframing: dict[str, Any] | None = None,
    design_inventory: dict[str, Any] | None = None,
    coherence_recovery_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate V3 manifests, then expand them in bounded typed batches."""
    try:
        from ._llm import LLMJSONProtocolError, call_llm_json_contract
    except ImportError:
        from _llm import LLMJSONProtocolError, call_llm_json_contract
    limit = max(
        DECOMPOSITION_MIN_SUBHYPOTHESES,
        min(int(max_subhypotheses or DECOMPOSITION_MAX_SUBHYPOTHESES), DECOMPOSITION_MAX_SUBHYPOTHESES),
    )
    inventory = design_inventory if isinstance(design_inventory, dict) else {}
    design_basis = inventory.get("design_basis") if isinstance(inventory.get("design_basis"), list) else []
    valid_design_basis_ids = [
        str(item.get("id") or "").strip()
        for item in design_basis
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    if not valid_design_basis_ids:
        raise ValueError("V3 research-question decomposition requires a non-empty design inventory")
    recovery_context = (
        coherence_recovery_context
        if isinstance(coherence_recovery_context, dict)
        else {}
    )
    manifest_prompt = (
        f"Plan at most {limit} independent ResearchQuestionContractV3 units. Return only a compact manifest, not full contracts. "
        "Each candidate must select one exact question_kind, one research_role, one independently answerable question, and source-grounded design_basis_ids. "
        "Do not emit causal_chain, causal_contract, evidence_paths, papers, findings, effect sizes, or invented thresholds. "
        "Use fewer candidates rather than filler.\n\n"
        f"Domain: {domain}\nObjective: {objective}\n\n"
        f"Question kinds: {json.dumps([kind.value for kind in QUESTION_KIND_SPECS], ensure_ascii=False)}\n\n"
        f"Design inventory (cite only these IDs in each design_basis_ids): {json.dumps(design_basis, ensure_ascii=False)}\n\n"
        f"Academic reframing context: {json.dumps(academic_reframing or {}, ensure_ascii=False)}\n\n"
        f"Rejected contract-set coherence context: {json.dumps(recovery_context, ensure_ascii=False)}\n\n"
        f"Raw task brief: {research_brief}\n\n"
        f"Return JSON only, following this schema:\n{json.dumps(_research_question_candidate_manifest_schema_v3(), ensure_ascii=False)}"
    )
    generation_diagnostics: dict[str, Any] = {
        "schema_version": "research_question_decomposition_diagnostics_v3",
        "manifest_attempts": [],
        "manifest_repairs": [],
        "contract_batches": [],
    }
    manifest_payload: dict[str, Any] = {}
    manifests: list[dict[str, Any]] = []
    manifest_errors: list[dict[str, Any]] = []
    for attempt in range(2):
        attempt_prompt = manifest_prompt
        if attempt:
            attempt_prompt += (
                "\n\nThe prior response failed the root envelope protocol. Regenerate the complete manifest once. "
                f"Diagnostics: {json.dumps(manifest_errors, ensure_ascii=False)}"
            )
        try:
            response = call_llm_json_contract(
                system="You plan domain-independent V3 scientific research-question contracts.",
                prompt=attempt_prompt,
                max_tokens=min(3_000, DECOMPOSITION_LLM_MAX_TOKENS),
                required_list_key="sub_hypotheses",
                protocol_name="LLM_DECOMPOSITION",
                expected_schema_version="research_question_candidate_manifest_v3",
                required_root_list_keys=("direction_axes",),
            )
        except LLMJSONProtocolError as exc:
            generation_diagnostics["manifest_attempts"].append({
                "attempt": attempt + 1,
                "status": exc.code,
                **dict(exc.diagnostics),
            })
            manifest_errors = [{"error_code": exc.code}]
            if attempt:
                exc.diagnostics["generation_diagnostics"] = generation_diagnostics
                raise
            continue
        manifest_payload = dict(response["payload"])
        manifests, manifest_errors = _validated_research_question_manifests_v3(
            manifest_payload,
            valid_design_basis_ids=set(valid_design_basis_ids),
            limit=limit,
        )
        raw_manifest_candidates = (
            manifest_payload.get("sub_hypotheses")
            if isinstance(manifest_payload.get("sub_hypotheses"), list)
            else []
        )
        generation_diagnostics["manifest_attempts"].append({
            "attempt": attempt + 1,
            "status": (
                "VALID"
                if manifests and not manifest_errors
                else "PARTIAL_VALID"
                if manifests
                else "CANDIDATE_PROTOCOL_INVALID"
            ),
            **dict(response["diagnostics"]),
            "accepted_manifest_count": len(manifests),
            "raw_candidates": copy.deepcopy(
                raw_manifest_candidates
            )[:limit],
            "validation_errors": copy.deepcopy(manifest_errors),
        })
        break

    repair_items = _manifest_repair_items_v3(
        list(manifest_payload.get("sub_hypotheses") or []),
        manifest_errors,
        reserved_candidate_ids={
            str(item.get("candidate_id") or "")
            for item in manifests
        },
    )
    if repair_items and len(manifests) < limit:
        accepted_candidate_ids = {
            str(item.get("candidate_id") or "")
            for item in manifests
        }
        expected_repair_ids = {
            str(item.get("replacement_candidate_id") or "")
            for item in repair_items
        }
        repair_prompt = (
            "Repair only the invalid V3 research-question manifest candidates below. "
            "Return one corrected candidate for each replacement_candidate_id and do not return any already accepted candidate. "
            "Each corrected candidate must copy replacement_candidate_id into candidate_id, select question_kind only from the allowed list, "
            "select research_role independently, and cite only supplied design_basis_ids. Return fewer candidates if an item cannot be repaired; "
            "do not invent a filler candidate.\n\n"
            f"Allowed question kinds: {json.dumps([kind.value for kind in QUESTION_KIND_SPECS], ensure_ascii=False)}\n\n"
            f"Already accepted candidate IDs: {json.dumps(sorted(accepted_candidate_ids), ensure_ascii=False)}\n\n"
            f"Invalid candidates and exact errors: {json.dumps(repair_items, ensure_ascii=False)}\n\n"
            f"Design inventory: {json.dumps(design_basis, ensure_ascii=False)}\n\n"
            f"Return JSON only, following this schema:\n{json.dumps(_research_question_candidate_manifest_schema_v3(), ensure_ascii=False)}"
        )
        try:
            repair_response = call_llm_json_contract(
                system="You repair only invalid V3 scientific research-question manifests.",
                prompt=repair_prompt,
                max_tokens=min(2_000, DECOMPOSITION_LLM_MAX_TOKENS),
                required_list_key="sub_hypotheses",
                protocol_name="LLM_DECOMPOSITION",
                expected_schema_version="research_question_candidate_manifest_v3",
                required_root_list_keys=("direction_axes",),
            )
        except LLMJSONProtocolError as exc:
            generation_diagnostics["manifest_repairs"].append({
                "attempt": 1,
                "status": exc.code,
                "replacement_candidate_ids": sorted(expected_repair_ids),
                **dict(exc.diagnostics),
            })
            if not manifests:
                raise LLMJSONProtocolError(
                    "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED",
                    "No valid V3 manifest remained after the targeted candidate repair failed",
                    {"generation_diagnostics": generation_diagnostics},
                ) from exc
        else:
            repair_payload = dict(repair_response["payload"])
            repaired_manifests, repair_errors = _validated_research_question_manifests_v3(
                repair_payload,
                valid_design_basis_ids=set(valid_design_basis_ids),
                limit=min(len(repair_items), limit - len(manifests)),
            )
            filtered_repairs: list[dict[str, Any]] = []
            for index, candidate in enumerate(repaired_manifests):
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id in accepted_candidate_ids:
                    repair_errors.append({
                        "candidate_id": candidate_id,
                        "index": index,
                        "error_code": "MANIFEST_REPAIR_DUPLICATES_ACCEPTED_CANDIDATE",
                    })
                    continue
                if candidate_id not in expected_repair_ids:
                    repair_errors.append({
                        "candidate_id": candidate_id,
                        "index": index,
                        "error_code": "MANIFEST_REPAIR_CANDIDATE_ID_UNEXPECTED",
                    })
                    continue
                filtered_repairs.append(candidate)
                accepted_candidate_ids.add(candidate_id)
            generation_diagnostics["manifest_repairs"].append({
                "attempt": 1,
                "status": (
                    "VALID"
                    if filtered_repairs and not repair_errors
                    else "PARTIAL_VALID"
                    if filtered_repairs
                    else "CANDIDATE_PROTOCOL_INVALID"
                ),
                "replacement_candidate_ids": sorted(expected_repair_ids),
                **dict(repair_response["diagnostics"]),
                "accepted_manifest_count": len(filtered_repairs),
                "raw_candidates": copy.deepcopy(
                    repair_payload.get("sub_hypotheses") or []
                )[:len(repair_items)],
                "validation_errors": copy.deepcopy(repair_errors),
            })
            manifests.extend(filtered_repairs)

    if not manifests:
        raise LLMJSONProtocolError(
            "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED",
            "No V3 research-question manifest passed generation and targeted repair",
            {"generation_diagnostics": generation_diagnostics},
        )

    expanded_candidates: list[dict[str, Any]] = []
    for batch_number, offset in enumerate(
        range(0, len(manifests), DECOMPOSITION_LLM_BATCH_SIZE),
        start=1,
    ):
        batch = manifests[offset : offset + DECOMPOSITION_LLM_BATCH_SIZE]
        pending_batch = list(batch)
        accepted_by_id: dict[str, dict[str, Any]] = {}
        batch_errors: list[dict[str, Any]] = []
        for attempt in range(2):
            batch_schema = _research_question_contract_batch_schema_v3(
                pending_batch
            )
            batch_prompt = (
                "Expand exactly the supplied compact manifests into complete ResearchQuestionContractV3 candidate declarations. "
                "Preserve candidate_id, question_text, question_kind, research_role, and design_basis_ids exactly. "
                "The supplied schema is already compiled per candidate: return every field shown inside each candidate and do not return schema metadata. "
                "Every required slot needs a source-visible definition with meaning, retrieval_concepts, minimum_evidence, and admission_rule. "
                "Do not emit fields from another question kind and do not use legacy causal artifacts.\n\n"
                f"Domain: {domain}\nObjective: {objective}\n\n"
                f"Design inventory: {json.dumps(design_basis, ensure_ascii=False)}\n\n"
                f"Candidate manifests: {json.dumps(pending_batch, ensure_ascii=False)}\n\n"
                f"Schema: {json.dumps(batch_schema, ensure_ascii=False)}"
            )
            if attempt:
                batch_prompt += (
                    "\n\nOnly the candidates still listed above failed the first expansion. Repair those candidates once, correcting these exact errors: "
                    f"{json.dumps(batch_errors, ensure_ascii=False)}"
                )
            try:
                response = call_llm_json_contract(
                    system="You expand compact scientific question manifests into strict V3 contracts.",
                    prompt=batch_prompt,
                    max_tokens=DECOMPOSITION_LLM_MAX_TOKENS,
                    required_list_key="sub_hypotheses",
                    protocol_name="LLM_DECOMPOSITION",
                    expected_schema_version="research_question_contract_batch_v3",
                )
            except LLMJSONProtocolError as exc:
                generation_diagnostics["contract_batches"].append({
                    "batch_number": batch_number,
                    "attempt": attempt + 1,
                    "candidate_ids": [item["candidate_id"] for item in pending_batch],
                    "status": exc.code,
                    **dict(exc.diagnostics),
                })
                batch_errors = [{"error_code": exc.code}]
                if attempt:
                    break
                continue
            accepted_attempt, batch_errors = _validate_complete_expanded_research_question_batch_v3(
                dict(response["payload"]),
                pending_batch,
                objective=objective,
                domain=domain,
            )
            for candidate in accepted_attempt:
                accepted_by_id[str(candidate.get("candidate_id") or "")] = candidate
            accepted_attempt_ids = {
                str(candidate.get("candidate_id") or "")
                for candidate in accepted_attempt
            }
            failed_ids = {
                str(item.get("candidate_id") or "")
                for item in pending_batch
                if str(item.get("candidate_id") or "") not in accepted_attempt_ids
            }
            generation_diagnostics["contract_batches"].append({
                "batch_number": batch_number,
                "attempt": attempt + 1,
                "candidate_ids": [item["candidate_id"] for item in pending_batch],
                "status": (
                    "VALID"
                    if accepted_attempt and not failed_ids and not batch_errors
                    else "PARTIAL_VALID"
                    if accepted_attempt
                    else "CANDIDATE_PROTOCOL_INVALID"
                ),
                **dict(response["diagnostics"]),
                "accepted_candidate_ids": sorted(accepted_attempt_ids),
                "failed_candidate_ids": sorted(failed_ids),
                "raw_candidates": copy.deepcopy(
                    (response.get("payload") or {}).get("sub_hypotheses") or []
                )[:len(pending_batch)],
                "validation_errors": copy.deepcopy(batch_errors),
            })
            if not failed_ids:
                break
            pending_batch = [
                item
                for item in pending_batch
                if str(item.get("candidate_id") or "") in failed_ids
            ]
        expanded_candidates.extend(
            accepted_by_id[candidate_id]
            for candidate_id in [
                str(item.get("candidate_id") or "")
                for item in batch
            ]
            if candidate_id in accepted_by_id
        )

    if not expanded_candidates:
        raise LLMJSONProtocolError(
            "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED",
            "No complete V3 research-question contract passed typed expansion and its one targeted repair",
            {"generation_diagnostics": generation_diagnostics},
        )

    return {
        "schema_version": "research_question_objective_decomposition_v3",
        "direction_axes": manifest_payload.get("direction_axes") if isinstance(manifest_payload.get("direction_axes"), list) else [],
        "sub_hypotheses": expanded_candidates,
        "combination_hypothesis": {},
        "generation_diagnostics": generation_diagnostics,
        "iteration_audit": {
            "schema_version": "research_question_decomposition_generation_v3",
            "legacy_causal_decomposition_used": False,
            "returned_sub_hypothesis_count": len(expanded_candidates),
            "design_inventory_schema_version": str(inventory.get("schema_version") or ""),
            "design_basis_count": len(valid_design_basis_ids),
            "coherence_recovery_applied": bool(recovery_context),
            "manifest_call_count": len(generation_diagnostics["manifest_attempts"]),
            "manifest_repair_call_count": len(generation_diagnostics["manifest_repairs"]),
            "contract_batch_call_count": len(generation_diagnostics["contract_batches"]),
        },
    }


def repair_research_question_candidates_v3_with_llm(
    *,
    objective: str,
    domain: str,
    research_brief: str,
    academic_reframing: dict[str, Any],
    design_inventory: dict[str, Any],
    rejected_candidates: list[dict[str, Any]],
    max_subhypotheses: int,
) -> dict[str, Any]:
    """Run one protocol-directed repair call for explicitly rejected candidates."""

    try:
        from ._llm import call_llm_json_contract
    except ImportError:
        from _llm import call_llm_json_contract
    repair_inputs = [
        {
            "candidate_id": str(item.get("candidate_id") or ""),
            "validation_error_code": str(item.get("validation_error_code") or ""),
            "validation_error_message": str(item.get("validation_error_message") or ""),
            "raw_candidate": copy.deepcopy(item.get("raw_candidate") or {}),
        }
        for item in rejected_candidates
        if isinstance(item, dict)
    ]
    limit = max(
        1,
        min(int(max_subhypotheses or 1), DECOMPOSITION_MAX_SUBHYPOTHESES),
    )
    repair_inputs = repair_inputs[:limit]
    repaired_candidates: list[dict[str, Any]] = []
    batch_diagnostics: list[dict[str, Any]] = []
    for batch_number, offset in enumerate(
        range(0, len(repair_inputs), DECOMPOSITION_LLM_BATCH_SIZE),
        start=1,
    ):
        repair_batch = repair_inputs[
            offset : offset + DECOMPOSITION_LLM_BATCH_SIZE
        ]
        repair_manifests: list[dict[str, Any]] = []
        for item in repair_batch:
            raw_candidate = copy.deepcopy(item.get("raw_candidate") or {})
            raw_candidate["candidate_id"] = str(item.get("candidate_id") or "")
            raw_candidate["repair_of_candidate_id"] = str(
                item.get("candidate_id") or ""
            )
            repair_manifests.append(raw_candidate)
        schema = _research_question_contract_batch_schema_v3(repair_manifests)
        try:
            response = call_llm_json_contract(
                system=(
                    "You repair rejected scientific research-question contracts from explicit protocol errors. "
                    "You do not invent papers, findings, thresholds, or legacy causal fields."
                ),
                prompt=(
                    f"Repair exactly this bounded batch of at most {DECOMPOSITION_LLM_BATCH_SIZE} rejected ResearchQuestionContractV3 candidates. "
                    "Return one repaired candidate for each input that can be made source-grounded. Preserve its "
                    "candidate_id and set repair_of_candidate_id to that same identifier. Do not paraphrase an "
                    "invalid object into a different research task. Resolve every supplied validation_error_code. "
                    "The response schema is already compiled per candidate. Return every field shown inside each "
                    "candidate and do not return discriminator or schema metadata. Return fewer candidates when "
                    "the source brief cannot support a valid repair.\n\n"
                    f"Domain: {domain}\nObjective: {objective}\n\n"
                    f"Design inventory: {json.dumps(design_inventory, ensure_ascii=False)}\n\n"
                    f"Academic reframing context: {json.dumps(academic_reframing, ensure_ascii=False)}\n\n"
                    f"Rejected candidates and validator diagnostics: {json.dumps(repair_batch, ensure_ascii=False)}\n\n"
                    f"Raw task brief: {research_brief}\n\n"
                    f"Return JSON only, following this concrete schema:\n"
                    f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
                ),
                max_tokens=DECOMPOSITION_LLM_MAX_TOKENS,
                required_list_key="sub_hypotheses",
                protocol_name="LLM_DECOMPOSITION_CANDIDATE_REPAIR",
                expected_schema_version="research_question_contract_batch_v3",
            )
        except Exception as exc:
            batch_diagnostics.append({
                "batch_number": batch_number,
                "candidate_ids": [
                    str(item.get("candidate_id") or "")
                    for item in repair_batch
                ],
                "status": "REPAIR_CALL_FAILED",
                "error_type": type(exc).__name__,
                "error_message": normalize_space(str(exc))[:1000],
            })
            continue
        payload = dict(response["payload"])
        batch_candidates = [
            _compile_question_kind_slots_v3(item)
            for item in payload["sub_hypotheses"]
            if isinstance(item, dict)
        ]
        repaired_candidates.extend(batch_candidates)
        batch_diagnostics.append({
            "batch_number": batch_number,
            "candidate_ids": [
                str(item.get("candidate_id") or "")
                for item in repair_batch
            ],
            "status": "COMPLETED",
            "returned_candidate_count": len(batch_candidates),
            **dict(response["diagnostics"]),
        })
    return {
        "schema_version": "research_question_candidate_protocol_repair_v3",
        "sub_hypotheses": repaired_candidates,
        "returned_candidate_count": len(repaired_candidates),
        "call_count": len(batch_diagnostics),
        "failed_batch_count": sum(
            item.get("status") == "REPAIR_CALL_FAILED"
            for item in batch_diagnostics
        ),
        "batch_diagnostics": batch_diagnostics,
    }


def audit_research_domain_contract_propagation(
    expected_contract: dict[str, Any] | None,
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(expected_contract, dict):
        return {
            "schema_version": "research_domain_contract_propagation_audit_v1",
            "status": "NOT_EVALUATED_NO_PROJECT_CONTRACT",
            "evaluated_sub_hypothesis_count": 0,
            "mismatched_sub_hypothesis_ids": [],
        }
    expected = validate_research_domain_contract(expected_contract)
    mismatched_ids: list[str] = []
    evaluated_count = 0
    for index, item in enumerate(sub_hypotheses, start=1):
        if not isinstance(item, dict):
            continue
        evaluated_count += 1
        sub_id = str(
            item.get("id") or item.get("sub_hypothesis_id") or f"SH{index}"
        )
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        try:
            actual = validate_research_domain_contract(
                contract.get("research_domain_contract")
            )
        except (TypeError, ValueError):
            mismatched_ids.append(sub_id)
            continue
        if actual != expected:
            mismatched_ids.append(sub_id)
    return {
        "schema_version": "research_domain_contract_propagation_audit_v1",
        "status": "PASS" if not mismatched_ids else "PROPAGATION_MISMATCH",
        "expected_status": expected["status"],
        "expected_primary_domain_id": expected["primary_domain_id"],
        "expected_active_domain_ids": list(expected["active_domain_ids"]),
        "evaluated_sub_hypothesis_count": evaluated_count,
        "mismatched_sub_hypothesis_ids": mismatched_ids,
    }


def rebind_project_research_domain_contracts_v3(
    project: dict[str, Any],
) -> dict[str, Any]:
    expected = build_project_research_domain_contract(project)
    if expected["status"] != "READY":
        audit = {
            "schema_version": "research_domain_contract_binding_audit_v1",
            "status": "DOMAIN_CONTRACT_REPAIR_REQUIRED",
            "project_domain_contract": expected,
            "rebound_sub_hypothesis_ids": [],
        }
        project["research_domain_contract_binding_audit"] = audit
        return audit

    rebound_ids: list[str] = []
    for index, item in enumerate(project.get("sub_hypotheses", []), start=1):
        if not isinstance(item, dict):
            continue
        sub_id = str(
            item.get("id") or item.get("sub_hypothesis_id") or f"SH{index}"
        )
        existing = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        try:
            current_domain = validate_research_domain_contract(
                existing.get("research_domain_contract")
            )
        except (TypeError, ValueError):
            current_domain = None
        if current_domain == expected:
            continue
        question = (
            dict(item.get("research_question"))
            if isinstance(item.get("research_question"), dict)
            else dict(existing.get("research_question") or {})
        )
        question["research_domain_contract"] = dict(expected)
        seed = {
            **copy.deepcopy(item),
            "research_question": question,
            "research_question_contract": copy.deepcopy(existing),
        }
        rebound = build_research_question_contract(
            project,
            seed,
            epistemic_profile=(
                item.get("epistemic_profile")
                if isinstance(item.get("epistemic_profile"), dict)
                else {}
            ),
        )
        item["research_question"] = dict(rebound.get("research_question") or {})
        item["scientific_scope"] = dict(rebound.get("scientific_scope") or {})
        item["claim_target"] = dict(rebound.get("claim_target") or {})
        item["evidence_contract"] = dict(rebound.get("evidence_contract") or {})
        item["routing_contract"] = dict(rebound.get("routing_contract") or {})
        item["research_question_contract"] = rebound
        item["research_question_retrieval_plan"] = build_question_retrieval_plan(
            rebound
        )
        rebound_ids.append(sub_id)

    propagation = audit_research_domain_contract_propagation(
        expected,
        [
            item
            for item in project.get("sub_hypotheses", [])
            if isinstance(item, dict)
        ],
    )
    if propagation["status"] != "PASS":
        raise RuntimeError(
            "Research-domain contract rebinding failed for "
            + ", ".join(propagation["mismatched_sub_hypothesis_ids"])
        )
    audit = {
        "schema_version": "research_domain_contract_binding_audit_v1",
        "status": "REBOUND" if rebound_ids else "READY_NO_CHANGES",
        "project_domain_contract": expected,
        "rebound_sub_hypothesis_ids": rebound_ids,
        "propagation_audit": propagation,
    }
    project["research_domain_contract_binding_audit"] = audit
    return audit


def build_objective_decomposition(
    objective: str,
    domain: str = "",
    research_brief: str = "",
    max_subhypotheses: int = 6,
    use_llm: bool = True,
    coherence_recovery_context: dict[str, Any] | None = None,
    research_domain_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_objective = normalize_space(objective)
    clean_domain = normalize_space(domain)
    raw_research_brief = str(research_brief or objective)
    if not clean_objective:
        raise ValueError("A non-empty research objective is required before decomposition.")
    final_limit = max(
        DECOMPOSITION_MIN_SUBHYPOTHESES,
        min(
            int(max_subhypotheses or DECOMPOSITION_MAX_SUBHYPOTHESES),
            DECOMPOSITION_MAX_SUBHYPOTHESES,
        ),
    )
    candidate_pool_target = final_limit
    academic_reframing = academic_reframing_for_objective(
        objective=clean_objective,
        domain=clean_domain,
        research_brief=raw_research_brief,
        use_llm=use_llm,
    )
    effective_objective = (
        normalize_space(str(academic_reframing.get("academic_objective") or ""))
        if academic_reframing.get("applied")
        else clean_objective
    ) or clean_objective
    raw: dict[str, Any] = {}
    design_inventory: dict[str, Any] = {}
    extractor = "heuristic"
    llm_error = ""
    llm_protocol_status = ""
    llm_response_diagnostics: dict[str, Any] = {}
    if use_llm:
        try:
            from ._llm import LLMJSONProtocolError
        except ImportError:
            from _llm import LLMJSONProtocolError
        try:
            design_inventory = extract_research_design_inventory_v3_with_llm(
                objective=effective_objective,
                domain=clean_domain,
                research_brief=raw_research_brief,
                academic_reframing=academic_reframing,
            )
            raw = decompose_research_questions_v3_with_llm(
                objective=effective_objective,
                domain=clean_domain,
                research_brief=raw_research_brief,
                max_subhypotheses=final_limit,
                academic_reframing=academic_reframing,
                design_inventory=design_inventory,
                coherence_recovery_context=coherence_recovery_context,
            )
            extractor = "llm_v3_manifest_then_typed_contract_batches"
            llm_response_diagnostics = dict(raw.get("generation_diagnostics") or {})
        except LLMJSONProtocolError as exc:
            llm_protocol_status = exc.code
            llm_error = str(exc)
            llm_response_diagnostics = dict(exc.diagnostics or {})
            extractor = "llm_v3_decomposition_protocol_failed"
            terminal_diagnostics = _latest_decomposition_diagnostics_v3(
                llm_response_diagnostics
            )
            log_event(
                "WARN",
                "v3_objective_decomposition_protocol_failed",
                status=llm_protocol_status,
                attempt_count=int(terminal_diagnostics.get("attempt_count") or 0),
                response_chars=int(terminal_diagnostics.get("response_chars") or 0),
                finish_reason=str(terminal_diagnostics.get("finish_reason") or ""),
                top_level_keys=list(terminal_diagnostics.get("top_level_keys") or []),
                response_truncated=bool(terminal_diagnostics.get("response_truncated")),
                accepted_manifest_count=int(
                    terminal_diagnostics.get("accepted_manifest_count") or 0
                ),
                validation_error_code_counts=dict(
                    terminal_diagnostics.get("validation_error_code_counts") or {}
                ),
            )
        except Exception as exc:
            llm_error = str(exc)
            llm_protocol_status = (
                "LLM_DECOMPOSITION_TIMEOUT"
                if "timeout" in llm_error.casefold()
                else "LLM_DECOMPOSITION_INVOCATION_FAILED"
            )
            extractor = "llm_v3_decomposition_invocation_failed"
            log_event(
                "WARN",
                "v3_objective_decomposition_llm_failed",
                status=llm_protocol_status,
                error=llm_error[:240],
            )

    declared_design_basis_ids = {
        str(item.get("id") or "").strip()
        for item in (design_inventory.get("design_basis") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    raw_sub_hypotheses = (
        raw.get("sub_hypotheses")
        if isinstance(raw, dict) and isinstance(raw.get("sub_hypotheses"), list)
        else []
    )
    raw_llm_candidates = copy.deepcopy(raw_sub_hypotheses)
    repair_llm_candidates: list[dict[str, Any]] = []
    candidate_validation_records: list[dict[str, Any]] = []
    source_grounded_sub_hypotheses: list[dict[str, Any]] = []
    raw_candidate_lookup: dict[str, tuple[int, dict[str, Any]]] = {}
    seen_raw_candidate_ids: set[str] = set()
    for raw_index, item in enumerate(raw_sub_hypotheses):
        candidate_id = _candidate_protocol_identity(item, raw_index)
        if not isinstance(item, dict):
            candidate_validation_records.append({
                "candidate_id": candidate_id,
                "stage": "initial",
                "status": "REJECTED",
                "raw_candidate_index": raw_index,
                "validation_error_code": "CANDIDATE_NOT_OBJECT",
                "validation_error_message": "Research-question candidate must be a JSON object",
            })
            continue
        if candidate_id in seen_raw_candidate_ids:
            candidate_validation_records.append({
                "candidate_id": candidate_id,
                "stage": "initial",
                "status": "REJECTED",
                "raw_candidate_index": raw_index,
                "validation_error_code": "DUPLICATE_RAW_CANDIDATE_ID",
                "validation_error_message": (
                    "Each raw LLM candidate must declare a unique candidate_id"
                ),
            })
            continue
        seen_raw_candidate_ids.add(candidate_id)
        raw_candidate_lookup[candidate_id] = (raw_index, item)
        question = item.get("research_question")
        if not isinstance(question, dict):
            candidate_validation_records.append({
                "candidate_id": candidate_id,
                "stage": "initial",
                "status": "REJECTED",
                "raw_candidate_index": raw_index,
                "validation_error_code": "RESEARCH_QUESTION_DECLARATION_REQUIRED",
                "validation_error_message": "Candidate must declare a research_question object",
            })
            continue
        raw_basis_ids = question.get("design_basis_ids")
        if isinstance(raw_basis_ids, str):
            raw_basis_ids = [raw_basis_ids]
        referenced_basis_ids = {
            str(value).strip()
            for value in raw_basis_ids or []
            if str(value).strip()
        }
        if not referenced_basis_ids:
            candidate_validation_records.append({
                "candidate_id": candidate_id,
                "stage": "initial",
                "status": "REJECTED",
                "raw_candidate_index": raw_index,
                "validation_error_code": "DESIGN_BASIS_REFERENCE_REQUIRED",
                "validation_error_message": "Candidate must cite at least one design_basis_id",
            })
            continue
        unknown_basis_ids = sorted(referenced_basis_ids - declared_design_basis_ids)
        if unknown_basis_ids:
            candidate_validation_records.append({
                "candidate_id": candidate_id,
                "stage": "initial",
                "status": "REJECTED",
                "raw_candidate_index": raw_index,
                "validation_error_code": "UNKNOWN_DESIGN_BASIS_REFERENCE",
                "validation_error_message": (
                    "Candidate references undeclared design_basis_ids: "
                    + ", ".join(unknown_basis_ids)
                ),
            })
            continue
        source_grounded_sub_hypotheses.append(item)
    rejected_design_basis_reference_count = len([
        item
        for item in candidate_validation_records
        if item.get("validation_error_code")
        in {"DESIGN_BASIS_REFERENCE_REQUIRED", "UNKNOWN_DESIGN_BASIS_REFERENCE"}
    ])

    direction_axes = normalize_direction_axes(
        raw.get("direction_axes") if isinstance(raw, dict) else [],
        reframing_axes=academic_reframing.get("reframing_axes"),
    )
    initial_contract_audit: list[dict[str, Any]] = []
    candidate_pool = normalize_sub_hypotheses(
        source_grounded_sub_hypotheses,
        objective=effective_objective,
        domain=clean_domain,
        max_subhypotheses=candidate_pool_target,
        require_research_question_contract=True,
        research_domain_contract=research_domain_contract,
        validation_audit=initial_contract_audit,
        validation_stage="initial",
    )
    for record in initial_contract_audit:
        candidate_id = str(record.get("candidate_id") or "")
        raw_index, _ = raw_candidate_lookup.get(candidate_id, (-1, {}))
        record["raw_candidate_index"] = raw_index
    candidate_validation_records.extend(initial_contract_audit)

    rejected_for_repair: list[dict[str, Any]] = []
    for record in candidate_validation_records:
        if record.get("status") != "REJECTED":
            continue
        candidate_id = str(record.get("candidate_id") or "")
        _, raw_candidate = raw_candidate_lookup.get(candidate_id, (-1, {}))
        rejected_for_repair.append({
            **copy.deepcopy(record),
            "raw_candidate": copy.deepcopy(raw_candidate),
        })

    candidate_repair_audit: dict[str, Any] = {
        "schema_version": "research_question_candidate_protocol_repair_audit_v3",
        "attempted": False,
        "call_count": 0,
        "failed_batch_count": 0,
        "batch_diagnostics": [],
        "input_rejected_candidate_count": len(rejected_for_repair),
        "returned_candidate_count": 0,
        "accepted_repair_count": 0,
        "status": "NOT_REQUIRED",
        "error_code": "",
        "error_message": "",
    }
    if llm_protocol_status:
        candidate_repair_audit.update({
            "status": "NOT_APPLICABLE_GENERATION_PROTOCOL_FAILED",
            "error_code": llm_protocol_status,
            "error_message": llm_error[:500],
        })
    if (
        use_llm
        and rejected_for_repair
        and len(candidate_pool) < candidate_pool_target
    ):
        candidate_repair_audit["attempted"] = True
        try:
            repair_result = repair_research_question_candidates_v3_with_llm(
                objective=effective_objective,
                domain=clean_domain,
                research_brief=raw_research_brief,
                academic_reframing=academic_reframing,
                design_inventory=design_inventory,
                rejected_candidates=rejected_for_repair,
                max_subhypotheses=candidate_pool_target - len(candidate_pool),
            )
        except Exception as exc:
            candidate_repair_audit.update({
                "status": "REPAIR_CALL_FAILED",
                "error_code": "LLM_CANDIDATE_REPAIR_FAILED",
                "error_message": normalize_space(str(exc))[:1000],
            })
            log_event(
                "WARN",
                "objective_decomposition_candidate_repair_failed",
                error_type=type(exc).__name__,
                error=normalize_space(str(exc))[:240],
            )
        else:
            candidate_repair_audit["call_count"] = int(
                repair_result.get("call_count") or 0
            )
            candidate_repair_audit["failed_batch_count"] = int(
                repair_result.get("failed_batch_count") or 0
            )
            candidate_repair_audit["batch_diagnostics"] = copy.deepcopy(
                repair_result.get("batch_diagnostics") or []
            )
            repair_llm_candidates = [
                copy.deepcopy(item)
                for item in (repair_result.get("sub_hypotheses") or [])
                if isinstance(item, dict)
            ]
            candidate_repair_audit["returned_candidate_count"] = len(
                repair_llm_candidates
            )
            rejected_candidate_ids = {
                str(item.get("candidate_id") or "")
                for item in rejected_for_repair
                if str(item.get("candidate_id") or "")
            }
            repair_source_grounded: list[dict[str, Any]] = []
            repair_candidate_lookup: dict[str, tuple[int, dict[str, Any]]] = {}
            seen_repair_candidate_ids: set[str] = set()
            for repair_index, item in enumerate(repair_llm_candidates):
                candidate_id = _candidate_protocol_identity(item, repair_index)
                if candidate_id in seen_repair_candidate_ids:
                    candidate_validation_records.append({
                        "candidate_id": candidate_id,
                        "stage": "repair",
                        "status": "REJECTED",
                        "raw_candidate_index": repair_index,
                        "validation_error_code": "DUPLICATE_REPAIR_CANDIDATE_ID",
                        "validation_error_message": (
                            "The one-shot repair response must contain at most one repair "
                            "for each rejected candidate_id"
                        ),
                    })
                    continue
                seen_repair_candidate_ids.add(candidate_id)
                repair_candidate_lookup[candidate_id] = (repair_index, item)
                repair_of = normalize_space(
                    str(item.get("repair_of_candidate_id") or "")
                )
                if (
                    candidate_id not in rejected_candidate_ids
                    or repair_of != candidate_id
                ):
                    candidate_validation_records.append({
                        "candidate_id": candidate_id,
                        "stage": "repair",
                        "status": "REJECTED",
                        "raw_candidate_index": repair_index,
                        "validation_error_code": "REPAIR_ORIGIN_MISMATCH",
                        "validation_error_message": (
                            "Repair must preserve candidate_id and set repair_of_candidate_id "
                            "to the rejected candidate identity"
                        ),
                    })
                    continue
                question = (
                    item.get("research_question")
                    if isinstance(item.get("research_question"), dict)
                    else {}
                )
                raw_basis_ids = question.get("design_basis_ids")
                if isinstance(raw_basis_ids, str):
                    raw_basis_ids = [raw_basis_ids]
                referenced_basis_ids = {
                    str(value).strip()
                    for value in raw_basis_ids or []
                    if str(value).strip()
                }
                unknown_basis_ids = sorted(
                    referenced_basis_ids - declared_design_basis_ids
                )
                if not referenced_basis_ids or unknown_basis_ids:
                    candidate_validation_records.append({
                        "candidate_id": candidate_id,
                        "stage": "repair",
                        "status": "REJECTED",
                        "raw_candidate_index": repair_index,
                        "validation_error_code": (
                            "UNKNOWN_DESIGN_BASIS_REFERENCE"
                            if unknown_basis_ids
                            else "DESIGN_BASIS_REFERENCE_REQUIRED"
                        ),
                        "validation_error_message": (
                            "Repair references undeclared design_basis_ids: "
                            + ", ".join(unknown_basis_ids)
                            if unknown_basis_ids
                            else "Repair must cite at least one design_basis_id"
                        ),
                    })
                    continue
                repair_source_grounded.append(item)
            repair_contract_audit: list[dict[str, Any]] = []
            repaired_candidates = normalize_sub_hypotheses(
                repair_source_grounded,
                objective=effective_objective,
                domain=clean_domain,
                max_subhypotheses=candidate_pool_target - len(candidate_pool),
                require_research_question_contract=True,
                research_domain_contract=research_domain_contract,
                validation_audit=repair_contract_audit,
                validation_stage="repair",
                sub_hypothesis_id_offset=len(candidate_pool),
            )
            for record in repair_contract_audit:
                candidate_id = str(record.get("candidate_id") or "")
                repair_index, _ = repair_candidate_lookup.get(
                    candidate_id, (-1, {})
                )
                record["raw_candidate_index"] = repair_index
            candidate_validation_records.extend(repair_contract_audit)
            accepted_candidate_ids = {
                str(item.get("candidate_id") or "")
                for item in candidate_pool
                if str(item.get("candidate_id") or "")
            }
            accepted_repairs: list[dict[str, Any]] = []
            for repaired in repaired_candidates:
                candidate_id = str(repaired.get("candidate_id") or "")
                if candidate_id in accepted_candidate_ids:
                    candidate_validation_records.append({
                        "candidate_id": candidate_id,
                        "stage": "repair",
                        "status": "REJECTED",
                        "validation_error_code": "DUPLICATE_ACCEPTED_CANDIDATE_ID",
                        "validation_error_message": (
                            "Repair candidate_id duplicates an already accepted candidate"
                        ),
                    })
                    continue
                accepted_candidate_ids.add(candidate_id)
                accepted_repairs.append(repaired)
            candidate_pool.extend(accepted_repairs)
            candidate_repair_audit["accepted_repair_count"] = len(
                accepted_repairs
            )
            failed_batch_count = int(
                candidate_repair_audit.get("failed_batch_count") or 0
            )
            repair_call_count = int(
                candidate_repair_audit.get("call_count") or 0
            )
            candidate_repair_audit["status"] = (
                "REPAIR_PARTIALLY_ACCEPTED"
                if accepted_repairs and failed_batch_count
                else "REPAIR_ACCEPTED"
                if accepted_repairs
                else "REPAIR_CALL_FAILED"
                if repair_call_count and failed_batch_count == repair_call_count
                else "REPAIR_EXHAUSTED"
            )
            if candidate_repair_audit["status"] == "REPAIR_CALL_FAILED":
                candidate_repair_audit["error_code"] = "LLM_CANDIDATE_REPAIR_FAILED"
                candidate_repair_audit["error_message"] = "; ".join(
                    str(item.get("error_message") or "")
                    for item in candidate_repair_audit["batch_diagnostics"]
                    if item.get("status") == "REPAIR_CALL_FAILED"
                )[:1000]
    batched_llm_attempted = (
        isinstance(raw, dict)
        and raw.get("schema_version") == "research_question_objective_decomposition_v3"
    )
    batched_llm_applied = batched_llm_attempted and bool(candidate_pool)
    if not candidate_pool:
        extractor = (
            extractor
            if llm_protocol_status
            else "llm_v3_candidate_protocol_repair_exhausted"
            if use_llm and candidate_repair_audit.get("status") == "REPAIR_EXHAUSTED"
            else "llm_v3_candidate_protocol_repair_required"
            if use_llm and rejected_for_repair
            else "research_question_contract_v3_required"
        )
        batched_llm_applied = False

    _assign_decomposition_candidate_ids(candidate_pool)
    candidate_preflight = annotate_subhypotheses_scientific_operationality(
        candidate_pool
    )
    coverage_matrix = build_candidate_direction_coverage_matrix(
        candidate_pool,
        direction_axes,
    )
    # The accepted candidate pool is already the final value-ranked set.  In
    # iterative mode it was assembled from small LLM batches; in legacy mode it
    # was returned as one direct set. Keep the local coverage matrix as an audit,
    # but do not run a second "candidate auction" that asks the model to
    # over-generate alternatives.
    sub_hypotheses = [
        copy.deepcopy(item)
        for item in candidate_pool[:final_limit]
        if isinstance(item, dict)
    ]
    domain_contract_propagation = audit_research_domain_contract_propagation(
        research_domain_contract,
        sub_hypotheses,
    )
    if domain_contract_propagation["status"] == "PROPAGATION_MISMATCH":
        raise RuntimeError(
            "Research-domain contract propagation failed for "
            + ", ".join(domain_contract_propagation["mismatched_sub_hypothesis_ids"])
        )
    selection_audit = {
        "schema_version": "research_question_contract_selection_v3",
        "algorithm": "llm_research_question_contract_validation_and_source_direction_coverage",
        "candidate_count": len(candidate_pool),
        "selected_count": len(sub_hypotheses),
        "selected_candidate_ids": [
            str(item.get("candidate_id") or item.get("id") or "")
            for item in sub_hypotheses
        ],
        "final_limit": final_limit,
        "selection_is_post_llm_competition": False,
        "selection_order": "llm_research_question_contract_order",
    }
    initial_set_acceptance = audit_selected_direction_coverage(
        sub_hypotheses,
        direction_axes,
        coverage_matrix,
        expected_count=max(
            0,
            len(sub_hypotheses),
        ),
    )
    missing_direction_generation: dict[str, Any] = {
        "schema_version": "missing_direction_generation_v3",
        "applied": False,
        "disabled": True,
        "reason": (
            "bounded_llm_batch_final_set_with_local_coverage_audit"
            if batched_llm_applied
            else "single_pass_llm_final_set_with_local_coverage_audit"
        ),
        "requested_axis_ids": list(
            initial_set_acceptance.get("repair_axis_ids") or []
        ),
        "generated_candidate_count": 0,
        "returned_candidate_count": 0,
        "error": "",
    }
    _renumber_selected_subhypotheses(sub_hypotheses)
    # The decomposition set is owned exclusively by the LLM (or the explicit
    # non-LLM fallback selected by the caller).  Never synthesize extra SHs
    # from heuristic academic-reframing candidates merely to satisfy retrieval
    # breadth: they pollute the SH pool and make later evidence gaps misleading.
    minimum_topup_audit = {
        "schema_version": "minimum_retrieval_decomposition_policy_v3",
        "applied": False,
        "disabled": True,
        "minimum_required": 0,
        "original_count": len(sub_hypotheses),
        "final_count": len(sub_hypotheses),
        "added": 0,
        "reason": "minimum_subhypothesis_count_disabled_llm_set_preserved",
    }
    _renumber_selected_subhypotheses(sub_hypotheses)
    shared_knowledge_registry = apply_v3_subhypothesis_relationships(
        sub_hypotheses
    )
    # The V3 SH does not own a legacy causal dependent-variable gate.
    # contract.  Its declared scope and evidence slots are assessed below;
    # deliberately do not pass it through the retired causal repair stages.
    dependent_variable_scope_audit = {
        "schema_version": "research_question_scope_preflight_v3",
        "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
        "total": len(sub_hypotheses),
    }
    object_contract_summary = {
        "schema_version": "research_question_scope_preflight_v3",
        "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
        "total": len(sub_hypotheses),
    }
    object_maturity_summary = {
        "schema_version": "research_question_scope_preflight_v3",
        "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
        "total": len(sub_hypotheses),
    }
    preflight_summary = annotate_subhypotheses_scientific_operationality(sub_hypotheses)
    coverage_matrix = build_candidate_direction_coverage_matrix(
        sub_hypotheses,
        direction_axes,
    )
    final_set_acceptance = audit_selected_direction_coverage(
        sub_hypotheses,
        direction_axes,
        coverage_matrix,
        expected_count=max(
            0,
            len(sub_hypotheses),
        ),
    )
    if not sub_hypotheses:
        decomposition_status = (
            llm_protocol_status
            or (
                "DECOMPOSITION_CANDIDATE_REPAIR_EXHAUSTED"
                if candidate_repair_audit.get("status")
                in {"REPAIR_EXHAUSTED", "REPAIR_CALL_FAILED"}
                else "DECOMPOSITION_CANDIDATE_REPAIR_REQUIRED"
                if rejected_for_repair
                else "LLM_DECOMPOSITION_DISABLED"
                if not use_llm
                else "LLM_DECOMPOSITION_ROOT_PROTOCOL_INVALID"
            )
        )
    elif preflight_summary["total"] and preflight_summary["blocked"] == preflight_summary["total"]:
        decomposition_status = "needs_scientific_model_revision"
    elif (
        preflight_summary["blocked"]
        or (
            direction_axes
            and final_set_acceptance.get("status") != "accepted"
        )
    ):
        decomposition_status = "partially_ready_for_subhypothesis_retrieval"
    else:
        decomposition_status = "ready_for_subhypothesis_retrieval"
    validation_error_counts: dict[str, int] = {}
    for record in candidate_validation_records:
        if record.get("status") != "REJECTED":
            continue
        error_code = str(
            record.get("validation_error_code")
            or "RESEARCH_QUESTION_CONTRACT_VALIDATION_FAILED"
        )
        validation_error_counts[error_code] = (
            validation_error_counts.get(error_code, 0) + 1
        )
    candidate_validation_audit = {
        "schema_version": "research_question_candidate_validation_audit_v3",
        "status": (
            "PASS"
            if candidate_pool and not validation_error_counts
            else "PARTIAL"
            if candidate_pool
            else decomposition_status
        ),
        "initial_raw_candidate_count": len(raw_llm_candidates),
        "repair_raw_candidate_count": len(repair_llm_candidates),
        "accepted_candidate_count": len(candidate_pool),
        "rejected_validation_record_count": sum(
            validation_error_counts.values()
        ),
        "validation_error_code_counts": validation_error_counts,
        "records": candidate_validation_records,
    }
    llm_iteration_audit = (
        dict(raw.get("iteration_audit") or {})
        if batched_llm_attempted and isinstance(raw, dict)
        else {}
    )
    llm_iteration_audit.update({
        "raw_llm_candidate_count": len(raw_llm_candidates),
        "protocol_repair_call_count": int(
            candidate_repair_audit.get("call_count") or 0
        ),
        "repair_returned_candidate_count": len(repair_llm_candidates),
        "accepted_subhypothesis_count": len(candidate_pool),
        "rejected_candidate_count": sum(validation_error_counts.values()),
        "candidate_validation_status": candidate_validation_audit["status"],
    })
    decomposition = {
        "objective": clean_objective,
        "decomposition_objective": effective_objective,
        "domain": clean_domain,
        "research_brief": raw_research_brief,
        "research_brief_source": "verbatim_project_brief" if research_brief else "objective_fallback",
        "academic_reframing": academic_reframing,
        "research_design_inventory": design_inventory,
        "mixed_parent_objective_preflight": (
            academic_reframing.get("mixed_parent_objective_preflight")
            if isinstance(academic_reframing, dict)
            else {}
        ),
        "status": decomposition_status,
        "extractor": extractor,
        "sub_hypotheses": sub_hypotheses,
        "shared_knowledge_registry": shared_knowledge_registry,
        "direction_axes": direction_axes,
        "candidate_pool": candidate_pool,
        "raw_llm_candidates": raw_llm_candidates,
        "repair_llm_candidates": repair_llm_candidates,
        "llm_response_diagnostics": llm_response_diagnostics,
        "candidate_validation_audit": candidate_validation_audit,
        "candidate_repair_audit": candidate_repair_audit,
        "candidate_pool_policy": {
            "schema_version": (
                "research_question_contract_decomposition_policy_v3"
            ),
            "requested_candidate_count": candidate_pool_target,
            "actual_candidate_count": len(candidate_pool),
            "raw_llm_candidate_count": len(raw_sub_hypotheses),
            "raw_repair_candidate_count": len(repair_llm_candidates),
            "rejected_design_basis_reference_count": rejected_design_basis_reference_count,
            "design_inventory_basis_count": len(declared_design_basis_ids),
            "final_limit": final_limit,
            "generation_range": [
                DECOMPOSITION_MIN_SUBHYPOTHESES,
                final_limit,
            ],
            "post_generation_competition": False,
            "llm_selection_policy": "direct_up_to_6_research_question_contracts_validate_without_legacy_causal_fallback",
            "entity_breadth_gate_enabled": bool(DECOMPOSITION_ENTITY_BREADTH_GATE_ENABLED),
            "bounded_llm_generation_attempted": bool(batched_llm_attempted),
            "bounded_llm_generation_applied": bool(batched_llm_applied),
            "contract_batch_size": (
                DECOMPOSITION_LLM_BATCH_SIZE if batched_llm_applied else 0
            ),
        },
        "llm_iteration_audit": llm_iteration_audit,
        "candidate_scientific_operationality_preflight": candidate_preflight,
        "coverage_matrix": coverage_matrix,
        "set_selection": selection_audit,
        "initial_set_acceptance": initial_set_acceptance,
        "missing_direction_generation": missing_direction_generation,
        "final_set_acceptance": final_set_acceptance,
        "scientific_object_contract_preflight": object_contract_summary,
        "scientific_operationality_preflight": preflight_summary,
        "research_domain_contract_propagation": domain_contract_propagation,
        "object_maturity_preflight": object_maturity_summary,
        "dependent_variable_scope_audit": dependent_variable_scope_audit,
        "minimum_retrieval_decomposition_policy": minimum_topup_audit,
        "combination_hypothesis": normalize_combination_hypothesis(raw.get("combination_hypothesis") if isinstance(raw, dict) else {}, sub_hypotheses),
        "execution_constraints": normalize_execution_constraints(raw.get("execution_constraints") if isinstance(raw, dict) else {}),
        "decomposition_rules": [
            "Each SH must be an explicit ResearchQuestionContractV3 selected through the question_kind discriminator with typed scope and evidence slots.",
            "Question-kind and research-role variant fields are merged only from the selected discriminated schema path.",
            (
                "The decomposition preserves the returned typed question set (up to six). It never maps legacy causal artefacts into the V3 contract or tops up with heuristic SHs."
            ),
            "The local direction matrix audits coverage after generation; it does not launch a second LLM candidate-auction or missing-direction pass.",
            "When a claim combines mechanism discovery with causal validation, retain separate discovery and validation evidence paths; no single paper is required to carry both responsibilities.",
            "A combined conclusion is admissible only after the relevant component hypotheses are independently evaluated.",
            "Missing quantitative bounds remain explicitly unresolved; they must not be fabricated from the objective.",
        ],
        "createdAt": time.time(),
    }
    if llm_error:
        decomposition["llm_error"] = llm_error
    return decomposition


def objective_decomposition_persistence_projection(
    decomposition: dict[str, Any],
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist decomposition provenance without duplicating V3 contracts.

    The full decomposition remains the immediate tool response.  Once saved,
    each selected ResearchQuestionContractV3 is authoritative only in its
    immutable per-SH artifact. Raw LLM candidates and validator diagnostics are
    retained here only as decomposition protocol evidence; they are never read
    as accepted contracts or retrieval authority.
    """
    source = decomposition if isinstance(decomposition, dict) else {}
    selected = [item for item in sub_hypotheses if isinstance(item, dict)]
    sub_hypothesis_refs: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        sub_hypothesis_refs.append(
            {
                "sub_hypothesis_id": str(
                    item.get("id") or item.get("sub_hypothesis_id") or f"SH{index}"
                ),
                "candidate_id": str(item.get("candidate_id") or ""),
                "focus": _subhypothesis_log_text(
                    item.get("focus")
                    or (contract.get("research_question") or {}).get("question_text"),
                    limit=260,
                ),
                "research_question_contract_id": str(contract.get("contract_id") or ""),
                "contract_revision": str(
                    contract.get("contract_revision")
                    or contract.get("declaration_hash")
                    or ""
                ),
                "contract_hash": str(contract.get("declaration_hash") or ""),
            }
        )
    retained_fields = (
        "schema_version",
        "objective",
        "decomposition_objective",
        "domain",
        "research_brief",
        "research_brief_source",
        "academic_reframing",
        "research_design_inventory",
        "mixed_parent_objective_preflight",
        "status",
        "extractor",
        "direction_axes",
        "candidate_pool_policy",
        "llm_iteration_audit",
        "llm_response_diagnostics",
        "raw_llm_candidates",
        "repair_llm_candidates",
        "candidate_validation_audit",
        "candidate_repair_audit",
        "candidate_scientific_operationality_preflight",
        "coverage_matrix",
        "set_selection",
        "initial_set_acceptance",
        "missing_direction_generation",
        "final_set_acceptance",
        "scientific_object_contract_preflight",
        "scientific_operationality_preflight",
        "object_maturity_preflight",
        "dependent_variable_scope_audit",
        "minimum_retrieval_decomposition_policy",
        "combination_hypothesis",
        "execution_constraints",
        "decomposition_rules",
        "createdAt",
        "llm_error",
    )
    projection = {
        key: copy.deepcopy(source[key])
        for key in retained_fields
        if key in source
    }
    projection["persistence_schema_version"] = "objective_decomposition_summary_v3"
    projection["sub_hypothesis_count"] = len(sub_hypothesis_refs)
    projection["sub_hypothesis_refs"] = sub_hypothesis_refs
    projection["contract_authority"] = (
        "immutable_v3_subhypothesis_contract_artifacts_only"
    )
    projection["candidate_pool_storage"] = (
        "raw_candidates_and_validation_audit_persisted"
    )
    return projection


def _merge_decomposition_direction_axes(
    existing: list[dict[str, Any]],
    incoming: Any,
) -> list[dict[str, Any]]:
    output = [copy.deepcopy(axis) for axis in existing if isinstance(axis, dict)]
    seen: set[str] = set()
    for axis in output:
        key = normalize_space(
            str(axis.get("id") or axis.get("label") or axis.get("description") or "")
        ).lower()
        if key:
            seen.add(key)
    for axis in incoming if isinstance(incoming, list) else []:
        if not isinstance(axis, dict):
            continue
        key = normalize_space(
            str(axis.get("id") or axis.get("label") or axis.get("description") or "")
        ).lower()
        if key and key in seen:
            continue
        copied = copy.deepcopy(axis)
        output.append(copied)
        if key:
            seen.add(key)
    return output


def _token_jaccard(left: Any, right: Any) -> float:
    left_tokens = set(_minimum_topup_key(left).split())
    right_tokens = set(_minimum_topup_key(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _subhypothesis_focus_anchor_text(item: dict[str, Any]) -> str:
    data = item if isinstance(item, dict) else {}
    value = data.get("focus_anchor")
    if isinstance(value, dict):
        return normalize_space(
            str(
                value.get("anchor")
                or value.get("focus")
                or value.get("scientific_object")
                or ""
            )
        )
    return normalize_space(str(value or ""))


def _duplicate_summary_text(value: Any, limit: int = 220) -> str:
    text = normalize_space(str(value or ""))
    return text[:limit]


def _subhypothesis_claim_contract_summary(item: dict[str, Any]) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    causal_contract = (
        data.get("causal_contract")
        if isinstance(data.get("causal_contract"), dict)
        else {}
    )
    epistemic_profile = (
        data.get("epistemic_profile")
        if isinstance(data.get("epistemic_profile"), dict)
        else {}
    )
    direction_axis_ids = [
        str(coverage.get("axis_id") or "")
        for coverage in (data.get("direction_coverage") or [])
        if isinstance(coverage, dict)
        and str(coverage.get("axis_id") or "").strip()
        and str(coverage.get("coverage_strength") or "").strip().lower()
        in {"full", "partial"}
    ][:8]
    dependent_variables = normalize_text_list(data.get("dependent_variables"))[:4]
    moderators = normalize_text_list(
        data.get("moderators") or data.get("boundary_conditions")
    )[:4]
    causal_steps = normalize_text_list(data.get("causal_chain"))[:4]
    comparison = (
        data.get("comparison")
        or data.get("baseline_or_comparator")
        or data.get("comparator")
        or data.get("baseline")
        or ""
    )
    return {
        "id": str(data.get("id") or data.get("candidate_id") or ""),
        "scientific_object": _duplicate_summary_text(data.get("scientific_object")),
        "focus_anchor": _duplicate_summary_text(_subhypothesis_focus_anchor_text(data)),
        "input_axis": _duplicate_summary_text(data.get("independent_variable")),
        "mechanism_axis": _duplicate_summary_text(
            causal_contract.get("pivotal_mechanism")
            or causal_contract.get("mechanism")
            or " | ".join(causal_steps[:2])
        ),
        "outcome_axis": _duplicate_summary_text(
            causal_contract.get("outcome") or " | ".join(dependent_variables)
        ),
        "comparison_axis": _duplicate_summary_text(comparison),
        "boundary_or_context_axis": _duplicate_summary_text(" | ".join(moderators)),
        "evidence_standard": _duplicate_summary_text(
            data.get("evidence_standard_hint")
            or epistemic_profile.get("evidence_standard_id")
            or " | ".join(
                normalize_text_list(epistemic_profile.get("evidence_standard_ids"))
            )
        ),
        "retrieval_query": _duplicate_summary_text(data.get("retrieval_query"), 260),
        "source_axis_ids": direction_axis_ids,
    }


def _subhypothesis_axis_vector(
    *,
    item: dict[str, Any],
    scientific_object: str,
    independent_variable: str,
    causal_contract: dict[str, Any],
    causal_chain: list[str],
    dependent_variables: list[str],
    comparison: str,
    moderators: list[str],
    epistemic_profile: dict[str, Any],
) -> dict[str, Any]:
    declared = item.get("axis_vector") if isinstance(item.get("axis_vector"), dict) else {}
    mechanism = (
        causal_contract.get("pivotal_mechanism")
        or causal_contract.get("mechanism")
        or declared.get("mechanism_axis")
        or " | ".join(causal_chain[:2])
    )
    outcome = (
        causal_contract.get("outcome")
        or declared.get("outcome_axis")
        or " | ".join(dependent_variables[:4])
    )
    boundary = (
        " | ".join(moderators[:4])
        or str(declared.get("boundary_or_context_axis") or "")
    )
    evidence_standard = (
        str(
            epistemic_profile.get("evidence_standard_id")
            or item.get("evidence_standard_hint")
            or ""
        )
        or " | ".join(normalize_text_list(epistemic_profile.get("evidence_standard_ids")))
        or str(declared.get("evidence_standard") or "")
    )
    return {
        "scientific_object": scientific_object,
        "input_axis": independent_variable,
        "mechanism_axis": normalize_space(str(mechanism or "")),
        "outcome_axis": normalize_space(str(outcome or "")),
        "comparison_axis": comparison,
        "boundary_or_context_axis": normalize_space(str(boundary or "")),
        "evidence_standard": normalize_space(str(evidence_standard or "")),
    }


def _duplicate_key_fields(
    source_map: dict[str, list[str]],
    duplicate_key: str,
) -> list[str]:
    return [
        field
        for field, values in source_map.items()
        if duplicate_key in values
    ]


def _duplicate_overlap_is_input_axis_only(
    overlap_fields: list[dict[str, Any]],
) -> bool:
    if not overlap_fields:
        return False
    for item in overlap_fields:
        candidate_fields = {
            str(value or "")
            for value in item.get("candidate_fields", [])
        }
        accepted_fields = {
            str(value or "")
            for value in item.get("accepted_fields", [])
        }
        if candidate_fields != {"independent_variable"}:
            return False
        if accepted_fields != {"independent_variable"}:
            return False
    return True


def subhypothesis_duplicate_key_sources(item: dict[str, Any]) -> dict[str, list[str]]:
    data = item if isinstance(item, dict) else {}
    sources: dict[str, list[str]] = {}

    def add_key(source: str, key: str) -> None:
        normalized = normalize_space(str(key or ""))
        if len(normalized) < 4:
            return
        values = sources.setdefault(source, [])
        if normalized not in values:
            values.append(normalized)

    def add_value(source: str, value: Any) -> None:
        normalized = _minimum_topup_key(value)
        if len(normalized) >= 4:
            add_key(source, normalized)

    raw_object = data.get("scientific_object")
    if isinstance(raw_object, str):
        for key in _minimum_topup_keys_from_object_value(raw_object):
            add_key("scientific_object", key)
    for alias in normalize_text_list(data.get("scientific_object_aliases")):
        for key in _minimum_topup_keys_from_object_value(alias):
            add_key("scientific_object_aliases", key)
    for key in (
        "focus",
        "focus_anchor",
        "scientific_object",
        "independent_variable",
        "retrieval_query",
    ):
        value = _subhypothesis_focus_anchor_text(data) if key == "focus_anchor" else data.get(key)
        add_value(key, value)
    for value in normalize_text_list(data.get("exclusive_concrete_objects")):
        add_value("exclusive_concrete_objects", value)
    return sources


def subhypothesis_duplicate_key_set(item: dict[str, Any]) -> set[str]:
    return {
        key
        for values in subhypothesis_duplicate_key_sources(item).values()
        for key in values
    }


def subhypothesis_duplicate_hard_key_set(item: dict[str, Any]) -> set[str]:
    """Return anchors that later batches must not reuse verbatim.

    Broad parent populations (for example, high-temperature superconductors)
    legitimately recur across independently testable mechanism hypotheses.  The
    full claim contract remains visible to the LLM, but only focus and explicit
    exclusive-object anchors are forbidden as hard lexical duplicates.
    """

    sources = subhypothesis_duplicate_key_sources(item)
    return {
        key
        for field in ("focus", "focus_anchor", "exclusive_concrete_objects")
        for key in sources.get(field, [])
    }


def _claim_contract_has_independent_falsification_test(
    candidate: dict[str, Any],
    accepted: dict[str, Any],
) -> bool:
    """Whether two SHs sharing a parent object have distinct tests.

    A renamed mechanism or downstream readout is not enough.  A changed input,
    comparator, or bounded context changes the experiment or observation that
    can falsify the claim and therefore supports a separate SH.  For
    source-grounded observational work, two predeclared source directions may
    legitimately share the same sampling design: they are also independent
    when both their mechanism--outcome contract and their covered source axis
    differ.  This prevents a narrower instance of a shared parent population
    from swallowing a distinct, decision-relevant endpoint such as carbon
    sequestration merely because it reuses the same reference population.
    """

    left = _subhypothesis_claim_contract_summary(candidate)
    right = _subhypothesis_claim_contract_summary(accepted)

    def differs(axis: str) -> bool:
        left_key = _minimum_topup_key(left.get(axis))
        right_key = _minimum_topup_key(right.get(axis))
        return bool(left_key and right_key and left_key != right_key)

    changed_design = any(
        differs(axis)
        for axis in (
            "input_axis",
            "comparison_axis",
            "boundary_or_context_axis",
        )
    )
    if changed_design:
        return True

    def covered_source_axes(item: dict[str, Any]) -> set[str]:
        return {
            normalize_space(str(coverage.get("axis_id") or ""))
            for coverage in (item.get("direction_coverage") or [])
            if isinstance(coverage, dict)
            and normalize_space(str(coverage.get("axis_id") or ""))
            and str(coverage.get("coverage_strength") or "").strip().lower()
            in {"full", "partial"}
        }

    candidate_source_axes = covered_source_axes(candidate)
    accepted_source_axes = covered_source_axes(accepted)
    different_source_direction = bool(
        candidate_source_axes
        and accepted_source_axes
        and candidate_source_axes - accepted_source_axes
    )
    different_mechanism_outcome_contract = (
        differs("mechanism_axis") and differs("outcome_axis")
    )
    return bool(
        different_source_direction and different_mechanism_outcome_contract
    )


def _duplicate_overlap_is_shared_parent_object_only(
    overlap_fields: list[dict[str, Any]],
) -> bool:
    """Return true when every collision is only a reusable object context."""

    if not overlap_fields:
        return False
    reusable_fields = {"scientific_object", "scientific_object_aliases"}
    for item in overlap_fields:
        candidate_fields = {
            str(value or "") for value in item.get("candidate_fields", [])
        }
        accepted_fields = {
            str(value or "") for value in item.get("accepted_fields", [])
        }
        if not candidate_fields or not accepted_fields:
            return False
        if not candidate_fields <= reusable_fields:
            return False
        if not accepted_fields <= reusable_fields:
            return False
    return True


def duplicate_subhypothesis_diagnostic(
    candidate: dict[str, Any],
    accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_sources = subhypothesis_duplicate_key_sources(candidate)
    candidate_keys = {key for values in candidate_sources.values() for key in values}
    candidate_focus = str(candidate.get("focus") or "")
    candidate_query = candidate.get("retrieval_query")
    for existing in accepted:
        if not isinstance(existing, dict):
            continue
        existing_sources = subhypothesis_duplicate_key_sources(existing)
        existing_keys = {key for values in existing_sources.values() for key in values}
        matched_id = str(existing.get("id") or existing.get("candidate_id") or "")
        overlap_keys = sorted(candidate_keys & existing_keys)
        if overlap_keys:
            all_overlap_fields = [
                {
                    "key": key,
                    "candidate_fields": _duplicate_key_fields(candidate_sources, key),
                    "accepted_fields": _duplicate_key_fields(existing_sources, key),
                }
                for key in overlap_keys
            ]
            overlap_fields = all_overlap_fields[:8]
            shared_parent_object_only = _duplicate_overlap_is_shared_parent_object_only(
                all_overlap_fields
            )
            independently_testable = _claim_contract_has_independent_falsification_test(
                candidate,
                existing,
            )
            if not (
                _duplicate_overlap_is_input_axis_only(all_overlap_fields)
                or (shared_parent_object_only and independently_testable)
            ):
                return {
                    "duplicate": True,
                    "reason": "object_anchor_overlap",
                    "matched_accepted_id": matched_id,
                    "overlap_keys": overlap_keys[:12],
                    "overlap_fields": overlap_fields,
                    "candidate_claim_contract": _subhypothesis_claim_contract_summary(candidate),
                    "accepted_claim_contract": _subhypothesis_claim_contract_summary(existing),
                    "repair_instruction": (
                        "Do not return another SH with these shared object, focus, exclusive-object, or query keys. If the candidate keeps the same object-input-comparison-retrieval intent "
                        "and only changes a downstream readout or mechanism label, treat it as an evidence path or localized subclaim of the accepted SH; "
                        "a shared parent population is allowed when the input, comparison, or bounded context changes the independent falsification test, or when a new declared source direction changes both the pivotal mechanism and outcome."
                    ),
                }
        independently_testable = _claim_contract_has_independent_falsification_test(
            candidate,
            existing,
        )
        subsumption_pairs: list[dict[str, Any]] = []
        for left in sorted(candidate_keys):
            for right in sorted(existing_keys):
                if min(len(left), len(right)) >= 8 and (left in right or right in left):
                    candidate_fields = _duplicate_key_fields(candidate_sources, left)
                    accepted_fields = _duplicate_key_fields(existing_sources, right)
                    if (
                        set(candidate_fields) == {"independent_variable"}
                        or set(accepted_fields) == {"independent_variable"}
                    ):
                        continue
                    subsumption_pairs.append({
                        "candidate_key": left,
                        "accepted_key": right,
                        "candidate_fields": candidate_fields,
                        "accepted_fields": accepted_fields,
                    })
                    if len(subsumption_pairs) >= 4:
                        break
            if len(subsumption_pairs) >= 4:
                break
        if subsumption_pairs and not independently_testable:
            return {
                "duplicate": True,
                "reason": "object_anchor_subsumption",
                "matched_accepted_id": matched_id,
                "subsumption_pairs": subsumption_pairs,
                "candidate_claim_contract": _subhypothesis_claim_contract_summary(candidate),
                "accepted_claim_contract": _subhypothesis_claim_contract_summary(existing),
                "repair_instruction": (
                    "The candidate's duplicate keys are contained in, or contain, an accepted SH's keys. Do not narrow, broaden, or rename the same claim space; "
                    "choose a source-grounded axis with a different independent falsification test or return no candidate."
                ),
            }
        focus_similarity = _token_jaccard(candidate_focus, existing.get("focus"))
        if focus_similarity >= 0.72 and not independently_testable:
            return {
                "duplicate": True,
                "reason": "focus_token_overlap",
                "matched_accepted_id": matched_id,
                "similarity": round(focus_similarity, 4),
                "candidate_claim_contract": _subhypothesis_claim_contract_summary(candidate),
                "accepted_claim_contract": _subhypothesis_claim_contract_summary(existing),
                "repair_instruction": (
                    "The focus sentence overlaps too strongly with an accepted SH. Return a candidate only if its claim contract and falsification condition are independently different."
                ),
            }
        query_similarity = _token_jaccard(candidate_query, existing.get("retrieval_query"))
        if query_similarity >= 0.72 and not independently_testable:
            return {
                "duplicate": True,
                "reason": "retrieval_query_token_overlap",
                "matched_accepted_id": matched_id,
                "similarity": round(query_similarity, 4),
                "candidate_claim_contract": _subhypothesis_claim_contract_summary(candidate),
                "accepted_claim_contract": _subhypothesis_claim_contract_summary(existing),
                "repair_instruction": (
                    "The retrieval query intent overlaps too strongly with an accepted SH. Do not use synonym swaps; change the source-grounded object, input/comparison, boundary, evidence standard, or falsification test."
                ),
            }
    return {
        "duplicate": False,
        "reason": "",
        "candidate_claim_contract": _subhypothesis_claim_contract_summary(candidate),
    }


def is_duplicate_subhypothesis(
    candidate: dict[str, Any],
    accepted: list[dict[str, Any]],
) -> tuple[bool, str]:
    diagnostic = duplicate_subhypothesis_diagnostic(candidate, accepted)
    return bool(diagnostic.get("duplicate")), str(diagnostic.get("reason") or "")


_ENTITY_BREADTH_NON_ENTITY_TERMS = frozenset({
    "accuracy", "precision", "recall", "specificity", "sensitivity", "auc",
    "rmse", "mae", "error", "calibration", "calibration error", "lead time",
    "timeliness", "false positive", "false positive rate", "false negative",
    "false negative rate", "rate", "ratio", "score", "threshold", "effect size",
    "performance", "robustness", "latency", "throughput", "uncertainty",
    "uncertainty interval", "confidence interval", "failure rate",
    "incident rate", "adverse event rate",
})


def _entity_bundle_parts(value: Any) -> list[str]:
    text = normalize_space(str(value or ""))
    if not text:
        return []
    if not re.search(r"(?:,|;|/|\+|\band\b|\bor\b)", text, flags=re.IGNORECASE):
        return []
    pieces = [
        normalize_space(part)
        for part in re.split(r"\s*(?:,|;|/|\+|\band\b|\bor\b)\s*", text, flags=re.IGNORECASE)
        if normalize_space(part)
    ]
    meaningful: list[str] = []
    for piece in pieces:
        key = _preflight_text(piece)
        if not key or key in _ENTITY_BREADTH_NON_ENTITY_TERMS:
            continue
        if key in _PREFLIGHT_CONCRETE_READOUT_MARKERS:
            continue
        tokens = [token for token in key.split() if token]
        if len(tokens) >= 2 or re.search(r"\b[A-Z]{2,}\b", piece) or len(pieces) >= 3:
            meaningful.append(piece)
    return meaningful


def _looks_like_entity_bundle(
    value: Any,
    *,
    max_entities: int = DECOMPOSITION_SH_MAX_PRIMARY_ENTITY_COUNT,
) -> bool:
    return len(_entity_bundle_parts(value)) > max(1, int(max_entities or 1))


def _causal_contract_supporting_mediators(item: dict[str, Any]) -> list[str]:
    contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    return normalize_text_list(
        contract.get("supporting_mediators")
        or item.get("supporting_mediators")
        or item.get("mediators")
    )


def assess_subhypothesis_entity_breadth(
    item: dict[str, Any],
    *,
    max_primary_entities: int = DECOMPOSITION_SH_MAX_PRIMARY_ENTITY_COUNT,
    max_exclusive_objects: int = DECOMPOSITION_SH_MAX_EXCLUSIVE_OBJECTS,
    max_supporting_mediators: int = DECOMPOSITION_SH_MAX_SUPPORTING_MEDIATORS,
) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    blocking_reasons: list[str] = []
    scientific_object_parts = _entity_bundle_parts(data.get("scientific_object"))
    focus_anchor_parts = _entity_bundle_parts(_subhypothesis_focus_anchor_text(data))
    independent_variable_parts = _entity_bundle_parts(data.get("independent_variable"))
    focus_parts = _entity_bundle_parts(data.get("focus"))
    exclusive_objects = normalize_text_list(data.get("exclusive_concrete_objects"))
    supporting_mediators = _causal_contract_supporting_mediators(data)
    retrieval_terms = [
        token
        for token in re.split(r"\s+", normalize_space(str(data.get("retrieval_query") or "")))
        if token
    ]

    if len(scientific_object_parts) > max_primary_entities:
        blocking_reasons.append("scientific_object_entity_bundle")
    if len(focus_anchor_parts) > max_primary_entities:
        blocking_reasons.append("focus_anchor_entity_bundle")
    if len(independent_variable_parts) > max_primary_entities:
        blocking_reasons.append("independent_variable_entity_bundle")
    if len(focus_parts) > max_primary_entities + 2:
        blocking_reasons.append("focus_entity_bundle")
    if len(exclusive_objects) > max_exclusive_objects:
        blocking_reasons.append("too_many_exclusive_concrete_objects")
    if len(supporting_mediators) > max_supporting_mediators:
        blocking_reasons.append("too_many_supporting_mediators")
    if len(retrieval_terms) > DECOMPOSITION_SH_MAX_RETRIEVAL_QUERY_TERMS:
        blocking_reasons.append("retrieval_query_too_long")

    return {
        "schema_version": "subhypothesis_entity_breadth_audit_v1",
        "status": "rejected" if blocking_reasons else "ready",
        "blocking_reasons": blocking_reasons,
        "entity_counts": {
            "scientific_object_parts": len(scientific_object_parts),
            "focus_anchor_parts": len(focus_anchor_parts),
            "independent_variable_parts": len(independent_variable_parts),
            "focus_parts": len(focus_parts),
            "exclusive_objects": len(exclusive_objects),
            "supporting_mediators": len(supporting_mediators),
            "retrieval_query_terms": len(retrieval_terms),
        },
        "entity_examples": {
            "scientific_object_parts": scientific_object_parts[:6],
            "focus_anchor_parts": focus_anchor_parts[:6],
            "independent_variable_parts": independent_variable_parts[:6],
            "focus_parts": focus_parts[:6],
            "exclusive_objects": exclusive_objects[:6],
            "supporting_mediators": supporting_mediators[:6],
        },
    }


_DECOMPOSITION_PREFLIGHT_PERMANENT_REJECTION_REASONS = frozenset({
    # These are not incomplete claim contracts. They either place the wrong
    # semantic role in the object slot or make two declared roles logically
    # incompatible, so a later batch must choose a different framing.
    "research_action_as_object",
    "boundary_condition_as_object",
    "readout_as_object",
    "comparison_object_excluded",
    "axis_role_object_input_overlap",
    "axis_role_object_mechanism_overlap",
    "axis_role_input_mechanism_overlap",
})

# A causal contract must state whether its pivotal field names an explanatory
# process/state or merely a measured result.  This vocabulary describes the
# *epistemic role* of a field rather than any scientific discipline, so the
# same validation applies to laboratory, observational, engineering, and
# formal-science projects.
_PIVOTAL_MECHANISM_ROLES = frozenset({
    "CAUSAL_PROCESS",
    "MEDIATOR_STATE",
    "DIRECT_TARGET",
    "READOUT_PROXY",
    "NOT_REQUIRED",
    "UNSPECIFIED",
})


def _decomposition_repair_target_id(
    candidate: dict[str, Any],
    *,
    round_index: int,
) -> str:
    """Create a system-owned identity for one repairable claim contract.

    LLM-local labels such as ``C1`` are useful for displaying a batch, but
    recur across calls and cannot safely identify a repair target.  The target
    ID combines the originating round/local label with a digest of the
    scientific claim axes, so later repairs can replace the same queue entry
    rather than append another ambiguous ``C1`` record.
    """

    item = candidate if isinstance(candidate, dict) else {}
    local_id = normalize_space(str(item.get("candidate_id") or item.get("id") or "draft"))
    payload = {
        "scientific_object": normalize_space(str(item.get("scientific_object") or "")),
        "focus": normalize_space(str(item.get("focus") or "")),
        "input": normalize_space(str(item.get("independent_variable") or "")),
        "causal_chain": normalize_text_list(item.get("causal_chain"))[:4],
        "dependent_variables": normalize_text_list(item.get("dependent_variables"))[:4],
        "causal_contract": (
            item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    safe_local_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", local_id).strip("-") or "draft"
    return f"DPR-R{int(round_index)}-{safe_local_id}-{digest}"


def _decomposition_repair_contract_snapshot(
    candidate: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact causal-role evidence an LLM needs to repair a draft."""

    item = candidate if isinstance(candidate, dict) else {}
    audit = assessment if isinstance(assessment, dict) else {}
    variables = audit.get("variables") if isinstance(audit.get("variables"), dict) else {}
    contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    focus_anchor = item.get("focus_anchor") if isinstance(item.get("focus_anchor"), dict) else {}
    axis_audit = variables.get("axis_separation_audit") if isinstance(
        variables.get("axis_separation_audit"), dict
    ) else {}
    outcome_consistency = axis_audit.get("outcome_field_consistency") if isinstance(
        axis_audit.get("outcome_field_consistency"), dict
    ) else {}
    return {
        "scientific_object": normalize_space(str(item.get("scientific_object") or "")),
        "focus": normalize_space(str(item.get("focus") or "")),
        "independent_variable": normalize_space(str(item.get("independent_variable") or "")),
        "pivotal_mechanism": normalize_space(str(contract.get("pivotal_mechanism") or "")),
        "canonical_outcome": normalize_space(str(contract.get("outcome") or "")),
        "causal_chain": normalize_text_list(item.get("causal_chain"))[:6],
        "dependent_variables": normalize_text_list(item.get("dependent_variables"))[:8],
        "focus_anchor": {
            "anchor": normalize_space(str(focus_anchor.get("anchor") or "")),
            "intervention_anchor": normalize_space(str(focus_anchor.get("intervention_anchor") or "")),
            "mechanism_anchor": normalize_space(str(focus_anchor.get("mechanism_anchor") or "")),
            "outcome_anchor": normalize_space(str(focus_anchor.get("outcome_anchor") or "")),
        },
        "outcome_field_consistency": outcome_consistency,
        "axis_role_blocking_reasons": list(axis_audit.get("blocking_reasons") or []),
    }


def _upsert_decomposition_repair_queue(
    queue: list[dict[str, Any]],
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    """Replace the current diagnostic for one repair target, preserving order."""

    target_id = normalize_space(str(record.get("repair_target_id") or ""))
    if not target_id:
        return [*queue, record]
    updated: list[dict[str, Any]] = []
    replaced = False
    for existing in queue:
        if normalize_space(str(existing.get("repair_target_id") or "")) == target_id:
            if not replaced:
                updated.append(record)
                replaced = True
            continue
        updated.append(existing)
    if not replaced:
        updated.append(record)
    return updated


def _remove_decomposition_repair_target(
    queue: list[dict[str, Any]],
    target_id: str,
) -> list[dict[str, Any]]:
    normalized_target = normalize_space(target_id)
    return [
        record for record in queue
        if normalize_space(str(record.get("repair_target_id") or "")) != normalized_target
    ]


def classify_decomposition_preflight_rejection(
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    *,
    round_index: int,
    repair_target_id: str = "",
    repair_attempt_count: int = 0,
    repair_origin_candidate_id: str = "",
) -> dict[str, Any]:
    """Classify a blocked LLM draft as repairable or permanently rejected.

    The operationality gate is deliberately strict before retrieval, but most
    failures mean that a valid scientific direction is underspecified rather
    than invalid. Passing all blocked drafts into the anti-duplicate contract
    made a repair of the same object/input/axis impossible. Only explicit
    object-role, scope, and hard-axis contradictions therefore become
    permanent rejection patterns; all other blockers form a bounded repair
    queue for the next LLM batch.
    """

    item = candidate if isinstance(candidate, dict) else {}
    audit = assessment if isinstance(assessment, dict) else {}
    blocking_reasons = [
        normalize_space(str(reason))
        for reason in (audit.get("blocking_reasons") or [])
        if normalize_space(str(reason))
    ]
    permanent_reasons = [
        reason for reason in blocking_reasons
        if reason in _DECOMPOSITION_PREFLIGHT_PERMANENT_REJECTION_REASONS
    ]
    disposition = "permanent_rejection" if permanent_reasons else "repair_required"
    direction_axis_ids = [
        normalize_space(str(coverage.get("axis_id") or ""))
        for coverage in (item.get("direction_coverage") or [])
        if isinstance(coverage, dict)
        and normalize_space(str(coverage.get("axis_id") or ""))
    ]
    required_revisions = normalize_text_list(audit.get("required_revisions"))
    if not required_revisions:
        required_revisions = [
            _PREFLIGHT_REVISION_GUIDANCE[reason]
            for reason in blocking_reasons
            if reason in _PREFLIGHT_REVISION_GUIDANCE
        ]
    repair_instruction = (
        "Do not reuse this malformed object-role, scope, or axis contract. "
        "Choose a different source-grounded framing with non-overlapping roles."
        if disposition == "permanent_rejection"
        else "Retain the scientific direction when useful, but repair every listed blocker "
        "with concrete object, input, outcome, comparison, evidence-path, and "
        "falsification details."
    )
    candidate_id = normalize_space(str(item.get("candidate_id") or item.get("id") or ""))
    stable_target_id = normalize_space(repair_target_id) or _decomposition_repair_target_id(
        item,
        round_index=round_index,
    )
    return {
        "round": round_index,
        "reason": "scientific_operationality_rejected",
        "preflight_disposition": disposition,
        "candidate_id": candidate_id,
        "repair_target_id": stable_target_id,
        "repair_origin_candidate_id": normalize_space(repair_origin_candidate_id) or candidate_id,
        "repair_attempt_count": max(0, int(repair_attempt_count or 0)),
        "repair_status": "pending" if disposition == "repair_required" else "not_repairable",
        "scientific_object": normalize_space(str(item.get("scientific_object") or "")),
        "focus": normalize_space(str(item.get("focus") or "")),
        "retrieval_query": normalize_space(str(item.get("retrieval_query") or "")),
        "direction_axis_ids": direction_axis_ids[:8],
        "blocking_reasons": blocking_reasons,
        "permanent_rejection_reasons": permanent_reasons,
        "required_revisions": required_revisions[:8],
        "repair_instruction": repair_instruction,
        "causal_contract_snapshot": _decomposition_repair_contract_snapshot(item, audit),
    }


def _assign_decomposition_candidate_ids(
    candidates: list[dict[str, Any]],
) -> None:
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, dict) and not normalize_space(
            str(candidate.get("candidate_id") or "")
        ):
            candidate["candidate_id"] = f"C{index + 1}"


def _renumber_selected_subhypotheses(
    sub_hypotheses: list[dict[str, Any]],
) -> None:
    for index, item in enumerate(sub_hypotheses):
        if isinstance(item, dict):
            item["id"] = f"SH{index + 1}"


def build_v3_shared_knowledge_registry(
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build project-level background reuse metadata from V3 declarations.

    The registry only concerns foundational context. Direct evidence continues
    to be scoped to the originating SH and must independently pass its slot
    admission contract.
    """
    registry: dict[str, dict[str, Any]] = {}
    candidate_to_subhypothesis = {
        normalize_space(str(item.get("candidate_id") or "")): str(item.get("id") or "")
        for item in sub_hypotheses
        if isinstance(item, dict)
        and normalize_space(str(item.get("candidate_id") or ""))
        and str(item.get("id") or "")
    }
    for item in sub_hypotheses:
        if not isinstance(item, dict):
            continue
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        plan = (
            item.get("research_question_retrieval_plan")
            if isinstance(item.get("research_question_retrieval_plan"), dict)
            else {}
        )
        independence = (
            contract.get("independence_contract")
            if isinstance(contract.get("independence_contract"), dict)
            else {}
        )
        foundation_tasks = (
            plan.get("foundation_context_tasks")
            if isinstance(plan.get("foundation_context_tasks"), list)
            else []
        )
        for task in foundation_tasks:
            if not isinstance(task, dict):
                continue
            foundation = (
                task.get("foundation_context_contract")
                if isinstance(task.get("foundation_context_contract"), dict)
                else {}
            )
            key = normalize_space(str(
                task.get("shared_context_key")
                or foundation.get("shared_context_key")
                or ""
            ))
            if not key:
                continue
            entry = registry.setdefault(
                key,
                {
                    "schema_version": "v3_shared_knowledge_registry_v1",
                    "shared_context_key": key,
                    "kind": "FOUNDATIONAL_CONTEXT_ONLY",
                    "owner_sub_hypothesis_id": str(item.get("id") or ""),
                    "consumer_sub_hypothesis_ids": [],
                    "dependency_sub_hypothesis_ids": [],
                    "research_object_anchors": list(foundation.get("research_object_anchors") or []),
                    "target_construct_anchors": list(foundation.get("target_construct_anchors") or []),
                    "counts_as_direct_primary_evidence": False,
                    "counts_toward_core_slot_readiness": False,
                },
            )
            sub_id = str(item.get("id") or "")
            if sub_id and sub_id not in entry["consumer_sub_hypothesis_ids"]:
                entry["consumer_sub_hypothesis_ids"].append(sub_id)
            for candidate_id in independence.get("depends_on_candidate_ids") or []:
                dependency_id = candidate_to_subhypothesis.get(
                    normalize_space(str(candidate_id))
                )
                if dependency_id and dependency_id not in entry["dependency_sub_hypothesis_ids"]:
                    entry["dependency_sub_hypothesis_ids"].append(dependency_id)
    for entry in registry.values():
        entry["consumer_sub_hypothesis_ids"].sort()
        entry["dependency_sub_hypothesis_ids"].sort()
    return registry


def apply_v3_subhypothesis_relationships(
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve candidate-local dependencies after selected SHs receive IDs."""
    candidate_to_subhypothesis = {
        normalize_space(str(item.get("candidate_id") or "")): str(item.get("id") or "")
        for item in sub_hypotheses
        if isinstance(item, dict)
    }
    for item in sub_hypotheses:
        if not isinstance(item, dict):
            continue
        contract = (
            item.get("research_question_contract")
            if isinstance(item.get("research_question_contract"), dict)
            else {}
        )
        independence = (
            contract.get("independence_contract")
            if isinstance(contract.get("independence_contract"), dict)
            else {}
        )
        dependencies = list(dict.fromkeys(
            candidate_to_subhypothesis.get(normalize_space(str(candidate_id)), "")
            for candidate_id in independence.get("depends_on_candidate_ids") or []
            if candidate_to_subhypothesis.get(normalize_space(str(candidate_id)), "")
        ))
        item["v3_subhypothesis_relationships"] = {
            "research_role": str(contract.get("research_role") or ""),
            "depends_on_sub_hypothesis_ids": dependencies,
            "independent_falsification_target": str(
                independence.get("independent_falsification_target") or ""
            ),
            "overlap_justification": str(independence.get("overlap_justification") or ""),
            "shared_context_keys": list(independence.get("shared_context_keys") or []),
        }
    return build_v3_shared_knowledge_registry(sub_hypotheses)


_CONCRETE_OBJECT_ANCHOR_PATTERN = re.compile(
    r"\b(?:[A-Za-z]{1,16}\d+[A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)*|[A-Z]{2,}(?:-[A-Za-z0-9]+)+)\b"
)
_CONCRETE_OBJECT_DESCRIPTIVE_SUFFIXES = frozenset({
    "associated", "dependent", "driven", "expressing", "mediated",
    "positive", "restricted", "specific",
})


def _concrete_object_anchors(*values: Any) -> list[str]:
    """Find named technical objects whose reuse would collapse SH scope.

    This deliberately does not treat broad domain words as exclusive.  It
    catches stable alphanumeric or hyphenated technical identifiers wherever
    they are used as a focus, causal-chain, or retrieval anchor. Broad
    platform terms intentionally remain shareable.
    """

    anchors: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            for anchor in _concrete_object_anchors(*value):
                if anchor not in anchors:
                    anchors.append(anchor)
            continue
        if isinstance(value, dict):
            for anchor in _concrete_object_anchors(*value.values()):
                if anchor not in anchors:
                    anchors.append(anchor)
            continue
        text = normalize_space(str(value or ""))
        for match in _CONCRETE_OBJECT_ANCHOR_PATTERN.findall(text):
            # Keep the complete identifier.  Truncating an alphanumeric token
            # at its first digit turns distinct symbols (for example a gene
            # family member with a letter suffix) into false ownership matches.
            # Only a known descriptive hyphen suffix is removed, so a stable
            # symbol and its adjectival use remain one object without corrupting
            # identifiers such as mutation or isoform names.
            normalized_match = match.strip("-")
            primary, separator, suffix = normalized_match.partition("-")
            if separator and suffix.lower() in _CONCRETE_OBJECT_DESCRIPTIVE_SUFFIXES:
                normalized_match = primary
            normalized = normalized_match.upper()
            if normalized not in anchors:
                anchors.append(normalized)
    return anchors


def _subhypothesis_focus_anchor(
    *,
    focus: str,
    scientific_object: str,
    independent_variable: str,
    causal_chain: list[str],
    dependent_variables: list[str],
    canonical_outcome: str = "",
    retrieval_query: str,
    evidence_paths: list[dict[str, Any]],
    declared_anchor: Any,
    declared_exclusive_objects: Any = None,
) -> dict[str, Any]:
    observed_objects = _concrete_object_anchors(
        focus,
        scientific_object,
        independent_variable,
        causal_chain,
        dependent_variables,
        retrieval_query,
        evidence_paths,
    )
    declared_objects = _concrete_object_anchors(declared_exclusive_objects)
    named_objects = list(dict.fromkeys([*declared_objects, *observed_objects]))
    anchor_source = (
        declared_anchor.get("anchor")
        if isinstance(declared_anchor, dict)
        else declared_anchor
    )
    anchor = normalize_space(str(anchor_source or "")) or normalize_space(
        " | ".join(value for value in (scientific_object, independent_variable, *(causal_chain[1:2]), *(dependent_variables[:1])) if value)
    )
    return {
        "anchor": anchor or focus,
        "scientific_object": scientific_object,
        "exclusive_concrete_objects": named_objects,
        "declared_exclusive_concrete_objects": declared_objects,
        "supporting_concrete_objects": [],
        "intervention_anchor": independent_variable,
        "mechanism_anchor": causal_chain[1] if len(causal_chain) > 1 else (causal_chain[0] if causal_chain else ""),
        # ``dependent_variables`` can contain complementary readouts.  They
        # must not silently redefine the decision-relevant outcome merely by
        # appearing first in a list.  The causal contract is the authority
        # whenever it declares an outcome; the legacy first-readout fallback
        # is retained only for incomplete contracts.
        "outcome_anchor": canonical_outcome or (
            dependent_variables[0] if dependent_variables else ""
        ),
    }


_RETRIEVAL_OBJECT_PROFILE_ROLES = {
    "primary_system",
    "input_or_parameter",
    "mechanism_or_material",
    "model_or_platform",
    "measurement_or_readout",
}


def normalize_retrieval_object_profiles(
    raw_profiles: Any,
    *,
    scientific_object: str,
    scientific_object_aliases: list[str],
    independent_variable: str,
    causal_chain: list[str],
    dependent_variables: list[str],
) -> list[dict[str, Any]]:
    """Keep a small, auditable set of SH-local retrieval objects.

    ``scientific_object`` remains the SH's identity and the only default
    direct-core anchor.  The additional profiles are independently searched
    corpus entry points (input/parameter, material/mechanism, platform, or
    readout), not aliases of the primary object and not replacements for it.
    """
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_profile(
        value: Any,
        *,
        role: str,
        aliases: Any = (),
        retrieval_anchor: Any = "",
        source: str,
        core_capable: bool = False,
    ) -> None:
        object_value = normalize_space(str(value or ""))
        key = _preflight_text(object_value)
        if not object_value or not key or key in seen or len(object_value) < 3:
            return
        # A lone generic word is not a separate research object.  Phrases
        # such as "photon wavelength" remain valid because they are concrete,
        # searchable parameters rather than generic glue.
        tokens = [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+./-]*", object_value.lower())]
        if len(tokens) == 1 and tokens[0] in {
            "analysis", "cell", "cells", "data", "effect", "method",
            "model", "models", "performance", "process", "result",
            "results", "system", "systems", "technology", "variable",
        }:
            return
        normalized_role = normalize_space(str(role or "")).lower()
        if normalized_role not in _RETRIEVAL_OBJECT_PROFILE_ROLES:
            normalized_role = "mechanism_or_material"
        normalized_aliases = [
            alias
            for alias in normalize_text_list(aliases)
            if _preflight_text(alias) and _preflight_text(alias) != key
        ][:6]
        profiles.append({
            "id": f"OBJ{len(profiles) + 1}",
            "object": object_value,
            "role": normalized_role,
            "aliases": normalized_aliases,
            "query_anchor": normalize_space(str(retrieval_anchor or object_value)),
            "source": source,
            "core_capable": bool(core_capable),
        })
        seen.add(key)

    # The primary profile is always present and preserves the established
    # source-bound object policy used by direct-core verification.
    add_profile(
        scientific_object,
        role="primary_system",
        aliases=scientific_object_aliases,
        source="scientific_object",
        core_capable=True,
    )
    for raw in raw_profiles if isinstance(raw_profiles, list) else []:
        if not isinstance(raw, dict):
            continue
        add_profile(
            raw.get("object") or raw.get("query_anchor") or raw.get("anchor"),
            role=str(raw.get("role") or "mechanism_or_material"),
            aliases=raw.get("aliases") or [],
            retrieval_anchor=raw.get("query_anchor") or raw.get("retrieval_anchor"),
            source="llm_declared",
            core_capable=bool(raw.get("core_capable") is True),
        )

    return profiles[:3]


_AXIS_ROLE_NONCAUSAL_MARKERS = (
    "parameter_constraint",
    "theoretical_derivation",
    "formal_theorem",
    "mathematical_proof",
    "consistency_or_no_go",
    "existence_or_detection",
    "measurement_validity",
    "method_performance",
    "model_comparison",
    "association_or_structure",
    "prediction_or_forecast",
    "descriptive_catalog",
    "classification_description",
    "simulation_validation",
    "engineering_validation",
    "evidence_synthesis",
    "feasibility",
)
_AXIS_ROLE_CAUSAL_MARKERS = (
    "causal",
    "mechanism",
    "mechanistic",
    "intervention",
    "experimental_intervention",
    "perturb",
    "mediator",
    "mediation",
    "pathway",
    "dose",
    "response",
)
_AXIS_ROLE_CONTENT_TOKEN_DENYLIST = frozenset({
    *(_MIXED_PARENT_STOPWORDS | _MIXED_PARENT_GENERIC_TERMS),
    "claim",
    "claims",
    "constraint",
    "constraints",
    "endpoint",
    "endpoints",
    "evidence",
    "hypothesis",
    "input",
    "inputs",
    "mechanism",
    "mechanisms",
    "object",
    "objects",
    "output",
    "outputs",
    "parameter",
    "parameters",
    "readout",
    "readouts",
    "variable",
    "variables",
})


def _axis_role_text_values(value: Any) -> list[str]:
    """Flatten only declared scientific text for SH-local role auditing."""

    values = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, (list, tuple, set)):
            nested = _axis_role_text_values(list(raw))
        elif isinstance(raw, dict):
            nested = []
            for key in (
                "anchor",
                "scientific_object",
                "independent_variable",
                "intervention_anchor",
                "mechanism_anchor",
                "outcome_anchor",
                "pivotal_mechanism",
                "outcome",
                "query_anchor",
                "retrieval_query",
                "object",
                "input",
                "mechanism",
                "readout",
            ):
                if key in raw:
                    nested.extend(_axis_role_text_values(raw.get(key)))
        else:
            clean = normalize_space(str(raw or ""))
            nested = [clean] if clean else []
        for item in nested:
            key = _preflight_text(item)
            if key and key not in seen:
                seen.add(key)
                output.append(item)
    return output


def _axis_role_content_tokens(value: Any) -> set[str]:
    tokens = {
        token
        for text in _axis_role_text_values(value)
        for token in re.findall(r"[a-z0-9][a-z0-9+_-]*", _preflight_text(text))
    }
    return {
        token
        for token in tokens
        if token not in _AXIS_ROLE_CONTENT_TOKEN_DENYLIST
        and token not in _PREFLIGHT_GENERIC_INDEPENDENT_VARIABLES
        and token not in _PREFLIGHT_GENERIC_OUTCOMES
        and token not in _PREFLIGHT_GENERIC_COMPARISONS
    }


def _axis_role_stem(token: str) -> str:
    """Provide a deliberately small lexical normalizer for role auditing.

    This is not a domain ontology or semantic inference.  It only prevents
    inflectional variants such as ``interaction``/``interactions`` from hiding
    that an input is merely a restatement of the proposed mediator.
    """
    normalized = str(token or "").strip().lower()
    if len(normalized) > 4 and normalized.endswith("ies"):
        return normalized[:-3] + "y"
    if len(normalized) > 3 and normalized.endswith("s") and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


def _axis_role_semantic_nucleus_overlap(left: Any, right: Any) -> dict[str, Any]:
    """Audit whether two causal roles share the same declared lexical nucleus."""
    left_tokens = {_axis_role_stem(token) for token in _axis_role_content_tokens(left)}
    right_tokens = {_axis_role_stem(token) for token in _axis_role_content_tokens(right)}
    left_tokens.discard("")
    right_tokens.discard("")
    shared = sorted(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    coverage = len(shared) / smaller if smaller else 0.0
    return {
        "left_stemmed_content_tokens": sorted(left_tokens)[:16],
        "right_stemmed_content_tokens": sorted(right_tokens)[:16],
        "shared_stemmed_content_tokens": shared[:16],
        "smaller_axis_coverage": round(coverage, 4),
        "semantic_nucleus_collapsed": bool(
            len(shared) >= 2 and coverage >= 0.8
        ),
    }


def _preflight_input_has_operational_basis(value: Any) -> bool:
    """Whether a declared input carries a manipulable or calibrated basis."""
    source = str(value or "")
    normalized = _preflight_text(source)
    if not normalized:
        return False
    if _preflight_has_technical_identifier(source):
        return True
    if _preflight_has_operational_variable_marker(source):
        return True
    # Quantified continuous variables are operational even when their unit is
    # outside the small marker vocabulary (for example, a formal parameter).
    return bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:%|[a-zµμ]+)\b", normalized))


def _normalize_causal_input_contract(
    source: dict[str, Any],
    *,
    independent_variable: str,
) -> dict[str, Any]:
    """Type the declared input without inventing an experimental contrast.

    A descriptive state may be a useful property of an object, but it is not
    automatically the input side of a locally testable causal edge.  It must
    first be reframed as a parameter, exposure, stratification, or intervention
    with an operational definition or a declared contrast.
    """

    raw_role = normalize_space(str(
        source.get("input_role") or source.get("input_type") or ""
    )).upper()
    raw_role = re.sub(r"[^A-Z]+", "_", raw_role).strip("_")
    input_value = normalize_space(str(
        source.get("input_operational_definition")
        or source.get("input")
        or independent_variable
        or ""
    ))
    contrast = normalize_text_list(
        source.get("input_contrast")
        or source.get("comparison_levels")
        or source.get("input_levels")
    )
    if raw_role not in CAUSAL_INPUT_ROLE_TYPES:
        raw_role = ""
    descriptive_by_text = bool(
        input_value
        and any(marker in _preflight_text(input_value) for marker in _DESCRIPTIVE_STATE_INPUT_MARKERS)
    )
    parameter_by_text = bool(
        input_value
        and any(marker in _preflight_text(input_value) for marker in _PARAMETER_INPUT_MARKERS)
    )
    explicitly_calibrated = bool(
        _preflight_has_technical_identifier(input_value)
        or re.search(r"\b\d+(?:\.\d+)?\b", input_value)
    )
    has_operational_basis = bool(
        _preflight_input_has_operational_basis(input_value) or contrast
    )
    input_type = (
        raw_role
        or (
            "PARAMETER"
            if parameter_by_text
            else "DESCRIPTIVE_STATE"
            if descriptive_by_text and not contrast and not explicitly_calibrated
            else "UNSPECIFIED"
        )
    )
    direct_edge_eligible = bool(
        input_value
        and input_type != "DESCRIPTIVE_STATE"
        and (has_operational_basis or input_type in {"EXPOSURE", "STRATIFICATION"})
    )
    return {
        "input_type": input_type,
        "operational_definition": input_value,
        "contrast_or_levels": contrast[:8],
        "has_operational_basis": has_operational_basis,
        "direct_local_edge_eligible": direct_edge_eligible,
        "requires_reframing": bool(input_type == "DESCRIPTIVE_STATE"),
        "reframing_reason": (
            "descriptive_state_requires_declared_contrast_or_operational_role"
            if input_type == "DESCRIPTIVE_STATE"
            else ""
        ),
    }


def _normalize_causal_claim_layer_contract(
    source: dict[str, Any],
    *,
    declared_outcome: str,
) -> dict[str, Any]:
    """Separate local endpoints from transfer or decision interpretations."""

    raw_layer = normalize_space(str(source.get("claim_layer") or "")).upper()
    raw_layer = re.sub(r"[^A-Z]+", "_", raw_layer).strip("_")
    transfer_target = normalize_space(str(source.get("transfer_target") or ""))
    transfer_basis = normalize_space(str(source.get("transfer_basis") or ""))
    validation_status = normalize_space(str(
        source.get("transfer_validation_status") or ""
    )).upper()
    local_outcome = normalize_space(str(
        source.get("local_empirical_outcome")
        or source.get("local_outcome")
        or ""
    ))
    text = _preflight_text(declared_outcome)
    inferred_interpretation = bool(
        text and any(marker in text for marker in _TRANSFER_OR_INTERPRETATION_MARKERS)
    )
    claim_layer = (
        raw_layer
        if raw_layer in CAUSAL_CLAIM_LAYERS
        else "CROSS_SYSTEM_TRANSFER"
        if transfer_target
        else "DECISION_INTERPRETATION"
        if inferred_interpretation
        else "LOCAL_EMPIRICAL"
    )
    canonical_local_outcome = (
        local_outcome
        or (declared_outcome if claim_layer == "LOCAL_EMPIRICAL" else "")
    )
    requires_local_outcome = bool(claim_layer != "LOCAL_EMPIRICAL")
    return {
        "claim_layer": claim_layer,
        "declared_outcome": declared_outcome,
        "local_empirical_outcome": canonical_local_outcome,
        "transfer_target": transfer_target,
        "transfer_basis": transfer_basis,
        "transfer_validation_status": validation_status or "NOT_APPLICABLE",
        "requires_local_empirical_outcome": requires_local_outcome,
        "local_outcome_present": bool(canonical_local_outcome),
        "direct_local_edge_endpoint": canonical_local_outcome,
        "requires_reframing": bool(requires_local_outcome and not canonical_local_outcome),
        "reframing_reason": (
            "nonlocal_claim_requires_local_empirical_outcome_before_retrieval"
            if requires_local_outcome and not canonical_local_outcome
            else ""
        ),
    }


def _axis_role_overlap(left: Any, right: Any) -> dict[str, Any]:
    left_values = _axis_role_text_values(left)
    right_values = _axis_role_text_values(right)
    left_tokens = _axis_role_content_tokens(left_values)
    right_tokens = _axis_role_content_tokens(right_values)
    shared_tokens = sorted(left_tokens & right_tokens)
    union_tokens = left_tokens | right_tokens
    exact_phrase_pairs: list[dict[str, str]] = []
    containment_pairs: list[dict[str, str]] = []
    left_contains_right = False
    right_contains_left = False
    for left_value in left_values:
        left_key = _preflight_text(left_value)
        if not left_key:
            continue
        left_token_count = len(left_key.split())
        for right_value in right_values:
            right_key = _preflight_text(right_value)
            if not right_key:
                continue
            right_token_count = len(right_key.split())
            if left_key == right_key:
                exact_phrase_pairs.append({
                    "left": left_value,
                    "right": right_value,
                })
                continue
            shorter, longer = (
                (left_key, right_key)
                if left_token_count <= right_token_count
                else (right_key, left_key)
            )
            if len(shorter.split()) >= 2 and re.search(
                rf"\b{re.escape(shorter)}\b",
                longer,
            ):
                if shorter == right_key and longer == left_key:
                    left_contains_right = True
                elif shorter == left_key and longer == right_key:
                    right_contains_left = True
                containment_pairs.append({
                    "left": left_value,
                    "right": right_value,
                })
    jaccard = len(shared_tokens) / len(union_tokens) if union_tokens else 0.0
    high_overlap = bool(
        exact_phrase_pairs
        or containment_pairs
        or (len(shared_tokens) >= 2 and jaccard >= 0.82)
    )
    return {
        "left_values": left_values[:8],
        "right_values": right_values[:8],
        "left_content_tokens": sorted(left_tokens)[:16],
        "right_content_tokens": sorted(right_tokens)[:16],
        "shared_content_tokens": shared_tokens[:16],
        "content_token_jaccard": round(jaccard, 4),
        "exact_phrase_pairs": exact_phrase_pairs[:8],
        "containment_pairs": containment_pairs[:8],
        "left_contains_right": left_contains_right,
        "right_contains_left": right_contains_left,
        "high_overlap": high_overlap,
    }


def _axis_overlap_exact_or_high(overlap: dict[str, Any]) -> bool:
    return bool(
        overlap.get("exact_phrase_pairs")
        or (
            float(overlap.get("content_token_jaccard") or 0.0) >= 0.82
            and len(overlap.get("shared_content_tokens") or []) >= 2
        )
    )


def _subhypothesis_mechanism_axis_required(
    item: dict[str, Any],
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> bool:
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else (
        item.get("epistemic_profile") if isinstance(item.get("epistemic_profile"), dict) else {}
    )
    causal_contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    evidence_mode = normalize_space(str(item.get("evidence_mode") or "")).lower()
    primary_mode = normalize_space(str(profile.get("primary_mode") or "")).lower()
    constraint_type = normalize_space(str(causal_contract.get("constraint_type") or "")).lower()
    claim_types = " ".join(str(value or "") for value in (profile.get("claim_types") or causal_contract.get("claim_types") or []))
    combined = " ".join(
        str(value or "").lower()
        for value in (
            evidence_mode,
            primary_mode,
            constraint_type,
            claim_types,
        )
    )
    if (
        profile.get("requires_intervention") is True
        or primary_mode == "experimental_intervention"
        or any(marker in constraint_type for marker in ("causal", "mechanism", "mechanistic"))
        or "causal" in evidence_mode
    ):
        return True
    if any(marker in constraint_type for marker in _AXIS_ROLE_NONCAUSAL_MARKERS):
        return False
    if any(marker in combined for marker in _AXIS_ROLE_NONCAUSAL_MARKERS) and primary_mode in _NONINTERVENTIONAL_MODES:
        return False
    return any(marker in combined for marker in _AXIS_ROLE_CAUSAL_MARKERS)


def _pivotal_mechanism_role_assessment(
    causal_contract: dict[str, Any],
    *,
    dependent_variables: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Classify the epistemic role of the declared pivotal mechanism.

    A word such as ``activity``, ``rate``, or ``abundance`` is not globally
    forbidden as a mediator: a scientific model may legitimately use a
    measured state as an intermediate variable.  The hard, domain-neutral
    failure is narrower—when the purported mechanism is also one of the SH's
    declared endpoint readouts, it is a readout proxy rather than an
    explanatory causal axis.  Explicit LLM role labels remain auditable and
    take precedence when valid.
    """

    contract = causal_contract if isinstance(causal_contract, dict) else {}
    mechanism = normalize_space(str(contract.get("pivotal_mechanism") or ""))
    raw_role = normalize_space(str(
        contract.get("pivotal_mechanism_role")
        or contract.get("mechanism_role")
        or ""
    )).upper().replace("-", "_").replace(" ", "_")
    declared_role = raw_role if raw_role in _PIVOTAL_MECHANISM_ROLES else ""
    readouts = normalize_text_list(dependent_variables)
    readout_overlaps = [
        _axis_role_overlap([mechanism], [readout])
        for readout in readouts
        if mechanism and readout
    ]
    overlapping_readouts = [
        readout
        for readout, overlap in zip(readouts, readout_overlaps)
        if _axis_overlap_exact_or_high(overlap)
        or overlap.get("left_contains_right")
        or overlap.get("right_contains_left")
    ]
    if declared_role:
        effective_role = declared_role
        source = "declared"
    elif not mechanism:
        effective_role = "UNSPECIFIED"
        source = "missing_mechanism"
    elif overlapping_readouts:
        effective_role = "READOUT_PROXY"
        source = "inferred_from_declared_readout_overlap"
    else:
        effective_role = "UNSPECIFIED"
        source = "not_declared"
    return {
        "declared_role": declared_role or "UNSPECIFIED",
        "effective_role": effective_role,
        "source": source,
        "mechanism": mechanism,
        "overlapping_declared_readouts": overlapping_readouts[:8],
        "invalid_declared_role": bool(raw_role and not declared_role),
        "allowed_roles": sorted(_PIVOTAL_MECHANISM_ROLES),
    }


def audit_subhypothesis_axis_role_separation(
    sub_hypothesis: dict[str, Any],
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect one SH reusing the same concept as object/input/mechanism.

    Cross-SH anti-duplication is not enough: a single malformed SH can put the
    same semantic nucleus into ``scientific_object``, ``independent_variable``,
    and ``causal_contract.pivotal_mechanism``.  Retrieval then has no
    independent object/input/mechanism contract.  This audit is intentionally
    conservative and source-preserving: it reports or blocks the collapse; it
    does not invent replacement science.
    """

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    causal_chain = _axis_role_text_values(item.get("causal_chain"))
    causal_contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    focus_anchor = item.get("focus_anchor") if isinstance(item.get("focus_anchor"), dict) else {}
    scientific_object_values = _axis_role_text_values(
        item.get("scientific_object")
    )
    input_values = _axis_role_text_values(
        item.get("independent_variable")
    )
    mechanism_values = _axis_role_text_values(
        causal_contract.get("pivotal_mechanism")
    )
    outcome_values = _axis_role_text_values(
        causal_contract.get("outcome")
    )
    input_contract = (
        causal_contract.get("input_contract")
        if isinstance(causal_contract.get("input_contract"), dict)
        else _normalize_causal_input_contract(
            causal_contract,
            independent_variable=input_values[0] if input_values else "",
        )
    )
    claim_layer_contract = (
        causal_contract.get("claim_layer_contract")
        if isinstance(causal_contract.get("claim_layer_contract"), dict)
        else _normalize_causal_claim_layer_contract(
            causal_contract,
            declared_outcome=outcome_values[0] if outcome_values else "",
        )
    )
    role_values = {
        "scientific_object": scientific_object_values,
        "focus_anchor": _axis_role_text_values(focus_anchor.get("anchor") or item.get("focus_anchor")),
        "input": input_values,
        "mechanism": mechanism_values,
        "outcome": outcome_values,
    }
    overlaps = {
        "scientific_object_vs_input": _axis_role_overlap(scientific_object_values, input_values),
        "scientific_object_vs_mechanism": _axis_role_overlap(scientific_object_values, mechanism_values),
        "input_vs_mechanism": _axis_role_overlap(input_values, mechanism_values),
        "input_vs_outcome": _axis_role_overlap(input_values, outcome_values),
        "mechanism_vs_outcome": _axis_role_overlap(mechanism_values, outcome_values),
    }
    mechanism_required = _subhypothesis_mechanism_axis_required(
        item,
        epistemic_profile=epistemic_profile,
    )
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    mechanism_role = _pivotal_mechanism_role_assessment(
        causal_contract,
        dependent_variables=normalize_text_list(item.get("dependent_variables")),
    )
    if input_contract.get("requires_reframing"):
        blocking_reasons.append("input_descriptive_state_not_operationalized")
    if claim_layer_contract.get("requires_reframing"):
        blocking_reasons.append("claim_layer_missing_local_empirical_outcome")
    object_input_overlap = overlaps["scientific_object_vs_input"]
    object_mechanism_overlap = overlaps["scientific_object_vs_mechanism"]
    input_mechanism_overlap = overlaps["input_vs_mechanism"]
    input_mechanism_nucleus = _axis_role_semantic_nucleus_overlap(
        input_values,
        mechanism_values,
    )
    if (
        _axis_overlap_exact_or_high(object_input_overlap)
        or object_input_overlap.get("left_contains_right")
    ):
        blocking_reasons.append("axis_role_object_input_overlap")
    elif object_input_overlap.get("right_contains_left"):
        warnings.append("axis_role_input_wraps_scientific_object")
    if mechanism_required and (
        _axis_overlap_exact_or_high(object_mechanism_overlap)
        or object_mechanism_overlap.get("left_contains_right")
    ):
        blocking_reasons.append("axis_role_object_mechanism_overlap")
    elif mechanism_required and object_mechanism_overlap.get("right_contains_left"):
        warnings.append("axis_role_mechanism_wraps_scientific_object")
    if mechanism_required and mechanism_role.get("effective_role") == "READOUT_PROXY":
        blocking_reasons.append("pivotal_mechanism_is_readout_proxy")
    elif mechanism_required and mechanism_role.get("invalid_declared_role"):
        blocking_reasons.append("pivotal_mechanism_role_invalid")
    if mechanism_required and _axis_overlap_exact_or_high(input_mechanism_overlap):
        blocking_reasons.append("axis_role_input_mechanism_overlap")
    elif (
        mechanism_required
        and input_mechanism_nucleus.get("semantic_nucleus_collapsed")
        and not _preflight_input_has_operational_basis(input_values[0] if input_values else "")
    ):
        # A mechanism label with an added abstract noun (for example,
        # "interaction strength" -> "interactions") is not an independently
        # manipulable input.  Report it before provider dispatch so the LLM
        # repair path can request an actual condition, perturbation, exposure,
        # or calibrated parameter rather than fabricate a literature query.
        blocking_reasons.append("axis_role_input_mechanism_semantic_collapse")
    elif mechanism_required and input_mechanism_overlap.get("high_overlap"):
        warnings.append("axis_role_input_mechanism_overlap")
    focus_anchor_outcome_values = _axis_role_text_values(
        focus_anchor.get("outcome_anchor") or focus_anchor.get("outcome")
    )
    dependent_outcome_values = _axis_role_text_values(
        item.get("dependent_variables")
    )
    focus_outcome_overlap = _axis_role_overlap(
        outcome_values,
        focus_anchor_outcome_values,
    )
    dependent_outcome_overlaps = [
        _axis_role_overlap(outcome_values, value)
        for value in dependent_outcome_values
    ]
    # A dependent variable can be an auxiliary measurement distinct from a
    # final endpoint.  It becomes a contract defect only when both a declared
    # focus outcome and every dependent readout point to different measurement
    # families.  This avoids silently choosing one inconsistent field.
    if (
        outcome_values
        and focus_anchor_outcome_values
        and not focus_outcome_overlap.get("shared_content_tokens")
        and dependent_outcome_values
        and not any(audit.get("shared_content_tokens") for audit in dependent_outcome_overlaps)
    ):
        blocking_reasons.append("axis_role_outcome_field_conflict")
    if not mechanism_required:
        if object_mechanism_overlap["high_overlap"]:
            warnings.append("axis_role_object_mechanism_overlap_noncausal")
        if input_mechanism_overlap["high_overlap"]:
            warnings.append("axis_role_input_mechanism_overlap_noncausal")
    if overlaps["input_vs_outcome"]["high_overlap"]:
        warnings.append("axis_role_input_outcome_overlap")
    if overlaps["mechanism_vs_outcome"]["high_overlap"]:
        warnings.append(
            "axis_role_mechanism_outcome_overlap"
            if mechanism_required
            else "axis_role_mechanism_outcome_overlap_noncausal"
        )
    return {
        "schema_version": "subhypothesis_axis_role_separation_v2",
        "status": "BLOCKED" if blocking_reasons else "PASS",
        "blocking": bool(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "mechanism_axis_required": mechanism_required,
        "role_values": role_values,
        "overlaps": overlaps,
        "semantic_nucleus_audits": {
            "input_vs_mechanism": input_mechanism_nucleus,
        },
        "pivotal_mechanism_role": mechanism_role,
        "causal_contract_execution": {
            "input_contract": input_contract,
            "claim_layer_contract": claim_layer_contract,
            "local_direct_edge_executable": bool(
                input_contract.get("direct_local_edge_eligible")
                and claim_layer_contract.get("local_outcome_present")
            ),
        },
        "outcome_field_consistency": {
            "canonical_outcome": outcome_values[:8],
            "focus_anchor_outcome": focus_anchor_outcome_values[:8],
            "dependent_variables": dependent_outcome_values[:12],
            "focus_anchor_overlap": focus_outcome_overlap,
            "dependent_variable_overlaps": dependent_outcome_overlaps[:12],
        },
        "policy": {
            "scientific_object_vs_input": "hard_block",
            "scientific_object_vs_mechanism": (
                "hard_block_when_causal_or_mechanistic"
            ),
            "input_vs_mechanism": "hard_block_when_causal_or_mechanistic",
            "input_mechanism_semantic_nucleus": "hard_block_when_input_lacks_operational_basis",
            "pivotal_mechanism_readout_proxy": "hard_block_when_causal_pivotal_field_duplicates_a_declared_readout",
            "outcome_overlaps": "diagnostic_warning",
            "outcome_field_consistency": "hard_block_when_focus_and_all_declared_readouts_conflict",
        },
    }


def _normalize_research_question_subhypothesis_v3(
    item: dict[str, Any],
    *,
    objective: str,
    domain: str,
    sub_hypothesis_id: str,
    research_domain_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalise an explicitly declared SH V3 without causal projection.

    This is deliberately separate from the retired legacy normaliser.  A V3
    input is a typed research question, so it must not be routed through
    causal-chain completion, outcome repair, evidence-path generation, or
    object/process/outcome alignment merely to satisfy older storage fields.
    """
    source = item if isinstance(item, dict) else {}
    question = source.get("research_question") if isinstance(source.get("research_question"), dict) else {}
    existing_contract = (
        source.get("research_question_contract")
        if isinstance(source.get("research_question_contract"), dict)
        and source.get("research_question_contract", {}).get("schema_version")
        == RESEARCH_QUESTION_CONTRACT_VERSION
        else {}
    )
    question_text = normalize_space(
        str(
            question.get("question_text")
            or question.get("text")
            or (existing_contract.get("research_question") or {}).get("question_text")
            or ""
        )
    )
    scope = (
        question.get("scientific_scope")
        if isinstance(question.get("scientific_scope"), dict)
        else existing_contract.get("scientific_scope")
        if isinstance(existing_contract.get("scientific_scope"), dict)
        else {}
    )
    scientific_object = normalize_space(
        str(
            scope.get("research_object")
            or ""
        )
    )
    profile = normalize_epistemic_profile(
        source.get("epistemic_profile") or {},
        fallback_text=" ".join(
            value
            for value in (
                question_text,
                scientific_object,
                str(question.get("question_kind") or ""),
            )
            if value
        ),
    )
    seed = {
        **source,
        "id": sub_hypothesis_id,
        "focus": question_text,
        "scientific_object": scientific_object,
        "research_question": {
            **question,
            "question_text": question_text,
            "scientific_scope": scope,
            **(
                {"claim_target": dict(question.get("claim_target") or {})}
                if isinstance(question.get("claim_target"), dict)
                else {}
            ),
            **(
                {"evidence_contract": dict(question.get("evidence_contract") or {})}
                if isinstance(question.get("evidence_contract"), dict)
                else {}
            ),
            **(
                {"routing_contract": dict(question.get("routing_contract") or {})}
                if isinstance(question.get("routing_contract"), dict)
                else {}
            ),
            **(
                {"operationalization": dict(question.get("operationalization") or {})}
                if isinstance(question.get("operationalization"), dict)
                else {}
            ),
            **(
                {"slot_definitions": dict(question.get("slot_definitions") or {})}
                if isinstance(question.get("slot_definitions"), dict)
                else {}
            ),
            **(
                {"independence_contract": dict(question.get("independence_contract") or {})}
                if isinstance(question.get("independence_contract"), dict)
                else {}
            ),
            **(
                {"boundary_contract": dict(question.get("boundary_contract") or {})}
                if isinstance(question.get("boundary_contract"), dict)
                else {}
            ),
            **(
                {"measurement_mapping": dict(question.get("measurement_mapping") or {})}
                if isinstance(question.get("measurement_mapping"), dict)
                else {}
            ),
            **(
                {"threshold_governance": dict(question.get("threshold_governance") or {})}
                if isinstance(question.get("threshold_governance"), dict)
                else {}
            ),
            "research_role": str(question.get("research_role") or ""),
            "design_basis_ids": list(question.get("design_basis_ids") or []),
        },
    }
    if isinstance(question.get("causal_model"), dict):
        seed["research_question"]["causal_model"] = dict(question["causal_model"])
    if isinstance(research_domain_contract, dict):
        seed["research_question"]["research_domain_contract"] = dict(
            validate_research_domain_contract(research_domain_contract)
        )
    contract = build_research_question_contract(
        {"project_id": "", "objective": objective, "domain": domain},
        seed,
        epistemic_profile=profile,
    )
    return {
        "id": sub_hypothesis_id,
        "candidate_id": normalize_space(str(source.get("candidate_id") or sub_hypothesis_id)),
        "repair_of_candidate_id": normalize_space(str(source.get("repair_of_candidate_id") or "")),
        "focus": question_text,
        "primary_field": normalize_space(str(source.get("primary_field") or domain or "")),
        "adjacent_fields": normalize_text_list(source.get("adjacent_fields")),
        "scientific_object": scientific_object,
        "scientific_object_aliases": normalize_text_list(source.get("scientific_object_aliases")),
        "epistemic_profile": profile,
        "claim_types": list(profile.get("claim_types") or []),
        "hypothesis_type": normalize_space(str(source.get("hypothesis_type") or "")),
        "scale": normalize_space(str(source.get("scale") or "")),
        "priority_rationale": dict(source.get("priority_rationale") or {}),
        "research_question": dict(contract.get("research_question") or {}),
        "scientific_scope": dict(contract.get("scientific_scope") or {}),
        "claim_target": dict(contract.get("claim_target") or {}),
        "evidence_contract": dict(contract.get("evidence_contract") or {}),
        "routing_contract": dict(contract.get("routing_contract") or {}),
        "research_question_contract": contract,
        "research_question_retrieval_plan": build_question_retrieval_plan(contract),
        "evidence_pipeline_schema": "research_question_evidence_v3",
        "legacy_causal_artifacts_status": "STALE_SCHEMA",
        "scientific_operationality_preflight_required": True,
        "status": "pending_retrieval",
        "source_objective": objective,
    }


def _research_question_validation_error_code(error: Exception) -> str:
    message = normalize_space(str(error)).casefold()
    mappings = (
        ("comparison_contract_v4 is only permitted", "QUESTION_KIND_FIELD_MISMATCH"),
        ("causal_model is permitted only", "QUESTION_KIND_FIELD_MISMATCH"),
        ("must not carry causal_model", "QUESTION_KIND_FIELD_MISMATCH"),
        ("unknown question_kind", "QUESTION_KIND_INVALID"),
        ("explicit research_question.question_kind", "QUESTION_KIND_REQUIRED"),
        ("question_text", "QUESTION_TEXT_REQUIRED"),
        ("research_domain_contract", "RESEARCH_DOMAIN_CONTRACT_INVALID"),
        ("missing required slots", "REQUIRED_SLOT_MISSING"),
        ("required_slots", "REQUIRED_SLOT_MISSING"),
        ("slot definitions", "SLOT_DEFINITION_INVALID"),
        ("slot_definitions", "SLOT_DEFINITION_INVALID"),
        ("operationalization", "OPERATIONALIZATION_INCOMPLETE"),
        ("research_role", "RESEARCH_ROLE_INVALID"),
        ("design_basis_ids", "DESIGN_BASIS_REFERENCE_REQUIRED"),
        ("independence_contract", "INDEPENDENCE_CONTRACT_INCOMPLETE"),
        ("boundary-heterogeneity", "BOUNDARY_CONTRACT_INCOMPLETE"),
        ("measurement-validity", "MEASUREMENT_MAPPING_INCOMPLETE"),
        ("falsification_rule", "THRESHOLD_GOVERNANCE_INCOMPLETE"),
        ("benchmark_comparison", "COMPARISON_CONTRACT_INCOMPLETE"),
        ("comparison_contract_v4", "COMPARISON_CONTRACT_INCOMPLETE"),
    )
    for marker, code in mappings:
        if marker in message:
            return code
    if isinstance(error, TypeError):
        return "RESEARCH_QUESTION_PROTOCOL_TYPE_ERROR"
    return "RESEARCH_QUESTION_CONTRACT_VALIDATION_FAILED"


def _candidate_protocol_identity(item: Any, index: int) -> str:
    source = item if isinstance(item, dict) else {}
    return normalize_space(
        str(source.get("candidate_id") or source.get("id") or f"RAW{index + 1}")
    )


def normalize_sub_hypotheses(
    raw_items: Any,
    *,
    objective: str,
    domain: str,
    max_subhypotheses: int,
    require_research_question_contract: bool = True,
    research_domain_contract: dict[str, Any] | None = None,
    validation_audit: list[dict[str, Any]] | None = None,
    validation_stage: str = "initial",
    sub_hypothesis_id_offset: int = 0,
) -> list[dict[str, Any]]:
    """Normalize only explicitly declared ResearchQuestionContractV3 items.

    ``require_research_question_contract`` remains in the call signature so a
    caller can be upgraded without a TypeError, but it cannot re-enable the
    retired causal-tuple normalizer. An item without either a V3 question or
    a V3 contract is intentionally omitted and must be re-decomposed by the
    V3 question generator; it is never projected into an A→M→Y schema.
    """
    del require_research_question_contract
    items = raw_items if isinstance(raw_items, list) else []
    normalized: list[dict[str, Any]] = []
    for raw_index, item in enumerate(items):
        candidate_id = _candidate_protocol_identity(item, raw_index)
        if not isinstance(item, dict):
            if validation_audit is not None:
                validation_audit.append({
                    "candidate_id": candidate_id,
                    "stage": validation_stage,
                    "status": "REJECTED",
                    "validation_error_code": "CANDIDATE_NOT_OBJECT",
                    "validation_error_message": "Research-question candidate must be a JSON object",
                })
            continue
        declared_question = (
            dict(item.get("research_question"))
            if isinstance(item.get("research_question"), dict)
            else {}
        )
        declared_contract = (
            dict(item.get("research_question_contract"))
            if isinstance(item.get("research_question_contract"), dict)
            and item.get("research_question_contract", {}).get("schema_version")
            == RESEARCH_QUESTION_CONTRACT_VERSION
            else {}
        )
        if not declared_question and not declared_contract:
            if validation_audit is not None:
                validation_audit.append({
                    "candidate_id": candidate_id,
                    "stage": validation_stage,
                    "status": "REJECTED",
                    "validation_error_code": "RESEARCH_QUESTION_DECLARATION_REQUIRED",
                    "validation_error_message": (
                        "Candidate must explicitly declare research_question or a current V3 contract"
                    ),
                })
            continue
        try:
            normalized_item = _normalize_research_question_subhypothesis_v3(
                item,
                objective=objective,
                domain=domain,
                sub_hypothesis_id=(
                    f"SH{sub_hypothesis_id_offset + len(normalized) + 1}"
                ),
                research_domain_contract=research_domain_contract,
            )
        except (TypeError, ValueError) as exc:
            if validation_audit is not None:
                validation_audit.append({
                    "candidate_id": candidate_id,
                    "stage": validation_stage,
                    "status": "REJECTED",
                    "validation_error_code": _research_question_validation_error_code(exc),
                    "validation_error_message": normalize_space(str(exc))[:1000],
                })
            continue
        normalized.append(normalized_item)
        if validation_audit is not None:
            validation_audit.append({
                "candidate_id": candidate_id,
                "stage": validation_stage,
                "status": "ACCEPTED",
                "validation_error_code": "",
                "validation_error_message": "",
                "research_question_contract_id": str(
                    (normalized_item.get("research_question_contract") or {}).get(
                        "contract_id"
                    )
                    or ""
                ),
            })
        if len(normalized) >= max_subhypotheses:
            break
    return normalized


_ACADEMIC_HEURISTIC_SEGMENT_PREFIX = re.compile(
    r"^(?:researchers?\s+(?:investigated|studied|examined|evaluated)\s+|"
    r"experts?\s+.*?\s+(?:focused\s+on|investigated|studied)\s+|"
    r"(?:exploring|including|include|includes|such\s+as)\s+|"
    r"(?:to\s+)?(?:address|manage|improve|reduce)\s+)",
    flags=re.IGNORECASE,
)


_ACADEMIC_LEXICALIZED_CONJUNCTIONS = (
    "oil and gas",
    "research and development",
    "supply and demand",
    "trial and error",
)


def _academic_split_candidate_alternatives(segment: str) -> list[str]:
    """Split example lists without shredding lexicalized compound nouns."""

    clean = normalize_space(segment)
    if not clean:
        return []
    coarse = [
        normalize_space(part)
        for part in re.split(r",\s+|\bas\s+well\s+as\b", clean, flags=re.IGNORECASE)
        if normalize_space(part)
    ]
    output: list[str] = []
    for part in coarse or [clean]:
        part = re.sub(r"^(?:and|or)\s+", "", normalize_space(part), flags=re.IGNORECASE)
        lowered = part.lower()
        if any(compound in lowered for compound in _ACADEMIC_LEXICALIZED_CONJUNCTIONS):
            output.append(part)
            continue
        # Split only short symmetric alternatives.  Long prose joined by "and"
        # is usually a mechanism or comparison sentence, not an object list.
        if (
            re.search(r"\b(?:and|or)\b", part, flags=re.IGNORECASE)
            and len(re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", part)) <= 7
        ):
            pieces = [
                normalize_space(piece)
                for piece in re.split(r"\b(?:and|or)\b", part, flags=re.IGNORECASE)
                if normalize_space(piece)
            ]
            if len(pieces) >= 2 and all(len(piece.split()) <= 4 for piece in pieces):
                output.extend(pieces)
                continue
        output.append(part)
    return list(dict.fromkeys(item for item in output if item))


def _parent_context_has_carbon_storage_scope(parent_context: str) -> bool:
    normalized = _preflight_text(parent_context)
    return bool(
        re.search(r"\b(?:co2|carbon\s+dioxide)\b", normalized)
        or re.search(
            r"\bcarbon\s+(?:capture|sequestration|storage|removal)\b",
            normalized,
        )
        or re.search(r"\b(?:geologic|geological|biologic|biological)\s+carbon\b", normalized)
    )


def _component_has_carbon_storage_context(component: str) -> bool:
    normalized = _preflight_text(component)
    return bool(
        re.search(r"\b(?:co2|carbon\s+dioxide|carbon|sequestration|storage|injection|capture|removal)\b", normalized)
    )


def _component_is_geologic_storage_site(component: str) -> bool:
    normalized = _preflight_text(component)
    return bool(re.search(
        r"\b(?:aquifer|aquifers|reservoir|reservoirs|formation|formations|"
        r"subsurface|geologic|geological|basin|basins|caprock|wellbore|"
        r"depleted\s+oil|oil\s+and\s+gas|saline)\b",
        normalized,
    ))


def _component_is_biologic_carbon_sink(component: str) -> bool:
    normalized = _preflight_text(component)
    return bool(re.search(
        r"\b(?:forest|forests|soil|soils|wetland|wetlands|biologic|biological|"
        r"biomass|ecosystem|ecosystems|agricultural|agroforestry|biochar|"
        r"microalgae|algae|vegetation|peatland|peatlands)\b",
        normalized,
    ))


def _academic_restore_fragmented_component_from_parent(
    component: str,
    parent_context: str,
) -> str:
    clean = normalize_space(component)
    key = _preflight_text(clean)
    if not clean:
        return clean
    for match in re.finditer(
        r"\b(?:depleted\s+)?oil\s+and\s+gas\s+reservoirs?\b",
        str(parent_context or ""),
        flags=re.IGNORECASE,
    ):
        phrase = normalize_space(match.group(0))
        if key in {
            "gas reservoir",
            "gas reservoirs",
            "oil reservoir",
            "oil reservoirs",
            "depleted oil",
            "depleted oil reservoir",
            "depleted oil reservoirs",
        }:
            return phrase
    return clean


def _academic_contextualize_component_with_parent_core(
    component: str,
    parent_context: str,
) -> str:
    """Preserve a parent target/carrier when an extracted component is a site.

    This prevents fallback decomposition from turning "CO2 storage in depleted
    oil and gas reservoirs" into a naked "gas reservoirs" query.  The rule is
    general in shape: a location/platform component inherits the parent carrier
    only when the parent declares a carrier/process scope and the component
    itself lacks it.
    """

    clean = _academic_restore_fragmented_component_from_parent(
        normalize_space(component),
        parent_context,
    )
    if not clean:
        return clean
    if (
        _parent_context_has_carbon_storage_scope(parent_context)
        and not _component_has_carbon_storage_context(clean)
    ):
        if _component_is_geologic_storage_site(clean):
            return normalize_space(f"CO2 storage in {clean}")
        if _component_is_biologic_carbon_sink(clean):
            return normalize_space(f"carbon sequestration in {clean}")
    return clean


def _academic_parent_query_core_context(
    scientific_object: str,
    parent_context: str,
) -> list[str]:
    terms: list[str] = []
    if _parent_context_has_carbon_storage_scope(parent_context):
        if _component_is_geologic_storage_site(scientific_object):
            terms.extend(["CO2 storage", "geologic carbon sequestration"])
        elif _component_is_biologic_carbon_sink(scientific_object):
            terms.extend(["carbon sequestration", "carbon dioxide removal"])
        elif re.search(r"\b(?:co2|carbon)\b", _preflight_text(scientific_object)):
            terms.append("carbon dioxide sequestration")
    return list(dict.fromkeys(normalize_space(term) for term in terms if normalize_space(term)))


# Discipline-driven readout/mechanism profiles.  The source taxonomy mirrors
# paperseek_core.disciplines.OPENALEX_FIELDS, but deliberately excludes entries
# whose domain is Social Sciences (Arts & Humanities, Business, Decision
# Sciences, Economics/Finance, Psychology, Social Sciences).  The goal is not
# to infer scientific truth from the discipline label; it is to stop fallback
# decomposition from filling every SH with the same generic metric/template.
_NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "discipline_ids": ("11", "34"),
        "label": "Agricultural and Biological Sciences / Veterinary",
        "axis": "agricultural_biological_systems",
        "patterns": (
            r"\bagricultur", r"\bagronom", r"\bcrop", r"\bplant", r"\bsoil\b",
            r"\bforest", r"\bhorticultur", r"\bfisher", r"\blivestock",
            r"\banimal", r"\bveterinary", r"\bbiodiversity", r"\becology",
            r"\becosystem", r"\bmarine\b", r"\bfreshwater\b",
        ),
        "readouts": (
            "biomass yield", "crop yield", "growth rate", "species richness",
            "biodiversity index", "soil organic carbon", "nutrient uptake",
            "photosynthetic rate", "survival rate", "disease incidence",
        ),
        "mechanism": (
            "growth, nutrient cycling, ecological interaction, disease pressure, "
            "and environmental stress-response pathways"
        ),
    },
    {
        "discipline_ids": ("13",),
        "label": "Biochemistry, Genetics and Molecular Biology",
        "axis": "biochemistry_molecular_biology",
        "patterns": (
            r"\bprotein", r"\benzyme", r"\bgene\b", r"\bgenetic", r"\bgenom",
            r"\btranscript", r"\brna\b", r"\bdna\b", r"\bchromosome",
            r"\bmutation", r"\bvariant", r"\breceptor", r"\bpathway",
            r"\bmetabol", r"\bcell\s+line", r"\bexpression\b",
        ),
        "readouts": (
            "enzyme activity", "expression level", "protein abundance",
            "binding affinity", "mutation frequency", "pathway activity",
            "metabolite concentration", "fluorescence intensity",
            "copy number", "fold change",
        ),
        "mechanism": (
            "molecular binding, gene regulation, enzymatic activity, pathway "
            "state, and cellular response"
        ),
    },
    {
        "discipline_ids": ("15",),
        "label": "Chemical Engineering",
        "axis": "chemical_engineering_process",
        "patterns": (
            r"\breactor", r"\bprocess\b", r"\bseparation", r"\bmembrane",
            r"\badsorption", r"\babsorption", r"\bdistillation",
            r"\bthermodynamic", r"\bmass\s+transfer", r"\bheat\s+transfer",
            r"\bunit\s+operation", r"\bscale[-\s]?up", r"\bthroughput",
        ),
        "readouts": (
            "conversion rate", "selectivity", "reaction yield",
            "mass transfer coefficient", "separation factor",
            "energy consumption", "pressure drop", "throughput",
            "purity", "process yield",
        ),
        "mechanism": (
            "transport, reaction kinetics, phase equilibrium, separation "
            "performance, and process-scale operating constraints"
        ),
    },
    {
        "discipline_ids": ("16",),
        "label": "Chemistry",
        "axis": "chemistry_reaction_or_characterization",
        "patterns": (
            r"\bmolecule", r"\bcompound", r"\breaction", r"\bcataly",
            r"\bligand", r"\bcrystal", r"\belectrochem", r"\bspectroscop",
            r"\bchromatograph", r"\bsynthesis", r"\bredox\b",
            r"\bphotochem", r"\bpolymer", r"\bsolvent",
        ),
        "readouts": (
            "reaction yield", "selectivity", "rate constant",
            "binding affinity", "faradaic efficiency", "overpotential",
            "absorbance", "crystallinity", "purity", "conductivity",
        ),
        "mechanism": (
            "reaction kinetics, thermodynamics, molecular structure, charge "
            "transfer, and analytical characterization"
        ),
    },
    {
        "discipline_ids": ("17",),
        "label": "Computer Science",
        "axis": "computer_science_model_or_system",
        "patterns": (
            r"\balgorithm", r"\bcomputational\s+model", r"\bmachine\s+learning",
            r"\bdeep\s+learning", r"\bneural\s+network", r"\bclassifier",
            r"\bdataset", r"\bsoftware", r"\brobot", r"\bcomputer\s+vision",
            r"\binformation\s+retrieval", r"\bdistributed", r"\bdatabase",
            r"\bcyber", r"\btelecommunication",
        ),
        "readouts": (
            "accuracy", "F1 score", "AUC", "RMSE", "classification error",
            "latency", "throughput", "memory usage", "calibration error",
            "robustness score",
        ),
        "mechanism": (
            "model architecture, data representation, optimization, calibration, "
            "runtime behavior, and generalization error"
        ),
    },
    {
        "discipline_ids": ("19",),
        "label": "Earth and Planetary Sciences",
        "axis": "earth_planetary_system",
        "patterns": (
            r"\bgeolog", r"\bgeochem", r"\bgeophys", r"\bmineral",
            r"\brock\b", r"\bsediment", r"\bbasin", r"\baquifer",
            r"\breservoir", r"\bseismic", r"\bmeteorolog", r"\batmospher",
            r"\boceanograph", r"\bremote\s+sensing", r"\bplanet",
            r"\bsubsurface", r"\bpermeability", r"\bporosity",
        ),
        "readouts": (
            "permeability", "porosity", "concentration", "flux",
            "isotopic ratio", "seismic velocity", "subsidence rate",
            "temperature anomaly", "mass balance", "uncertainty interval",
        ),
        "mechanism": (
            "transport, geochemical reaction, structural setting, fluid flow, "
            "remote-sensing observation, and temporal variability"
        ),
    },
    {
        "discipline_ids": ("21",),
        "label": "Energy",
        "axis": "energy_system_or_device",
        "patterns": (
            r"\benergy\s+(?:storage|conversion|system|technology|fuel|resource|efficien)",
            r"\bbatter", r"\bfuel\s+cell", r"\bphotovoltaic",
            r"\bsolar\b", r"\bwind\b", r"\bturbine", r"\bgrid\b",
            r"\belectroly[sz]er", r"\bnuclear\s+(?:energy|reactor|fuel)",
            r"\bcombustion", r"\benergy\s+conversion", r"\bpower\s+system",
        ),
        "readouts": (
            "conversion efficiency", "round-trip efficiency", "energy density",
            "power density", "capacity factor", "cycle life",
            "levelized cost of energy", "emissions intensity",
            "curtailment rate", "discharge duration",
        ),
        "mechanism": (
            "energy conversion, storage losses, dispatch constraints, degradation, "
            "resource availability, and system integration"
        ),
    },
    {
        "discipline_ids": ("22",),
        "label": "Engineering",
        "axis": "engineering_device_or_infrastructure",
        "patterns": (
            r"\bdevice", r"\bsensor", r"\bcontrol\s+system", r"\bstructure",
            r"\bbridge\b", r"\bmanufactur", r"\brobot", r"\binstrument",
            r"\bmechanical", r"\belectrical", r"\bcivil\b", r"\baerospace",
            r"\bbiomedical", r"\btransportation", r"\bautomation",
        ),
        "readouts": (
            "failure rate", "mean time between failures", "tracking error",
            "control error", "response time", "precision", "tensile strength",
            "vibration amplitude", "throughput", "defect density",
        ),
        "mechanism": (
            "design parameters, control dynamics, mechanical stress, reliability, "
            "manufacturing tolerance, and operating environment"
        ),
    },
    {
        "discipline_ids": ("23",),
        "label": "Environmental Science",
        "axis": "environmental_system_or_pollutant",
        "patterns": (
            r"\benvironment", r"\bpollut", r"\bwater\s+quality",
            r"\bair\s+quality", r"\bwastewater", r"\bremediation",
            r"\bcontamin", r"\becosystem", r"\bbiodiversity",
            r"\bwater\s+resource", r"\blimnolog", r"\btoxicity",
        ),
        "readouts": (
            "pollutant concentration", "removal efficiency",
            "PM2.5 concentration", "toxicity", "biodiversity index",
        ),
        "mechanism": (
            "source emission, transport, exposure, degradation or removal, "
            "and ecological response"
        ),
    },
    {
        "discipline_ids": ("24",),
        "label": "Immunology and Microbiology",
        "axis": "immunology_microbiology",
        "patterns": (
            r"\bimmune", r"\bimmun", r"\bpathogen", r"\bvirus", r"\bviral",
            r"\bbacteria", r"\bbacterial", r"\bmicrobi", r"\bvaccine",
            r"\bantibody", r"\bt\s*cell", r"\bb\s*cell", r"\bcytokine",
            r"\binfect", r"\bparasite", r"\bfung", r"\bvirology",
        ),
        "readouts": (
            "viral load", "bacterial load", "CFU count", "antibody titer",
            "neutralization titer", "cytokine concentration",
            "infection rate", "immune cell count", "pathogen clearance rate",
            "growth inhibition",
        ),
        "mechanism": (
            "pathogen replication, host immune activation, antibody or cellular "
            "response, microbial growth, and clearance dynamics"
        ),
    },
    {
        "discipline_ids": ("25",),
        "label": "Materials Science",
        "axis": "materials_structure_property",
        "patterns": (
            r"\bmaterial", r"\balloy", r"\bpolymer", r"\bceramic",
            r"\bcomposite", r"\bnanomaterial", r"\bquantum\s+dot",
            r"\bcoating", r"\bfilm\b", r"\belectrode", r"\bcathode",
            r"\banode", r"\bmetallurg", r"\bcrystal", r"\bporosity",
            r"\bgrain\s+size", r"\bdefect", r"\bmo[sx]2\b",
        ),
        "readouts": (
            "particle size", "size distribution", "quantum yield",
            "photoluminescence intensity", "tensile strength",
            "fracture toughness", "conductivity", "porosity",
            "defect density", "capacity retention",
        ),
        "mechanism": (
            "composition, microstructure, defects, interface state, processing "
            "history, and structure-property relationships"
        ),
    },
    {
        "discipline_ids": ("26",),
        "label": "Mathematics",
        "axis": "mathematics_formal_result",
        "patterns": (
            r"\btheorem", r"\bproof", r"\blemma", r"\bcorollary",
            r"\bconjecture", r"\bgraph\b", r"\boperator", r"\bequation",
            r"\bbound\b", r"\boptimization", r"\bstochastic", r"\btopology",
            r"\bgeometry", r"\balgebra", r"\bprobability",
        ),
        "readouts": (
            "proof validity", "error bound", "convergence rate",
            "spectral gap", "regret bound", "sample complexity",
            "approximation ratio", "stability condition",
            "counterexample condition", "posterior interval",
        ),
        "mechanism": (
            "assumptions, definitions, lemmas, limiting cases, proof structure, "
            "and counterexample boundary"
        ),
    },
    {
        "discipline_ids": ("27", "29", "35", "36"),
        "label": "Medicine / Nursing / Dentistry / Health Professions",
        "axis": "health_clinical_or_diagnostic",
        "patterns": (
            r"\bpatient", r"\bclinical", r"\bdisease", r"\bdiagnos",
            r"\btherapy", r"\btreatment", r"\bsurgery", r"\bcancer",
            r"\boncology", r"\bcardiovascular", r"\bneurology",
            r"\bradiology", r"\bpathology", r"\bpediatric",
            r"\brehabilitation", r"\bnursing", r"\bdent", r"\boral\b",
            r"\bimplant", r"\bsymptom", r"\bmortality",
        ),
        "readouts": (
            "mortality", "survival rate", "hazard ratio", "response rate",
            "symptom score", "adverse event rate", "incidence",
            "sensitivity", "specificity", "quality-of-life score",
        ),
        "mechanism": (
            "disease pathway, diagnostic signal, treatment exposure, clinical "
            "response, adverse events, and patient-level heterogeneity"
        ),
    },
    {
        "discipline_ids": ("28",),
        "label": "Neuroscience",
        "axis": "neuroscience_circuit_or_behavior",
        "patterns": (
            r"\bneuron", r"\bneural", r"\bbrain", r"\bsynap", r"\bcircuit",
            r"\bhippocamp", r"\bdentate", r"\bcortex", r"\bmemory",
            r"\brecall", r"\bEEG\b", r"\beeg\b", r"\bfMRI\b", r"\bfmri\b",
            r"\boptogen", r"\bstimulation", r"\bspike", r"\bfiring",
        ),
        "readouts": (
            "firing rate", "spike rate", "synaptic plasticity index",
            "BOLD signal", "EEG power", "recall accuracy",
            "reaction time", "behavioral response accuracy",
            "connectivity strength", "calcium signal",
        ),
        "mechanism": (
            "neural encoding, circuit activity, synaptic plasticity, stimulation "
            "response, and behavioral readout"
        ),
    },
    {
        "discipline_ids": ("30",),
        "label": "Pharmacology, Toxicology and Pharmaceutics",
        "axis": "pharmacology_toxicology_pharmaceutics",
        "patterns": (
            r"\bdrug", r"\bcompound", r"\bdose", r"\bpharmacokinetic",
            r"\bpharmacodynamic", r"\bformulation", r"\btoxicity",
            r"\btoxicolog", r"\btherapeutic", r"\bpotency", r"\bbioavailability",
            r"\bclearance", r"\bcmax\b", r"\bauc\b", r"\bhalf[-\s]?life",
        ),
        "readouts": (
            "IC50", "EC50", "Cmax", "AUC", "clearance", "half-life",
            "bioavailability", "toxicity", "potency", "adverse event rate",
        ),
        "mechanism": (
            "dose exposure, absorption, distribution, metabolism, elimination, "
            "target engagement, and toxic response"
        ),
    },
    {
        "discipline_ids": ("31",),
        "label": "Physics and Astronomy — astronomy/cosmology",
        "axis": "astronomy_cosmology_observation",
        "patterns": (
            r"\bgalax", r"\bstar\b", r"\bstellar", r"\bcosmolog",
            r"\bastronom", r"\bredshift", r"\bdark\s+energy",
            r"\bbao\b", r"\bsupernova", r"\bluminosity", r"\bexoplanet",
            r"\bplanetary", r"\bcosmic", r"\btelescope", r"\bsurvey\b",
        ),
        "readouts": (
            "redshift", "luminosity", "posterior interval",
            "spectral line intensity", "distance modulus",
            "parameter constraint", "signal-to-noise",
            "calibration error", "uncertainty interval", "model evidence",
        ),
        "mechanism": (
            "astronomical observation, calibration, survey selection, physical "
            "model constraint, and uncertainty propagation"
        ),
    },
    {
        "discipline_ids": ("31",),
        "label": "Physics and Astronomy — physical measurement/theory",
        "axis": "physics_measurement_or_theory",
        "patterns": (
            r"\bphysics", r"\bquantum", r"\bplasma", r"\bparticle",
            r"\bphoton", r"\boptical", r"\blaser", r"\bspectra",
            r"\bspectral", r"\bcondensed\s+matter", r"\bnuclear",
            r"\bmagnetic", r"\bcoherence", r"\bcross\s+section",
        ),
        "readouts": (
            "cross section", "spectral line intensity", "energy resolution",
            "magnetic field strength", "coherence time", "signal-to-noise",
            "redshift", "luminosity", "posterior interval", "error bound",
        ),
        "mechanism": (
            "physical interaction, field dynamics, measurement response, model "
            "constraint, uncertainty, and limiting-case behavior"
        ),
    },
)

_DISCIPLINE_SCOPE_PROFILE_BY_AXIS = {
    str(profile["axis"]): profile for profile in _NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES
}
_DISCIPLINE_READOUT_MARKERS = frozenset(
    readout
    for profile in _NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES
    for readout in profile.get("readouts", ())
)


def _academic_reframed_expected_mechanism(
    *,
    scientific_object: str,
    academic_objective: str,
    research_brief: str,
    outcome: str,
) -> str:
    parent_context = _scope_text(academic_objective, research_brief)
    local_context = _scope_text(scientific_object, outcome)
    axes = _contextual_readout_axes(
        local_context=local_context,
        parent_context=parent_context,
    )
    local_key = _preflight_text(local_context)
    if _parent_context_has_carbon_storage_scope(parent_context):
        if _component_is_geologic_storage_site(scientific_object):
            return "CO2 injection, migration, trapping, leakage control, and storage permanence"
        if _component_is_biologic_carbon_sink(scientific_object):
            return "carbon uptake, biomass or soil carbon accumulation, disturbance, and re-release"
        return "carbon dioxide capture, transfer, retention, leakage, and lifecycle accounting"
    if "economic_cost" in axes:
        return "capital, operating, maintenance, monitoring, and lifecycle cost drivers"
    if "energy_storage_efficiency" in axes:
        return "charge-discharge losses, conversion efficiency, degradation, and operational dispatch"
    if "durability_degradation" in axes:
        return "material degradation, cycling stress, aging, and capacity retention"
    for axis in axes:
        profile = _DISCIPLINE_SCOPE_PROFILE_BY_AXIS.get(axis)
        if isinstance(profile, dict) and profile.get("mechanism"):
            return str(profile.get("mechanism") or "")
    if "safety_or_adverse" in axes:
        return "failure modes, exposure pathways, adverse events, and risk controls"
    if "measurement_or_model_accuracy" in axes:
        return "measurement protocol, calibration, error sources, and validation against reference data"
    if "biological_function" in axes:
        return "biological activity, viability, expression state, and functional response"
    if "manufacturing_or_material_quality" in axes:
        return "process parameters, material structure, defect formation, and quality attributes"
    if local_key:
        return f"specific mechanism linking {scientific_object} to {outcome}"
    return "specific mechanism linking the declared object to the declared measurable outcome"


def _academic_is_template_mechanism_placeholder(value: Any) -> bool:
    normalized = _preflight_text(value)
    return bool(
        "expected mechanism under" in normalized
        or "measurement material population process" in normalized
        or "implementation constraints" in normalized
        or normalized
        in {
            "expected mechanism",
            "specific mechanism",
            "mechanism under constraints",
            "mechanism process",
        }
    )


def academic_reframed_candidate_components(
    *,
    original_objective: str,
    academic_objective: str = "",
    research_brief: str = "",
    max_subhypotheses: int = 6,
) -> list[str]:
    """Extract candidate scientific objects/strategies from the user's text.

    This fallback is intentionally domain-neutral.  It only recovers concrete
    user-supplied phrases so a failed LLM call does not make the academic
    objective's leading constraint phrase (for example "Under uncertainty...")
    become the SH object.
    """

    text = " ".join(
        part
        for part in (
            str(academic_objective or ""),
            str(original_objective or ""),
            str(research_brief or ""),
        )
        if part.strip()
    )
    parenthetical_segments: list[str] = []
    for match in re.finditer(r"\(([^()]{4,220})\)", text):
        inner = normalize_space(match.group(1))
        inner = re.sub(r"^(?:e\.?g\.?|i\.?e\.?|for example)\s*,?\s*", "", inner, flags=re.IGNORECASE)
        if inner:
            parenthetical_segments.extend(_academic_split_candidate_alternatives(inner))
    text_without_parentheticals = re.sub(r"\([^)]*\)", " ", text)
    raw_segments = parenthetical_segments + re.split(
        r"(?:[.;:?!\n]+|,\s+|\bincluding\b|\bsuch\s+as\b|\bas\s+well\s+as\b|\balso\s+that\b|\band\s+also\s+that\b|\band\s+that\b)",
        text_without_parentheticals,
        flags=re.IGNORECASE,
    )
    components: list[str] = []
    for segment in raw_segments:
        clean = normalize_space(segment)
        clean = re.sub(r"^[\"'“”‘’\s]+|[\"'“”‘’\s]+$", "", clean)
        clean = re.sub(r"\([^)]*\)", " ", clean)
        clean = re.sub(r"^(?:e\.?g\.?|i\.?e\.?|for example)\s*,?\s*", "", clean, flags=re.IGNORECASE)
        clean = _ACADEMIC_HEURISTIC_SEGMENT_PREFIX.sub("", clean).strip(" ,.;:-")
        clean = re.sub(r"^(?:and|or|with|while)\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^(?:how\s+can\s+we\s+|one\s+of\s+the\s+challenges\s+of\s+)", "", clean, flags=re.IGNORECASE)
        clean = re.sub(
            r"^(?:technologists?\s+(?:are\s+)?(?:also\s+)?experimenting\s+with\s+|"
            r"scientists?\s+(?:are\s+)?(?:also\s+)?(?:developing|testing)\s+|"
            r"but\s+|while\s+also\s+investigating\s+(?:the\s+role\s+of\s+)?)",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"\b(?:among others?|among other systems?|etc\.?)$", "", clean, flags=re.IGNORECASE)
        clean = normalize_space(clean)
        lowered = clean.lower()
        if len(clean) < 6:
            continue
        if any(marker in lowered for marker in (
            "better manage", "how can", "challenge of managing", "potential solutions",
            "future of", "challenges and opportunities", "opportunities in",
            "other storage methods", "research needs", "urgent research needs",
        )):
            continue
        if lowered.startswith(("under ", "which ", "what ", "why ", "whether ", "the challenge", "one of the challenges")):
            continue
        token_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", clean))
        if (
            _SCIENTIFIC_OBJECT_RESEARCH_ACTION_RE.search(clean)
            or lowered.startswith((
                "environmental impact of",
                "economic impact of",
                "cost of",
                "focus on",
                "a focus on",
                "using standardized metrics",
                "standardized metrics",
                "potential for adverse",
                "adverse effects",
            ))
            or lowered in {"permanence", "stability", "efficacy", "effectiveness"}
            or (
                token_count <= 5
                and (
                    _preflight_has_concrete_readout_marker(clean)
                    or _preflight_is_broad_outcome_phrase(clean)
                    or re.search(
                        r"\b(?:rate|rates|index|score|capacity|efficiency|"
                        r"emissions?|footprint|health|risk|cost)\b",
                        lowered,
                    )
                )
            )
        ):
            continue
        if lowered in {"data", "reliable data", "potential solutions", "the issue"}:
            continue
        if token_count > 14:
            continue
        clean = _academic_contextualize_component_with_parent_core(clean, text)
        if clean not in components:
            components.append(clean)
        if len(components) >= max_subhypotheses:
            break
    return components[:max_subhypotheses]


_ROUND_TRIP_EFFICIENCY_READOUT_KEYS = frozenset({
    "round trip efficiency",
    "roundtrip efficiency",
    "round trip efficiencies",
    "roundtrip efficiencies",
})

_ROUND_TRIP_EFFICIENCY_RE = re.compile(
    r"\b(?:round[-\s]?trip|roundtrip)\s+efficienc(?:y|ies)\b"
    r"|\befficienc(?:y|ies)\s+(?:round[-\s]?trip|roundtrip)\b",
    flags=re.IGNORECASE,
)


def _scope_text(*parts: Any) -> str:
    flattened: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            flattened.extend(str(value) for value in part.values())
        elif isinstance(part, (list, tuple, set)):
            flattened.extend(str(value) for value in part)
        elif part is not None:
            flattened.append(str(part))
    return normalize_space(" ".join(value for value in flattened if value))


def _scope_has_any(context: str, patterns: Iterable[str]) -> bool:
    normalized = _preflight_text(context)
    if not normalized:
        return False
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)


def _is_round_trip_efficiency_readout(value: Any) -> bool:
    key = _preflight_text(value)
    return (
        key in _ROUND_TRIP_EFFICIENCY_READOUT_KEYS
        or bool(_ROUND_TRIP_EFFICIENCY_RE.search(str(value or "")))
    )


def _round_trip_efficiency_supported_by_scope(
    *,
    local_context: str,
    parent_context: str = "",
) -> bool:
    """Return True only when round-trip efficiency is a scope-valid readout.

    `storage` and `efficiency` are far too broad by themselves: carbon
    sequestration, sample storage, data storage, and biological retention tasks
    all contain those words.  Round-trip efficiency is reserved for energy
    storage or electrochemical charge/discharge contexts.
    """

    local = _preflight_text(local_context)
    parent = _preflight_text(parent_context)
    combined = _preflight_text(" ".join([local, parent]))
    if not combined:
        return False
    explicit_charge_discharge_scope = _scope_has_any(combined, (
        r"\bcharge\s+discharge\b",
        r"\bcharge\s+and\s+discharge\b",
        r"\bcharge\s+discharge\s+loss",
        r"\bcoulombic\s+efficien",
    ))
    energy_device_scope = _scope_has_any(local, (
        r"\bbatter(?:y|ies)\b",
        r"\blithium\s+ion\b",
        r"\bli\s+ion\b",
        r"\bflow\s+batter",
        r"\bredox\s+flow\b",
        r"\belectrochemical\s+(?:cell|storage|system|device)\b",
        r"\bsupercapacitor\b",
        r"\bgrid\s+energy\s+storage\b",
        r"\belectricity\s+storage\b",
        r"\benergy\s+storage\s+(?:technology|system|device|method|methods)\b",
        r"\bpumped\s+hydro\b",
        r"\bcompressed\s+air\s+energy\s+storage\b",
        r"\bliquid\s+air\s+energy\s+storage\b",
    ))
    explicit_round_trip = _scope_has_any(combined, (
        r"\bround\s+trip\b",
        r"\broundtrip\b",
    ))
    if explicit_charge_discharge_scope or energy_device_scope:
        return True
    if explicit_round_trip:
        return False
    return bool(
        _scope_has_any(local, (r"\benergy\s+storage\b", r"\bgrid\s+storage\b"))
        and _scope_has_any(combined, (r"\befficien", r"\bperformance\b", r"\bloss(?:es)?\b"))
    )


def _contextual_readout_axes(
    *,
    local_context: str,
    parent_context: str = "",
) -> list[str]:
    """Classify SH-local language into measurement/readout axes."""

    local = _preflight_text(local_context)
    parent = _preflight_text(parent_context)
    combined = _preflight_text(" ".join([local, parent]))
    axes: list[str] = []

    def add(axis: str) -> None:
        if axis not in axes:
            axes.append(axis)

    local_carbon_storage = _scope_has_any(local, (
        r"\bsequestration\b",
        r"\bcarbon\s+dioxide\s+removal\b",
        r"\bcarbon\s+removal\b",
        r"\bcdr\b",
        r"\bco2\s+(?:storage|injection|capture|removal)\b",
        r"\bgeologic(?:al)?\s+(?:storage|carbon|sequestration)\b",
        r"\bsaline\s+aquifer",
        r"\bdepleted\s+(?:oil\s+and\s+gas\s+)?reservoir",
        r"\b(?:gas|oil)\s+reservoir",
        r"\bleakage\b",
        r"\bpermanence\b",
        r"\bstorage\s+capacity\b",
        r"\bcarbon\s+stock\b",
        r"\bsoil\s+carbon\b",
        r"\bbiochar\b",
        r"\bafforestation\b",
        r"\breforestation\b",
    ))
    parent_carbon_storage = _scope_has_any(parent, (
        r"\bsequestration\b",
        r"\bcarbon\s+dioxide\b",
        r"\bcarbon\s+capture\b",
        r"\bco2\b",
        r"\bcarbon\s+removal\b",
    ))
    local_carbon_storage_anchor = _scope_has_any(local, (
        r"\baquifer",
        r"\breservoir",
        r"\bformation",
        r"\bforest",
        r"\bsoil",
        r"\bwetland",
        r"\bbiologic(?:al)?\s+system",
    ))
    local_biologic_carbon_sink = _component_is_biologic_carbon_sink(local)
    # A lifecycle/environmental-impact SH needs impact metrics even when its
    # subject is also a carbon-storage system.  Classify the declared local
    # measurement objective first; this rule is independent of material,
    # species, or intervention domain.
    if _scope_has_any(local, (
        r"\blife\s*[- ]?cycle\b",
        r"\blifecycle\b",
        r"\benvironmental\s+impact\b",
        r"\bcarbon\s+footprint\b",
        r"\bgreenhouse\s+gas\b",
        r"\bwater\s+(?:use|usage|footprint)\b",
    )):
        add("lifecycle_environmental_impact")
    if parent_carbon_storage and local_biologic_carbon_sink:
        add("biologic_carbon_sequestration")
    if local_carbon_storage or (parent_carbon_storage and local_carbon_storage_anchor):
        add("carbon_storage_permanence")

    if _scope_has_any(local, (
        r"\bcost\b",
        r"\bcosts\b",
        r"\beconomic",
        r"\bexpense",
        r"\bmaintenance\b",
        r"\bcapex\b",
        r"\bopex\b",
        r"\bleveli[sz]ed\b",
        r"\blcos\b",
        r"\bafford",
        r"\bcost\s+per\s+(?:ton|tonne)",
        r"\babatement\s+cost\b",
    )):
        add("economic_cost")

    if _scope_has_any(local, (
        r"\breliab",
        r"\bresilien",
        r"\bcurtailment\b",
        r"\bloss\s+of\s+load\b",
        r"\bfirm\s+capacity\b",
        r"\bcapacity\s+value\b",
        r"\bdispatch",
        r"\bgrid\s+stability\b",
        r"\brenewable\s+supply\b",
        r"\bdemand\s+matching\b",
    )):
        add("grid_reliability")

    if _scope_has_any(local, (
        r"\bcycle\s+life\b",
        r"\blifetime\b",
        r"\bdurab",
        r"\bdegrad",
        r"\bcapacity\s+retention\b",
        r"\bcapacity\s+fade\b",
        r"\bageing\b",
        r"\baging\b",
        r"\bstability\b",
    )):
        add("durability_degradation")

    if _scope_has_any(local, (
        r"\bsafety\b",
        r"\badverse\b",
        r"\brisk\b",
        r"\bfailure\b",
        r"\bhazard\b",
        r"\btoxicity\b",
        r"\bthermal\s+runaway\b",
        r"\bincident\b",
        r"\bleakage\b",
        r"\bside\s+effect\b",
        r"\bharm\b",
    )):
        add("safety_or_adverse")

    if _round_trip_efficiency_supported_by_scope(
        local_context=local_context,
        parent_context=parent_context,
    ):
        add("energy_storage_efficiency")
    elif _scope_has_any(local, (r"\befficien", r"\bperformance\b")):
        if parent_carbon_storage or _scope_has_any(local, (r"\bcapture\b", r"\bsequestration\b", r"\bco2\b")):
            add("carbon_capture_efficiency")
        else:
            add("general_effect_size")

    if _scope_has_any(local, (
        r"\baccuracy\b",
        r"\bprecision\b",
        r"\bsensitivity\b",
        r"\bspecificity\b",
        r"\bauc\b",
        r"\brmse\b",
        r"\berror\b",
        r"\bcalibration\b",
        r"\bfidelity\b",
        r"\bsignal\b",
        r"\bdetection\b",
        r"\bclassification\b",
    )):
        add("measurement_or_model_accuracy")

    if _scope_has_any(local, (
        r"\bviability\b",
        r"\bmetabolic\b",
        r"\bexpression\b",
        r"\bsurvival\b",
        r"\bgrowth\b",
        r"\bpotency\b",
        r"\bcell\b",
    )):
        add("biological_function")

    if _scope_has_any(local, (
        r"\byield\b",
        r"\bpurity\b",
        r"\bporosity\b",
        r"\bdefect\b",
        r"\bparticle\s+size\b",
        r"\bconductivity\b",
        r"\btensile\b",
        r"\bfracture\b",
        r"\bstiffness\b",
        r"\bmanufactur",
        r"\bsynthesi[sz]",
        r"\bpreparation\b",
    )):
        add("manufacturing_or_material_quality")

    for profile in _NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES:
        if _scope_has_any(local, profile.get("patterns", ())):
            add(str(profile.get("axis") or ""))

    if not axes:
        if parent_carbon_storage and local_carbon_storage_anchor:
            add("carbon_storage_permanence")
        elif _round_trip_efficiency_supported_by_scope(
            local_context=local_context,
            parent_context=parent_context,
        ):
            add("energy_storage_efficiency")
    axis_priority = {
        "lifecycle_environmental_impact": 1,
        "economic_cost": 1,
        "grid_reliability": 2,
        "durability_degradation": 3,
        "safety_or_adverse": 4,
        "energy_storage_efficiency": 5,
        "biologic_carbon_sequestration": 6,
        "carbon_storage_permanence": 7,
        "carbon_capture_efficiency": 8,
        "measurement_or_model_accuracy": 9,
        "biological_function": 10,
        "manufacturing_or_material_quality": 11,
        "general_effect_size": 12,
        "pharmacology_toxicology_pharmaceutics": 3,
        "health_clinical_or_diagnostic": 4,
        "materials_structure_property": 7,
        "chemical_engineering_process": 8,
        "chemistry_reaction_or_characterization": 9,
        "astronomy_cosmology_observation": 8,
        "physics_measurement_or_theory": 9,
        "earth_planetary_system": 10,
    }
    for offset, profile in enumerate(_NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES, 20):
        axis_priority.setdefault(str(profile.get("axis") or ""), offset)
    return sorted(axes, key=lambda axis: axis_priority.get(axis, 99))


_READOUTS_BY_SCOPE_AXIS: dict[str, tuple[str, ...]] = {
    "lifecycle_environmental_impact": (
        "carbon footprint",
        "greenhouse gas emissions",
        "water usage",
        "land-use impact",
    ),
    "energy_storage_efficiency": (
        "round-trip efficiency",
        "energy density",
        "discharge duration",
    ),
    "carbon_storage_permanence": (
        "CO2 storage capacity",
        "leakage rate",
        "carbon retention",
        "net CO2 removal rate",
    ),
    "biologic_carbon_sequestration": (
        "carbon stock change",
        "net CO2 removal rate",
        "carbon retention",
        "ecosystem health index",
    ),
    "carbon_capture_efficiency": (
        "CO2 capture efficiency",
        "net CO2 removal rate",
        "leakage rate",
    ),
    "economic_cost": (
        "levelized cost of storage",
        "cost per tonne CO2 stored",
        "capital cost",
        "operating cost",
    ),
    "grid_reliability": (
        "loss of load probability",
        "curtailment rate",
        "capacity value",
        "firm capacity",
    ),
    "durability_degradation": (
        "cycle life",
        "capacity retention",
        "degradation rate",
    ),
    "safety_or_adverse": (
        "failure rate",
        "incident rate",
        "adverse event rate",
        "toxicity",
    ),
    "measurement_or_model_accuracy": (
        "accuracy",
        "RMSE",
        "calibration error",
        "fidelity score",
    ),
    "biological_function": (
        "viability",
        "metabolic activity",
        "expression level",
        "growth inhibition",
    ),
    "manufacturing_or_material_quality": (
        "yield",
        "purity",
        "defect density",
        "conductivity",
    ),
    "general_effect_size": (
        "effect size",
        "response rate",
        "change score",
    ),
}
_READOUTS_BY_SCOPE_AXIS.update({
    str(profile["axis"]): tuple(str(value) for value in profile.get("readouts", ()))
    for profile in _NON_SOCIAL_DISCIPLINE_SCOPE_PROFILES
})


def _contextual_readouts_for_scope(
    *,
    local_context: str,
    parent_context: str = "",
    existing_readouts: Any = None,
    limit: int = 3,
    default_effect_size: bool = True,
) -> tuple[list[str], list[str]]:
    axes = _contextual_readout_axes(
        local_context=local_context,
        parent_context=parent_context,
    )
    readouts: list[str] = []

    def add(value: Any) -> None:
        clean = normalize_space(str(value or ""))
        if (
            clean
            and clean not in readouts
            and _preflight_has_concrete_readout_marker(clean)
        ):
            readouts.append(clean)

    for axis in axes:
        for readout in _READOUTS_BY_SCOPE_AXIS.get(axis, ()):
            add(readout)
            if len(readouts) >= max(1, int(limit)):
                return readouts[: max(1, int(limit))], axes

    for readout in normalize_text_list(existing_readouts):
        if _is_round_trip_efficiency_readout(readout) and not _round_trip_efficiency_supported_by_scope(
            local_context=local_context,
            parent_context=parent_context,
        ):
            continue
        add(readout)
        if len(readouts) >= max(1, int(limit)):
            return readouts[: max(1, int(limit))], axes

    if not readouts and default_effect_size:
        add("effect size")
    return readouts[: max(1, int(limit))], axes


def _repair_dependent_variables_for_scope(
    *,
    dependent_variables: list[str],
    local_context: str,
    parent_context: str = "",
    limit: int = 3,
) -> tuple[list[str], dict[str, Any]]:
    """Demote globally broadcast readouts that do not fit the SH-local scope."""

    existing = normalize_text_list(dependent_variables)
    has_round_trip = any(_is_round_trip_efficiency_readout(value) for value in existing)
    round_trip_supported = _round_trip_efficiency_supported_by_scope(
        local_context=local_context,
        parent_context=parent_context,
    )
    inferred, axes = _contextual_readouts_for_scope(
        local_context=local_context,
        parent_context=parent_context,
        existing_readouts=existing,
        limit=max(limit, len(existing), 3),
    )
    repaired = list(existing)
    reason = ""
    if has_round_trip and not round_trip_supported:
        reason = "round_trip_efficiency_scope_mismatch"
        repaired = [
            value for value in inferred
            if not _is_round_trip_efficiency_readout(value)
        ]
        for value in existing:
            if not _is_round_trip_efficiency_readout(value) and value not in repaired:
                repaired.append(value)
    elif not _preflight_concrete_readouts(existing):
        reason = "missing_or_generic_dependent_variable"
        repaired = inferred

    if not repaired:
        repaired = inferred
    repaired = [
        value for value in repaired
        if value and _preflight_has_concrete_readout_marker(value)
    ]
    if not repaired:
        repaired = ["effect size"]
    repaired = repaired[: max(1, int(limit))]
    changed = [_preflight_text(value) for value in repaired] != [
        _preflight_text(value) for value in existing[: max(1, int(limit))]
    ]
    audit = {
        "schema_version": "dependent_variable_scope_audit_v1",
        "applied": bool(changed),
        "reason": reason,
        "round_trip_efficiency_present": has_round_trip,
        "round_trip_efficiency_scope_supported": round_trip_supported,
        "readout_scope_axes": axes,
        "original_dependent_variables": existing,
        "repaired_dependent_variables": repaired,
    }
    return repaired, audit


def _replace_round_trip_efficiency_text(value: Any, replacement: str) -> Any:
    if isinstance(value, str):
        return _ROUND_TRIP_EFFICIENCY_RE.sub(replacement, value)
    if isinstance(value, list):
        return [_replace_round_trip_efficiency_text(item, replacement) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_round_trip_efficiency_text(item, replacement) for item in value)
    if isinstance(value, dict):
        return {
            key: _replace_round_trip_efficiency_text(item, replacement)
            for key, item in value.items()
        }
    return value


def repair_subhypotheses_dependent_variable_scope(
    sub_hypotheses: list[dict[str, Any]],
    *,
    parent_objective: str = "",
    domain: str = "",
    research_brief: str = "",
) -> dict[str, Any]:
    """Repair SH readouts that were broadcast from a parent objective."""

    parent_context = _scope_text(parent_objective, domain, research_brief)
    changed: list[dict[str, Any]] = []
    round_trip_present_count = 0
    total = len(sub_hypotheses or [])
    for item in sub_hypotheses or []:
        if not isinstance(item, dict):
            continue
        previous_audit = (
            item.get("dependent_variable_scope_audit")
            if isinstance(item.get("dependent_variable_scope_audit"), dict)
            else {}
        )
        existing = normalize_text_list(item.get("dependent_variables"))
        if (
            any(_is_round_trip_efficiency_readout(value) for value in existing)
            or previous_audit.get("round_trip_efficiency_present")
        ):
            round_trip_present_count += 1
        local_context = _scope_text(
            item.get("focus"),
            item.get("scientific_object"),
            item.get("scientific_object_aliases"),
            item.get("independent_variable"),
            item.get("causal_chain"),
            item.get("moderators"),
            item.get("boundary_conditions"),
            item.get("tradeoff_or_conflict"),
            item.get("quantifiable_bounds"),
            item.get("threshold_to_test"),
            item.get("falsification_condition"),
        )
        repaired, audit = _repair_dependent_variables_for_scope(
            dependent_variables=existing,
            local_context=local_context,
            parent_context=parent_context,
            limit=max(3, len(existing) or 3),
        )
        effective_audit = (
            previous_audit
            if previous_audit.get("applied") and not audit.get("applied")
            else audit
        )
        item["dependent_variable_scope_audit"] = effective_audit
        if not audit.get("applied"):
            if previous_audit.get("applied"):
                changed.append({
                    "sub_hypothesis_id": str(item.get("id") or ""),
                    "reason": previous_audit.get("reason"),
                    "readout_scope_axes": list(previous_audit.get("readout_scope_axes") or []),
                    "old_dependent_variables": list(previous_audit.get("original_dependent_variables") or []),
                    "new_dependent_variables": list(previous_audit.get("repaired_dependent_variables") or existing),
                })
            continue
        old_primary = existing[0] if existing else ""
        new_primary = repaired[0] if repaired else "effect size"
        item["dependent_variables"] = repaired
        item["outcome_audit"] = _preflight_outcome_audit(repaired)
        if old_primary and _is_round_trip_efficiency_readout(old_primary):
            for key in (
                "causal_chain",
                "causal_contract",
                "evidence_paths",
                "evidence_path_failure_policy",
                "retrieval_query",
                "query_variants",
                "falsification_condition",
                "counter_hypothesis",
            ):
                if key in item:
                    item[key] = _replace_round_trip_efficiency_text(item.get(key), new_primary)
        if (
            item.get("retrieval_query")
            and _ROUND_TRIP_EFFICIENCY_RE.search(str(item.get("retrieval_query") or ""))
            and not audit.get("round_trip_efficiency_scope_supported")
        ):
            item["retrieval_query"] = focused_subhypothesis_query(
                domain,
                str(item.get("focus") or item.get("scientific_object") or ""),
                normalize_text_list(item.get("causal_chain")),
                str(item.get("independent_variable") or ""),
                repaired,
                evidence_mode=str(item.get("evidence_mode") or ""),
                moderators=normalize_text_list(item.get("moderators")),
                epistemic_profile=(
                    item.get("epistemic_profile")
                    if isinstance(item.get("epistemic_profile"), dict)
                    else None
                ),
            )
        changed.append({
            "sub_hypothesis_id": str(item.get("id") or ""),
            "reason": audit.get("reason"),
            "readout_scope_axes": list(audit.get("readout_scope_axes") or []),
            "old_dependent_variables": existing,
            "new_dependent_variables": repaired,
        })
    return {
        "schema_version": "dependent_variable_scope_audit_v1",
        "applied": bool(changed),
        "round_trip_efficiency_present_count": round_trip_present_count,
        "shared_round_trip_overbroadcast_detected": bool(
            total >= 2 and round_trip_present_count >= max(2, total)
        ),
        "changed_count": len(changed),
        "changed": changed[:24],
    }


def _academic_reframed_concrete_readouts(
    *,
    academic_objective: str,
    research_brief: str,
    component: str = "",
    limit: int = 3,
) -> list[str]:
    """Infer measurable readout anchors for deterministic top-up SHs."""

    parent_context = _scope_text(academic_objective, research_brief)
    local_context = _scope_text(component)
    inferred, _axes = _contextual_readouts_for_scope(
        local_context=local_context,
        parent_context=parent_context,
        limit=limit,
        default_effect_size=False,
    )
    if inferred:
        return inferred[: max(1, int(limit))]

    context = _preflight_text(" ".join([parent_context, local_context]))
    readouts: list[str] = []

    def add(value: str) -> None:
        clean = normalize_space(value)
        if clean and clean not in readouts and _preflight_has_concrete_readout_marker(clean):
            readouts.append(clean)

    if re.search(r"\b(?:efficien\w*|round[-\s]?trip|roundtrip)\b", context):
        add(
            "round-trip efficiency"
            if _round_trip_efficiency_supported_by_scope(
                local_context=local_context,
                parent_context=parent_context,
            )
            else "effect size"
        )
    if re.search(r"\b(?:cost|inexpensive|economic|maintenance)\b", context):
        add("levelized cost of storage" if re.search(r"\b(?:storage|battery|grid|energy)\b", context) else "cost")
    if re.search(r"\b(?:density|capacity)\b", context):
        add("energy density" if re.search(r"\b(?:energy|battery|storage|electrode|cathode|anode)\b", context) else "density")
    if re.search(r"\b(?:cycle life|life cycle|lifetime|durability|degradation)\b", context):
        add("cycle life" if re.search(r"\b(?:battery|electrode|cell|storage)\b", context) else "degradation rate")

    for marker in sorted(
        _PREFLIGHT_CONCRETE_READOUT_MARKERS | _DISCIPLINE_READOUT_MARKERS,
        key=lambda item: (-len(item), item),
    ):
        if len(readouts) >= max(1, int(limit)):
            break
        marker_key = _preflight_text(marker)
        if marker_key and re.search(rf"\b{re.escape(marker_key)}\b", context):
            add(marker)

    if not readouts:
        add("effect size")
    return readouts[: max(1, int(limit))]


def _academic_reframed_default_comparison(
    *,
    component: str,
    academic_objective: str,
    research_brief: str,
    original_objective: str = "",
) -> str:
    component_key = _preflight_text(component)
    baseline_candidates = academic_reframed_candidate_components(
        original_objective=original_objective,
        academic_objective=academic_objective,
        research_brief=research_brief,
        max_subhypotheses=8,
    )
    for candidate in baseline_candidates:
        candidate_key = _preflight_text(candidate)
        if candidate_key and candidate_key != component_key and candidate_key not in component_key:
            return f"{component} versus {candidate}"
    context = normalize_space(" ".join([academic_objective, original_objective, research_brief]))
    named_match = re.search(
        r"\b([A-Za-z0-9][A-Za-z0-9+/\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9+/\-]*){0,4})\s+"
        r"(?:versus|vs\.?|compared\s+with|compared\s+to|relative\s+to)\b",
        context,
        flags=re.IGNORECASE,
    )
    if named_match:
        candidate = normalize_space(named_match.group(1))
        if candidate and _preflight_text(candidate) != component_key:
            return f"{component} versus {candidate}"
    return f"{component} versus current standard comparator"


def _minimum_topup_key(value: Any) -> str:
    normalized = _preflight_text(value)
    tokens = [
        token
        for token in normalized.split()
        if token
        and token not in {
            "and", "or", "with", "without", "versus", "vs", "compared", "to",
            "relative", "under", "varying", "conditions", "condition",
            "effect", "effects", "impact", "impacts", "technology",
            "technologies", "method", "methods", "system", "systems",
        }
    ]
    return " ".join(tokens)


def _minimum_topup_keys_from_object_value(value: Any) -> set[str]:
    normalized = normalize_space(str(value or ""))
    if not normalized:
        return set()
    pieces = [normalized]
    if re.search(r"\b(?:versus|vs\.?|compared\s+with|compared\s+to|relative\s+to)\b", normalized, flags=re.IGNORECASE):
        pieces.extend(
            part for part in re.split(
                r"\b(?:versus|vs\.?|compared\s+with|compared\s+to|relative\s+to)\b",
                normalized,
                flags=re.IGNORECASE,
            )
            if normalize_space(part)
        )
    if re.search(r"\band\b", normalized, flags=re.IGNORECASE):
        pieces.extend(part for part in re.split(r"\band\b", normalized, flags=re.IGNORECASE) if normalize_space(part))
    keys: set[str] = set()
    for piece in pieces:
        key = _minimum_topup_key(piece)
        if len(key) >= 4:
            keys.add(key)
    return keys


def _minimum_topup_object_keys(item: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("scientific_object",):
        raw = item.get(key)
        if isinstance(raw, str):
            values.append(raw)
    for alias in normalize_text_list(item.get("scientific_object_aliases")):
        values.append(alias)
    keys: set[str] = set()
    for value in values:
        keys.update(_minimum_topup_keys_from_object_value(value))
    return keys


def normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        clean = normalize_space(str(item or ""))
        if clean and clean not in output:
            output.append(clean)
    return output


_OBJECT_MATURITY_STATUSES = {
    "directly_established",
    "component_evidence_only",
    "translational_bridge",
    "speculative_unanchored",
    "contract_repair_required",
}
_OBJECT_MATURITY_COMPONENT_STATUSES = {
    "component_evidence_only",
    "translational_bridge",
    "speculative_unanchored",
}
_OBJECT_MATURITY_SPECULATIVE_MARKERS = (
    "future", "vision", "ultimate", "aspirational", "speculative", "could",
    "would", "potential", "potentially", "toward", "towards", "long-term",
    "long term", "not yet", "proof of concept", "prospective", "next-generation",
    "next generation",
)
_OBJECT_MATURITY_UNFORMED_DIRECT_OBJECT_MARKERS = (
    "transplant", "transplantation", "transfer into", "transferable",
    "upload", "download", "write into", "write-in", "write in", "implant into",
    "replacement of", "equivalent integration", "human-level",
)
_OBJECT_MATURITY_ESTABLISHED_TECHNICAL_EXCEPTIONS = (
    "digital pcr", "digital pathology", "digital imaging", "digital twin",
    "digital image", "digital holography", "digital signal processing",
    "digital microfluidic", "digital microfluidics", "digital droplet",
    "transplantation model", "cell transplantation", "tissue transplantation",
    "organ transplantation", "stem cell transplantation",
)
_OBJECT_MATURITY_COMPONENT_ANCHOR_MARKERS = (
    "assay", "benchmark", "biomarker", "catalyst", "cell", "cohort",
    "decoder", "decoding", "device", "electrode", "experiment", "interface",
    "material", "membrane", "model", "molecule", "nanoparticle", "network",
    "platform", "prosthesis", "reactor", "recording", "sensor", "simulation",
    "stimulation", "system", "testbed", "interface", "encoding", "readout",
)
_OBJECT_MATURITY_BOUNDARY_MARKERS = (
    "boundary", "safety", "toxicity", "stability", "failure", "artifact",
    "artefact", "heterogeneity", "individual difference", "generalization",
    "generalisation", "translation", "longitudinal", "long-term", "scalability",
    "calibration", "drift", "side effect", "adverse",
)
GENERIC_COMPONENT_BRIDGE_MODIFIERS = frozenset({
    "model system",
    "platform validation",
    "mechanism assay",
    "translation",
    "translational bridge",
    "cross-scale validation",
    "cross scale validation",
    "cross-scale feasibility",
    "cross scale feasibility",
    "feasibility",
    "framework",
    "roadmap",
    "therapeutic application",
    "therapeutic applications",
    "therapeutic intervention",
    "therapeutic interventions",
    "improvement in symptoms",
    "symptom improvement",
    "safety",
    "failure mode",
    "heterogeneity",
    "stability",
    "limitation",
    "limitations",
    "ethical implication",
    "ethical implications",
    "neurological damage",
    "disease-related pathway",
    "disease-related pathways",
})
_OBJECT_MATURITY_LOW_SPECIFICITY_TEMPLATE_TERMS = frozenset({
    "application", "applications", "assay", "bridge", "cross", "cross-scale",
    "damage", "ethical", "feasibility", "failure", "framework",
    "heterogeneity", "implication", "implications", "improvement",
    "limitation", "limitations", "mechanism", "model", "pathway",
    "pathways", "platform", "roadmap", "safety", "scale", "stability",
    "symptom", "symptoms", "therapeutic", "translation", "translational",
    "validation",
})
_OBJECT_MATURITY_METHOD_OR_PLATFORM_MARKERS = frozenset(
    _OBJECT_MATURITY_COMPONENT_ANCHOR_MARKERS
    + (
        # Non-HSS discipline-derived method/platform language, following the
        # natural-science, health, engineering, computation, mathematics, and
        # environmental fields in paperseek_core.disciplines.  These are not
        # discipline labels; they are searchable evidence-form anchors.
        "ablation", "ablation study", "adsorption", "algorithm", "annealing",
        "animal model", "assay", "atomic force microscopy", "batch reactor",
        "bayesian model", "bench-scale", "benchmark", "benchmark dataset",
        "biomarker assay", "bioreactor", "cell culture", "characterization",
        "characterisation", "chemical vapor deposition", "chromatography",
        "clinical trial", "cohort", "computational fluid dynamics",
        "computational model", "confocal microscopy", "controlled trial",
        "crispr", "cross validation", "cross-validation", "cryogenic imaging",
        "cryo electron microscopy", "cryo electron tomography", "cryo-em",
        "cryo-et", "cyclic voltammetry", "deep learning", "deposition",
        "diagnostic assay", "diagnostic test", "distillation", "dose response",
        "electrochemical impedance", "electrolysis", "electrophysiology",
        "enzyme assay", "external validation", "fabrication", "field sampling",
        "field trial", "finite element", "flow cytometry", "flow reactor",
        "fluorescence microscopy", "gas chromatography", "genomics",
        "geochemical analysis", "geophysical survey", "growth assay",
        "histology", "histopathology", "hplc", "hydrothermal synthesis",
        "imaging", "immunoassay", "immunofluorescence", "in vivo",
        "in vitro", "knockdown", "knockout", "laser ablation",
        "life cycle assessment", "machine learning", "mass spectrometry",
        "mathematical model", "mechanical testing", "mesocosm", "metabolomics",
        "microcosm", "microfluidics", "microscopy", "monte carlo",
        "mri", "multiomics", "multi-omics", "nmr", "numerical simulation",
        "optogenetic activation", "optogenetic stimulation", "organoid",
        "pathology assay", "pcr", "pilot-scale", "plot experiment",
        "polymerization", "proteomics", "prototype", "qpcr", "quantum simulation",
        "randomized controlled trial", "randomised controlled trial", "reactor",
        "remote sensing", "rna-seq", "scanning electron microscopy",
        "sequencing", "simulation", "single-cell sequencing", "spectroscopy",
        "stimulation", "synchrotron", "techno-economic analysis", "testbed",
        "thin film deposition", "tms", "tacs", "dbs", "tomography",
        "toxicology assay", "transmission electron microscopy", "ultrasound",
        "x-ray diffraction", "xps",
    )
)
_OBJECT_MATURITY_MODEL_SYSTEM_MARKERS = frozenset({
    "animal model", "bench-scale", "bench scale", "cell culture", "cell line",
    "clinical cohort", "cohort", "dentate gyrus", "drosophila",
    "earth system model", "ex vivo", "field trial", "finite element model",
    "hippocampus", "human cohort", "in vivo", "in vitro", "lab-scale",
    "lab scale", "mesocosm", "mice", "microcosm", "mouse", "mouse model",
    "murine model", "organoid", "patient cohort", "pilot-scale", "pilot scale",
    "plot experiment", "prototype", "rat model", "simulation", "testbed",
    "zebrafish",
})
_OBJECT_MATURITY_OBJECT_ENTITY_MARKERS = frozenset({
    "alloy", "anode", "battery", "biomarker", "biomolecule", "catalyst",
    "cathode", "cell", "cells", "circuit", "circuits", "cohort", "compound",
    "disease", "electrode", "engram", "enzyme", "gene", "genome",
    "hippocampus", "interface", "material", "membrane", "memory", "memories",
    "molecule", "nanoparticle", "neuron", "neurons", "pathway", "pathways",
    "polymer", "protein", "quantum dot", "reactor", "sensor", "tissue",
    "waste stream",
})


def _object_maturity_status(value: Any) -> str:
    status = normalize_space(str(value or "")).lower().replace("-", "_").replace(" ", "_")
    if status in {
        "direct", "established", "mature", "directly_anchorable",
        "directly_anchorable", "direct_object",
    }:
        return "directly_established"
    if status in {"component_only", "component", "components", "component_evidence"}:
        return "component_evidence_only"
    if status in {"bridge", "translation_bridge", "translational"}:
        return "translational_bridge"
    if status in {"speculative", "unanchored", "speculative_unanchored", "future_vision"}:
        return "speculative_unanchored"
    if status in {"contract_repair_required", "invalid_object_contract", "object_contract_invalid"}:
        return "contract_repair_required"
    return status if status in _OBJECT_MATURITY_STATUSES else "directly_established"


def _object_maturity_unique(values: Any, *, limit: int = 8) -> list[str]:
    return [
        item for item in normalize_text_list(values)
        if len(item) >= 3
    ][: max(0, int(limit))]


def _object_maturity_anchor_key(value: Any) -> str:
    text = normalize_space(str(value or "")).lower()
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )
    text = re.sub(r"[^a-z0-9+./'\-\s]+", " ", text)
    return normalize_space(text)


def _object_maturity_phrase_in_text(phrase: str, text: str) -> bool:
    phrase_key = _object_maturity_anchor_key(phrase).replace("-", " ")
    text_key = _object_maturity_anchor_key(text).replace("-", " ")
    if not phrase_key or not text_key:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase_key)}(?![a-z0-9])", text_key))


def _object_maturity_modifier_hits(value: Any) -> list[str]:
    text = _object_maturity_anchor_key(value)
    hits = [
        modifier
        for modifier in sorted(GENERIC_COMPONENT_BRIDGE_MODIFIERS, key=len, reverse=True)
        if _object_maturity_phrase_in_text(modifier, text)
    ]
    return list(dict.fromkeys(hits))


def _strip_object_maturity_modifier_phrases(value: Any) -> str:
    cleaned = _object_maturity_anchor_key(value).replace("-", " ")
    for modifier in sorted(GENERIC_COMPONENT_BRIDGE_MODIFIERS, key=len, reverse=True):
        modifier_key = _object_maturity_anchor_key(modifier).replace("-", " ")
        if not modifier_key:
            continue
        cleaned = re.sub(
            rf"(?<![a-z0-9]){re.escape(modifier_key)}(?![a-z0-9])",
            " ",
            cleaned,
        )
    cleaned = re.sub(
        r"\b(?:creation|created|creating|of|for|toward|towards|using|with|"
        r"compared|comparison|to|versus|vs|final|future|potential|natural)\b",
        " ",
        cleaned,
    )
    return normalize_space(cleaned)


def _object_maturity_anchor_tokens(value: Any) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9+./'-]*", _object_maturity_anchor_key(value))
        if token
    ]


def _object_maturity_anchor_contains_any(value: Any, markers: Iterable[str]) -> bool:
    text = _object_maturity_anchor_key(value)
    return any(_object_maturity_phrase_in_text(marker, text) for marker in markers)


def _object_maturity_modifier_only_anchor(value: Any) -> bool:
    normalized = _object_maturity_anchor_key(value)
    if not normalized:
        return True
    comparable = normalized.replace("-", " ")
    modifier_keys = {
        _object_maturity_anchor_key(item).replace("-", " ")
        for item in GENERIC_COMPONENT_BRIDGE_MODIFIERS
    }
    if comparable in modifier_keys:
        return True
    tokens = [
        token
        for token in _object_maturity_anchor_tokens(comparable)
        if token not in _MIXED_PARENT_STOPWORDS
    ]
    if not tokens:
        return True
    concrete_tokens = [
        token
        for token in tokens
        if token not in _OBJECT_MATURITY_LOW_SPECIFICITY_TEMPLATE_TERMS
    ]
    return not concrete_tokens


def _object_maturity_anchor_specific_enough(value: Any) -> bool:
    cleaned = _object_maturity_anchor_key(value)
    if not cleaned:
        return False
    if re.search(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b", str(value or "")):
        return True
    tokens = [
        token
        for token in _object_maturity_anchor_tokens(cleaned)
        if token not in _MIXED_PARENT_STOPWORDS
        and token not in _OBJECT_MATURITY_LOW_SPECIFICITY_TEMPLATE_TERMS
    ]
    return len(tokens) >= 1 and len(_object_maturity_anchor_tokens(cleaned)) >= 1


def _object_maturity_classify_anchor(value: Any) -> dict[str, Any]:
    original = normalize_space(str(value or ""))
    modifier_hits = _object_maturity_modifier_hits(original)
    stripped = _strip_object_maturity_modifier_phrases(original)
    normalized = stripped or _object_maturity_anchor_key(original)
    modifier_only = bool(
        not stripped
        or _object_maturity_modifier_only_anchor(original)
        or not _object_maturity_anchor_specific_enough(normalized)
    )
    roles: list[str] = []
    if modifier_only:
        roles.append("modifier_only")
    else:
        original_upper_has_identifier = bool(
            re.search(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b", original)
        )
        if (
            original_upper_has_identifier
            or _object_maturity_anchor_contains_any(normalized, _OBJECT_MATURITY_OBJECT_ENTITY_MARKERS)
            or (
                len(_object_maturity_anchor_tokens(normalized)) >= 2
                and not _object_maturity_anchor_contains_any(
                    normalized,
                    _OBJECT_MATURITY_METHOD_OR_PLATFORM_MARKERS
                    | _PREFLIGHT_CONCRETE_READOUT_MARKERS
                    | _OBJECT_MATURITY_MODEL_SYSTEM_MARKERS,
                )
            )
        ):
            roles.append("object_anchor")
        if _object_maturity_anchor_contains_any(normalized, _OBJECT_MATURITY_METHOD_OR_PLATFORM_MARKERS):
            roles.append("method_or_platform_anchor")
        if (
            _object_maturity_anchor_contains_any(normalized, _PREFLIGHT_CONCRETE_READOUT_MARKERS)
            or _object_maturity_phrase_in_text("fidelity", normalized)
            or _object_maturity_phrase_in_text("retention", normalized)
            or _object_maturity_phrase_in_text("recall accuracy", normalized)
            or _object_maturity_phrase_in_text("memory recall", normalized)
        ):
            roles.append("readout_anchor")
        if _object_maturity_anchor_contains_any(normalized, _OBJECT_MATURITY_MODEL_SYSTEM_MARKERS):
            roles.append("model_system_anchor")
    return {
        "anchor": original,
        "normalized_anchor": normalized,
        "roles": list(dict.fromkeys(roles)),
        "modifier_hits": modifier_hits,
        "cannot_count_as_object_anchor": bool(modifier_only or "object_anchor" not in roles),
        "modifier_only": modifier_only,
    }


def _typed_object_maturity_anchors_from_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Read typed component-bridge anchors only from canonical typed fields.

    Legacy flat anchor fields are intentionally ignored here.  They are kept
    only as raw diagnostics by the caller, never promoted into typed anchors.
    """

    typed_source = (
        payload.get("typed_component_bridge_anchors")
        if isinstance(payload.get("typed_component_bridge_anchors"), dict)
        else {}
    )
    object_anchors = _object_maturity_unique(
        payload.get("object_anchors")
        or typed_source.get("object_anchors"),
        limit=12,
    )
    method_anchors = _object_maturity_unique(
        payload.get("method_or_platform_anchors")
        or typed_source.get("method_or_platform_anchors"),
        limit=12,
    )
    readout_anchors = _object_maturity_unique(
        payload.get("readout_anchors")
        or typed_source.get("readout_anchors"),
        limit=12,
    )
    model_system_anchors = _object_maturity_unique(
        payload.get("model_system_anchors")
        or typed_source.get("model_system_anchors"),
        limit=12,
    )
    role_modifiers = _object_maturity_unique(
        payload.get("role_modifiers")
        or typed_source.get("role_modifiers"),
        limit=16,
    )
    forbidden_as_object_anchors = _object_maturity_unique(
        payload.get("forbidden_as_object_anchors")
        or typed_source.get("forbidden_as_object_anchors"),
        limit=16,
    )
    classifications: list[dict[str, Any]] = []
    object_anchors = _object_maturity_unique(object_anchors, limit=12)
    method_anchors = _object_maturity_unique(method_anchors, limit=12)
    readout_anchors = _object_maturity_unique(readout_anchors, limit=12)
    model_system_anchors = _object_maturity_unique(model_system_anchors, limit=12)
    role_modifiers = _object_maturity_unique(role_modifiers, limit=16)
    forbidden_as_object_anchors = _object_maturity_unique(forbidden_as_object_anchors, limit=16)
    support_count = len(method_anchors) + len(readout_anchors) + len(model_system_anchors)
    quality_passes = bool(object_anchors and support_count)
    bad_anchors = _object_maturity_unique(
        forbidden_as_object_anchors
        + [
            str(record.get("anchor") or "")
            for record in classifications
            if record.get("modifier_only")
        ],
        limit=16,
    )
    return {
        "schema_version": "object_maturity_typed_anchor_audit_v1",
        "object_anchors": object_anchors,
        "method_or_platform_anchors": method_anchors,
        "readout_anchors": readout_anchors,
        "model_system_anchors": model_system_anchors,
        "role_modifiers": role_modifiers,
        "forbidden_as_object_anchors": forbidden_as_object_anchors,
        "anchor_classification": classifications[:32],
        "quality": {
            "status": (
                "component_bridge_anchor_quality_passed"
                if quality_passes
                else "component_bridge_anchor_repair_required"
            ),
            "passes": quality_passes,
            "requires_object_anchor": True,
            "requires_method_or_readout_or_model_system_anchor": True,
            "object_anchor_count": len(object_anchors),
            "method_or_platform_anchor_count": len(method_anchors),
            "readout_anchor_count": len(readout_anchors),
            "model_system_anchor_count": len(model_system_anchors),
            "bad_anchors": bad_anchors,
            "reason": (
                "component anchors include at least one searchable object plus method/platform, readout, or model-system evidence"
                if quality_passes
                else "component anchors are role templates rather than searchable scientific entities"
            ),
        },
    }


def _normalize_object_maturity_audit(
    payload: dict[str, Any] | None,
    *,
    sub_hypothesis: dict[str, Any],
    parent_objective: str,
    original_objective: str,
    domain: str,
    research_brief: str,
    extractor: str,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    scientific_object = normalize_space(str(sub_hypothesis.get("scientific_object") or ""))
    focus = normalize_space(str(sub_hypothesis.get("focus") or ""))
    status = _object_maturity_status(
        payload.get("object_status")
        or payload.get("literature_anchorability")
        or payload.get("status")
    )
    mature_terms = _object_maturity_unique(
        payload.get("mature_direct_search_terms"),
        limit=8,
    )
    typed_anchor_audit = _typed_object_maturity_anchors_from_payload(
        payload,
    )
    candidate_set = (
        sub_hypothesis.get("mature_searchable_object_candidates")
        if isinstance(sub_hypothesis.get("mature_searchable_object_candidates"), dict)
        else {}
    )
    selected_candidate = (
        candidate_set.get("selected_candidate")
        if isinstance(candidate_set.get("selected_candidate"), dict)
        else {}
    )
    selected_validation = (
        selected_candidate.get("validation")
        if isinstance(selected_candidate.get("validation"), dict)
        else {}
    )
    selected_candidate_identity_verified = bool(
        selected_validation.get("passes") is True
        and _object_maturity_anchor_key(selected_validation.get("scientific_object"))
        == _object_maturity_anchor_key(scientific_object)
    )
    if selected_candidate_identity_verified and not mature_terms:
        mature_terms = _object_maturity_unique(
            [scientific_object, *normalize_text_list(selected_validation.get("retrieval_terms"))],
            limit=8,
        )
    if selected_candidate_identity_verified and status in _OBJECT_MATURITY_COMPONENT_STATUSES:
        # The LLM's bridge wording often reports an open *mechanism*, not an
        # unformed object.  Keep that uncertainty under claim_completeness
        # below, while restoring the verified object to direct identity.
        status = "directly_established"
    # Object identity and claim completeness are separate dimensions.  A
    # mature material/model/population may be directly searchable even when
    # the SH's full causal mechanism remains open.  The latter limits the
    # claim, never retroactively makes the object an immature bridge.
    object_identity_maturity = normalize_space(
        str(payload.get("object_identity_maturity") or "")
    ).upper()
    if object_identity_maturity not in {
        "MATURE_DIRECT_OBJECT", "MATURE_COMPARABLE_SYSTEM",
        "COMPONENT_OR_PLATFORM_ONLY", "FUTURE_OR_UNFORMED_OBJECT",
        "OBJECT_IDENTITY_UNVERIFIED",
    }:
        object_identity_maturity = (
            "MATURE_DIRECT_OBJECT"
            if selected_candidate_identity_verified or status == "directly_established"
            else "COMPONENT_OR_PLATFORM_ONLY"
            if status in _OBJECT_MATURITY_COMPONENT_STATUSES
            else "OBJECT_IDENTITY_UNVERIFIED"
        )
    claim_completeness = normalize_space(
        str(payload.get("claim_completeness") or "")
    ).upper()
    if claim_completeness not in {
        "DIRECT_LOCAL_EDGE_SUPPORTED", "PARTIAL_CAUSAL_CHAIN_SUPPORTED",
        "WHOLE_CLAIM_ESTABLISHED", "WHOLE_CLAIM_NOT_ESTABLISHED",
        "CLAIM_NOT_ASSESSED",
    }:
        claim_completeness = (
            "WHOLE_CLAIM_ESTABLISHED"
            if payload.get("whole_sh_direct_core_allowed") is True
            else "PARTIAL_CAUSAL_CHAIN_SUPPORTED"
            if object_identity_maturity in {"MATURE_DIRECT_OBJECT", "MATURE_COMPARABLE_SYSTEM"}
            else "CLAIM_NOT_ASSESSED"
        )
    # Object identity answers a different question from claim completeness:
    # can the system retrieve a paper that directly tests one declared causal
    # edge on this object?  A mature object answers yes even if no source, and
    # perhaps no combination of sources yet, establishes the complete SH.
    #
    # Do not preserve a false LLM/old-state direct-core flag for a mature
    # identity.  In the old representation that flag was often used to say
    # "the whole mechanism is unresolved".  Treating it as a local-edge ban
    # is exactly what created the directly_established/component_bridge
    # contradiction seen in the groupchat log.
    mature_direct_identity = object_identity_maturity in {
        "MATURE_DIRECT_OBJECT", "MATURE_COMPARABLE_SYSTEM"
    }
    if status == "contract_repair_required":
        mature_direct_identity = False
        direct_anchorable = False
        direct_local_edge_allowed = False
        direct_core_allowed = False
        whole_sh_direct_core_allowed = False
        retrieval_mode = "contract_repair_required"
        retrieval_mode_resolution_source = "scientific_object_contract_failure"
        direct_core_disallowed_reason = "scientific_object_contract_failed"
        whole_sh_direct_core_disallowed_reason = "scientific_object_contract_failed"
    elif mature_direct_identity:
        # A direct/comparable object has a stable literature identity.  Its
        # local causal edges may be retrieved and later composed across
        # papers, regardless of whether the whole SH has closed.
        status = "directly_established"
        direct_anchorable = True
        direct_local_edge_allowed = True
        direct_core_allowed = True
        whole_sh_direct_core_allowed = bool(
            claim_completeness == "WHOLE_CLAIM_ESTABLISHED"
            and payload.get("whole_sh_direct_core_allowed") is True
        )
        retrieval_mode = "direct_edge_bundle"
        retrieval_mode_resolution_source = (
            "mature_direct_object_whole_claim_established"
            if whole_sh_direct_core_allowed
            else "mature_direct_object_local_edges_only"
        )
        direct_core_disallowed_reason = ""
        whole_sh_direct_core_disallowed_reason = (
            "whole_claim_not_established"
            if claim_completeness != "WHOLE_CLAIM_ESTABLISHED"
            else "whole_claim_permission_not_declared"
            if payload.get("whole_sh_direct_core_allowed") is not True
            else ""
        )
    else:
        # Only an actually unformed/component-only identity receives the
        # component-bridge route.  Its old direct flags are not trusted.
        direct_anchorable = False
        direct_local_edge_allowed = False
        direct_core_allowed = False
        whole_sh_direct_core_allowed = False
        retrieval_mode = "component_bridge_boundary"
        retrieval_mode_resolution_source = "non_direct_object_identity"
        direct_core_disallowed_reason = "object_identity_not_directly_anchorable"
        whole_sh_direct_core_disallowed_reason = "object_identity_not_directly_anchorable"
    forbidden_claims = _object_maturity_unique(
        payload.get("forbidden_direct_core_claims")
        or payload.get("forbidden_claims"),
        limit=6,
    )
    if not forbidden_claims and not direct_core_allowed:
        forbidden_claims = [
            f"Do not claim direct validation of {scientific_object or focus} as an established empirical object."
        ]
    bridge_gap = normalize_space(str(payload.get("bridge_gap_statement") or payload.get("gap_statement") or ""))
    if not bridge_gap and not direct_core_allowed:
        bridge_gap = (
            f"Available literature should be read as component, platform, translation, or boundary evidence; "
            f"direct evidence for {scientific_object or focus} remains unanchored."
        )
    rewrite_reason = normalize_space(str(payload.get("rewrite_reason") or payload.get("reason") or ""))
    if not rewrite_reason:
        rewrite_reason = (
            "The declared scientific object appears to have a stable direct literature identity."
            if direct_core_allowed
            else "The declared scientific_object is a schema-level contract error and must be repaired before retrieval."
            if status == "contract_repair_required"
            else "The declared object is a future capability or umbrella target; route retrieval through component, bridge, and boundary evidence instead of direct-core validation."
        )
    scope_preservation = normalize_space(str(payload.get("scope_preservation") or ""))
    if not scope_preservation:
        scope_preservation = (
            "The original parent objective is preserved; only the evidence role is downgraded from direct-core proof to component-bridge evaluation when needed."
        )
    anchor_quality = (
        typed_anchor_audit.get("quality")
        if isinstance(typed_anchor_audit.get("quality"), dict)
        else {}
    )
    anchor_repair_required = bool(
        status in _OBJECT_MATURITY_COMPONENT_STATUSES
        and not anchor_quality.get("passes")
    )
    declared_contract = (
        sub_hypothesis.get("causal_contract")
        if isinstance(sub_hypothesis.get("causal_contract"), dict)
        else {}
    )
    declared_readouts = _object_maturity_unique(
        normalize_text_list(sub_hypothesis.get("dependent_variables"))
        + normalize_text_list(declared_contract.get("outcome")),
        limit=12,
    )
    declared_object_terms = _object_maturity_unique(
        [scientific_object]
        + normalize_text_list(sub_hypothesis.get("scientific_object_aliases"))
        + normalize_text_list(selected_validation.get("aliases")),
        limit=12,
    )

    def has_declared_provenance(anchor: Any, declared_values: list[str]) -> bool:
        value = _object_maturity_anchor_key(anchor)
        if not value:
            return False
        value_tokens = set(_object_maturity_anchor_tokens(value))
        for declared in declared_values:
            declared_key = _object_maturity_anchor_key(declared)
            declared_tokens = set(_object_maturity_anchor_tokens(declared_key))
            if value == declared_key or value in declared_key or declared_key in value:
                return True
            if len(value_tokens & declared_tokens) >= min(2, len(value_tokens), len(declared_tokens)):
                return True
        return False

    typed_object_anchors = _object_maturity_unique(
        [anchor for anchor in typed_anchor_audit.get("object_anchors") or []
         if has_declared_provenance(anchor, declared_object_terms)]
        + declared_object_terms,
        limit=12,
    )
    typed_readout_anchors = _object_maturity_unique(
        [anchor for anchor in typed_anchor_audit.get("readout_anchors") or []
         if has_declared_provenance(anchor, declared_readouts)]
        + declared_readouts,
        limit=12,
    )
    anchor_provenance = {
        "policy": "declared_or_selected_object_only; llm_anchor_only_is_not_protected",
        "object_anchors": [
            {"term": anchor, "origin": "selected_object_or_declared_alias"}
            for anchor in typed_object_anchors
        ],
        "readout_anchors": [
            {"term": anchor, "origin": "declared_outcome_or_dependent_variable"}
            for anchor in typed_readout_anchors
        ],
    }
    return {
        "schema_version": OBJECT_MATURITY_PREFLIGHT_VERSION,
        "status": (
            "component_bridge_anchor_repair_required"
            if anchor_repair_required
            else "ready"
        ),
        "sub_hypothesis_id": str(sub_hypothesis.get("id") or ""),
        "scientific_object": scientific_object,
        "focus": focus,
        "object_status": status,
        "literature_anchorability": status,
        "object_identity_maturity": object_identity_maturity,
        "object_identity_verified": bool(
            object_identity_maturity in {"MATURE_DIRECT_OBJECT", "MATURE_COMPARABLE_SYSTEM"}
        ),
        "object_identity_evidence": {
            "source": "validated_llm_object_candidate"
            if selected_candidate_identity_verified else "maturity_audit",
            "candidate_validation_passed": selected_candidate_identity_verified,
            "canonical_object": scientific_object,
            "aliases": _object_maturity_unique(
                selected_validation.get("aliases") or sub_hypothesis.get("scientific_object_aliases"),
                limit=12,
            ),
        },
        "claim_completeness": claim_completeness,
        "direct_object_anchorable": direct_anchorable,
        "direct_core_evidence_allowed": direct_core_allowed,
        "direct_local_edge_evidence_allowed": direct_local_edge_allowed,
        "whole_sh_direct_core_allowed": whole_sh_direct_core_allowed,
        "direct_core_disallowed_reason": direct_core_disallowed_reason,
        "whole_sh_direct_core_disallowed_reason": whole_sh_direct_core_disallowed_reason,
        "retrieval_mode": retrieval_mode,
        "retrieval_mode_resolution_source": retrieval_mode_resolution_source,
        "mature_direct_search_terms": mature_terms,
        "raw_component_evidence_anchors": _object_maturity_unique(
            payload.get("component_evidence_anchors")
            or payload.get("component_anchors")
            or payload.get("component_evidence_terms"),
            limit=16,
        ),
        "raw_translational_bridge_anchors": _object_maturity_unique(
            payload.get("translational_bridge_anchors")
            or payload.get("bridge_anchors")
            or payload.get("bridge_terms"),
            limit=16,
        ),
        "raw_boundary_or_safety_anchors": _object_maturity_unique(
            payload.get("boundary_or_safety_anchors")
            or payload.get("boundary_anchors")
            or payload.get("safety_anchors"),
            limit=16,
        ),
        "typed_component_bridge_anchors": {
            "schema_version": typed_anchor_audit.get("schema_version"),
            "object_anchors": typed_object_anchors,
            "method_or_platform_anchors": list(typed_anchor_audit.get("method_or_platform_anchors") or []),
            "readout_anchors": typed_readout_anchors,
            "model_system_anchors": list(typed_anchor_audit.get("model_system_anchors") or []),
            "role_modifiers": list(typed_anchor_audit.get("role_modifiers") or []),
            "forbidden_as_object_anchors": list(typed_anchor_audit.get("forbidden_as_object_anchors") or []),
            "anchor_classification": list(typed_anchor_audit.get("anchor_classification") or []),
        },
        "object_anchors": typed_object_anchors,
        "method_or_platform_anchors": list(typed_anchor_audit.get("method_or_platform_anchors") or []),
        "readout_anchors": typed_readout_anchors,
        "anchor_provenance": anchor_provenance,
        "model_system_anchors": list(typed_anchor_audit.get("model_system_anchors") or []),
        "role_modifiers": list(typed_anchor_audit.get("role_modifiers") or []),
        "forbidden_as_object_anchors": list(typed_anchor_audit.get("forbidden_as_object_anchors") or []),
        "component_bridge_anchor_quality": anchor_quality,
        "component_bridge_anchor_repair_required": anchor_repair_required,
        "component_evidence_anchors": [],
        "translational_bridge_anchors": [],
        "boundary_or_safety_anchors": [],
        "forbidden_direct_core_claims": forbidden_claims,
        "bridge_gap_statement": bridge_gap,
        "rewrite_reason": rewrite_reason,
        "scope_preservation": scope_preservation,
        "parent_objective_preserved": parent_objective,
        "original_objective_preserved": original_objective,
        "domain": domain,
        "audit_basis": normalize_text_list(payload.get("audit_basis"))[:8],
        "extractor": extractor,
    }


def _heuristic_subhypothesis_object_maturity_audit(
    sub_hypothesis: dict[str, Any],
    *,
    parent_objective: str,
    original_objective: str,
    domain: str,
    research_brief: str,
) -> dict[str, Any]:
    scientific_object = normalize_space(str(sub_hypothesis.get("scientific_object") or ""))
    text = normalize_space(
        " ".join(
            str(part or "")
            for part in (
                scientific_object,
                sub_hypothesis.get("focus"),
                sub_hypothesis.get("retrieval_query"),
                parent_objective,
                research_brief[:2000],
            )
        )
    )
    lowered = text.lower()
    object_lowered = scientific_object.lower()
    established_exception = any(marker in lowered for marker in _OBJECT_MATURITY_ESTABLISHED_TECHNICAL_EXCEPTIONS)
    unformed_marker_hit = any(marker in lowered for marker in _OBJECT_MATURITY_UNFORMED_DIRECT_OBJECT_MARKERS)
    speculative_marker_hit = any(marker in lowered for marker in _OBJECT_MATURITY_SPECULATIVE_MARKERS)
    object_has_future_modifier = bool(
        re.search(
            r"\b(?:digital|virtual|artificial|synthetic|programmable|autonomous|human-level)\b",
            object_lowered,
            flags=re.IGNORECASE,
        )
    )
    direct_object_like_method = bool(
        any(marker in object_lowered for marker in _PREFLIGHT_VARIABLE_RESOLUTION_MARKERS)
        or any(marker in object_lowered for marker in _PREFLIGHT_OPERATIONAL_VARIABLE_MARKERS)
        or re.search(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b", scientific_object)
    )
    status = "directly_established"
    if not established_exception and unformed_marker_hit and (
        object_has_future_modifier or speculative_marker_hit or "human" in lowered
    ):
        status = "speculative_unanchored"
    elif not established_exception and object_has_future_modifier and speculative_marker_hit and not direct_object_like_method:
        status = "component_evidence_only"
    return _normalize_object_maturity_audit(
        {
            "object_status": status,
            "direct_object_anchorable": status == "directly_established",
            "direct_core_evidence_allowed": status == "directly_established",
            "retrieval_mode": "direct_core" if status == "directly_established" else "component_bridge_boundary",
            "mature_direct_search_terms": [scientific_object] if scientific_object and status == "directly_established" else [],
            "audit_basis": [
                "future_capability_marker" if speculative_marker_hit else "",
                "direct_object_unformed_marker" if unformed_marker_hit else "",
                "technical_exception" if established_exception else "",
            ],
            "rewrite_reason": (
                "Deterministic audit found future-capability or transfer/implantation language without a stable direct-object identity."
                if status != "directly_established"
                else "Deterministic audit found no clear evidence that the declared object is an unanchored future capability."
            ),
        },
        sub_hypothesis=sub_hypothesis,
        parent_objective=parent_objective,
        original_objective=original_objective,
        domain=domain,
        research_brief=research_brief,
        extractor="heuristic",
    )


def _mature_searchable_object_candidate_validation(candidate: dict[str, Any]) -> dict[str, Any]:
    """Validate an LLM-proposed retrieval object without domain-specific rules."""

    object_name = normalize_space(str(candidate.get("scientific_object") or ""))
    object_type = normalize_space(str(candidate.get("object_type") or "")).lower()
    aliases = _object_maturity_unique(candidate.get("aliases"), limit=8)
    search_terms = _object_maturity_unique(candidate.get("retrieval_terms"), limit=10)
    maturity = normalize_space(str(candidate.get("maturity") or "")).lower()
    rationale = normalize_space(str(candidate.get("direct_evidence_rationale") or ""))
    content_tokens = [
        token for token in _object_maturity_anchor_tokens(object_name)
        if token not in _OBJECT_MATURITY_LOW_SPECIFICITY_TEMPLATE_TERMS
        and token not in _MIXED_PARENT_STOPWORDS
    ]
    specific_identity = bool(
        _object_maturity_anchor_specific_enough(object_name)
        and (len(content_tokens) >= 2 or re.search(r"[A-Z0-9]{2,}(?:-[A-Z0-9]+)*", object_name))
    )
    maturity_declared = maturity in {
        "mature", "established", "directly_established", "searchable_now",
    }
    type_supported = object_type in MATURE_SEARCHABLE_OBJECT_TYPES
    passes = bool(
        specific_identity and type_supported and maturity_declared and search_terms and rationale
    )
    reasons = []
    if not specific_identity:
        reasons.append("OBJECT_IDENTITY_NOT_SPECIFIC")
    if not type_supported:
        reasons.append("OBJECT_TYPE_NOT_TYPED")
    if not maturity_declared:
        reasons.append("MATURITY_NOT_ESTABLISHED")
    if not search_terms:
        reasons.append("RETRIEVAL_TERMS_MISSING")
    if not rationale:
        reasons.append("DIRECT_EVIDENCE_RATIONALE_MISSING")
    return {
        "passes": passes,
        "scientific_object": object_name,
        "object_type": object_type,
        "aliases": aliases,
        "retrieval_terms": search_terms,
        "rejection_reasons": reasons,
    }


def _llm_mature_searchable_object_candidates(
    sub_hypotheses: list[dict[str, Any]],
    *,
    parent_objective: str,
    original_objective: str,
    domain: str,
    research_brief: str,
) -> dict[str, dict[str, Any]]:
    """Ask the LLM to turn every SH into concrete, searchable object choices.

    The candidates are deliberately generated before the maturity audit.  This
    separates *choosing a literature object* from *judging whether that object
    has direct evidence*, which prevents a broad future objective from leaking
    into a high-volume retrieval plan.
    """

    compact_items = []
    for item in sub_hypotheses:
        if not isinstance(item, dict):
            continue
        compact_items.append({
            "id": str(item.get("id") or ""),
            "focus": str(item.get("focus") or "")[:800],
            "declared_scientific_object": str(item.get("scientific_object") or "")[:300],
            "independent_variable": str(item.get("independent_variable") or "")[:300],
            "dependent_variables": normalize_text_list(item.get("dependent_variables"))[:8],
            "causal_chain": normalize_text_list(item.get("causal_chain"))[:8],
            "retrieval_query": str(item.get("retrieval_query") or "")[:500],
        })
    if not compact_items:
        return {}
    system = (
        "You curate literature-searchable scientific objects before evidence retrieval. "
        "Return JSON only. You work across all scientific domains and must not "
        "invent a domain-specific taxonomy."
    )
    instructions = (
        "For EACH supplied sub-hypothesis, produce 3 to 6 candidate objects that are "
        "already mature and concrete enough to search in the literature. A valid object is "
        "a named material family or composition class, defined comparable/model "
        "system, mechanism subsystem, defined population, device or reaction architecture, "
        "ecological system, formal model, or benchmark dataset. Split broad umbrella phrases "
        "into concrete alternatives where the supplied SH supports doing so. Do not return a "
        "future capability, a final societal/engineering goal, a method alone, a readout alone, "
        "or a vague category as the object. A method, assay, instrument, spectroscopy technique, "
        "simulation workflow, or readout may be mentioned only as a supporting term and must not "
        "be emitted as scientific_object. Do not fabricate named entities absent from the SH "
        "or research brief: when the context cannot support a mature object, explicitly return "
        "no mature candidate and explain why the SH must be rewritten. The output must preserve "
        "the parent objective as scope, but it may narrow the retrieval object.\n\n"
        "For every candidate give: scientific_object; object_type from the allowed enum; aliases; "
        "retrieval_terms; maturity (mature|uncertain); direct_evidence_rationale; scope_relation. "
        "Prefer candidates with aliases and terms likely to occur in titles/abstracts.\n\n"
        "Return exactly: {\"object_candidate_sets\":[{\"sub_hypothesis_id\":\"SH1\","
        "\"candidates\":[...],\"rewrite_required_if_no_candidate\":true,"
        "\"rewrite_reason\":\"...\"}]}"
    )
    output: dict[str, dict[str, Any]] = {}
    batch_size = max(1, int(OBJECT_MATURITY_LLM_BATCH_SIZE or 2))
    for start in range(0, len(compact_items), batch_size):
        batch = compact_items[start : start + batch_size]
        payload = {
            "prompt_version": MATURE_OBJECT_CANDIDATE_PROMPT_VERSION,
            "parent_objective": parent_objective,
            "original_objective": original_objective,
            "domain": domain,
            "research_brief": research_brief[:6000],
            "allowed_object_types": sorted(MATURE_SEARCHABLE_OBJECT_TYPES),
            "sub_hypotheses": batch,
        }
        try:
            raw = _call_project_llm_json(
                system=system,
                prompt=(instructions + "\n\nINPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str)),
                max_tokens=OBJECT_MATURITY_LLM_MAX_TOKENS,
                fallback_list_key="object_candidate_sets",
            )
        except Exception as exc:
            log_event(
                "WARN", "mature_searchable_object_candidate_generation_failed",
                sub_hypothesis_ids=[str(item.get("id") or "") for item in batch],
                error=str(exc)[:500],
            )
            continue
        for candidate_set in raw.get("object_candidate_sets", []) if isinstance(raw, dict) else []:
            if not isinstance(candidate_set, dict):
                continue
            sub_id = str(candidate_set.get("sub_hypothesis_id") or "").strip()
            if not sub_id:
                continue
            normalized_candidates = []
            for candidate in candidate_set.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                validation = _mature_searchable_object_candidate_validation(candidate)
                normalized_candidates.append({**candidate, "validation": validation})
            selected = next(
                (candidate for candidate in normalized_candidates if candidate["validation"].get("passes")),
                None,
            )
            output[sub_id] = {
                "schema_version": MATURE_OBJECT_CANDIDATE_PROMPT_VERSION,
                "candidates": normalized_candidates[:6],
                "selected_candidate": selected,
                "rewrite_required_if_no_candidate": bool(
                    candidate_set.get("rewrite_required_if_no_candidate", True)
                ),
                "rewrite_reason": normalize_space(str(candidate_set.get("rewrite_reason") or "")),
                "llm_called": True,
            }
    return output


def _apply_mature_searchable_object_candidate(
    item: dict[str, Any],
    candidate_set: dict[str, Any] | None,
) -> None:
    """Persist candidate generation and make a selected object the SH retrieval identity."""

    candidate_set = candidate_set if isinstance(candidate_set, dict) else {}
    item["mature_searchable_object_candidates"] = candidate_set
    selected = candidate_set.get("selected_candidate")
    if not isinstance(selected, dict) or not isinstance(selected.get("validation"), dict):
        return
    validation = selected["validation"]
    if not validation.get("passes"):
        return
    selected_object = str(validation.get("scientific_object") or "").strip()
    if not selected_object:
        return
    original_object = normalize_space(str(item.get("scientific_object") or ""))
    item["retrieval_object_profile"] = {
        "schema_version": MATURE_OBJECT_CANDIDATE_PROMPT_VERSION,
        "role": "mature_searchable_object",
        "scientific_object": selected_object,
        "object_type": str(validation.get("object_type") or ""),
        "aliases": list(validation.get("aliases") or []),
        "retrieval_terms": list(validation.get("retrieval_terms") or []),
        "source": "llm_mature_object_candidate_generation",
    }
    # The original broad label remains auditable, while all alignment and query
    # code sees the concrete object rather than treating a future umbrella as a
    # direct literature entity.
    if original_object and _object_maturity_anchor_key(original_object) != _object_maturity_anchor_key(selected_object):
        item["original_scientific_object"] = original_object
    item["scientific_object"] = selected_object
    item["scientific_object_aliases"] = _object_maturity_unique(
        [*normalize_text_list(item.get("scientific_object_aliases")), *validation.get("aliases", [])],
        limit=12,
    )


def _llm_subhypothesis_object_maturity_audits(
    sub_hypotheses: list[dict[str, Any]],
    *,
    parent_objective: str,
    original_objective: str,
    domain: str,
    research_brief: str,
    academic_reframing: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    compact_items = []
    for item in sub_hypotheses:
        if not isinstance(item, dict):
            continue
        compact_items.append({
            "id": str(item.get("id") or ""),
            "focus": str(item.get("focus") or "")[:800],
            "scientific_object": str(item.get("scientific_object") or "")[:300],
            "scientific_object_aliases": normalize_text_list(item.get("scientific_object_aliases"))[:12],
            "independent_variable": str(item.get("independent_variable") or "")[:300],
            "dependent_variables": normalize_text_list(item.get("dependent_variables"))[:8],
            "causal_chain": normalize_text_list(item.get("causal_chain"))[:8],
            "retrieval_query": str(item.get("retrieval_query") or "")[:400],
            "evidence_paths": [
                {
                    "id": str(path.get("id") or ""),
                    "role": str(path.get("role") or ""),
                    "query": str(path.get("retrieval_query") or "")[:240],
                }
                for path in (item.get("evidence_paths") or [])
                if isinstance(path, dict)
            ][:8],
        })
    if not compact_items:
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    system_prompt = (
        "You are a scientific literature-anchorability auditor. You decide whether a "
        "sub-hypothesis's declared scientific_object is a mature literature identity and, "
        "separately, how complete the SH-level claim is. Never treat an unresolved overall "
        "mechanism as proof that a named, established object is unsearchable. Return JSON only."
    )
    prompt_prefix = (
        "Audit only the sub-hypotheses in the supplied batch before retrieval. Do not judge whether "
        "the future goal is interesting; first judge whether each declared scientific_object can be used "
        "as a direct strong literature anchor for already-existing empirical/formal papers, then separately "
        "judge the completeness of the whole SH claim. Do not "
        "treat components, mediators, enabling methods, model systems, platforms, or comparators as "
        "synonyms of an unformed final object. If direct evidence is not yet a stable literature "
        "object, route it as component_evidence_only, translational_bridge, or "
        "speculative_unanchored. This is domain-general: apply it to natural sciences, medicine, "
        "engineering, materials, computation, mathematics, and environmental science without "
        "using humanities/social-science-only standards.\n\n"
        "Status meanings:\n"
        "- directly_established: a stable term and direct experimental/formal system exist; declared local causal edges are searchable.\n"
        "- component_evidence_only: final object is too synthetic/umbrella-like; literature supports enabling components only.\n"
        "- translational_bridge: direct final evidence is absent, but model-system or cross-scale bridge evidence is plausible.\n"
        "- speculative_unanchored: final object is mainly a future capability/vision; direct-core validation must be forbidden.\n\n"
        "For non-direct statuses, return typed anchors, not a bag of template words. Every "
        "component_bridge_boundary SH must include at least one object_anchors item and at least "
        "one method_or_platform_anchors, readout_anchors, or model_system_anchors item. "
        "Template modifiers such as model system, platform validation, mechanism assay, "
        "translation, cross-scale validation, therapeutic applications, improvement in symptoms, "
        "ethical implications, neurological damage, safety, failure mode, heterogeneity, "
        "stability, limitation, and disease-related pathways must go in role_modifiers or "
        "forbidden_as_object_anchors, never object_anchors. Use searchable natural-science, "
        "health, engineering, computation, mathematics, materials, chemical, environmental, "
        "earth/agricultural, or formal-model anchors; ignore humanities/social-science-only "
        "framing terms as anchor sources. Do not emit legacy flat anchor fields; "
        "only the typed anchor groups are operational. "
        "A mature direct object may have direct local-edge evidence even if its full mechanism is open. "
        "In that case set object_identity_maturity=MATURE_DIRECT_OBJECT, "
        "direct_local_edge_evidence_allowed=true, whole_sh_direct_core_allowed=false, and use "
        "claim_completeness=PARTIAL_CAUSAL_CHAIN_SUPPORTED or WHOLE_CLAIM_NOT_ESTABLISHED. "
        "Set both direct permissions false only when the object itself is unformed, future, or merely a component/platform. "
        "Do not decide a retrieval_mode: the program derives that from the two dimensions above.\n\n"
    )
    output_schema = (
        "Return exactly one JSON object containing audits for only the supplied batch:\n"
        "{\n"
        '  "audits": [\n'
        "    {\n"
        '      "sub_hypothesis_id": "SH1",\n'
        '      "object_status": "directly_established|component_evidence_only|translational_bridge|speculative_unanchored",\n'
        '      "object_identity_maturity": "MATURE_DIRECT_OBJECT|MATURE_COMPARABLE_SYSTEM|COMPONENT_OR_PLATFORM_ONLY|FUTURE_OR_UNFORMED_OBJECT",\n'
        '      "claim_completeness": "DIRECT_LOCAL_EDGE_SUPPORTED|PARTIAL_CAUSAL_CHAIN_SUPPORTED|WHOLE_CLAIM_ESTABLISHED|WHOLE_CLAIM_NOT_ESTABLISHED",\n'
        '      "direct_object_anchorable": true,\n'
        '      "direct_local_edge_evidence_allowed": true,\n'
        '      "whole_sh_direct_core_allowed": false,\n'
        '      "direct_core_evidence_allowed": true,\n'
        '      "mature_direct_search_terms": ["only if directly established"],\n'
        '      "object_anchors": ["searchable component object/entity terms, e.g. material, pathway, disease, circuit, device, algorithm object"],\n'
        '      "method_or_platform_anchors": ["searchable methods/platforms such as assay names, stimulation methods, sequencing, spectroscopy, simulation, reactor, LCA, benchmark"],\n'
        '      "readout_anchors": ["measurable readouts such as recall accuracy, fidelity, yield, AUC, RMSE, toxicity"],\n'
        '      "model_system_anchors": ["model systems such as mouse, organoid, pilot-scale reactor, cohort, finite-element model, benchmark dataset"],\n'
        '      "role_modifiers": ["modifier-only words such as translation, safety, feasibility, platform validation"],\n'
        '      "forbidden_as_object_anchors": ["anchors that are too generic to count as object identity"],\n'
        '      "forbidden_direct_core_claims": ["claims that component papers must not be used to support"],\n'
        '      "bridge_gap_statement": "what gap remains between component evidence and the parent objective",\n'
        '      "rewrite_reason": "brief audit rationale",\n'
        '      "scope_preservation": "how the original objective is preserved without overclaiming",\n'
        '      "audit_basis": ["short evidence for the classification"]\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    batch_size = max(1, int(OBJECT_MATURITY_LLM_BATCH_SIZE or 2))
    for batch_start in range(0, len(compact_items), batch_size):
        batch_items = compact_items[batch_start : batch_start + batch_size]
        payload = {
            "parent_objective": parent_objective,
            "original_objective": original_objective,
            "domain": domain,
            "research_brief": research_brief[:6000],
            "academic_reframing": academic_reframing or {},
            "batch": {
                "batch_index": batch_start // batch_size + 1,
                "batch_size": len(batch_items),
                "max_batch_size": batch_size,
            },
            "sub_hypotheses": batch_items,
        }
        try:
            raw = _call_project_llm_json(
                system=system_prompt,
                prompt=(
                    prompt_prefix
                    + f"INPUT_JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
                    + output_schema
                ),
                max_tokens=OBJECT_MATURITY_LLM_MAX_TOKENS,
                fallback_list_key="audits",
            )
        except Exception as exc:
            log_event(
                "WARN",
                "object_maturity_llm_batch_failed",
                batch_index=batch_start // batch_size + 1,
                batch_size=len(batch_items),
                sub_hypothesis_ids=[
                    str(item.get("id") or "")
                    for item in batch_items
                    if isinstance(item, dict)
                ],
                error=str(exc)[:500],
            )
            continue
        audits = raw.get("audits") if isinstance(raw, dict) else []
        for audit in audits if isinstance(audits, list) else []:
            if not isinstance(audit, dict):
                continue
            sub_id = str(audit.get("sub_hypothesis_id") or audit.get("id") or "").strip()
            if sub_id:
                by_id[sub_id] = audit
    return by_id


def _component_bridge_evidence_paths_for_audit(
    item: dict[str, Any],
    audit: dict[str, Any],
) -> list[dict[str, Any]]:
    scientific_object = normalize_space(str(item.get("scientific_object") or ""))
    focus = normalize_space(str(item.get("focus") or scientific_object))
    readouts = normalize_text_list(item.get("dependent_variables"))
    readout = _preflight_first_concrete_readout(readouts, readouts) or (
        readouts[0] if readouts else "measurable readout"
    )
    typed = (
        audit.get("typed_component_bridge_anchors")
        if isinstance(audit.get("typed_component_bridge_anchors"), dict)
        else {}
    )
    object_anchors = _object_maturity_unique(
        normalize_text_list(audit.get("object_anchors"))
        + normalize_text_list(typed.get("object_anchors")),
        limit=10,
    )
    method_anchors = _object_maturity_unique(
        normalize_text_list(audit.get("method_or_platform_anchors"))
        + normalize_text_list(typed.get("method_or_platform_anchors")),
        limit=10,
    )
    readout_anchors = _object_maturity_unique(
        normalize_text_list(audit.get("readout_anchors"))
        + normalize_text_list(typed.get("readout_anchors"))
        + ([readout] if readout and readout != "measurable readout" else []),
        limit=10,
    )
    model_system_anchors = _object_maturity_unique(
        normalize_text_list(audit.get("model_system_anchors"))
        + normalize_text_list(typed.get("model_system_anchors")),
        limit=10,
    )
    role_modifiers = _object_maturity_unique(
        normalize_text_list(audit.get("role_modifiers"))
        + normalize_text_list(typed.get("role_modifiers")),
        limit=12,
    )
    component_anchors = _object_maturity_unique(
        object_anchors + method_anchors + model_system_anchors + readout_anchors,
        limit=12,
    )
    bridge_anchors = _object_maturity_unique(
        object_anchors + model_system_anchors + method_anchors[:4],
        limit=8,
    )
    boundary_anchors: list[str] = []
    bridge_gap = str(audit.get("bridge_gap_statement") or "")
    component_support_anchors = _object_maturity_unique(
        method_anchors + readout_anchors + model_system_anchors,
        limit=12,
    )
    structured_query_groups = {
        "required_object_group": object_anchors,
        "required_method_or_mechanism_group": method_anchors,
        "optional_model_group": model_system_anchors,
        "optional_readout_group": readout_anchors,
        "modifiers": role_modifiers,
        "forbidden_terms": normalize_text_list(item.get("query_forbidden_terms")),
    }
    return [
        {
            "id": "component_evidence_path",
            "role": "component_evidence",
            "polarity": "supportive",
            "causal_steps": [
                "component, enabling method, model system, or platform evidence",
                ", ".join(component_anchors[:5]),
                readout,
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchors[:5],
                component_support_anchors[:6],
                fallback=str(item.get("retrieval_query") or focus),
            ),
            "structured_query_groups": structured_query_groups,
            "failure_scope": "component_support_gap_not_direct_core_falsification",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "component_anchor_group": component_anchors[:8],
            "component_object_anchor_group": object_anchors[:8],
            "method_or_platform_anchor_group": method_anchors[:8],
            "readout_anchor_group": readout_anchors[:8],
            "model_system_anchor_group": model_system_anchors[:8],
            "role_modifiers": role_modifiers[:8],
            "component_evidence_counts_as_core": False,
            "direct_core_disallowed_by_object_maturity": True,
            "source": "object_maturity_component_bridge_rewrite",
        },
        {
            "id": "translational_bridge_path",
            "role": "translational_bridge",
            "polarity": "boundary",
            "causal_steps": [
                "component evidence in a model or bounded system",
                ", ".join(bridge_anchors[:5]),
                f"bridge validity toward {scientific_object}",
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchors[:5],
                _object_maturity_unique(model_system_anchors + method_anchors + readout_anchors, limit=6),
                fallback=str(item.get("retrieval_query") or focus),
            ),
            "structured_query_groups": structured_query_groups,
            "failure_scope": "translation_bridge_gap",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "component_anchor_group": list(dict.fromkeys([*bridge_anchors[:6], *component_anchors[:4]])),
            "component_object_anchor_group": object_anchors[:8],
            "method_or_platform_anchor_group": method_anchors[:8],
            "readout_anchor_group": readout_anchors[:8],
            "model_system_anchor_group": model_system_anchors[:8],
            "role_modifiers": role_modifiers[:8],
            "component_evidence_counts_as_core": False,
            "direct_core_disallowed_by_object_maturity": True,
            "source": "object_maturity_component_bridge_rewrite",
        },
        {
            "id": "boundary_or_safety_evidence_path",
            "role": "boundary_or_safety_evidence",
            "polarity": "boundary",
            "causal_steps": [
                "component or bridge evidence",
                ", ".join(boundary_anchors[:5]),
                bridge_gap or f"conditions limiting transfer to {scientific_object}",
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchors[:4],
                component_support_anchors[:5],
                boundary_anchors[:5],
                fallback=str(item.get("retrieval_query") or focus),
            ),
            "structured_query_groups": structured_query_groups,
            "failure_scope": "boundary_safety_gap",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "component_anchor_group": list(dict.fromkeys([*boundary_anchors[:6], *component_anchors[:4]])),
            "component_object_anchor_group": object_anchors[:8],
            "method_or_platform_anchor_group": method_anchors[:8],
            "readout_anchor_group": readout_anchors[:8],
            "model_system_anchor_group": model_system_anchors[:8],
            "role_modifiers": role_modifiers[:8],
            "component_evidence_counts_as_core": False,
            "direct_core_disallowed_by_object_maturity": True,
            "source": "object_maturity_component_bridge_rewrite",
        },
        {
            "id": "context_review",
            "role": "background_or_framework",
            "polarity": "context",
            "causal_steps": [
                f"definitions and feasibility map for {scientific_object}",
                bridge_gap or "direct-object evidence is not assumed",
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchors[:4],
                component_support_anchors[:5],
                bridge_anchors[:3],
                fallback=str(item.get("retrieval_query") or focus),
            ),
            "structured_query_groups": structured_query_groups,
            "failure_scope": "context_only_gap",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "component_anchor_group": list(dict.fromkeys([*component_anchors[:5], *bridge_anchors[:4]])),
            "component_object_anchor_group": object_anchors[:8],
            "method_or_platform_anchor_group": method_anchors[:8],
            "readout_anchor_group": readout_anchors[:8],
            "model_system_anchor_group": model_system_anchors[:8],
            "role_modifiers": role_modifiers[:8],
            "component_evidence_counts_as_core": False,
            "direct_core_disallowed_by_object_maturity": True,
            "source": "object_maturity_component_bridge_rewrite",
        },
    ]


def _apply_object_maturity_retrieval_profile(
    item: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    # This is the only maturity state downstream code may consume.  Replace
    # legacy audit snapshots atomically whenever the retrieval object changes;
    # otherwise one module can see "direct" while another sees "bridge".
    # Most callers pass the normalized v3 audit above.  Keep this small
    # defensive canonicalization as well, because operationality repair and
    # tests may call this boundary directly with an interrupted/stale record.
    audit = dict(audit) if isinstance(audit, dict) else {}
    raw_status = str(audit.get("object_status") or "").strip()
    raw_identity = str(audit.get("object_identity_maturity") or "").strip().upper()
    direct_identity = raw_identity in {
        "MATURE_DIRECT_OBJECT", "MATURE_COMPARABLE_SYSTEM"
    } or raw_status == "directly_established"
    if (
        direct_identity
        and raw_status != "contract_repair_required"
        and audit.get("object_rewrite_required") is not True
    ):
        claim_completeness = str(audit.get("claim_completeness") or "").strip().upper()
        whole_claim_allowed = bool(
            claim_completeness == "WHOLE_CLAIM_ESTABLISHED"
            and audit.get("whole_sh_direct_core_allowed") is True
        )
        audit.update({
            "object_status": "directly_established",
            "object_identity_maturity": raw_identity or "MATURE_DIRECT_OBJECT",
            "direct_object_anchorable": True,
            "direct_local_edge_evidence_allowed": True,
            "direct_core_evidence_allowed": True,
            "whole_sh_direct_core_allowed": whole_claim_allowed,
            "retrieval_mode": "direct_edge_bundle",
            "retrieval_mode_resolution_source": (
                "mature_direct_object_whole_claim_established"
                if whole_claim_allowed
                else "mature_direct_object_local_edges_only"
            ),
            "direct_core_disallowed_reason": "",
            "whole_sh_direct_core_disallowed_reason": (
                ""
                if whole_claim_allowed
                else "whole_claim_not_established"
                if claim_completeness != "WHOLE_CLAIM_ESTABLISHED"
                else "whole_claim_permission_not_declared"
            ),
        })
    item["object_maturity_resolution"] = dict(audit)
    item["object_maturity_audit"] = dict(audit)
    if bool(audit.get("object_rewrite_required")) or str(
        audit.get("retrieval_mode") or ""
    ) == "subhypothesis_object_rewrite_required":
        item["direct_core_evidence_allowed"] = False
        item["direct_local_edge_evidence_allowed"] = False
        item["whole_sh_direct_core_allowed"] = False
        item["object_maturity_retrieval_mode"] = "subhypothesis_object_rewrite_required"
        item["direct_core_disallowed_reason"] = "mature_searchable_object_rewrite_required"
        item["whole_sh_direct_core_disallowed_reason"] = "mature_searchable_object_rewrite_required"
        item["retrieval_mode_resolution_source"] = "mature_searchable_object_rewrite_required"
        item["evidence_path_policy"] = "rewrite_subhypothesis_before_retrieval"
        item["evidence_paths"] = []
        item["retrieval_query"] = ""
        item["status"] = "needs_scientific_object_rewrite"
        item["object_rewrite_required"] = True
        return
    if str(audit.get("retrieval_mode") or "") == "contract_repair_required" or str(
        audit.get("object_status") or ""
    ) == "contract_repair_required":
        item["direct_core_evidence_allowed"] = False
        item["direct_local_edge_evidence_allowed"] = False
        item["whole_sh_direct_core_allowed"] = False
        item["object_maturity_retrieval_mode"] = "contract_repair_required"
        item["direct_core_disallowed_reason"] = "scientific_object_contract_failed"
        item["whole_sh_direct_core_disallowed_reason"] = "scientific_object_contract_failed"
        item["retrieval_mode_resolution_source"] = "scientific_object_contract_failure"
        item["evidence_path_policy"] = "scientific_object_contract_repair_required"
        item["evidence_paths"] = []
        item["retrieval_query"] = ""
        item["status"] = "blocked_scientific_object_contract"
        return
    if bool(audit.get("direct_core_evidence_allowed")):
        item["direct_core_evidence_allowed"] = True
        # ``direct_core_evidence_allowed`` is intentionally retained as the
        # backwards-compatible local-edge permission.  The route name makes
        # the composition rule explicit: different papers may support
        # different edges, and one paper need not close the whole SH.
        item["object_maturity_retrieval_mode"] = str(
            audit.get("retrieval_mode") or "direct_edge_bundle"
        )
        item["direct_local_edge_evidence_allowed"] = True
        item["whole_sh_direct_core_allowed"] = bool(
            audit.get("whole_sh_direct_core_allowed") is True
        )
        item["whole_sh_direct_core_disallowed_reason"] = str(
            audit.get("whole_sh_direct_core_disallowed_reason") or ""
        )
        item["retrieval_mode_resolution_source"] = str(
            audit.get("retrieval_mode_resolution_source")
            or "mature_direct_object_local_edges_only"
        )
        # Remove state from a previous component-bridge pass.  Leaving any of
        # these markers behind activates component operationality downstream
        # even after the current canonical audit has restored direct identity.
        item.pop("direct_core_disallowed_reason", None)
        item.pop("direct_core_disallowed_by_object_maturity", None)
        if str(item.get("evidence_path_policy") or "") in {
            "component_bridge_boundary_paths",
            "component_bridge_anchor_repair_required",
        }:
            item["evidence_paths"] = []
        item["evidence_path_policy"] = "cross_paper_edge_bundle_paths"
        causal_contract = (
            dict(item.get("causal_contract"))
            if isinstance(item.get("causal_contract"), dict)
            else {}
        )
        causal_contract["core_evidence_definition"] = (
            "A source-bound test of one declared SH-local causal edge. "
            "Cross-paper edge composition is permitted; a single paper does "
            "not need to prove the complete sub-hypothesis."
        )
        causal_contract["whole_sh_claim_policy"] = (
            "whole_claim_allowed"
            if item["whole_sh_direct_core_allowed"]
            else "compose_and_calibrate_to_weakest_edge"
        )
        item["causal_contract"] = causal_contract
        return
    item["direct_core_evidence_allowed"] = False
    item["object_maturity_retrieval_mode"] = "component_bridge_boundary"
    item["direct_local_edge_evidence_allowed"] = False
    item["whole_sh_direct_core_allowed"] = False
    item["direct_core_disallowed_reason"] = str(
        audit.get("direct_core_disallowed_reason")
        or "object_identity_not_directly_anchorable"
    )
    item["whole_sh_direct_core_disallowed_reason"] = str(
        audit.get("whole_sh_direct_core_disallowed_reason")
        or item["direct_core_disallowed_reason"]
    )
    item["retrieval_mode_resolution_source"] = str(
        audit.get("retrieval_mode_resolution_source")
        or "non_direct_object_identity"
    )
    anchor_quality = (
        audit.get("component_bridge_anchor_quality")
        if isinstance(audit.get("component_bridge_anchor_quality"), dict)
        else {}
    )
    item["component_bridge_anchor_quality"] = anchor_quality
    item["typed_component_bridge_anchors"] = (
        dict(audit.get("typed_component_bridge_anchors"))
        if isinstance(audit.get("typed_component_bridge_anchors"), dict)
        else {}
    )
    if anchor_quality.get("passes") is False:
        item["status"] = "component_bridge_anchor_repair_required"
        item["evidence_path_policy"] = "component_bridge_anchor_repair_required"
        item["evidence_paths"] = []
    else:
        item["evidence_path_policy"] = "component_bridge_boundary_paths"
        item["evidence_paths"] = _component_bridge_evidence_paths_for_audit(item, audit)
    item["object_anchors"] = _object_maturity_unique(audit.get("object_anchors"), limit=8)
    item["method_or_platform_anchors"] = _object_maturity_unique(audit.get("method_or_platform_anchors"), limit=8)
    item["readout_anchors"] = _object_maturity_unique(audit.get("readout_anchors"), limit=8)
    item["model_system_anchors"] = _object_maturity_unique(audit.get("model_system_anchors"), limit=8)
    item["role_modifiers"] = _object_maturity_unique(audit.get("role_modifiers"), limit=12)
    item["forbidden_as_object_anchors"] = _object_maturity_unique(audit.get("forbidden_as_object_anchors"), limit=12)
    item["component_evidence_anchors"] = []
    item["translational_bridge_anchors"] = []
    item["boundary_or_safety_anchors"] = []
    item["retrieval_query"] = (
        ""
        if anchor_quality.get("passes") is False
        else _compact_retrieval_query(
            item["object_anchors"][:5],
            (
                item["method_or_platform_anchors"][:4]
                + item["model_system_anchors"][:3]
                + item["readout_anchors"][:3]
            ),
            fallback=str(item.get("retrieval_query") or item.get("focus") or ""),
        )
    )
    causal_contract = (
        dict(item.get("causal_contract"))
        if isinstance(item.get("causal_contract"), dict)
        else {}
    )
    causal_contract["core_evidence_definition"] = (
        "Direct-core evidence for the final declared object is disallowed until "
        "the object has a stable literature identity; component and bridge papers "
        "may inform feasibility, mechanisms, and gaps only."
    )
    causal_contract["auxiliary_evidence_definition"] = (
        "Component, platform, model-system, translational-bridge, boundary, and safety evidence."
    )
    causal_contract["object_maturity_bridge_gap"] = str(audit.get("bridge_gap_statement") or "")
    item["causal_contract"] = causal_contract
    if anchor_quality.get("passes") is not False:
        item["status"] = (
            "pending_component_bridge_retrieval"
            if str(item.get("status") or "").startswith("pending") or not str(item.get("status") or "")
            else item.get("status")
        )


def annotate_subhypotheses_object_maturity_preflight(
    sub_hypotheses: list[dict[str, Any]],
    *,
    parent_objective: str,
    original_objective: str = "",
    domain: str = "",
    research_brief: str = "",
    academic_reframing: dict[str, Any] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    items = [item for item in (sub_hypotheses or []) if isinstance(item, dict)]
    candidate_sets: dict[str, dict[str, Any]] = {}
    candidate_generation_error = ""
    # Object selection intentionally precedes every object-contract and
    # maturity audit.  Otherwise a broad aspirational label can consume a
    # retrieval budget before the system ever asks for a usable literature
    # identity.
    if use_llm and items:
        try:
            candidate_sets = _llm_mature_searchable_object_candidates(
                items,
                parent_objective=parent_objective,
                original_objective=original_objective,
                domain=domain,
                research_brief=research_brief,
            )
        except Exception as exc:
            candidate_generation_error = str(exc)[:500]
            candidate_sets = {}
    for index, item in enumerate(items):
        sub_id = str(item.get("id") or f"SH{index + 1}")
        candidate_set = candidate_sets.get(sub_id)
        if candidate_set:
            _apply_mature_searchable_object_candidate(item, candidate_set)
    object_contract_audits = {
        str(item.get("id") or f"SH{index + 1}"): audit_subhypothesis_scientific_object_contract(item)
        for index, item in enumerate(items)
    }
    for index, item in enumerate(items):
        sub_id = str(item.get("id") or f"SH{index + 1}")
        audit = object_contract_audits.get(sub_id) or {}
        audit["sub_hypothesis_id"] = sub_id
        _apply_scientific_object_contract_audit_to_item(item, audit)
    maturity_eligible_items = [
        item
        for index, item in enumerate(items)
        if (object_contract_audits.get(str(item.get("id") or f"SH{index + 1}")) or {}).get("valid") is True
    ]
    llm_audits: dict[str, dict[str, Any]] = {}
    llm_error = ""
    if use_llm and maturity_eligible_items:
        try:
            llm_audits = _llm_subhypothesis_object_maturity_audits(
                maturity_eligible_items,
                parent_objective=parent_objective,
                original_objective=original_objective,
                domain=domain,
                research_brief=research_brief,
                academic_reframing=academic_reframing,
            )
        except Exception as exc:
            llm_error = str(exc)[:500]
            llm_audits = {}
    counts = {status: 0 for status in _OBJECT_MATURITY_STATUSES}
    component_bridge_ids: list[str] = []
    anchor_repair_ids: list[str] = []
    direct_disallowed_ids: list[str] = []
    whole_sh_direct_disallowed_ids: list[str] = []
    object_rewrite_required_ids: list[str] = []
    audits_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        sub_id = str(item.get("id") or f"SH{index + 1}")
        object_contract = object_contract_audits.get(sub_id) or {}
        if object_contract.get("valid") is False:
            audit = _normalize_object_maturity_audit(
                {
                    "object_status": "contract_repair_required",
                    "direct_object_anchorable": False,
                    "direct_core_evidence_allowed": False,
                    "retrieval_mode": "contract_repair_required",
                    "forbidden_direct_core_claims": [
                        "Do not search, import, or synthesize this SH until scientific_object is repaired."
                    ],
                    "bridge_gap_statement": "The scientific_object field is a research action, boundary parameter, or readout rather than a searchable scientific object.",
                    "rewrite_reason": str(object_contract.get("error_code") or "invalid scientific_object contract"),
                    "scope_preservation": "Repair the object slot first; do not downgrade this schema error into component-bridge retrieval.",
                },
                sub_hypothesis=item,
                parent_objective=parent_objective,
                original_objective=original_objective,
                domain=domain,
                research_brief=research_brief,
                extractor="scientific_object_contract_gate",
            )
            item["object_maturity_preflight"] = audit
            _apply_object_maturity_retrieval_profile(item, audit)
            status = str(audit.get("object_status") or "contract_repair_required")
            counts[status] = counts.get(status, 0) + 1
            direct_disallowed_ids.append(sub_id)
            whole_sh_direct_disallowed_ids.append(sub_id)
            audits_by_id[sub_id] = audit
            continue
        heuristic = _heuristic_subhypothesis_object_maturity_audit(
            item,
            parent_objective=parent_objective,
            original_objective=original_objective,
            domain=domain,
            research_brief=research_brief,
        )
        declared_audit = (
            item.get("object_maturity_audit")
            if isinstance(item.get("object_maturity_audit"), dict)
            else item.get("object_maturity_preflight")
            if isinstance(item.get("object_maturity_preflight"), dict)
            else {}
        )
        raw = llm_audits.get(sub_id) or declared_audit
        audit = _normalize_object_maturity_audit(
            raw,
            sub_hypothesis=item,
            parent_objective=parent_objective,
            original_objective=original_objective,
            domain=domain,
            research_brief=research_brief,
            extractor=(
                "llm"
                if sub_id in llm_audits
                else "declared"
                if declared_audit
                else heuristic.get("extractor") or "heuristic"
            ),
        ) if raw else heuristic
        # A deterministic high-risk finding is used as a safety floor when the
        # LLM returns a direct status but supplies no direct search terms. This
        # prevents a future capability from becoming a hard object anchor just
        # because it was phrased with measurable endpoints.
        if (
            heuristic.get("object_status") in _OBJECT_MATURITY_COMPONENT_STATUSES
            and audit.get("object_status") == "directly_established"
            and not audit.get("mature_direct_search_terms")
        ):
            audit = {
                **heuristic,
                "extractor": "heuristic_safety_override_after_llm",
                "llm_audit_overridden": raw,
            }
        candidate_set = candidate_sets.get(sub_id) or {}
        # A component/bridge conclusion is not a license to run a large core
        # quota against an object explicitly deemed non-direct.  It is the
        # signal that this SH needs a more concrete object rewrite.  The LLM's
        # candidates remain attached so the next decomposition/revision turn
        # has specific, auditable alternatives instead of generic advice.
        if (
            str(audit.get("object_status") or "") in _OBJECT_MATURITY_COMPONENT_STATUSES
            and not candidate_set.get("selected_candidate")
        ):
            audit = {
                **audit,
                "retrieval_mode": "subhypothesis_object_rewrite_required",
                "direct_core_evidence_allowed": False,
                "object_rewrite_required": True,
                "rewrite_reason": (
                    str(candidate_set.get("rewrite_reason") or "")
                    or str(audit.get("rewrite_reason") or "")
                    or "No mature, searchable object candidate was available for direct evidence retrieval."
                ),
            }
        item["object_maturity_preflight"] = audit
        _apply_object_maturity_retrieval_profile(item, audit)
        status = str(audit.get("object_status") or "directly_established")
        counts[status] = counts.get(status, 0) + 1
        quality = (
            audit.get("component_bridge_anchor_quality")
            if isinstance(audit.get("component_bridge_anchor_quality"), dict)
            else {}
        )
        if quality.get("passes") is False:
            anchor_repair_ids.append(sub_id)
        elif audit.get("retrieval_mode") == "component_bridge_boundary":
            component_bridge_ids.append(sub_id)
        if audit.get("object_rewrite_required") is True:
            object_rewrite_required_ids.append(sub_id)
        if not audit.get("direct_core_evidence_allowed"):
            direct_disallowed_ids.append(sub_id)
        if audit.get("whole_sh_direct_core_allowed") is not True:
            whole_sh_direct_disallowed_ids.append(sub_id)
        audits_by_id[sub_id] = audit
    summary = {
        "schema_version": OBJECT_MATURITY_PREFLIGHT_VERSION,
        "total": len(items),
        "directly_established": counts.get("directly_established", 0),
        "component_evidence_only": counts.get("component_evidence_only", 0),
        "translational_bridge": counts.get("translational_bridge", 0),
        "speculative_unanchored": counts.get("speculative_unanchored", 0),
        "contract_repair_required": counts.get("contract_repair_required", 0),
        "contract_repair_required_sub_hypothesis_ids": [
            sub_id
            for sub_id, audit in audits_by_id.items()
            if str(audit.get("object_status") or "") == "contract_repair_required"
        ],
        "component_bridge_retrieval": len(component_bridge_ids),
        "component_bridge_retrieval_sub_hypothesis_ids": component_bridge_ids,
        "component_bridge_anchor_repair_required": len(anchor_repair_ids),
        "component_bridge_anchor_repair_required_sub_hypothesis_ids": anchor_repair_ids,
        "direct_core_disallowed": len(direct_disallowed_ids),
        "direct_core_disallowed_sub_hypothesis_ids": direct_disallowed_ids,
        "whole_sh_direct_core_disallowed": len(whole_sh_direct_disallowed_ids),
        "whole_sh_direct_core_disallowed_sub_hypothesis_ids": whole_sh_direct_disallowed_ids,
        "object_rewrite_required": len(object_rewrite_required_ids),
        "object_rewrite_required_sub_hypothesis_ids": object_rewrite_required_ids,
        "status_by_id": {
            sub_id: str(audit.get("object_status") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "retrieval_mode_by_id": {
            sub_id: str(audit.get("retrieval_mode") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "retrieval_mode_resolution_source_by_id": {
            sub_id: str(audit.get("retrieval_mode_resolution_source") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "object_identity_maturity_by_id": {
            sub_id: str(audit.get("object_identity_maturity") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "claim_completeness_by_id": {
            sub_id: str(audit.get("claim_completeness") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "direct_local_edge_evidence_allowed_by_id": {
            sub_id: bool(audit.get("direct_local_edge_evidence_allowed") is True)
            for sub_id, audit in audits_by_id.items()
        },
        "whole_sh_direct_core_allowed_by_id": {
            sub_id: bool(audit.get("whole_sh_direct_core_allowed") is True)
            for sub_id, audit in audits_by_id.items()
        },
        "direct_core_disallowed_reason_by_id": {
            sub_id: str(audit.get("direct_core_disallowed_reason") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "whole_sh_direct_core_disallowed_reason_by_id": {
            sub_id: str(audit.get("whole_sh_direct_core_disallowed_reason") or "")
            for sub_id, audit in audits_by_id.items()
        },
        "audits_by_id": audits_by_id,
        "llm_error": llm_error,
        "mature_object_candidate_prompt_version": MATURE_OBJECT_CANDIDATE_PROMPT_VERSION,
        "mature_object_candidate_sets_generated": len(candidate_sets),
        "mature_object_candidate_generation_error": candidate_generation_error,
    }
    return summary


def normalize_causal_contract(
    value: Any,
    *,
    objective: str,
    focus: str,
    independent_variable: str,
    causal_chain: list[str],
    dependent_variables: list[str],
    alternative_mechanisms: list[str],
    boundary_conditions: list[str],
    epistemic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize the scientific contract without forcing all mediators into search.

    The legacy causal chain is retained only as an audit field elsewhere.
    It is not used to repair missing contract axes here: pivotal mechanism
    and outcome must be explicitly declared by the causal contract.
    """

    source = value if isinstance(value, dict) else {}
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    raw_constraint_type = normalize_space(str(source.get("constraint_type") or ""))
    constraint_type = re.sub(r"[^a-z0-9]+", "_", raw_constraint_type.lower()).strip("_")
    if not constraint_type:
        claim_types = profile.get("claim_types") if isinstance(profile.get("claim_types"), list) else []
        constraint_type = str(claim_types[0] if claim_types else "causal_constraint")
    # A missing pivotal edge is a contract defect, not evidence that the
    # sub-hypothesis focus is itself a mechanism.  Falling back to ``focus``
    # (or the first causal step) makes the scientific object, input, and
    # mechanism collapse onto one phrase and is only discovered by the
    # pre-provider degeneracy gate.  Preserve the absence so the retrieval
    # layer can route the SH through contract repair or a non-causal query
    # shape explicitly.
    pivotal_mechanism = normalize_space(str(
        source.get("pivotal_mechanism") or ""
    ))
    supplied_mediators = normalize_text_list(source.get("supporting_mediators"))
    supporting_mediators = list(dict.fromkeys(supplied_mediators))[:6]
    declared_outcome = normalize_space(str(source.get("outcome") or ""))
    input_contract = _normalize_causal_input_contract(
        source,
        independent_variable=independent_variable,
    )
    claim_layer_contract = _normalize_causal_claim_layer_contract(
        source,
        declared_outcome=declared_outcome,
    )
    # Downstream edge retrieval always sees a locally observable endpoint.
    # A transfer target remains an explicit T1 interpretation edge; it never
    # silently replaces the E2 local mechanism -> outcome endpoint.
    outcome = normalize_space(str(
        claim_layer_contract.get("local_empirical_outcome") or declared_outcome
    ))
    pivotal_mechanism_role = _pivotal_mechanism_role_assessment(
        {
            "pivotal_mechanism": pivotal_mechanism,
            "pivotal_mechanism_role": source.get("pivotal_mechanism_role")
            or source.get("mechanism_role"),
        },
        dependent_variables=dependent_variables,
    )
    return {
        "version": "claim_evidence_contract_v3",
        "parent_decision_link": normalize_space(str(
            source.get("parent_decision_link") or objective or focus
        )),
        "constraint_type": constraint_type,
        "primary_epistemic_mode": str(profile.get("primary_mode") or ""),
        "claim_types": list(profile.get("claim_types") or []),
        "requires_intervention": bool(profile.get("requires_intervention") is True),
        "input_contract": input_contract,
        "pivotal_mechanism": pivotal_mechanism,
        "pivotal_mechanism_role": pivotal_mechanism_role.get("effective_role"),
        "pivotal_mechanism_role_assessment": pivotal_mechanism_role,
        "supporting_mediators": supporting_mediators,
        "outcome": outcome,
        "claim_layer_contract": claim_layer_contract,
        "boundary_conditions": list(dict.fromkeys(
            normalize_text_list(source.get("boundary_conditions"))
            + list(boundary_conditions)
        ))[:6],
        "confounders_or_alternatives": list(dict.fromkeys(
            normalize_text_list(source.get("confounders_or_alternatives"))
            + list(alternative_mechanisms)
        ))[:6],
        "path_failure_policy": normalize_path_failure_policy(
            source.get("path_failure_policy"),
            focus=focus,
            outcome=outcome,
        ),
    }


def _path_role_core_falsification_capable(role: str, path_id: str = "") -> bool:
    role_metadata = EVIDENCE_ROLE_REGISTRY.get(str(role or "").strip().lower())
    if role_metadata is None:
        role_metadata = EVIDENCE_ROLE_REGISTRY.get(str(path_id or "").strip().lower())
    if role_metadata is not None:
        return bool(role_metadata.get("core_eligible") is True)
    text = f"{role} {path_id}".lower()
    if any(
        marker in text
        for marker in (
            "direct_observation", "parameter_constraint", "model_comparison",
            "theoretical_derivation", "formal_proof", "counterexample",
            "simulation_validation", "performance_validation", "descriptive_catalog",
            "evidence_synthesis", "direct_claim_validation",
        )
    ):
        return True
    if any(marker in text for marker in ("support", "component", "context", "background", "framework", "constraint")):
        return False
    return any(
        marker in text
        for marker in (
            "core", "validation", "validated", "external", "generalization",
            "compar", "increment", "causal_identification", "causal_validation",
            "predictive_validation", "integrative", "integrated", "adverse",
            "reversal", "opposing", "tradeoff", "trade_off",
        )
    )


def normalize_path_failure_policy(
    value: Any,
    *,
    focus: str,
    outcome: str = "",
) -> dict[str, Any]:
    """State how path-level negative/missing evidence affects the SH.

    This is intentionally role-based, not discipline-based.  It prevents a
    single component path from being over-interpreted as proof or refutation of
    a panel-level/integrated-model SH.
    """

    source = value if isinstance(value, dict) else {}
    observable = normalize_space(outcome) or "the decision-relevant outcome"
    return {
        "version": "path_failure_policy_v1",
        "whole_sh_falsification_rule": normalize_space(str(
            source.get("whole_sh_falsification_rule")
            or source.get("core_failure_rule")
            or source.get("integrative_failure_rule")
            or (
                f"The sub-hypothesis is falsified primarily when its core or "
                f"integrative validation path fails to support {focus} against "
                f"the declared comparison on {observable}."
            )
        )),
        "support_path_failure_rule": normalize_space(str(
            source.get("support_path_failure_rule")
            or source.get("component_failure_rule")
            or (
                "Failure, absence, or non-significance of an isolated support "
                "path weakens or localizes the mechanism but does not by itself "
                "falsify the whole sub-hypothesis unless the declared core path "
                "depends on that component."
            )
        )),
        "missing_path_interpretation": normalize_space(str(
            source.get("missing_path_interpretation")
            or (
                "A missing non-core evidence path should be reported as an "
                "evidence gap or boundary condition rather than treated as a "
                "hard retrieval blocker."
            )
        )),
        "component_success_interpretation": normalize_space(str(
            source.get("component_success_interpretation")
            or (
                "Component-level positive evidence supports plausibility, not "
                "completion of the panel-level or integrative core claim."
            )
        )),
        "core_paths_can_falsify_whole_sh": True,
        "support_paths_can_falsify_whole_sh_by_default": False,
        "missing_support_path_blocks_sh": False,
    }


def summarize_evidence_path_failure_policy(
    evidence_paths: list[dict[str, Any]],
    *,
    base_policy: Any = None,
) -> dict[str, Any]:
    policy = base_policy if isinstance(base_policy, dict) else {}
    summaries: list[dict[str, Any]] = []
    core_path_ids: list[str] = []
    support_path_ids: list[str] = []
    for path in evidence_paths:
        if not isinstance(path, dict):
            continue
        path_id = normalize_space(str(path.get("id") or path.get("role") or ""))
        role = normalize_space(str(path.get("role") or ""))
        can_falsify = (
            path.get("can_independently_falsify_sh")
            if isinstance(path.get("can_independently_falsify_sh"), bool)
            else _path_role_core_falsification_capable(role, path_id)
        )
        failure_scope = normalize_space(str(path.get("failure_scope") or ""))
        if not failure_scope:
            failure_scope = (
                "whole_sh_core_falsification"
                if can_falsify
                else "supporting_gap_or_mechanism_weakening"
            )
        if can_falsify:
            core_path_ids.append(path_id)
        else:
            support_path_ids.append(path_id)
        summaries.append({
            "id": path_id,
            "role": role,
            "polarity": _evidence_path_polarity(role, path_id, path.get("polarity")),
            "failure_scope": failure_scope,
            "can_independently_falsify_sh": bool(can_falsify),
            "missing_path_blocks_sh": bool(path.get("missing_path_blocks_sh") is True and can_falsify),
            "negative_evidence_interpretation": (
                "opposing evidence can falsify, reverse, or materially qualify the primary SH claim"
                if _evidence_path_polarity(role, path_id, path.get("polarity")) == "opposing"
                else
                "negative core/integrative validation can falsify or materially weaken the whole SH"
                if can_falsify
                else "negative or absent support evidence becomes a localized mechanism/boundary gap"
            ),
        })
    return {
        "version": "evidence_path_failure_policy_v1",
        "whole_sh_falsification_rule": str(policy.get("whole_sh_falsification_rule") or ""),
        "support_path_failure_rule": str(policy.get("support_path_failure_rule") or ""),
        "missing_path_interpretation": str(policy.get("missing_path_interpretation") or ""),
        "component_success_interpretation": str(policy.get("component_success_interpretation") or ""),
        "core_path_ids": core_path_ids,
        "support_path_ids": support_path_ids,
        "path_summaries": summaries,
        "synthesis_rule": (
            "Summarize by evidence_path. Do not merge all paths into one pool; "
            "component/support paths explain plausibility or gaps, while core "
            "paths control whole-SH completion and falsification."
        ),
    }


def _preflight_text(value: Any) -> str:
    """Return a conservative comparison key without changing source values."""

    text = normalize_space(str(value or "")).lower()
    return re.sub(r"[_\W]+", " ", text, flags=re.UNICODE).strip()


def _preflight_is_placeholder(value: Any) -> bool:
    return _preflight_text(value) in _PREFLIGHT_PLACEHOLDERS


def _preflight_has_marker(value: str, markers: Iterable[str]) -> bool:
    normalized = _preflight_text(value)
    if not normalized:
        return False
    for marker in markers:
        marker_key = _preflight_text(marker)
        if not marker_key:
            continue
        if re.search(rf"\b{re.escape(marker_key)}\b", normalized):
            return True
    return False


def _preflight_has_technical_identifier(value: str) -> bool:
    """Recognize stable identifiers without maintaining a domain word list."""

    return bool(re.search(
        r"\b(?:[A-Z]{2,}[A-Z0-9_-]*|[A-Za-z]+\d+[A-Za-z0-9_-]*)\b",
        str(value or ""),
    ))


def _preflight_has_operational_variable_marker(value: str) -> bool:
    normalized = _preflight_text(value)
    return any(
        re.search(rf"\b{re.escape(marker)}\b", normalized)
        for marker in _PREFLIGHT_OPERATIONAL_VARIABLE_MARKERS
    )


def _preflight_has_variable_resolution_marker(value: str) -> bool:
    normalized = _preflight_text(value)
    return any(
        re.search(rf"\b{re.escape(marker)}\b", normalized)
        for marker in _PREFLIGHT_VARIABLE_RESOLUTION_MARKERS
    )


def _preflight_low_resolution_input_terms(value: str) -> list[str]:
    """Return generic variable shells that still need parameter-level detail.

    The check is deliberately discipline-neutral.  It does not say that a
    membrane, material, policy, process, model, or treatment object is invalid;
    it says that broad shells such as "composition" or "conditions" need a
    dose/content/ratio/feature/threshold/parameter-level contrast before they
    are executable retrieval variables.
    """

    normalized = _preflight_text(value)
    if not normalized:
        return []
    if _preflight_has_variable_resolution_marker(value):
        return []
    if _preflight_has_technical_identifier(value) and not any(
        phrase in normalized for phrase in _PREFLIGHT_LOW_RESOLUTION_INPUT_PHRASES
    ):
        # A named gene/material/formal symbol can be operationalized by the
        # contract even when the lexical form is short.  Generic shells still
        # need a parameter-level contrast.
        return []
    matched: list[str] = []
    for phrase in _PREFLIGHT_LOW_RESOLUTION_INPUT_PHRASES:
        if phrase in normalized:
            matched.append(phrase)
    tokens = normalized.split()
    for head in _PREFLIGHT_LOW_RESOLUTION_INPUT_HEADS:
        if re.search(rf"\b{re.escape(head)}\b", normalized):
            # Short shell phrases such as "membrane composition", "process
            # conditions", or "model design" are too coarse.  Long clauses may
            # already provide a natural condition or context; leave those to
            # comparison/readout/falsification checks unless an explicit broad
            # phrase was matched above.
            if len(tokens) <= 5 or matched:
                matched.append(head)
    return sorted(set(matched))


def _preflight_is_low_resolution_independent_variable(value: str) -> bool:
    return bool(_preflight_low_resolution_input_terms(value))


def _preflight_is_unanchored_entity_phrase(value: str) -> bool:
    """Reject an adjective plus a broad entity head when no object is named.

    The check is lexical rather than topical.  It therefore treats an input
    such as ``non-specific molecules`` as incomplete while leaving a named
    entity, a quantitative composition, or a technical symbol to the normal
    causal-contract and retrieval checks.
    """

    normalized = _preflight_text(value)
    tokens = normalized.split()
    if not tokens or tokens[-1] not in _PREFLIGHT_GENERIC_ENTITY_HEADS:
        return False
    if _preflight_has_technical_identifier(value) or _preflight_has_operational_variable_marker(value):
        return False
    meaningful = [
        token for token in tokens[:-1]
        if token not in {"a", "an", "the", "of", "non", "not", "without"}
        and token not in _PREFLIGHT_NON_SPECIFYING_MODIFIERS
    ]
    return len(meaningful) <= 1


def _preflight_has_specific_existential_anchor(value: str) -> bool:
    """Return whether a binary existence claim names an executable subject."""

    if _preflight_has_technical_identifier(value) or _preflight_has_operational_variable_marker(value):
        return True
    normalized = _preflight_text(value)
    return (
        not _preflight_is_unanchored_entity_phrase(value)
        and len(normalized.split()) >= 3
    )


def _preflight_is_generic_independent_variable(value: str) -> bool:
    source = normalize_space(str(value or ""))
    normalized = _preflight_text(source)
    if normalized in _PREFLIGHT_GENERIC_INDEPENDENT_VARIABLES:
        return True
    existential_match = _PREFLIGHT_EXISTENTIAL_VARIABLE_RE.fullmatch(source)
    if not existential_match:
        return False
    subject = existential_match.group(1).strip()
    # An existential assertion is not an executable variable unless the
    # asserted entity is already tied to a technical identity, a quantitative
    # quantity, or an explicit intervention/measurement parameter.  This
    # catches broad "presence of X" formulations across domains without
    # enumerating subject-specific concepts.
    return not _preflight_has_specific_existential_anchor(subject)


def _preflight_is_generic_outcome(value: str) -> bool:
    normalized = _preflight_text(value)
    return (
        normalized in _PREFLIGHT_GENERIC_OUTCOMES
        or _preflight_is_unanchored_entity_phrase(value)
    )


def _preflight_is_broad_outcome_phrase(value: str) -> bool:
    normalized = _preflight_text(value)
    if not normalized:
        return True
    if normalized in _PREFLIGHT_GENERIC_OUTCOMES:
        return True
    if _preflight_is_unanchored_entity_phrase(value):
        return True
    if any(phrase in normalized for phrase in _PREFLIGHT_BROAD_OUTCOME_PHRASES):
        return True
    tokens = normalized.split()
    return any(token in _PREFLIGHT_BROAD_OUTCOME_TERMS for token in tokens)


def _preflight_has_concrete_readout_marker(value: str) -> bool:
    normalized = _preflight_text(value)
    if not normalized:
        return False
    if normalized in _PREFLIGHT_GENERIC_OUTCOMES:
        return False
    if _preflight_has_marker(
        value,
        _PREFLIGHT_CONCRETE_READOUT_MARKERS | _DISCIPLINE_READOUT_MARKERS,
    ):
        return True
    # Quantities with explicit units or mathematical/statistical notation are
    # concrete across domains even when the unit vocabulary is not enumerated.
    if re.search(
        r"\b\d+(?:\.\d+)?\s*(?:%|mg|g|kg|ng|ml|l|mm|cm|m|nm|um|μm|kpa|pa|mpa|"
        r"°c|celsius|kwh|mol|mmol|s|sec|min|h|hr|day|days|fold)\b",
        normalized,
    ):
        return True
    if re.search(r"\b(?:p\s*value|r\s*squared|r2|ci95|95\s*ci)\b", normalized):
        return True
    return False


def _preflight_concrete_readouts(readouts: list[str]) -> list[str]:
    values: list[str] = []
    for value in readouts:
        if (
            not _preflight_is_placeholder(value)
            and _preflight_has_concrete_readout_marker(value)
            and value not in values
        ):
            values.append(value)
    return values


def _preflight_generic_readouts(readouts: list[str]) -> list[str]:
    values: list[str] = []
    for value in readouts:
        if (
            (_preflight_is_placeholder(value) or _preflight_is_broad_outcome_phrase(value))
            and value not in values
        ):
                values.append(value)
    return values


def _preflight_outcome_audit(readouts: list[str]) -> dict[str, Any]:
    """Explain whether declared outcomes are operational readouts.

    This mirrors the LLM-facing outcome audit schema but remains deterministic
    so persisted projects and fallback decomposition are enforceable without
    trusting a model to police its own generic wording.
    """

    concrete = _preflight_concrete_readouts(readouts)
    generic = _preflight_generic_readouts(readouts)
    placeholders = [
        value for value in readouts
        if _preflight_is_placeholder(value)
    ]
    invalid = list(dict.fromkeys([*placeholders, *generic]))
    if not readouts:
        status = "missing"
    elif concrete:
        status = "concrete_readout_bound"
    else:
        status = "blocked_generic_or_placeholder"
    return {
        "schema_version": "subhypothesis_outcome_audit_v1",
        "status": status,
        "declared_outcomes": list(readouts),
        "concrete_readouts": concrete,
        "generic_or_placeholder_outcomes": invalid,
        "forbidden_generic_outcome_policy": (
            "Outcome fields may not stop at visualization, understanding, "
            "function, organization, performance, quality, effectiveness, "
            "reliability, reproducibility, result, impact, success, or "
            "reliable/reproducible results. They must name a measurable "
            "statistic, structural property, assay output, rate, concentration, "
            "error metric, threshold, physical quantity, clinical/event endpoint, "
            "manufacturing quality attribute, operational "
            "metric, or formal/model output."
        ),
        "blocks_retrieval_contract": bool(readouts and not concrete),
    }


def _preflight_first_concrete_readout(*sources: Any) -> str:
    for source in sources:
        for value in normalize_text_list(source):
            if not _preflight_is_placeholder(value) and _preflight_has_concrete_readout_marker(value):
                return normalize_space(str(value or ""))
    return ""


def _preflight_is_generic_comparison(value: str) -> bool:
    normalized = _preflight_text(value)
    return (
        normalized in _PREFLIGHT_GENERIC_COMPARISONS
        or _preflight_is_unanchored_entity_phrase(value)
    )


def _preflight_readouts(sub_hypothesis: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "dependent_variables", "dependent_variable", "observables", "readouts",
        "readout", "measurements", "measurement", "outcomes", "outcome",
    ):
        for value in normalize_text_list(sub_hypothesis.get(key)):
            if value not in values:
                values.append(value)
    return values


def _scientific_object_contract_repair_action(error_code: str) -> str:
    return {
        "RESEARCH_ACTION_AS_OBJECT": "derive_object_from_comparator_target_or_focus",
        "BOUNDARY_CONDITION_AS_OBJECT": "move_to_boundary_conditions",
        "READOUT_AS_OBJECT": "move_to_dependent_variables",
    }.get(str(error_code or ""), "repair_scientific_object_contract")


def _scientific_object_contract_target_field(error_code: str) -> str:
    return {
        "RESEARCH_ACTION_AS_OBJECT": "scientific_object/comparison/evidence_paths",
        "BOUNDARY_CONDITION_AS_OBJECT": "boundary_conditions/evidence_window",
        "READOUT_AS_OBJECT": "dependent_variables/readouts",
    }.get(str(error_code or ""), "scientific_object")


def _scientific_object_contract_suggested_object_candidates(
    sub_hypothesis: dict[str, Any],
) -> list[str]:
    """Return possible noun-like replacements without claiming they are valid."""

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    candidates: list[str] = []
    for key in (
        "focus",
        "focus_anchor",
        "comparison",
        "baseline_or_comparator",
        "independent_variable",
        "retrieval_query",
    ):
        value = item.get(key)
        if isinstance(value, dict):
            for nested_key in ("anchor", "object", "target", "primary_object"):
                text = normalize_space(str(value.get(nested_key) or ""))
                if text and text not in candidates:
                    candidates.append(text)
            continue
        for text in normalize_text_list(value):
            text = normalize_space(text)
            if (
                text
                and len(_preflight_text(text).split()) >= 2
                and not _SCIENTIFIC_OBJECT_RESEARCH_ACTION_RE.search(text)
                and not _SCIENTIFIC_OBJECT_BOUNDARY_PARAMETER_RE.search(text)
                and not _scientific_object_time_horizon_like(text)
                and text not in candidates
            ):
                candidates.append(text)
    return candidates[:6]


def _scientific_object_time_horizon_like(value: Any) -> bool:
    text = normalize_space(str(value or ""))
    normalized = _preflight_text(text)
    return bool(
        _SCIENTIFIC_OBJECT_TIME_HORIZON_RE.search(text)
        or any(marker in normalized for marker in _SCIENTIFIC_OBJECT_PARAMETER_MARKERS)
    )


def _scientific_object_generic_readout_only(value: Any) -> bool:
    normalized = _preflight_text(value)
    if not normalized:
        return False
    if normalized in _PREFLIGHT_GENERIC_OUTCOMES:
        return True
    tokens = [
        token for token in normalized.split()
        if token not in {"a", "an", "the", "of", "for", "and", "or", "overall", "relative"}
    ]
    return bool(tokens) and all(token in _PREFLIGHT_GENERIC_OUTCOMES for token in tokens)


def audit_subhypothesis_scientific_object_contract(
    sub_hypothesis: dict[str, Any],
) -> dict[str, Any]:
    """Audit whether ``scientific_object`` is actually an object.

    Object maturity asks whether a real object has a stable literature identity.
    This earlier contract gate asks a simpler question: did decomposition put a
    research action, readout, or boundary parameter in the object slot?  Those
    are schema errors, not merely immature objects, and must be repaired before
    retrieval can safely spend budget or synthesize gaps.
    """

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    sub_id = str(item.get("id") or "")
    original_object = normalize_space(str(item.get("scientific_object") or ""))
    normalized = _preflight_text(original_object)
    error_code = ""
    if original_object and _SCIENTIFIC_OBJECT_RESEARCH_ACTION_RE.search(original_object):
        error_code = "RESEARCH_ACTION_AS_OBJECT"
    elif original_object and (
        _SCIENTIFIC_OBJECT_BOUNDARY_PARAMETER_RE.search(original_object)
        or _scientific_object_time_horizon_like(original_object)
    ):
        error_code = "BOUNDARY_CONDITION_AS_OBJECT"
    elif original_object and _scientific_object_generic_readout_only(original_object):
        error_code = "READOUT_AS_OBJECT"

    if not error_code:
        return {
            "schema_version": SCIENTIFIC_OBJECT_CONTRACT_PREFLIGHT_VERSION,
            "sub_hypothesis_id": sub_id,
            "valid": True,
            "object_contract_valid": True,
            "status": "valid",
            "error": "",
            "error_code": "",
            "original_scientific_object": original_object,
            "normalized_scientific_object": normalized,
            "retrieval_allowed": True,
            "blocks_retrieval": False,
            "repair_action": "",
            "target_field": "scientific_object",
            "suggested_object_candidates": _scientific_object_contract_suggested_object_candidates(item),
        }

    repair_action = _scientific_object_contract_repair_action(error_code)
    blocking_reason = error_code.lower()
    return {
        "schema_version": SCIENTIFIC_OBJECT_CONTRACT_PREFLIGHT_VERSION,
        "sub_hypothesis_id": sub_id,
        "valid": False,
        "object_contract_valid": False,
        "status": "invalid",
        "error": error_code,
        "error_code": error_code,
        "blocking_reason": blocking_reason,
        "original_scientific_object": original_object,
        "normalized_scientific_object": normalized,
        "retrieval_allowed": False,
        "blocks_retrieval": True,
        "direct_core_evidence_allowed": False,
        "repair_action": repair_action,
        "target_field": _scientific_object_contract_target_field(error_code),
        "suggested_object_candidates": _scientific_object_contract_suggested_object_candidates(item),
        "claim_strength_policy": (
            "No literature search, component-bridge retrieval, core-validation path, "
            "or claim-strength increase is allowed until the object slot is repaired."
        ),
    }


def _apply_scientific_object_contract_audit_to_item(
    item: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    item["scientific_object_contract_audit"] = audit
    item["object_contract_valid"] = bool(audit.get("valid") is True)
    if audit.get("valid") is True:
        if str(item.get("status") or "") == "blocked_scientific_object_contract":
            item["status"] = "pending_retrieval"
        if item.get("retrieval_blocked_reason") == "scientific_object_contract_failed":
            item.pop("retrieval_blocked_reason", None)
        if item.get("object_maturity_retrieval_mode") == "contract_repair_required":
            item.pop("object_maturity_retrieval_mode", None)
        if item.get("direct_core_disallowed_reason") == "scientific_object_contract_failed":
            item.pop("direct_core_disallowed_reason", None)
        return
    item["scientific_operationality_preflight_required"] = True
    item["direct_core_evidence_allowed"] = False
    item["object_maturity_retrieval_mode"] = "contract_repair_required"
    item["retrieval_blocked_reason"] = "scientific_object_contract_failed"
    item["status"] = "blocked_scientific_object_contract"


def annotate_subhypotheses_scientific_object_contract(
    sub_hypotheses: list[dict[str, Any]],
    *,
    project_id: str = "",
    emit_logs: bool = False,
) -> dict[str, Any]:
    total = 0
    valid_ids: list[str] = []
    invalid_ids: list[str] = []
    invalid_by_error: dict[str, int] = {}
    audits_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sub_hypotheses or []):
        if not isinstance(item, dict):
            continue
        total += 1
        sub_id = str(item.get("id") or f"SH{index + 1}")
        audit = audit_subhypothesis_scientific_object_contract(item)
        audit["sub_hypothesis_id"] = sub_id
        _apply_scientific_object_contract_audit_to_item(item, audit)
        audits_by_id[sub_id] = audit
        if audit.get("valid") is True:
            valid_ids.append(sub_id)
            continue
        invalid_ids.append(sub_id)
        error_code = str(audit.get("error_code") or audit.get("error") or "UNKNOWN_OBJECT_CONTRACT_ERROR")
        invalid_by_error[error_code] = invalid_by_error.get(error_code, 0) + 1
        if emit_logs:
            log_event(
                "SCIENCE",
                "scientific_object_contract_failed",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                object_contract_error=error_code,
                original_scientific_object=str(audit.get("original_scientific_object") or ""),
                repair_action=str(audit.get("repair_action") or ""),
                target_field=str(audit.get("target_field") or ""),
                suggested_object_candidates=list(audit.get("suggested_object_candidates") or [])[:4],
            )
    return {
        "schema_version": SCIENTIFIC_OBJECT_CONTRACT_PREFLIGHT_VERSION,
        "total": total,
        "valid": len(valid_ids),
        "invalid": len(invalid_ids),
        "valid_sub_hypothesis_ids": valid_ids,
        "invalid_sub_hypothesis_ids": invalid_ids,
        "invalid_by_error": invalid_by_error,
        "audits_by_id": audits_by_id,
    }


def _preflight_comparisons(sub_hypothesis: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "controls", "control_variables", "comparison_conditions", "comparison", "comparisons",
        "counterfactual", "counterfactuals", "baseline", "baselines",
        "negative_control", "negative_controls", "reference_condition",
    ):
        for value in normalize_text_list(sub_hypothesis.get(key)):
            for condition in (normalize_space(part) for part in value.split("|")):
                if condition and condition not in values:
                    values.append(condition)
    return values


def _preflight_has_textual_comparison(*values: str) -> bool:
    text = f" {' '.join(str(value or '').lower() for value in values)} "
    return any(marker in text for marker in _PREFLIGHT_COMPARISON_MARKERS)


def _preflight_phrases_overlap(left: str, right: str) -> bool:
    """Detect an explicit comparison/exclusion contradiction, not loose term overlap."""

    left_key = _preflight_text(left)
    right_key = _preflight_text(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    # A multi-word declared object can be singular/plural or include a small
    # qualifier.  Do not treat one shared broad word as a contradiction.
    return (
        min(len(left_key.split()), len(right_key.split())) >= 2
        and (left_key in right_key or right_key in left_key)
    )


def reconcile_subhypothesis_excluded_comparators(
    sub_hypothesis: dict[str, Any],
) -> dict[str, Any]:
    """Remove explicit comparators that were accidentally listed as exclusions.

    ``excluded_nearby_objects`` is a vocabulary guard: it says which adjacent
    objects must not substitute for the SH's target object during retrieval.
    It must not contain the matched control, counterfactual, baseline, or
    comparison condition that makes the SH falsifiable.  This deterministic
    reconcile step fixes that field-level contradiction without weakening the
    operationality preflight: vague or generic comparisons are still blocked.
    """

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    if not item:
        return {}
    exclusions = normalize_text_list(
        item.get("excluded_nearby_objects") or item.get("excluded_objects")
    )
    if not exclusions:
        return {}
    comparisons = [
        value
        for value in _preflight_comparisons(item)
        if value
        and not _preflight_is_placeholder(value)
        and not _preflight_is_generic_comparison(value)
    ]
    if not comparisons:
        return {}

    removed: list[str] = []
    kept: list[str] = []
    matched_by_exclusion: dict[str, list[str]] = {}
    for excluded in exclusions:
        matched = [
            comparison
            for comparison in comparisons
            if _preflight_phrases_overlap(comparison, excluded)
        ]
        if matched:
            removed.append(excluded)
            matched_by_exclusion[excluded] = matched
        else:
            kept.append(excluded)
    if not removed:
        return {}

    item["excluded_nearby_objects"] = kept
    audit = {
        "schema_version": "subhypothesis_operationality_reconciliation_v1",
        "excluded_comparator_reconciled": True,
        "reason_code": "COMPARATOR_WAS_MARKED_AS_EXCLUDED_NEARBY_OBJECT",
        "removed_excluded_nearby_objects": removed,
        "matched_comparison_terms": matched_by_exclusion,
        "remaining_excluded_nearby_objects": kept,
        "claim_strength_impact": "none; field contradiction resolved before evidence retrieval",
    }
    item["scientific_operationality_reconciliation"] = audit
    log_event(
        "SCIENCE",
        "subhypothesis_excluded_comparator_reconciled",
        sub_hypothesis_id=str(item.get("id") or ""),
        removed=removed,
        remaining=kept,
    )
    return audit


def _preflight_semantic_view(value: Any) -> Any:
    """Return the stable scientific content of a preflight record.

    Preflight runs at more than one retrieval boundary.  Its persisted result
    must therefore be a scientific assertion about declared variables, not a
    new storage revision merely because the gate was evaluated again.
    """

    if not isinstance(value, dict):
        return value
    if "assessments_by_id" in value:
        assessments = value.get("assessments_by_id")
        return {
            "version": value.get("version"),
            "total": value.get("total"),
            "ready": value.get("ready"),
            "blocked": value.get("blocked"),
            "ready_sub_hypothesis_ids": list(value.get("ready_sub_hypothesis_ids") or []),
            "blocked_sub_hypothesis_ids": list(value.get("blocked_sub_hypothesis_ids") or []),
            "assessments_by_id": {
                str(key): _preflight_semantic_view(item)
                for key, item in sorted((assessments or {}).items())
                if isinstance(item, dict)
            },
        }
    if "audits_by_id" in value:
        audits = value.get("audits_by_id")
        return {
            "schema_version": value.get("schema_version"),
            "total": value.get("total"),
            "valid": value.get("valid"),
            "invalid": value.get("invalid"),
            "valid_sub_hypothesis_ids": list(value.get("valid_sub_hypothesis_ids") or []),
            "invalid_sub_hypothesis_ids": list(value.get("invalid_sub_hypothesis_ids") or []),
            "invalid_by_error": dict(value.get("invalid_by_error") or {}),
            "audits_by_id": {
                str(key): _preflight_semantic_view(item)
                for key, item in sorted((audits or {}).items())
                if isinstance(item, dict)
            },
        }
    return {
        "version": value.get("version"),
        "schema_version": value.get("schema_version"),
        "status": value.get("status"),
        "valid": value.get("valid"),
        "error_code": value.get("error_code"),
        "original_scientific_object": value.get("original_scientific_object"),
        "blocking_reasons": list(value.get("blocking_reasons") or []),
        "warnings": list(value.get("warnings") or []),
        "required_revisions": list(value.get("required_revisions") or []),
        "variables": value.get("variables") if isinstance(value.get("variables"), dict) else {},
        "enforcement": value.get("enforcement"),
    }


def _same_preflight_scientific_content(previous: Any, current: Any) -> bool:
    return json.dumps(
        _preflight_semantic_view(previous),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        _preflight_semantic_view(current),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reuse_equivalent_preflight(previous: Any, current: dict[str, Any]) -> dict[str, Any]:
    """Keep the persisted object when a recheck finds no scientific change."""

    return previous if isinstance(previous, dict) and _same_preflight_scientific_content(previous, current) else current


_COMPONENT_BRIDGE_OPERATIONALITY_ROLES = frozenset({
    "component_evidence",
    "enabling_component_evidence",
    "translational_bridge",
    "bridge_evidence",
    "boundary_or_safety_evidence",
    "boundary_or_generalization",
    "safety_or_failure_mode",
    "adverse_or_reversal",
    "background_or_framework",
    "context_review",
})


def _component_bridge_operationality_contract(
    item: dict[str, Any],
    evidence_paths: list[Any],
) -> dict[str, Any]:
    """Detect and summarize a non-direct object-maturity retrieval contract.

    A component/bridge/boundary SH is intentionally not a direct-core causal
    claim about the final object.  Its operationality should therefore be
    judged by whether it has searchable component anchors, component/bridge
    evidence paths, and an explicit bridge gap / forbidden-direct-claim policy,
    not by whether one path can independently falsify the final object.
    """

    maturity: dict[str, Any] = {}
    for key in ("object_maturity_audit", "object_maturity_preflight"):
        source = item.get(key)
        if isinstance(source, dict):
            maturity.update(source)

    retrieval_mode = normalize_space(str(
        item.get("object_maturity_retrieval_mode")
        or maturity.get("retrieval_mode")
        or ""
    )).lower()
    evidence_path_policy = normalize_space(str(item.get("evidence_path_policy") or "")).lower()
    direct_core_allowed_value = (
        item.get("direct_core_evidence_allowed")
        if "direct_core_evidence_allowed" in item
        else maturity.get("direct_core_evidence_allowed")
    )
    direct_core_disallowed = (
        direct_core_allowed_value is False
        or bool(item.get("direct_core_disallowed_by_object_maturity") is True)
        or bool(maturity.get("direct_core_disallowed_by_object_maturity") is True)
        or bool(item.get("direct_core_disallowed_reason") == "object_maturity_preflight")
    )
    active = (
        retrieval_mode == "component_bridge_boundary"
        or evidence_path_policy == "component_bridge_boundary_paths"
        or direct_core_disallowed
    )
    if not active:
        return {"active": False}

    path_roles: list[str] = []
    path_ids: list[str] = []
    path_anchor_groups: list[str] = []
    for path in evidence_paths:
        if not isinstance(path, dict):
            continue
        path_id = normalize_space(str(path.get("id") or ""))
        role = normalize_space(str(path.get("role") or ""))
        role_key = role.lower()
        path_id_key = path_id.lower()
        relevant = (
            role_key in _COMPONENT_BRIDGE_OPERATIONALITY_ROLES
            or path_id_key in _COMPONENT_BRIDGE_OPERATIONALITY_ROLES
            or bool(path.get("direct_core_disallowed_by_object_maturity") is True)
            or bool(path.get("component_evidence_counts_as_core") is False and path.get("component_anchor_group"))
        )
        if not relevant:
            continue
        if role and role not in path_roles:
            path_roles.append(role)
        if path_id and path_id not in path_ids:
            path_ids.append(path_id)
        for value in normalize_text_list(path.get("component_anchor_group")):
            if value not in path_anchor_groups:
                path_anchor_groups.append(value)

    forbidden_claims = _object_maturity_unique(
        normalize_text_list(item.get("forbidden_direct_core_claims"))
        + normalize_text_list(maturity.get("forbidden_direct_core_claims")),
        limit=12,
    )
    typed = (
        maturity.get("typed_component_bridge_anchors")
        if isinstance(maturity.get("typed_component_bridge_anchors"), dict)
        else item.get("typed_component_bridge_anchors")
        if isinstance(item.get("typed_component_bridge_anchors"), dict)
        else {}
    )
    object_anchors = _object_maturity_unique(
        normalize_text_list(item.get("object_anchors"))
        + normalize_text_list(maturity.get("object_anchors"))
        + normalize_text_list(typed.get("object_anchors")),
        limit=16,
    )
    method_anchors = _object_maturity_unique(
        normalize_text_list(item.get("method_or_platform_anchors"))
        + normalize_text_list(maturity.get("method_or_platform_anchors"))
        + normalize_text_list(typed.get("method_or_platform_anchors")),
        limit=16,
    )
    readout_anchors = _object_maturity_unique(
        normalize_text_list(item.get("readout_anchors"))
        + normalize_text_list(maturity.get("readout_anchors"))
        + normalize_text_list(typed.get("readout_anchors")),
        limit=16,
    )
    model_system_anchors = _object_maturity_unique(
        normalize_text_list(item.get("model_system_anchors"))
        + normalize_text_list(maturity.get("model_system_anchors"))
        + normalize_text_list(typed.get("model_system_anchors")),
        limit=16,
    )
    role_modifiers = _object_maturity_unique(
        normalize_text_list(item.get("role_modifiers"))
        + normalize_text_list(maturity.get("role_modifiers"))
        + normalize_text_list(typed.get("role_modifiers")),
        limit=16,
    )
    forbidden_as_object_anchors = _object_maturity_unique(
        normalize_text_list(item.get("forbidden_as_object_anchors"))
        + normalize_text_list(maturity.get("forbidden_as_object_anchors"))
        + normalize_text_list(typed.get("forbidden_as_object_anchors")),
        limit=16,
    )
    component_anchors = _object_maturity_unique(
        object_anchors
        + method_anchors
        + readout_anchors
        + model_system_anchors
        + [
            anchor
            for anchor in path_anchor_groups
            if anchor in object_anchors
            or anchor in method_anchors
            or anchor in readout_anchors
            or anchor in model_system_anchors
        ],
        limit=16,
    )
    bridge_anchors = _object_maturity_unique(
        object_anchors + model_system_anchors + method_anchors[:4],
        limit=12,
    )
    boundary_anchors: list[str] = []
    anchor_quality = (
        maturity.get("component_bridge_anchor_quality")
        if isinstance(maturity.get("component_bridge_anchor_quality"), dict)
        else item.get("component_bridge_anchor_quality")
        if isinstance(item.get("component_bridge_anchor_quality"), dict)
        else {}
    )
    typed_anchor_contract_available = bool(
        anchor_quality
        or object_anchors
        or method_anchors
        or readout_anchors
        or model_system_anchors
        or role_modifiers
        or forbidden_as_object_anchors
    )
    quality_passes = (
        bool(anchor_quality.get("passes"))
        if "passes" in anchor_quality
        else bool(object_anchors and (method_anchors or readout_anchors or model_system_anchors))
        if typed_anchor_contract_available
        else False
    )
    causal_contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    bridge_gap = normalize_space(str(
        maturity.get("bridge_gap_statement")
        or item.get("bridge_gap_statement")
        or causal_contract.get("object_maturity_bridge_gap")
        or ""
    ))

    return {
        "active": True,
        "operationality_profile": "component_bridge_boundary",
        "object_status": normalize_space(str(maturity.get("object_status") or "")),
        "retrieval_mode": retrieval_mode or "component_bridge_boundary",
        "evidence_path_policy": evidence_path_policy,
        "direct_core_evidence_allowed": False,
        "direct_core_disallowed_by_object_maturity": True,
        "component_evidence_anchors": [],
        "translational_bridge_anchors": [],
        "boundary_or_safety_anchors": [],
        "object_anchors": object_anchors,
        "method_or_platform_anchors": method_anchors,
        "readout_anchors": readout_anchors,
        "model_system_anchors": model_system_anchors,
        "role_modifiers": role_modifiers,
        "forbidden_as_object_anchors": forbidden_as_object_anchors,
        "component_bridge_anchor_quality": anchor_quality,
        "component_bridge_anchor_repair_required": not quality_passes,
        "forbidden_direct_core_claims": forbidden_claims,
        "bridge_gap_statement": bridge_gap,
        "component_bridge_path_ids": path_ids,
        "component_bridge_path_roles": path_roles,
        "has_searchable_component_or_bridge_anchor": bool(
            quality_passes
        ),
        "has_component_bridge_evidence_paths": bool(path_ids),
    }


_PREFLIGHT_REVISION_GUIDANCE = {
    "scientific_object_missing": "Name the concrete entity, system, population, material, process, or formal object under study.",
    "research_action_as_object": "Replace the scientific_object with a noun-like entity/system/process under study; move the research action into comparison, evidence_paths, or the research question.",
    "boundary_condition_as_object": "Move the parameter, time horizon, baseline, or boundary condition out of scientific_object and into boundary_conditions, evidence_window, comparison_conditions, or the causal contract.",
    "readout_as_object": "Move the generic endpoint/readout out of scientific_object and into dependent_variables; name the actual entity, system, pathway, population, material, device, or formal object under study.",
    "independent_variable_missing": "Specify an independently manipulable variable, observed exposure, or defined model condition.",
    "independent_variable_not_operational": "Replace the abstract input with an isolatable comparison, dose, composition, perturbation, or explicitly defined natural condition.",
    "independent_variable_low_resolution": "Specify which parameter, composition dimension, dose, condition, feature set, process variable, exposure class, or perturbation is being changed.",
    "input_descriptive_state_not_operationalized": "Do not use a descriptive state as a causal input until it is framed as an intervention, exposure, stratification, or parameter with an operational definition or comparison level.",
    "claim_layer_missing_local_empirical_outcome": "Separate the local measurable endpoint from the transfer or decision interpretation; declare the local empirical outcome before asking retrieval to support a cross-system claim.",
    "axis_role_input_mechanism_semantic_collapse": "Separate the externally changed condition from the internal mediator; the input must name an intervention, calibrated parameter, exposure, comparison level, or defined natural condition rather than restating the mechanism.",
    "pivotal_mechanism_is_readout_proxy": "Replace the pivotal mechanism with a distinct causal process, mediator state, or direct target. A declared endpoint readout may be measured as an intermediate result, but it cannot also occupy the explanatory pivotal-mechanism slot.",
    "pivotal_mechanism_role_invalid": "Set pivotal_mechanism_role to CAUSAL_PROCESS, MEDIATOR_STATE, DIRECT_TARGET, READOUT_PROXY, or NOT_REQUIRED, and make the declared role agree with the causal-contract field.",
    "axis_role_outcome_field_conflict": "Make the causal-contract outcome, focus outcome, and declared dependent variables refer to one compatible measurement family; move unrelated readouts to auxiliary context or remove them.",
    "observable_outcome_missing": "Name at least one observable outcome or measurement readout.",
    "observable_outcome_not_operational": "Replace the generic outcome with a measurable endpoint, statistic, structural property, or bounded model output.",
    "comparison_missing": "Declare a matched control, counterfactual, dose/composition contrast, alternative mechanism, or reference condition.",
    "comparison_not_specific": "Replace the generic control label with the actual comparison object or condition.",
    "comparison_object_excluded": "Remove the comparison object from excluded_nearby_objects or replace it with a genuinely irrelevant neighboring object.",
    "falsification_condition_missing": "State the observation that would reject the proposed relation rather than merely weaken it.",
    "falsification_condition_not_specific": "Provide a sub-hypothesis-specific falsification condition tied to the declared comparison and outcome.",
    "profile_compatible_core_path_missing": "Add one direct core evidence path compatible with the epistemic profile, such as an observation/constraint, derivation, proof, validated simulation, or performance test.",
    "epistemic_contract_mismatch": "Rebuild the evidence contract from the declared research paradigm; do not require intervention, controlled experiments, or perturbations for observational, theoretical, or formal claims.",
    "component_bridge_anchor_missing": "For immature or speculative final objects, name searchable component, platform, model-system, mediator, boundary, or safety anchors instead of forcing the final object as a direct literature term.",
    "component_bridge_anchor_repair_required": "Replace role/template modifiers with typed searchable anchors: at least one object anchor plus at least one method/platform, readout, or model-system anchor. Terms such as model system, platform validation, mechanism assay, translation, feasibility, safety, failure mode, ethical implications, and neurological damage cannot be object anchors.",
    "component_bridge_evidence_paths_missing": "For immature or speculative final objects, include component_evidence, translational_bridge, boundary_or_safety_evidence, or context_review evidence paths.",
    "component_bridge_gap_statement_missing": "State the remaining bridge gap between current component evidence and the long-range parent objective.",
    "component_bridge_forbidden_direct_claim_missing": "List the direct-core claims that component or bridge papers must not be used to support.",
    "axis_role_object_input_overlap": "Separate the primary scientific object from the input/parameter axis; do not reuse the same semantic nucleus in scientific_object and independent_variable.",
    "axis_role_object_mechanism_overlap": "For causal or mechanistic claims, name a pivotal mechanism distinct from the primary scientific object.",
    "axis_role_input_mechanism_overlap": "For causal or mechanistic claims, replace a copied pivotal mechanism with the distinct mediator, process, or causal edge downstream of the input.",
}


_NONINTERVENTIONAL_MODES = frozenset({
    "observational_inference", "theoretical_derivation", "mathematical_proof",
    "computational_simulation", "classification_description", "synthesis_evaluation",
})
_INTERVENTION_REQUIREMENT_KEYS = frozenset({
    "intervention_required", "controlled_experiment_required", "perturbation_required",
})
_QUERY_AXIS_MARKERS = {
    "object": ("scientific_object", "object", "entity", "system"),
    "mechanism": ("mechanism", "pathway", "mediator", "causal_chain"),
    "outcome": ("outcome", "result", "endpoint", "readout", "dependent_variable"),
    "measurement": ("measurement", "measure", "assay", "likelihood", "posterior"),
    "material_population": ("material", "population", "cohort", "tissue", "sample"),
    "process": ("process", "implementation", "workflow", "condition"),
    "comparison": ("comparison", "baseline", "control", "counterfactual", "alternative model"),
}


def _epistemic_contract_boolean_requirements(value: Any) -> set[str]:
    """Find explicit intervention requirements without treating topic words as rules."""

    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key or "").strip().lower()
            if normalized in _INTERVENTION_REQUIREMENT_KEYS and nested is True:
                found.add(normalized)
            found.update(_epistemic_contract_boolean_requirements(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_epistemic_contract_boolean_requirements(nested))
    return found


def audit_subhypothesis_epistemic_contract(
    sub_hypothesis: dict[str, Any],
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect a paradigm-invalid evidence contract before retrieval spends budget."""

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else normalize_epistemic_profile(
        item.get("epistemic_profile") or {},
        fallback_text=" ".join(str(item.get(key) or "") for key in ("focus", "scientific_object", "causal_contract")),
    )
    primary_mode = str(profile.get("primary_mode") or "unresolved")
    requirements = _epistemic_contract_boolean_requirements({
        "causal_contract": item.get("causal_contract"),
        "evidence_requirements": item.get("evidence_requirements"),
        "evidence_paths": item.get("evidence_paths"),
    })
    mismatch = bool(primary_mode in _NONINTERVENTIONAL_MODES and requirements)
    query_texts = [
        str(item.get(key) or "")
        for key in ("retrieval_query", "query", "focus", "causal_contract")
    ]
    query_texts.extend(
        str(path.get("retrieval_query") or "")
        for path in (item.get("evidence_paths") or [])
        if isinstance(path, dict)
    )
    combined_query = " ".join(query_texts).lower()
    axes = sorted(
        axis for axis, markers in _QUERY_AXIS_MARKERS.items()
        if any(marker in combined_query for marker in markers)
    )
    # Six (or more) simultaneously stated axes approximates a request for a
    # title/abstract to restate the entire SH contract.  Existing independent
    # evidence-path queries mean the condition is already automatically split.
    paths = [path for path in (item.get("evidence_paths") or []) if isinstance(path, dict)]
    overconstrained = len(axes) >= 6
    auto_split_available = len(paths) >= 2
    return {
        "schema_version": "epistemic_contract_audit_v1",
        "primary_mode": primary_mode,
        "status": "EPISTEMIC_CONTRACT_MISMATCH" if mismatch else "VALID",
        "mismatch_code": "EPISTEMIC_CONTRACT_MISMATCH" if mismatch else "",
        "intervention_requirements_found": sorted(requirements),
        "query_constraint_status": "QUERY_OVERCONSTRAINED" if overconstrained else "OK",
        "query_axes_detected": axes,
        "auto_split_into_evidence_paths": bool(overconstrained and auto_split_available),
        "recovery_sequence": [
            "check_research_paradigm", "check_claim_type", "check_evidence_standard",
            "check_query_constraint_count", "split_into_evidence_path_queries",
            "relax_abstract_metadata_classification", "acquire_fulltext_and_reclassify",
        ],
    }


def _research_question_contract_for_operationality_v3(
    item: dict[str, Any],
    existing_contract: dict[str, Any],
) -> dict[str, Any]:
    """Return only a declared V3 contract for the V3 preflight.

    This deliberately has no branch that synthesizes a question from legacy
    causal fields.  A fresh decomposition must carry its own question; a
    contract lacking it is a visible revision request.
    """
    contract = existing_contract if isinstance(existing_contract, dict) else {}
    if contract.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION:
        return validate_research_question_contract(contract)
    question = item.get("research_question") if isinstance(item.get("research_question"), dict) else {}
    if not question:
        raise ValueError("V3 SH is missing research_question declaration")
    return build_research_question_contract(
        {"project_id": "", "objective": "", "domain": ""},
        {
            "id": item.get("id") or item.get("sub_hypothesis_id") or "",
            "research_question": question,
            "scientific_scope": item.get("scientific_scope")
            if isinstance(item.get("scientific_scope"), dict)
            else {},
            "claim_target": item.get("claim_target")
            if isinstance(item.get("claim_target"), dict)
            else {},
            "evidence_contract": item.get("evidence_contract")
            if isinstance(item.get("evidence_contract"), dict)
            else {},
            "routing_contract": item.get("routing_contract")
            if isinstance(item.get("routing_contract"), dict)
            else {},
        },
        epistemic_profile=(
            item.get("epistemic_profile")
            if isinstance(item.get("epistemic_profile"), dict)
            else {}
        ),
    )


def _assess_research_question_operationality_v3(
    item: dict[str, Any],
    existing_contract: dict[str, Any],
) -> dict[str, Any]:
    """Validate a V3 question without imposing causal SH slots.

    This gate says only whether typed source-directed retrieval can begin.  It
    does not demand an intervention, mediator, direct core paper, endpoint
    comparison, or object-maturity rewrite for measurement, theory, boundary,
    data, benchmark, and other non-causal question types.
    """
    blocking_reasons: list[str] = []
    contract: dict[str, Any] = {}
    try:
        contract = _research_question_contract_for_operationality_v3(
            item, existing_contract
        )
    except (TypeError, ValueError) as exc:
        blocking_reasons.append("research_question_contract_invalid")
        contract_error = str(exc)
    else:
        contract_error = ""
        question = contract.get("research_question") or {}
        if not normalize_space(str(question.get("question_text") or "")):
            blocking_reasons.append("research_question_text_missing")
        if not normalize_space(str(question.get("question_kind") or "")):
            blocking_reasons.append("research_question_kind_missing")
        evidence_contract = contract.get("evidence_contract") or {}
        if not normalize_text_list(evidence_contract.get("required_slots")):
            blocking_reasons.append("research_question_evidence_slots_missing")
        if not normalize_space(str(contract.get("contract_id") or "")):
            blocking_reasons.append("research_question_contract_identity_missing")
        if not normalize_space(
            str(contract.get("contract_revision") or contract.get("declaration_hash") or "")
        ):
            blocking_reasons.append("research_question_contract_revision_missing")
    scope = contract.get("scientific_scope") if isinstance(contract.get("scientific_scope"), dict) else {}
    question = contract.get("research_question") if isinstance(contract.get("research_question"), dict) else {}
    evidence = contract.get("evidence_contract") if isinstance(contract.get("evidence_contract"), dict) else {}
    routing = contract.get("routing_contract") if isinstance(contract.get("routing_contract"), dict) else {}
    return {
        "version": "research_question_operationality_v3",
        "status": "blocked" if blocking_reasons else "ready",
        "blocking_reasons": blocking_reasons,
        "warnings": [],
        "required_revisions": (
            [
                "Provide a complete ResearchQuestionContractV3: explicit question_text, question_kind, scope_tuple, evidence slots, and current contract identity/revision."
            ]
            if blocking_reasons
            else []
        ),
        "variables": {
            "research_question_contract": contract,
            "research_question_kind": str(question.get("question_kind") or ""),
            "research_question_text": str(question.get("question_text") or ""),
            "scope_tuple": scope,
            "required_evidence_slots": list(evidence.get("required_slots") or []),
            "required_comparability_axes": list(
                evidence.get("required_comparability_axes") or []
            ),
            "routing_contract": routing,
            "contract_error": contract_error,
            "legacy_causal_preflight_used": False,
            "outcome_operationality": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
            "missing_concrete_readout": False,
            "generic_readouts": [],
            "concrete_readouts": [],
            "low_resolution_input_terms": [],
        },
    }


def assess_subhypothesis_scientific_operationality(
    sub_hypothesis: dict[str, Any],
) -> dict[str, Any]:
    """Audit whether a sub-hypothesis is ready to spend retrieval budget.

    This is intentionally a *structural* Gate 1.  It determines whether the
    object, variables, outcomes, and scope are concrete enough to retrieve.
    It must not demand that a draft SH already contains one whole causal
    evidence path, a comparison result, or a hand-written falsification
    sentence: those are Gates 2--5 evidence-bundle questions and may be
    resolved by source-bound papers or a derived test plan after retrieval.
    """

    item = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    v3_contract = (
        item.get("research_question_contract")
        if isinstance(item.get("research_question_contract"), dict)
        else {}
    )
    if (
        item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
        or v3_contract.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION
        or isinstance(item.get("research_question"), dict)
    ):
        return _assess_research_question_operationality_v3(item, v3_contract)
    profile_seed = item.get("epistemic_profile") or {}
    if (
        not profile_seed
        and item.get("independent_variable")
        and not any(
            marker in " ".join(str(item.get(key) or "") for key in ("focus", "scientific_object", "causal_chain")) .lower()
            for marker in ("theorem", "proof", "lemma", "axiom", "counterexample", "derivation")
        )
    ):
        profile_seed = {"primary_mode": "experimental_intervention", "claim_types": ["causal_effect"]}
    epistemic_profile = normalize_epistemic_profile(
        profile_seed,
        fallback_text=" ".join(
            str(item.get(key) or "")
            for key in ("focus", "scientific_object", "causal_chain", "causal_contract", "evidence_paths", "declared_research_mode")
        ),
    )
    primary_mode = str(epistemic_profile.get("primary_mode") or "unresolved")
    requires_intervention = bool(epistemic_profile.get("requires_intervention") is True)
    epistemic_contract_audit = audit_subhypothesis_epistemic_contract(
        item,
        epistemic_profile=epistemic_profile,
    )
    evidence_mode = normalize_space(str(item.get("evidence_mode") or "causal_mechanism"))
    scientific_object = normalize_space(str(item.get("scientific_object") or item.get("focus") or ""))
    scientific_object_contract = audit_subhypothesis_scientific_object_contract(item)
    independent_variable = normalize_space(
        str(item.get("independent_variable") or "")
    )
    moderators = normalize_text_list(item.get("moderators") or item.get("moderator"))
    input_value = independent_variable
    input_role = "independent_variable"
    if not input_value and evidence_mode == "predictive_generalization" and moderators:
        input_value = moderators[0]
        input_role = "moderator"
    readouts = _preflight_readouts(item)
    comparisons = _preflight_comparisons(item)
    exclusions = normalize_text_list(
        item.get("excluded_nearby_objects") or item.get("excluded_objects")
    )
    falsification = normalize_space(
        str(item.get("falsification_condition") or item.get("falsification") or "")
    )
    falsification_source = normalize_space(
        str(item.get("falsification_condition_source") or "")
    ).lower()
    causal_chain = normalize_text_list(item.get("causal_chain"))
    concrete_readouts = _preflight_concrete_readouts(readouts)
    generic_readouts = _preflight_generic_readouts(readouts)
    outcome_audit = _preflight_outcome_audit(readouts)
    outcome_operationality = (
        "missing"
        if not readouts
        else "weak_missing_concrete_readout"
        if not concrete_readouts
        else "concrete_readout_bound"
    )
    evidence_paths = item.get("evidence_paths") if isinstance(item.get("evidence_paths"), list) else []
    has_profile_compatible_core_path = any(
        isinstance(path, dict)
        and (
            path.get("can_independently_falsify_sh") is True
            or _path_role_core_falsification_capable(
                str(path.get("role") or ""),
                str(path.get("id") or ""),
            )
        )
        for path in evidence_paths
    )
    claim_contract = item.get("causal_contract") if isinstance(item.get("causal_contract"), dict) else {}
    direct_claim_target = normalize_space(str(
        claim_contract.get("outcome")
        or claim_contract.get("pivotal_mechanism")
        or (readouts[0] if readouts else "")
    ))
    component_bridge_contract = _component_bridge_operationality_contract(
        item,
        evidence_paths,
    )
    component_bridge_active = bool(component_bridge_contract.get("active"))
    axis_separation_audit = audit_subhypothesis_axis_role_separation(
        item,
        epistemic_profile=epistemic_profile,
    )

    blocking_reasons: list[str] = []
    warnings: list[str] = []

    def block(reason: str) -> None:
        if reason not in blocking_reasons:
            blocking_reasons.append(reason)

    def warn(reason: str) -> None:
        if reason not in warnings:
            warnings.append(reason)

    if epistemic_contract_audit.get("status") == "EPISTEMIC_CONTRACT_MISMATCH":
        block("epistemic_contract_mismatch")
    elif epistemic_contract_audit.get("query_constraint_status") == "QUERY_OVERCONSTRAINED":
        warn(
            "query_overconstrained_autosplit"
            if epistemic_contract_audit.get("auto_split_into_evidence_paths")
            else "query_overconstrained_requires_evidence_paths"
        )
    for reason in axis_separation_audit.get("blocking_reasons") or []:
        block(str(reason))
    for warning in axis_separation_audit.get("warnings") or []:
        warn(str(warning))

    if not scientific_object or _preflight_is_placeholder(scientific_object):
        block("scientific_object_missing")
    elif scientific_object_contract.get("valid") is False:
        block(
            str(
                scientific_object_contract.get("blocking_reason")
                or str(scientific_object_contract.get("error_code") or "").lower()
                or "scientific_object_contract_invalid"
            )
        )

    if component_bridge_active:
        warn("direct_core_disallowed_by_object_maturity")
        if component_bridge_contract.get("component_bridge_anchor_repair_required"):
            block("component_bridge_anchor_repair_required")
        elif not component_bridge_contract.get("has_searchable_component_or_bridge_anchor"):
            block("component_bridge_anchor_missing")
        if not component_bridge_contract.get("has_component_bridge_evidence_paths"):
            block("component_bridge_evidence_paths_missing")
        if not component_bridge_contract.get("bridge_gap_statement"):
            block("component_bridge_gap_statement_missing")
        if not component_bridge_contract.get("forbidden_direct_core_claims"):
            block("component_bridge_forbidden_direct_claim_missing")
        if not readouts and not component_bridge_contract.get("bridge_gap_statement"):
            block("observable_outcome_missing")
        elif readouts and not concrete_readouts:
            block("observable_outcome_not_operational")
        elif generic_readouts:
            warn("generic_outcome_present_but_concrete_readout_available")
    elif requires_intervention:
        if not input_value or _preflight_is_placeholder(input_value):
            block("independent_variable_missing")
        elif _preflight_is_generic_independent_variable(input_value):
            block("independent_variable_not_operational")
        elif _preflight_is_low_resolution_independent_variable(input_value):
            block("independent_variable_low_resolution")

        if not readouts:
            block("observable_outcome_missing")
        elif not concrete_readouts:
            block("observable_outcome_not_operational")
        elif generic_readouts:
            warn("generic_outcome_present_but_concrete_readout_available")
    else:
        if not direct_claim_target or _preflight_is_placeholder(direct_claim_target):
            block("observable_outcome_missing")
        if not has_profile_compatible_core_path:
            warn("profile_compatible_core_path_to_be_retrieved")
        if generic_readouts:
            warn("generic_outcome_present_but_profile_target_available")

    comparison_from_text = _preflight_has_textual_comparison(
        falsification,
        *causal_chain,
    )
    if component_bridge_active:
        if not comparisons and primary_mode in {"observational_inference", "engineering_validation"}:
            warn("comparison_not_declared_for_component_bridge_profile")
    elif requires_intervention:
        if not comparisons and not comparison_from_text:
            # Comparison evidence belongs to Gate 4.  A specific input and
            # observable outcome still define a searchable SH, and the bundle
            # evaluator can require/target the missing discriminator without
            # discarding the entire retrieval branch.
            warn("comparison_to_be_resolved_by_evidence_bundle")
        elif comparisons and all(
            _preflight_is_placeholder(value) or _preflight_is_generic_comparison(value)
            for value in comparisons
        ):
            # A vague comparator cannot rescue an already non-operational SH;
            # retain it as a structural failure in that case.  Otherwise keep
            # the SH searchable and let Gate 4 retrieve a concrete matched
            # comparison rather than rejecting it before any evidence exists.
            gate_one_failure = {
                "scientific_object_missing",
                "research_action_as_object",
                "boundary_condition_as_object",
                "independent_variable_missing",
                "independent_variable_not_operational",
                "independent_variable_low_resolution",
                "observable_outcome_missing",
                "observable_outcome_not_operational",
                "axis_role_object_input_overlap",
                "axis_role_object_mechanism_overlap",
                "axis_role_input_mechanism_semantic_collapse",
                "axis_role_outcome_field_conflict",
            }
            if gate_one_failure.intersection(blocking_reasons):
                block("comparison_not_specific")
            else:
                warn("comparison_not_specific_for_evidence_bundle")
    elif not comparisons and primary_mode in {"observational_inference", "engineering_validation"}:
        warn("comparison_not_declared_for_profile")

    excluded_comparisons = [
        comparison
        for comparison in comparisons
        if any(_preflight_phrases_overlap(comparison, excluded) for excluded in exclusions)
    ]
    if excluded_comparisons:
        block("comparison_object_excluded")

    if component_bridge_active:
        if not falsification or _preflight_is_placeholder(falsification):
            warn("falsification_condition_supplied_by_component_bridge_gap")
    elif not falsification or _preflight_is_placeholder(falsification):
        # Gate 5 can deterministically derive a prediction from a declared
        # input -> mediator -> outcome graph.  Record the omission, but do not
        # turn a retrievable mechanistic question into NOT_SEARCHABLE merely
        # because its author did not pre-write that sentence.
        warn("falsification_prediction_to_be_derived")
    elif requires_intervention and (
        falsification_source == "generated_default"
        or _preflight_text(falsification)
        in {"result that would refute the chain", "result that would refute this chain", "falsification condition"}
        or (
            "matched interventions on" in falsification.lower()
            and "competing mechanism explains the result better" in falsification.lower()
        )
        or "the proposed observable outcome" in falsification.lower()
    ):
        warn("falsification_condition_not_specific_for_gate_5")

    if (
        not component_bridge_active
        and requires_intervention
        and evidence_mode == "causal_mechanism"
        and len(causal_chain) < 2
    ):
        warn("causal_chain_under_specified")
    if not item.get("alternative_mechanisms") and not component_bridge_active:
        warn("alternative_mechanism_not_declared")
    if exclusions and not any(exclusions):
        warn("excluded_nearby_objects_not_specific")

    required_revisions = [
        _PREFLIGHT_REVISION_GUIDANCE[reason]
        for reason in blocking_reasons
        if reason in _PREFLIGHT_REVISION_GUIDANCE
    ]
    return {
        "version": SCIENTIFIC_OPERATIONALITY_PREFLIGHT_VERSION,
        "status": "blocked" if blocking_reasons else "ready",
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "required_revisions": required_revisions,
        "variables": {
            "scientific_object": scientific_object,
            "input": input_value,
            "input_role": input_role,
            "low_resolution_input_terms": _preflight_low_resolution_input_terms(input_value),
            "readouts": readouts,
            "concrete_readouts": concrete_readouts,
            "generic_readouts": generic_readouts,
            "missing_concrete_readout": bool(readouts and not concrete_readouts),
            "outcome_operationality": outcome_operationality,
            "outcome_audit": outcome_audit,
            "comparisons": comparisons,
            "comparison_from_text": comparison_from_text,
            "excluded_comparisons": excluded_comparisons,
            "falsification": falsification,
            "evidence_mode": evidence_mode,
            "epistemic_profile": epistemic_profile,
            "primary_epistemic_mode": primary_mode,
            "requires_intervention": requires_intervention,
            "direct_claim_target": direct_claim_target,
            "has_profile_compatible_core_path": has_profile_compatible_core_path,
            "epistemic_contract_audit": epistemic_contract_audit,
            "scientific_object_contract_audit": scientific_object_contract,
            "object_contract_valid": bool(scientific_object_contract.get("valid") is True),
            "object_contract_error": str(
                scientific_object_contract.get("error_code")
                or scientific_object_contract.get("error")
                or ""
            ),
            "axis_separation_audit": axis_separation_audit,
            "axis_role_overlap_reasons": list(axis_separation_audit.get("blocking_reasons") or []),
            "causal_contract_execution": dict(
                axis_separation_audit.get("causal_contract_execution") or {}
            ),
            "operationality_profile": (
                component_bridge_contract.get("operationality_profile")
                if component_bridge_active
                else "direct_or_profile_core"
            ),
            "component_bridge_contract": component_bridge_contract,
            "direct_core_evidence_allowed": (
                component_bridge_contract.get("direct_core_evidence_allowed")
                if component_bridge_active
                else item.get("direct_core_evidence_allowed")
            ),
            "direct_core_disallowed_by_object_maturity": bool(
                component_bridge_contract.get("direct_core_disallowed_by_object_maturity")
            ),
        },
    }


def annotate_subhypotheses_scientific_operationality(
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach deterministic preflight results without dropping source SHs."""

    blocked_ids: list[str] = []
    ready_ids: list[str] = []
    total = 0
    assessments_by_id: dict[str, dict[str, Any]] = {}
    outcome_operationality_counts: dict[str, int] = {}
    missing_concrete_readout_ids: list[str] = []
    generic_readout_terms: list[str] = []
    concrete_readout_terms: list[str] = []
    low_resolution_input_terms: list[str] = []
    for index, item in enumerate(sub_hypotheses):
        if not isinstance(item, dict):
            continue
        total += 1
        is_research_question_v3 = bool(
            item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or isinstance(item.get("research_question"), dict)
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
        if not is_research_question_v3:
            reconcile_subhypothesis_excluded_comparators(item)
            contract_audit = audit_subhypothesis_scientific_object_contract(item)
            contract_audit["sub_hypothesis_id"] = str(item.get("id") or f"SH{index + 1}")
            _apply_scientific_object_contract_audit_to_item(item, contract_audit)
        assessment = assess_subhypothesis_scientific_operationality(item)
        assessment["enforcement"] = "required"
        assessment = _reuse_equivalent_preflight(
            item.get("scientific_operationality_preflight"), assessment
        )
        # Assigning the existing object is deliberate: it avoids manufacturing
        # a project-field vN artifact when the causal specification is intact.
        item["scientific_operationality_preflight"] = assessment
        variables = assessment.get("variables") if isinstance(assessment.get("variables"), dict) else {}
        if isinstance(variables.get("axis_separation_audit"), dict):
            item["axis_separation_audit"] = variables["axis_separation_audit"]
        sub_id = str(item.get("id") or f"SH{index + 1}")
        assessments_by_id[sub_id] = assessment
        outcome_operationality = str(variables.get("outcome_operationality") or "unknown")
        outcome_operationality_counts[outcome_operationality] = outcome_operationality_counts.get(outcome_operationality, 0) + 1
        if variables.get("missing_concrete_readout"):
            missing_concrete_readout_ids.append(sub_id)
        for value in normalize_text_list(variables.get("generic_readouts")):
            if value not in generic_readout_terms:
                generic_readout_terms.append(value)
        for value in normalize_text_list(variables.get("concrete_readouts")):
            if value not in concrete_readout_terms:
                concrete_readout_terms.append(value)
        for value in normalize_text_list(variables.get("low_resolution_input_terms")):
            if value not in low_resolution_input_terms:
                low_resolution_input_terms.append(value)
        if assessment["status"] == "blocked":
            if "scientific_operationality_preflight_prior_status" not in item:
                item["scientific_operationality_preflight_prior_status"] = str(
                    item.get("status") or ""
                )
            item["status"] = "blocked_scientific_operationality"
            blocked_ids.append(sub_id)
        elif str(item.get("status") or "").startswith("blocked_scientific_operationality"):
            item["status"] = "pending_retrieval"
            ready_ids.append(sub_id)
        else:
            ready_ids.append(sub_id)
    return {
        "version": SCIENTIFIC_OPERATIONALITY_PREFLIGHT_VERSION,
        "total": total,
        "ready": len(ready_ids),
        "blocked": len(blocked_ids),
        "ready_sub_hypothesis_ids": ready_ids,
        "blocked_sub_hypothesis_ids": blocked_ids,
        "outcome_operationality_counts": outcome_operationality_counts,
        "missing_concrete_readout_sub_hypothesis_ids": missing_concrete_readout_ids,
        "generic_readout_terms": generic_readout_terms[:24],
        "concrete_readout_terms": concrete_readout_terms[:24],
        "low_resolution_input_terms": low_resolution_input_terms[:24],
        "assessments_by_id": assessments_by_id,
    }


def apply_subhypothesis_scientific_object_contract_preflight(
    project: dict[str, Any],
    *,
    emit_logs: bool = True,
) -> dict[str, Any]:
    """Refresh and persist the object-slot contract audit on a project."""

    sub_hypotheses = project.get("sub_hypotheses")
    if not isinstance(sub_hypotheses, list):
        sub_hypotheses = []
        project["sub_hypotheses"] = sub_hypotheses
    project_id = str(project.get("project_id") or project.get("id") or "")
    v3_sub_hypotheses = [
        item for item in sub_hypotheses
        if isinstance(item, dict)
        and (
            item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or isinstance(item.get("research_question"), dict)
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
    ]
    legacy_sub_hypotheses = [
        item for item in sub_hypotheses
        if isinstance(item, dict)
        and item not in v3_sub_hypotheses
    ]
    if not v3_sub_hypotheses:
        # The public preflight is retained as a diagnostic API name, but the
        # V3 project workflow never runs an object/process/outcome adapter for
        # a legacy SH.  Historical artifacts must be re-decomposed instead.
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}")
            for index, item in enumerate(legacy_sub_hypotheses)
        ]
        summary = {
            "schema_version": "research_question_scope_preflight_v3",
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "total": len(sub_hypotheses),
            "valid": 0,
            "invalid": len(stale_ids),
            "valid_sub_hypothesis_ids": [],
            "invalid_sub_hypothesis_ids": stale_ids,
            "invalid_by_error": {"RESEARCH_QUESTION_CONTRACT_V3_REQUIRED": stale_ids},
            "audits_by_id": {},
            "legacy_causal_object_contract_used": False,
        }
        project["subhypothesis_scientific_object_contract_preflight"] = summary
        decomposition = project.get("objective_decomposition")
        if isinstance(decomposition, dict):
            decomposition["scientific_object_contract_preflight"] = summary
        return summary
    if v3_sub_hypotheses:
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}")
            for index, item in enumerate(legacy_sub_hypotheses)
        ]
        summary = {
            "schema_version": "research_question_scope_preflight_v3",
            "status": (
                "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
                if stale_ids
                else "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3"
            ),
            "total": len(sub_hypotheses),
            "valid": 0,
            "invalid": len(stale_ids),
            "valid_sub_hypothesis_ids": [],
            "invalid_sub_hypothesis_ids": stale_ids,
            "invalid_by_error": (
                {"MIXED_LEGACY_AND_V3_SUBHYPOTHESES": stale_ids}
                if stale_ids
                else {}
            ),
            "audits_by_id": {},
            "legacy_causal_object_contract_used": False,
        }
        project["subhypothesis_scientific_object_contract_preflight"] = summary
        decomposition = project.get("objective_decomposition")
        if isinstance(decomposition, dict):
            decomposition["scientific_object_contract_preflight"] = summary
        return summary
    raise AssertionError("V3 cutover branching must return before a legacy object-contract audit")


def apply_subhypothesis_scientific_operationality_preflight(
    project: dict[str, Any],
) -> dict[str, Any]:
    """Refresh and persist the preflight on a loaded project dictionary."""

    sub_hypotheses = project.get("sub_hypotheses")
    if not isinstance(sub_hypotheses, list):
        sub_hypotheses = []
        project["sub_hypotheses"] = sub_hypotheses
    v3_sub_hypotheses = [
        item for item in sub_hypotheses
        if isinstance(item, dict)
        and (
            item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or isinstance(item.get("research_question"), dict)
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
    ]
    legacy_sub_hypotheses = [
        item for item in sub_hypotheses
        if isinstance(item, dict)
        and item not in v3_sub_hypotheses
    ]
    if v3_sub_hypotheses and legacy_sub_hypotheses:
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or f"SH{index + 1}")
            for index, item in enumerate(legacy_sub_hypotheses)
        ]
        for item in legacy_sub_hypotheses:
            item["scientific_operationality_preflight"] = {
                "version": "research_question_operationality_v3",
                "status": "blocked",
                "enforcement": "required",
                "blocking_reasons": ["research_question_contract_v3_required"],
                "required_revisions": [
                    "Re-decompose every SH as an explicit ResearchQuestionContractV3; mixed legacy and V3 artifacts are prohibited."
                ],
                "variables": {
                    "legacy_causal_preflight_used": False,
                    "outcome_operationality": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
                },
            }
        dependent_variable_scope_audit = {
            "schema_version": "research_question_scope_preflight_v3",
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "total": len(sub_hypotheses),
            "stale_sub_hypothesis_ids": stale_ids,
            "legacy_causal_preflight_used": False,
        }
    elif legacy_sub_hypotheses:
        for item in legacy_sub_hypotheses:
            item["scientific_operationality_preflight"] = {
                "version": "research_question_operationality_v3",
                "status": "blocked",
                "enforcement": "required",
                "blocking_reasons": ["research_question_contract_v3_required"],
                "required_revisions": [
                    "Re-decompose this SH as an explicit ResearchQuestionContractV3; legacy causal operationality repair is unavailable."
                ],
                "variables": {
                    "legacy_causal_preflight_used": False,
                    "outcome_operationality": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
                },
            }
        dependent_variable_scope_audit = {
            "schema_version": "research_question_scope_preflight_v3",
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "total": len(sub_hypotheses),
            "stale_sub_hypothesis_ids": [
                str(item.get("id") or item.get("sub_hypothesis_id") or "")
                for item in legacy_sub_hypotheses
            ],
            "legacy_causal_preflight_used": False,
        }
    else:
        dependent_variable_scope_audit = {
            "schema_version": "research_question_scope_preflight_v3",
            "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
            "total": len(sub_hypotheses),
        }
    project["subhypothesis_dependent_variable_scope_audit"] = dependent_variable_scope_audit
    if v3_sub_hypotheses and legacy_sub_hypotheses:
        # Do not call the generic annotator on a mixed list: its legacy branch
        # would inspect causal fields while preparing a result that must be a
        # V3 hard-cutover rejection. Current V3 SHs may still be validated so
        # the report tells the user exactly which remaining items are stale.
        summary = annotate_subhypotheses_scientific_operationality(v3_sub_hypotheses)
        stale_assessments = {
            str(item.get("id") or item.get("sub_hypothesis_id") or ""): dict(
                item.get("scientific_operationality_preflight") or {}
            )
            for item in legacy_sub_hypotheses
        }
        stale_ids = [item for item in stale_assessments if item]
        summary["total"] = int(summary.get("total") or 0) + len(stale_ids)
        summary["blocked"] = int(summary.get("blocked") or 0) + len(stale_ids)
        summary["blocked_sub_hypothesis_ids"] = list(
            summary.get("blocked_sub_hypothesis_ids") or []
        ) + stale_ids
        summary["assessments_by_id"] = {
            **dict(summary.get("assessments_by_id") or {}),
            **stale_assessments,
        }
        summary["schema_version"] = "research_question_operationality_cutover_v3"
        summary["status"] = "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        summary["legacy_causal_preflight_used"] = False
    elif legacy_sub_hypotheses:
        # The list is entirely stale. Avoid the legacy annotator because it
        # would inspect causal slots after the hard cutover has rejected them.
        summary = {
            "version": "research_question_operationality_cutover_v3",
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "total": len(legacy_sub_hypotheses),
            "ready": 0,
            "blocked": len(legacy_sub_hypotheses),
            "ready_sub_hypothesis_ids": [],
            "blocked_sub_hypothesis_ids": [
                str(item.get("id") or item.get("sub_hypothesis_id") or "")
                for item in legacy_sub_hypotheses
                if str(item.get("id") or item.get("sub_hypothesis_id") or "")
            ],
            "assessments_by_id": {
                str(item.get("id") or item.get("sub_hypothesis_id") or ""): dict(
                    item.get("scientific_operationality_preflight") or {}
                )
                for item in legacy_sub_hypotheses
                if str(item.get("id") or item.get("sub_hypothesis_id") or "")
            },
            "legacy_causal_preflight_used": False,
        }
    else:
        summary = annotate_subhypotheses_scientific_operationality(sub_hypotheses)
    summary = _reuse_equivalent_preflight(
        project.get("subhypothesis_scientific_operationality_preflight"), summary
    )
    project["subhypothesis_scientific_operationality_preflight"] = summary

    decomposition = project.get("objective_decomposition")
    if isinstance(decomposition, dict):
        decomposition["dependent_variable_scope_audit"] = dependent_variable_scope_audit
        decomposition_summary = _reuse_equivalent_preflight(
            decomposition.get("scientific_operationality_preflight"), summary
        )
        decomposition["scientific_operationality_preflight"] = decomposition_summary
        if summary["total"] and summary["blocked"] == summary["total"]:
            decomposition["status"] = "needs_scientific_model_revision"
        elif summary["blocked"]:
            decomposition["status"] = "partially_ready_for_subhypothesis_retrieval"
        elif summary["total"]:
            decomposition["status"] = "ready_for_subhypothesis_retrieval"
    return summary


def apply_subhypothesis_object_maturity_preflight(
    project: dict[str, Any],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Refresh object-literature anchorability before retrieval.

    This does not reject speculative/frontier projects.  It prevents an
    unformed final capability from becoming a false direct-core object anchor
    by converting that SH to component/bridge/boundary retrieval mode.
    """

    sub_hypotheses = project.get("sub_hypotheses")
    if not isinstance(sub_hypotheses, list):
        sub_hypotheses = []
        project["sub_hypotheses"] = sub_hypotheses
    v2_subhypotheses = [
        item for item in sub_hypotheses
        if isinstance(item, dict)
        and (
            item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or isinstance(item.get("research_question"), dict)
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
    ]
    # Object maturity is a legacy direct-core causal-retrieval concern.  A
    # typed question is admitted through its evidence slots and source spans,
    # so no component-bridge rewrite is allowed to mutate a V3 declaration.
    if v2_subhypotheses:
        stale_subhypotheses = [
            item for item in sub_hypotheses
            if isinstance(item, dict) and item not in v2_subhypotheses
        ]
        for item in v2_subhypotheses:
            item["object_maturity_preflight"] = {
                "schema_version": "research_question_object_maturity_v3",
                "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
                "retrieval_mode": "TYPE_DIRECTED_SLOT_RETRIEVAL",
                "legacy_causal_object_maturity_used": False,
            }
        if not stale_subhypotheses:
            summary = {
                "schema_version": "research_question_object_maturity_v3",
                "status": "NOT_APPLICABLE_TO_RESEARCH_QUESTION_CONTRACT_V3",
                "total": len(v2_subhypotheses),
                "directly_established": 0,
                "component_evidence_only": 0,
                "translational_bridge": 0,
                "speculative_unanchored": 0,
                "contract_repair_required": 0,
                "audits_by_id": {
                    str(item.get("id") or f"SH{index + 1}"): dict(item["object_maturity_preflight"])
                    for index, item in enumerate(v2_subhypotheses)
                },
                "direct_local_edge_evidence_allowed_by_id": {},
                "whole_sh_direct_core_allowed_by_id": {},
            }
            project["subhypothesis_object_maturity_preflight"] = summary
            decomposition = project.get("objective_decomposition")
            if isinstance(decomposition, dict):
                decomposition["object_maturity_preflight"] = summary
            return summary
        summary = {
            "schema_version": "research_question_object_maturity_v3",
            "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
            "total": len(sub_hypotheses),
            "stale_sub_hypothesis_ids": [
                str(item.get("id") or item.get("sub_hypothesis_id") or "")
                for item in stale_subhypotheses
            ],
            "legacy_causal_object_maturity_used": False,
        }
        project["subhypothesis_object_maturity_preflight"] = summary
        decomposition = project.get("objective_decomposition")
        if isinstance(decomposition, dict):
            decomposition["object_maturity_preflight"] = summary
        return summary
    # The direct-core/object-maturity model belongs to the retired causal-SH
    # pipeline.  A project with no current question contract must be
    # re-decomposed instead of being mutated into a legacy retrieval profile.
    for item in sub_hypotheses:
        if isinstance(item, dict):
            item["evidence_pipeline_schema"] = "STALE_SCHEMA"
            item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
    stale_ids = [
        str(item.get("id") or item.get("sub_hypothesis_id") or "")
        for item in sub_hypotheses
        if isinstance(item, dict)
    ]
    summary = {
        "schema_version": "research_question_object_maturity_v3",
        "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
        "total": len(sub_hypotheses),
        "stale_sub_hypothesis_ids": stale_ids,
        "legacy_causal_object_maturity_used": False,
        "next_step": "Re-decompose the project as explicit ResearchQuestionContractV3 declarations.",
    }
    project["subhypothesis_object_maturity_preflight"] = summary
    decomposition = project.get("objective_decomposition")
    if isinstance(decomposition, dict):
        decomposition["object_maturity_preflight"] = summary
    return summary


_OPERATIONALITY_REPAIR_MUTABLE_FIELDS = (
    "scientific_object",
    "independent_variable",
    "dependent_variables",
    "outcome_audit",
    "scientific_object_aliases",
    "causal_contract",
    "causal_chain",
    "controls",
    "boundary_conditions",
    "evidence_window",
    "comparison",
    "comparison_conditions",
    "falsification_condition",
    "alternative_mechanisms",
    "retrieval_query",
)


def _call_project_llm_json(
    *,
    system: str,
    prompt: str,
    max_tokens: int,
    fallback_list_key: str = "",
) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    return call_llm_json(
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        fallback_list_key=fallback_list_key,
    )


def _required_scientific_operationality_blocks(
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        item
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
        and isinstance(item.get("scientific_operationality_preflight"), dict)
        and item["scientific_operationality_preflight"].get("status") == "blocked"
        and item["scientific_operationality_preflight"].get("enforcement") == "required"
    ]


def _scientific_operationality_repair_signature(
    blocked_subhypotheses: list[dict[str, Any]],
) -> str:
    entries = []
    for item in blocked_subhypotheses:
        assessment = item.get("scientific_operationality_preflight") or {}
        variables = assessment.get("variables") if isinstance(assessment, dict) else {}
        entries.append({
            "id": str(item.get("id") or ""),
            "blocking_reasons": list(assessment.get("blocking_reasons") or []),
            "variables": variables if isinstance(variables, dict) else {},
        })
    return json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _subhypothesis_concrete_object_owners(
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for item in sub_hypotheses:
        if not isinstance(item, dict):
            continue
        sub_id = str(item.get("id") or "").strip()
        if not sub_id:
            continue
        focus_anchor = item.get("focus_anchor") if isinstance(item.get("focus_anchor"), dict) else {}
        anchors = normalize_text_list(focus_anchor.get("exclusive_concrete_objects"))
        if not anchors:
            anchors = _concrete_object_anchors(
                item.get("focus"),
                item.get("scientific_object"),
                item.get("independent_variable"),
                item.get("causal_chain"),
                item.get("retrieval_query"),
            )
        for anchor in anchors:
            owners.setdefault(str(anchor).upper(), sub_id)
    return owners


def _repair_candidate_has_foreign_concrete_object(
    candidate: dict[str, Any],
    *,
    sub_hypothesis_id: str,
    owners: dict[str, str],
) -> str:
    candidate_anchors = _concrete_object_anchors(
        candidate.get("independent_variable"),
        candidate.get("dependent_variables"),
        candidate.get("causal_chain"),
        candidate.get("controls"),
        candidate.get("comparison_conditions") or candidate.get("comparison"),
        candidate.get("falsification_condition"),
        candidate.get("alternative_mechanisms"),
        candidate.get("retrieval_query"),
    )
    foreign = sorted({
        anchor for anchor in candidate_anchors
        if owners.get(anchor.upper()) and owners[anchor.upper()] != sub_hypothesis_id
    })
    return ", ".join(foreign)


def _build_scientific_operationality_repair_candidate(
    original: dict[str, Any],
    repair: dict[str, Any],
    *,
    project: dict[str, Any],
) -> dict[str, Any]:
    candidate = copy.deepcopy(original)
    original_object_contract = audit_subhypothesis_scientific_object_contract(original)
    object_contract_invalid = bool(original_object_contract.get("valid") is False)
    original_axis_separation = audit_subhypothesis_axis_role_separation(original)
    axis_object_disentanglement_required = any(
        reason in {
            "axis_role_object_input_overlap",
            "axis_role_object_mechanism_overlap",
        }
        for reason in (original_axis_separation.get("blocking_reasons") or [])
    )
    if (object_contract_invalid or axis_object_disentanglement_required) and "scientific_object" in repair:
        value = normalize_space(str(repair.get("scientific_object") or ""))
        if value:
            candidate["scientific_object"] = value
            candidate["scientific_object_repaired_from"] = str(
                original_object_contract.get("original_scientific_object")
                or original.get("scientific_object")
                or ""
            )
            candidate["scientific_object_contract_repair_action"] = str(
                original_object_contract.get("repair_action")
                or "repair_axis_role_separation"
            )
    if "independent_variable" in repair:
        value = normalize_space(str(repair.get("independent_variable") or ""))
        if value:
            candidate["independent_variable"] = value
    for field_name in (
        "dependent_variables",
        "causal_chain",
        "controls",
        "alternative_mechanisms",
    ):
        if field_name in repair:
            values = normalize_text_list(repair.get(field_name))
            if values:
                candidate[field_name] = values
    if "scientific_object_aliases" in repair:
        values = normalize_text_list(repair.get("scientific_object_aliases"))
        if values:
            candidate["scientific_object_aliases"] = values
    if "boundary_conditions" in repair:
        values = normalize_text_list(repair.get("boundary_conditions"))
        if values:
            candidate["boundary_conditions"] = values
            candidate["moderators"] = list(dict.fromkeys(
                normalize_text_list(candidate.get("moderators")) + values
            ))
    if isinstance(repair.get("evidence_window"), dict):
        candidate["evidence_window"] = dict(repair.get("evidence_window") or {})
    candidate["outcome_audit"] = _preflight_outcome_audit(
        normalize_text_list(candidate.get("dependent_variables"))
    )
    if "comparison_conditions" in repair or "comparison" in repair:
        comparisons = normalize_text_list(
            repair.get("comparison_conditions")
            if "comparison_conditions" in repair
            else repair.get("comparison")
        )
        if comparisons:
            candidate["comparison_conditions"] = comparisons
            candidate["comparison"] = " | ".join(comparisons)
    if "falsification_condition" in repair:
        value = normalize_space(str(repair.get("falsification_condition") or ""))
        if value:
            candidate["falsification_condition"] = value
            candidate["falsification_condition_source"] = "declared"
    if "retrieval_query" in repair:
        value = normalize_space(str(repair.get("retrieval_query") or ""))
        if value:
            candidate["retrieval_query"] = value
            candidate["query_variants"] = focused_query_variants(
                value,
                str(candidate.get("focus") or ""),
                project_research_domain_context(project),
                evidence_mode=str(candidate.get("evidence_mode") or "causal_mechanism"),
                moderators=normalize_text_list(candidate.get("moderators")),
            )

    existing_contract = candidate.get("causal_contract")
    existing_contract = existing_contract if isinstance(existing_contract, dict) else {}
    repair_contract = (
        repair.get("causal_contract")
        if isinstance(repair.get("causal_contract"), dict)
        else {}
    )
    repair_input_contract = (
        repair_contract.get("input_contract")
        if isinstance(repair_contract.get("input_contract"), dict)
        else {}
    )
    existing_input_contract = (
        existing_contract.get("input_contract")
        if isinstance(existing_contract.get("input_contract"), dict)
        else {}
    )
    existing_claim_layer = (
        existing_contract.get("claim_layer_contract")
        if isinstance(existing_contract.get("claim_layer_contract"), dict)
        else {}
    )
    repair_claim_layer = (
        repair_contract.get("claim_layer_contract")
        if isinstance(repair_contract.get("claim_layer_contract"), dict)
        else {}
    )
    candidate["causal_contract"] = normalize_causal_contract(
        {
            "parent_decision_link": repair_contract.get("parent_decision_link") or existing_contract.get("parent_decision_link"),
            "constraint_type": repair_contract.get("constraint_type") or existing_contract.get("constraint_type"),
            "input_role": repair_input_contract.get("input_type") or repair_contract.get("input_role") or existing_input_contract.get("input_type"),
            "input_operational_definition": repair_input_contract.get("operational_definition") or repair_contract.get("input_operational_definition") or existing_input_contract.get("operational_definition"),
            "input_contrast": repair_input_contract.get("contrast_or_levels") or repair_contract.get("input_contrast") or existing_input_contract.get("contrast_or_levels"),
            "pivotal_mechanism": repair_contract.get("pivotal_mechanism") or repair.get("pivotal_mechanism") or existing_contract.get("pivotal_mechanism"),
            "pivotal_mechanism_role": repair_contract.get("pivotal_mechanism_role") or repair.get("pivotal_mechanism_role") or existing_contract.get("pivotal_mechanism_role"),
            "outcome": (
                repair_claim_layer.get("declared_outcome")
                or repair_claim_layer.get("local_empirical_outcome")
                or repair_contract.get("outcome")
                or existing_claim_layer.get("declared_outcome")
                or existing_contract.get("outcome")
            ),
            "claim_layer": repair_claim_layer.get("claim_layer") or repair_contract.get("claim_layer") or existing_claim_layer.get("claim_layer"),
            "local_empirical_outcome": repair_claim_layer.get("local_empirical_outcome") or repair_contract.get("local_empirical_outcome") or existing_claim_layer.get("local_empirical_outcome"),
            "transfer_target": repair_claim_layer.get("transfer_target") or repair_contract.get("transfer_target") or existing_claim_layer.get("transfer_target"),
            "transfer_basis": repair_claim_layer.get("transfer_basis") or repair_contract.get("transfer_basis") or existing_claim_layer.get("transfer_basis"),
            "transfer_validation_status": repair_claim_layer.get("transfer_validation_status") or repair_contract.get("transfer_validation_status") or existing_claim_layer.get("transfer_validation_status"),
            "boundary_conditions": (
                normalize_text_list(existing_contract.get("boundary_conditions"))
                + normalize_text_list(candidate.get("boundary_conditions"))
            ),
            "confounders_or_alternatives": existing_contract.get("confounders_or_alternatives"),
        },
        objective=str(project.get("objective") or candidate.get("source_objective") or ""),
        focus=str(candidate.get("focus") or ""),
        independent_variable=str(candidate.get("independent_variable") or ""),
        causal_chain=normalize_text_list(candidate.get("causal_chain")),
        dependent_variables=normalize_text_list(candidate.get("dependent_variables")),
        alternative_mechanisms=normalize_text_list(candidate.get("alternative_mechanisms")),
        boundary_conditions=normalize_text_list(candidate.get("moderators")),
    )
    # ``focus_anchor`` is partly derivative metadata.  Keeping its identity
    # fields prevents a repair from stealing another SH's object, but retaining
    # stale input/mechanism/outcome fields would immediately recreate the
    # very axis conflict the repair just resolved.
    if isinstance(candidate.get("focus_anchor"), dict):
        focus_anchor = dict(candidate.get("focus_anchor") or {})
        repaired_contract = candidate.get("causal_contract") or {}
        focus_anchor["intervention_anchor"] = str(
            candidate.get("independent_variable") or ""
        )
        focus_anchor["mechanism_anchor"] = str(
            repaired_contract.get("pivotal_mechanism") or ""
        )
        focus_anchor["outcome_anchor"] = str(
            repaired_contract.get("outcome") or ""
        )
        candidate["focus_anchor"] = focus_anchor
    if object_contract_invalid or axis_object_disentanglement_required:
        for key in (
            "scientific_object_contract_audit",
            "axis_separation_audit",
            "object_maturity_preflight",
            "object_maturity_audit",
            "typed_component_bridge_anchors",
            "component_bridge_anchor_quality",
            "retrieval_blocked_reason",
        ):
            candidate.pop(key, None)
    if object_contract_invalid:
        if candidate.get("object_maturity_retrieval_mode") == "contract_repair_required":
            candidate.pop("object_maturity_retrieval_mode", None)
        repaired_contract = audit_subhypothesis_scientific_object_contract(candidate)
        _apply_scientific_object_contract_audit_to_item(candidate, repaired_contract)
    candidate["status"] = "pending_retrieval"
    return candidate


def _scientific_operationality_repair_prompt(
    project: dict[str, Any],
    blocked_subhypotheses: list[dict[str, Any]],
    owners: dict[str, str],
) -> str:
    blocked = []
    for item in blocked_subhypotheses:
        assessment = item.get("scientific_operationality_preflight") or {}
        variables = assessment.get("variables") if isinstance(assessment, dict) else {}
        variables = variables if isinstance(variables, dict) else {}
        focus_anchor = item.get("focus_anchor") if isinstance(item.get("focus_anchor"), dict) else {}
        blocked.append({
            "id": str(item.get("id") or ""),
            "focus": item.get("focus"),
            "focus_anchor": focus_anchor.get("anchor"),
            "scientific_object": item.get("scientific_object"),
            "exclusive_concrete_objects": focus_anchor.get("exclusive_concrete_objects", []),
            "excluded_nearby_objects": item.get("excluded_nearby_objects", []),
            "evidence_mode": item.get("evidence_mode"),
            "causal_contract_parent_decision_link": (
                (item.get("causal_contract") or {}).get("parent_decision_link")
                if isinstance(item.get("causal_contract"), dict) else ""
            ),
            "current_operational_fields": {
                field_name: item.get(field_name)
                for field_name in _OPERATIONALITY_REPAIR_MUTABLE_FIELDS
            },
            "preflight": {
                "blocking_reasons": assessment.get("blocking_reasons", []),
                "required_revisions": assessment.get("required_revisions", []),
                "outcome_operationality": (
                    (assessment.get("variables") or {}).get("outcome_operationality")
                    if isinstance(assessment.get("variables"), dict) else ""
                ),
                "generic_readouts": (
                    (assessment.get("variables") or {}).get("generic_readouts")
                    if isinstance(assessment.get("variables"), dict) else []
                ),
                "concrete_readouts": (
                    (assessment.get("variables") or {}).get("concrete_readouts")
                    if isinstance(assessment.get("variables"), dict) else []
                ),
                "outcome_audit": (
                    (assessment.get("variables") or {}).get("outcome_audit")
                    if isinstance(assessment.get("variables"), dict) else {}
                ),
                "scientific_object_contract_audit": (
                    (assessment.get("variables") or {}).get("scientific_object_contract_audit")
                    if isinstance(assessment.get("variables"), dict) else item.get("scientific_object_contract_audit", {})
                ),
                "object_contract_error": (
                    (assessment.get("variables") or {}).get("object_contract_error")
                    if isinstance(assessment.get("variables"), dict) else ""
                ),
                "low_resolution_input_terms": (
                    variables.get("low_resolution_input_terms")
                ),
                "axis_separation_audit": variables.get(
                    "axis_separation_audit",
                    item.get("axis_separation_audit", {}),
                ),
            },
        })
    schema = {
        "repairs": [{
            "id": "existing SH identifier",
            "scientific_object": "noun-like scientific entity/system/process only when preflight.object_contract_error is non-empty",
            "independent_variable": "parameterized perturbation, exposure class, dose, composition dimension, feature set, process variable, or defined condition distinct from scientific_object and causal_chain[1]",
            "dependent_variables": ["2-4 concrete measurable readouts, not placeholders and not copies of the input/mechanism"],
            "scientific_object_aliases": [
                "true semantic-equivalent names, acronyms, orthographic variants, or field-standard synonyms for the same unchanged scientific_object"
            ],
            "outcome_audit": {
                "status": "concrete_readout_bound",
                "concrete_readouts": ["same concrete readouts returned in dependent_variables"],
                "rejected_generic_outcomes": ["generic outcomes removed from the broken draft"],
                "revision_required": False,
                "rationale": "why the returned outcomes are measurable"
            },
            "causal_chain": ["defined input or contrast", "specific mediator state distinct from the input for causal claims", "concrete readout change"],
            "causal_contract": {
                "input_contract": {
                    "input_type": "INTERVENTION | EXPOSURE | STRATIFICATION | PARAMETER",
                    "operational_definition": "the declared input as a defined condition",
                    "contrast_or_levels": ["actual comparison levels when available"],
                },
                "pivotal_mechanism": "specific causal process, mediator state, or direct target; never a duplicated endpoint readout",
                "pivotal_mechanism_role": "CAUSAL_PROCESS | MEDIATOR_STATE | DIRECT_TARGET",
                "outcome": "one local observable endpoint consistent with dependent_variables",
                "claim_layer_contract": {
                    "claim_layer": "LOCAL_EMPIRICAL",
                    "local_empirical_outcome": "same local endpoint"
                }
            },
            "controls": ["concrete matched control or confounder"],
            "boundary_conditions": ["time horizon, system boundary, baseline, scenario, or protocol parameter moved out of scientific_object"],
            "evidence_window": {"time_horizon_years": 50, "purpose": "only when the broken object was a time horizon or assessment window"},
            "comparison_conditions": ["concrete counterfactual or reference condition"],
            "falsification_condition": "specific observation that rejects this SH relation",
            "alternative_mechanisms": ["competing explanation"],
            "retrieval_query": "4-12 English academic keywords or phrases without Boolean syntax",
        }]
    }
    payload = {
        "objective": str(project.get("objective") or ""),
        "domain": project_research_domain_context(project),
        "research_brief": str(project.get("research_brief") or "")[:12000],
        "blocked_subhypotheses": blocked,
        "concrete_object_ownership": owners,
        "allowed_mutable_fields": list(_OPERATIONALITY_REPAIR_MUTABLE_FIELDS),
        "schema": schema,
    }
    return (
        "Repair only the blocked causal sub-hypotheses in the supplied research decomposition. "
        "Keep the parent research direction and each SH's focus and focus_anchor identity, "
        "exclusive_concrete_objects, excluded_nearby_objects, evidence mode, SH identifier, and causal-contract "
        "parent decision link unchanged. Do not merge, delete, add, or renumber sub-hypotheses. "
        "The system will regenerate focus_anchor intervention/mechanism/outcome metadata from the repaired causal contract; do not preserve stale role fields. "
        "Treat preflight.axis_separation_audit as hard authority: a valid repair must not reuse the same "
        "semantic nucleus across scientific_object, independent_variable, the causal_chain[1]/pivotal-mechanism "
        "slot, and dependent_variables/outcome. scientific_object is the primary system/entity/process/formal "
        "object; independent_variable is the changed parameter, exposure, perturbation, or defined condition; "
        "causal_chain[1] is a distinct mediator/process only for causal or mechanistic claims; dependent_variables "
        "are concrete readouts. For a pivotal_mechanism_is_readout_proxy failure, return causal_contract with a "
        "new distinct pivotal_mechanism and set pivotal_mechanism_role to CAUSAL_PROCESS, MEDIATOR_STATE, or "
        "DIRECT_TARGET. Do not merely relabel the duplicated rate, score, activity, abundance, concentration, "
        "diversity, or other measurement as a mechanism. "
        "Keep scientific_object unchanged unless preflight.object_contract_error is non-empty or "
        "preflight.axis_separation_audit.blocking_reasons requires object/input or object/mechanism "
        "disentanglement. If axis separation requires it, narrow scientific_object to the primary system/object "
        "or change independent_variable/causal_chain so the roles are independent; never repair by copying one "
        "phrase into another role. If object_contract_error is "
        "RESEARCH_ACTION_AS_OBJECT, replace scientific_object with the noun-like entity/system/process under "
        "study and move the comparison action into comparison_conditions/evidence_paths. If it is "
        "BOUNDARY_CONDITION_AS_OBJECT, move the parameter or time horizon into boundary_conditions or "
        "evidence_window and derive the scientific_object from the SH focus, comparator, target system, "
        "or parent objective. If it is READOUT_AS_OBJECT, move the endpoint into dependent_variables and "
        "name the actual object being measured. "
        "You may add or repair scientific_object_aliases, but only with true semantic-equivalent names, acronyms, "
        "orthographic variants, or field-standard synonyms for the unchanged scientific_object. Do not put parent "
        "context objects, mediators, comparators, components, or broad generic tokens into scientific_object_aliases. "
        "Do not introduce a concrete technical object owned by another SH. "
        "For every requested repair, supply operational variables that directly address the listed preflight failures: "
        "a specific input or condition, measurable readout, concrete comparison, and SH-specific falsification condition. "
        "When a dependent variable is broad, such as function, performance, effectiveness, organization, formation, "
        "reliability, quality, impact, success, or result, replace it with 2-4 concrete measurable readouts. "
        "Return outcome_audit for every repair. The audit must reject generic outcomes such as reliable results, "
        "reproducible results, reliable and reproducible results, reliability, reproducibility, visualization, "
        "understanding, function, organization, performance, quality, effectiveness, effect, impact, result, "
        "and success unless they are paired with an actual measurable statistic, assay output, "
        "structural property, error metric, rate, concentration, physical quantity, clinical/event endpoint, "
        "manufacturing quality attribute, operational metric, or formal/model output. "
        "A valid readout must be observable as a statistic, structural property, assay output, rate, concentration, "
        "error metric, threshold, classification score, physical quantity, clinical/event endpoint, "
        "manufacturing quality attribute, operational metric, or formal/model output. Do not use placeholder "
        "phrases such as measurable endpoint, measurable readout, functional outcome, cellular function, system "
        "performance, visualization of an object, reliable results, reproducible results, reliable and reproducible "
        "results, or improved outcome. "
        "The retrieval query must stay within that SH's existing causal scope. Do not fabricate study results, "
        "measurements, papers, or factual claims. Return JSON only.\n\n"
        f"Repair context:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def repair_project_subhypotheses_scientific_operationality(
    project_id: str,
    *,
    use_llm: bool = True,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Repair required preflight failures before any SH can enter retrieval."""

    project = load_project(project_id)
    sub_hypotheses = [
        item for item in project.get("sub_hypotheses", []) if isinstance(item, dict)
    ]
    v3_sub_hypotheses = [
        item for item in sub_hypotheses
        if (
            item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            and (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
    ]
    object_contract_preflight = apply_subhypothesis_scientific_object_contract_preflight(
        project,
        emit_logs=True,
    )
    preflight = apply_subhypothesis_scientific_operationality_preflight(project)
    blocked = _required_scientific_operationality_blocks(project)
    expected_ids = [
        str(item.get("id") or "")
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    # This public repair endpoint is V3-only. In particular, it must not use
    # an LLM to fill historical causal fields when the project contains no
    # ResearchQuestionContractV3 declaration at all.
    if not v3_sub_hypotheses:
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or "")
            for item in sub_hypotheses
        ]
        project["updatedAt"] = time.time()
        save_project(project)
        return {
            "project_id": project_id,
            "status": "needs_research_question_contract_redecomposition",
            "attempts": 0,
            "expected_sub_hypothesis_ids": expected_ids,
            "blocked_sub_hypothesis_ids": [
                str(item.get("id") or "") for item in blocked
            ],
            "stale_sub_hypothesis_ids": stale_ids,
            "scientific_object_contract_preflight": object_contract_preflight,
            "scientific_operationality_preflight": preflight,
            "legacy_causal_repair_used": False,
            "next_step": "Re-decompose all SHs as explicit ResearchQuestionContractV3 declarations.",
        }
    # A V3 declaration is never repaired with the historical causal
    # operationality prompt. A malformed V3 question—or a project that mixes
    # a V3 question with stale SH artifacts—requires a fresh typed
    # decomposition.  This branch intentionally precedes every legacy repair
    # signature, owner calculation, and LLM call below.
    if v3_sub_hypotheses:
        stale_ids = [
            str(item.get("id") or item.get("sub_hypothesis_id") or "")
            for item in sub_hypotheses
            if item not in v3_sub_hypotheses
        ]
        project["updatedAt"] = time.time()
        save_project(project)
        return {
            "project_id": project_id,
            "status": (
                "needs_research_question_contract_redecomposition"
                if stale_ids
                else ("ready" if not blocked else "needs_research_question_contract_revision")
            ),
            "attempts": 0,
            "expected_sub_hypothesis_ids": expected_ids,
            "blocked_sub_hypothesis_ids": [
                str(item.get("id") or "") for item in blocked
            ],
            "stale_sub_hypothesis_ids": stale_ids,
            "scientific_object_contract_preflight": object_contract_preflight,
            "scientific_operationality_preflight": preflight,
            "legacy_causal_repair_used": False,
            "next_step": (
                "Re-decompose all SHs as explicit ResearchQuestionContractV3 declarations."
                if stale_ids
                else "Revise the invalid ResearchQuestionContractV3 declaration; causal-field repair is not available."
            ),
        }
    if not blocked:
        return {
            "project_id": project_id,
            "status": "ready",
            "attempts": 0,
            "expected_sub_hypothesis_ids": expected_ids,
            "blocked_sub_hypothesis_ids": [],
            "scientific_object_contract_preflight": object_contract_preflight,
            "scientific_operationality_preflight": preflight,
        }


_DISCOVERY_EVIDENCE_PATH_MARKERS = (
    "discover", "identif", "screen", "profil", "map", "association",
    "characteriz", "candidate", "omics",
)
_VALIDATION_EVIDENCE_PATH_MARKERS = (
    "validat", "causal", "intervention", "perturb", "experiment", "assay",
    "trial", "model", "replicat", "test",
)

_PREDICTIVE_GENERALIZATION_MARKERS = (
    "generaliz", "generalis", "external validation", "transportab", "subgroup performance",
    "calibration", "fairness", "bias", "domain shift", "distribution shift", "multi-site", "multisite",
)


def normalize_subhypothesis_evidence_mode(
    item: dict[str, Any],
    *,
    focus: str,
    causal_chain: list[str],
) -> str:
    declared = normalize_space(str(item.get("evidence_mode") or "")).lower().replace("-", "_").replace(" ", "_")
    if declared in {"predictive_generalization", "predictive_validation", "model_generalization", "transportability_validation"}:
        return "predictive_generalization"
    source = " ".join([focus, *causal_chain, str(item.get("falsification_condition") or "")]).lower()
    predictive_model = any(marker in source for marker in ("machine learning", "artificial intelligence", "statistical model", "prediction model", "predictive model", "algorithm"))
    predictive_boundary = any(marker in source for marker in _PREDICTIVE_GENERALIZATION_MARKERS)
    return "predictive_generalization" if predictive_model and predictive_boundary else "causal_mechanism"


def _evidence_path_role(value: Any) -> str:
    normalized = normalize_space(str(value or "")).lower().replace("-", "_").replace(" ", "_")
    if normalized in EVIDENCE_ROLE_REGISTRY:
        return normalized
    if normalized in {"core_effect_path", "core_effect", "supportive_core_effect", "primary_effect_path"}:
        return "core_validation"
    if normalized in {
        "adverse_or_reversal_path", "adverse_or_reversal", "reversal_path",
        "adverse_path", "opposing_path", "opposing_evidence",
        "negative_evidence", "tradeoff_path", "trade_off_path",
    }:
        return "adverse_or_reversal"
    if normalized in {
        "boundary_or_generalization_path", "boundary_or_generalization",
        "boundary_path", "generalization_path", "heterogeneity_path",
        "external_validity_path", "validity_boundary",
    }:
        return "boundary_or_generalization"
    if normalized in {"mechanism_discovery", "discovery", "candidate_discovery", "mapping"}:
        return "mechanism_discovery"
    if normalized in {"causal_validation", "validation", "experimental_validation", "intervention_validation"}:
        return "causal_validation"
    if normalized in {
        "direct_observation", "observation_constraint", "parameter_constraint",
        "survey_or_catalog_analysis", "mission_or_data_release", "model_comparison",
        "systematics_or_independent_dataset",
    }:
        return normalized
    if normalized in {
        "theoretical_derivation", "consistency_or_limiting_case", "observable_prediction",
        "formal_proof", "counterexample_or_assumption_boundary",
        "simulation_validation", "convergence_or_sensitivity",
        "performance_validation", "robustness_or_fault_mode",
        "descriptive_catalog", "sampling_or_definition_boundary",
        "evidence_synthesis", "heterogeneity_or_evidence_quality",
    }:
        return normalized
    if normalized in {
        "core_validation", "integrative_core_validation", "integrated_core_validation",
        "panel_validation", "panel_incremental_prediction", "incremental_prediction",
        "integrated_multiomics_core", "process_parameter_core",
    }:
        return "core_validation"
    if normalized in {
        "comparative_validation", "baseline_comparison", "incremental_value",
        "single_omics_comparison", "single_marker_comparison", "panel_comparison",
    }:
        return "comparative_validation"
    if normalized in {
        "supporting_mechanism", "mechanism_support", "component_mechanism",
        "component_mechanism_support", "component_support", "mechanism_component",
        "single_gene_mechanism_support", "metabolism_enzyme_component",
        "transporter_component", "toxicity_variant_component",
        "genomics_component", "transcriptomic_proteomic_component",
        "potency_purity_path", "sterility_path",
    }:
        return "supporting_mechanism"
    if normalized in {
        "component_evidence", "component_evidence_path",
        "component_bridge_evidence", "enabling_component_evidence",
        "platform_component_evidence",
    }:
        return "component_evidence"
    if normalized in {
        "translational_bridge", "translational_bridge_path",
        "translation_bridge", "bridge_evidence", "model_system_bridge",
    }:
        return "translational_bridge"
    if normalized in {
        "boundary_or_safety_evidence", "boundary_or_safety_evidence_path",
        "safety_boundary", "safety_evidence", "failure_boundary",
    }:
        return "boundary_or_safety_evidence"
    if normalized in {"supporting_constraint", "quality_constraint", "release_constraint"}:
        return "supporting_constraint"
    if normalized in {"deployment_constraint", "operational_feasibility", "operational_feasibility_path"}:
        return "deployment_constraint"
    if normalized in {
        "predictive_validation", "external_validation", "subgroup_validation",
        "boundary_validation", "transportability_validation", "model_generalization",
    }:
        return "predictive_validation"
    # Keep explicit, user-supplied panel/path roles when they clearly encode a
    # retrieval responsibility.  Without this, roles such as
    # ``metabolism_enzyme_component`` are silently dropped and all component
    # evidence collapses back into one broad SH query.
    if any(
        marker in normalized
        for marker in (
            "core", "compar", "increment", "support", "component",
            "constraint", "deployment", "validation", "generalization",
            "observation", "derivation", "proof", "counterexample", "simulation",
            "convergence", "performance", "robustness", "catalog", "synthesis",
        )
    ):
        return normalized[:80]
    return ""


def _evidence_path_polarity(role: str, path_id: str = "", supplied: Any = "") -> str:
    normalized = normalize_space(str(supplied or "")).lower().replace("-", "_").replace(" ", "_")
    if normalized in {"supportive", "opposing", "boundary", "mixed", "unclear"}:
        return normalized
    text = f"{role} {path_id}".lower()
    if any(marker in text for marker in ("adverse", "reversal", "opposing", "negative", "tradeoff")):
        return "opposing"
    if any(marker in text for marker in ("boundary", "generalization", "heterogeneity", "external_validity")):
        return "boundary"
    return "supportive"


def _compact_retrieval_query(*parts: Any, fallback: str = "") -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for value in normalize_text_list(part) if isinstance(part, list) else [part]:
            text = normalize_space(str(value or ""))
            if not text:
                continue
            # Retrieval queries are provider-facing; keep them concise and do
            # not introduce Boolean syntax here.
            text = re.sub(r"\b(?:AND|OR|NOT)\b", " ", text)
            for phrase in re.split(r"[|;,]+", text):
                clean = normalize_space(phrase)
                if not clean:
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                tokens.append(clean)
                if len(tokens) >= 12:
                    return normalize_space(" ".join(tokens))
    return normalize_space(" ".join(tokens)) or fallback


def ensure_profile_compatible_evidence_paths(
    paths: list[dict[str, Any]],
    *,
    focus: str,
    scientific_object: str = "",
    causal_chain: list[str] | None = None,
    dependent_variables: list[str] | None = None,
    boundary_conditions: list[str] | None = None,
    fallback_query: str = "",
    epistemic_profile: dict[str, Any] | None = None,
    evidence_role_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ensure direct and qualifying paths without imposing causal templates.

    This handles every non-interventional paradigm.  A direct observation,
    proof, derivation, simulation validation, or engineering benchmark can be
    the core path; an adverse/reversal path is neither synthesized nor made a
    prerequisite unless the SH itself is experimental and causal.
    """

    source_paths = [dict(path) for path in paths if isinstance(path, dict)]
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    mode = str(profile.get("primary_mode") or "unresolved")
    claim_types = [str(item) for item in profile.get("claim_types", []) if str(item)]
    object_anchor = normalize_space(scientific_object or focus)
    chain = list(causal_chain or [])
    readouts = list(dependent_variables or [])
    target = _preflight_first_concrete_readout(readouts, chain[-1:] if chain else []) or focus
    boundary = normalize_space(" ".join((boundary_conditions or [])[:2]))
    role_contract = evidence_role_contract if isinstance(evidence_role_contract, dict) else {}
    selected_roles = [
        str(role) for role in role_contract.get("selected_roles", [])
        if str(role) in EVIDENCE_ROLE_REGISTRY
    ]
    if selected_roles:
        existing = {
            str(path.get("role") or path.get("id") or "").strip().lower()
            for path in source_paths
        }
        for role in selected_roles:
            if role not in existing:
                source_paths.append(role_evidence_path(
                    role,
                    focus=focus,
                    scientific_object=object_anchor,
                    target=target or boundary,
                    fallback_query=fallback_query,
                ))
        return source_paths
    templates = {
        "observational_inference": (
            "direct_observation_or_parameter_constraint", "direct_observation",
            "observation catalog survey likelihood posterior parameter constraint",
            "systematics_or_independent_dataset", "systematic uncertainty calibration independent dataset model comparison",
        ),
        "theoretical_derivation": (
            "theoretical_derivation_path", "theoretical_derivation",
            "assumptions equation derivation stability limiting case prediction",
            "consistency_or_limiting_case", "consistency stability limiting case alternative assumption",
        ),
        "mathematical_proof": (
            "formal_proof_path", "formal_proof",
            "theorem proof lemma proposition",
            "counterexample_or_assumption_boundary", "counterexample assumption boundary generalization",
        ),
        "computational_simulation": (
            "simulation_validation_path", "simulation_validation",
            "numerical simulation convergence benchmark sensitivity",
            "convergence_or_sensitivity_path", "convergence sensitivity uncertainty benchmark",
        ),
        "engineering_validation": (
            "performance_validation_path", "performance_validation",
            "performance benchmark calibration robustness metric",
            "robustness_or_fault_mode_path", "robustness fault mode reliability operating condition",
        ),
        "classification_description": (
            "descriptive_catalog_path", "descriptive_catalog",
            "catalog classification specimen morphology characterization",
            "sampling_or_definition_boundary", "sampling definition boundary comparative characterization",
        ),
        "synthesis_evaluation": (
            "evidence_synthesis_path", "evidence_synthesis",
            "systematic review evidence synthesis meta analysis",
            "heterogeneity_or_evidence_quality_path", "heterogeneity evidence quality risk of bias",
        ),
        "unresolved": (
            "direct_claim_path", "direct_claim_validation",
            "direct evidence measurement model analysis",
            "claim_boundary_path", "assumption uncertainty boundary",
        ),
    }
    core_id, core_role, core_terms, qualifier_id, qualifier_terms = templates.get(
        mode, templates["unresolved"]
    )
    existing_ids = {str(path.get("id") or "").strip().lower() for path in source_paths}
    has_core = any(
        bool(path.get("can_independently_falsify_sh") is True)
        or str(path.get("role") or "").strip().lower()
        in {core_role, "core_validation", "comparative_validation", "predictive_validation"}
        for path in source_paths
    )
    if not has_core:
        source_paths.append({
            "id": core_id,
            "role": core_role,
            "polarity": "supportive",
            "causal_steps": [f"direct {', '.join(claim_types) or 'scientific'} target: {target}"],
            "retrieval_query": _compact_retrieval_query(object_anchor, core_terms, target, fallback=fallback_query),
            "failure_scope": "whole_sh_core_falsification",
            "can_independently_falsify_sh": True,
            "missing_path_blocks_sh": True,
            "source": "deterministic_epistemic_profile_path",
        })
    if qualifier_id not in existing_ids:
        source_paths.append({
            "id": qualifier_id,
            "role": qualifier_id.replace("_path", ""),
            "polarity": "boundary",
            "causal_steps": [boundary or f"qualification of {target}"],
            "retrieval_query": _compact_retrieval_query(object_anchor, qualifier_terms, boundary, target, fallback=fallback_query),
            "failure_scope": "claim_qualification_or_boundary_gap",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "source": "deterministic_epistemic_profile_path",
        })
    return source_paths


def ensure_core_adverse_boundary_evidence_paths(
    paths: list[dict[str, Any]],
    *,
    focus: str,
    scientific_object: str = "",
    independent_variable: str = "",
    causal_chain: list[str] | None = None,
    dependent_variables: list[str] | None = None,
    comparison: str = "",
    boundary_conditions: list[str] | None = None,
    fallback_query: str = "",
    epistemic_profile: dict[str, Any] | None = None,
    evidence_role_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ensure every SH can retrieve supportive, opposing, and boundary evidence."""

    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    if evidence_role_contract:
        return ensure_profile_compatible_evidence_paths(
            paths,
            focus=focus,
            scientific_object=scientific_object,
            causal_chain=causal_chain,
            dependent_variables=dependent_variables,
            boundary_conditions=boundary_conditions,
            fallback_query=fallback_query,
            epistemic_profile=profile,
            evidence_role_contract=evidence_role_contract,
        )
    if profile and not bool(profile.get("requires_intervention") is True):
        return ensure_profile_compatible_evidence_paths(
            paths,
            focus=focus,
            scientific_object=scientific_object,
            causal_chain=causal_chain,
            dependent_variables=dependent_variables,
            boundary_conditions=boundary_conditions,
            fallback_query=fallback_query,
            epistemic_profile=profile,
        )

    source_paths = [dict(path) for path in paths if isinstance(path, dict)]
    by_id = {str(path.get("id") or "").strip().lower() for path in source_paths}
    by_role = {str(path.get("role") or "").strip().lower() for path in source_paths}
    polarities = {str(path.get("polarity") or "").strip().lower() for path in source_paths}
    chain = list(causal_chain or [])
    readouts = list(dependent_variables or [])
    object_anchor = normalize_space(scientific_object or focus)
    strategy = normalize_space(independent_variable or (chain[0] if chain else "") or focus)
    mechanism = normalize_space(chain[1] if len(chain) > 2 else (chain[0] if chain else focus))
    outcome = _preflight_first_concrete_readout(readouts, chain[-1:] if chain else [])
    query_operationality = "concrete_readout_bound" if outcome else "weak_missing_concrete_readout"
    comparator = normalize_space(comparison or "baseline counterfactual comparison")
    boundary = normalize_space(" ".join((boundary_conditions or [])[:2]) or "boundary condition implementation context")

    def role_specific_query(role: str) -> str:
        role_key = str(role or "").lower()
        if "adverse" in role_key or "reversal" in role_key or "oppos" in role_key:
            return _compact_retrieval_query(
                object_anchor,
                strategy,
                "adverse effect failure mode implementation failure",
                outcome,
                comparator,
                fallback=fallback_query,
            )
        if "boundary" in role_key or "generalization" in role_key or "generalisation" in role_key:
            return _compact_retrieval_query(
                object_anchor,
                strategy,
                boundary,
                "heterogeneity threshold sensitivity external validation",
                outcome,
                fallback=fallback_query,
            )
        return _compact_retrieval_query(
            object_anchor,
            strategy,
            mechanism,
            outcome,
            comparator,
            "validation comparison",
            fallback=fallback_query,
        )

    def query_needs_mechanistic_rewrite(query: str, role: str) -> bool:
        text = normalize_space(query).lower()
        if not text:
            return True
        if any(
            placeholder in text
            for placeholder in (
                "measurable endpoint", "measurable readout", "functional outcome",
                "cellular function", "system performance", "reliable results",
                "reproducible results", "improved outcome", "net measurable outcome",
            )
        ):
            return True
        token_count = len(re.findall(r"[a-z0-9][a-z0-9-]*", text))
        if token_count < 6:
            return True
        generic_topic_markers = {
            "benefit", "benefits", "effectiveness", "effect", "effects",
            "impact", "impacts", "role", "management", "development",
            "progress", "framework", "overview", "adverse effects",
            "regional heterogeneity",
        }
        mechanism_markers = {
            "mechanism", "assay", "validation", "validated", "cohort",
            "controlled", "comparison", "baseline", "endpoint", "readout",
            "threshold", "sensitivity", "calibration", "external validation",
            "failure mode", "implementation failure", "heterogeneity",
            "toxicity", "survival", "expression", "exposure",
            "potency", "sterility", "quality", "dose", "response",
        }
        has_mechanism = any(marker in text for marker in mechanism_markers)
        role_key = str(role or "").lower()
        if any(marker in text for marker in generic_topic_markers) and not has_mechanism:
            return True
        if "adverse" in role_key or "reversal" in role_key or "oppos" in role_key:
            return not any(
                marker in text
                for marker in (
                    "negative", "null", "adverse",
                    "tradeoff", "trade-off",
                    "failure", "worse", "reduced"
                )
            ) or not any(marker in text for marker in ("baseline", "comparison", "endpoint", "outcome", "quality"))
        if "boundary" in role_key or "generalization" in role_key or "generalisation" in role_key:
            return not any(
                marker in text
                for marker in (
                    "boundary", "heterogeneity", "threshold", "moderator",
                    "external validation", "sensitivity", "subgroup",
                    "implementation context", "regional variation"
                )
            )
        return not any(
            marker in text
            for marker in (
                "validation", "cohort", "controlled", "assay", "comparison",
                "baseline", "endpoint", "readout", "dose", "exposure",
                "quality", "lifecycle", "model", "calibration"
            )
        )

    for path in source_paths:
        role = str(path.get("role") or path.get("id") or "").strip()
        if not role:
            continue
        if query_needs_mechanistic_rewrite(str(path.get("retrieval_query") or ""), role):
            path["retrieval_query"] = role_specific_query(role)
            path["query_rewrite_reason"] = "mechanistic_role_query_required"
        path["query_operationality"] = query_operationality
        path["query_readout_anchor"] = outcome
        if not outcome:
            if path.get("query_rewrite_reason"):
                path["mechanistic_query_rewrite_applied"] = True
            path["query_rewrite_reason"] = "concrete_readout_required_before_retrieval"

    def append_if_missing(path: dict[str, Any], *, role_markers: set[str], polarity: str) -> None:
        path_id = str(path.get("id") or "").strip().lower()
        role = str(path.get("role") or "").strip().lower()
        if path_id in by_id or bool(by_role & role_markers) or polarity in polarities:
            return
        source_paths.append(path)
        by_id.add(path_id)
        by_role.add(role)
        polarities.add(polarity)

    append_if_missing(
        {
            "id": "core_effect_path",
            "role": "core_validation",
            "polarity": "supportive",
            "causal_steps": [strategy, mechanism, outcome],
            "retrieval_query": _compact_retrieval_query(
                object_anchor,
                strategy,
                mechanism,
                outcome,
                comparator,
                fallback=fallback_query,
            ),
            "failure_scope": "whole_sh_core_falsification",
            "can_independently_falsify_sh": True,
            "missing_path_blocks_sh": True,
            "query_operationality": query_operationality,
            "query_readout_anchor": outcome,
            **(
                {"query_rewrite_reason": "concrete_readout_required_before_retrieval"}
                if not outcome else {}
            ),
            "source": "deterministic_required_evidence_path",
        },
        role_markers={"core_validation", "causal_validation", "comparative_validation", "predictive_validation"},
        polarity="supportive",
    )
    append_if_missing(
        {
            "id": "adverse_or_reversal_path",
            "role": "adverse_or_reversal",
            "polarity": "opposing",
            "causal_steps": [
                strategy,
                "adverse effect, failure mode, or implementation failure",
                f"worse or offset {outcome}",
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchor,
                strategy,
                "adverse effect failure mode implementation failure",
                outcome,
                fallback=fallback_query,
            ),
            "failure_scope": "whole_sh_claim_reversal_or_tradeoff",
            "can_independently_falsify_sh": True,
            "missing_path_blocks_sh": False,
            "query_operationality": query_operationality,
            "query_readout_anchor": outcome,
            **(
                {"query_rewrite_reason": "concrete_readout_required_before_retrieval"}
                if not outcome else {}
            ),
            "source": "deterministic_required_evidence_path",
        },
        role_markers={"adverse_or_reversal"},
        polarity="opposing",
    )
    append_if_missing(
        {
            "id": "boundary_or_generalization_path",
            "role": "boundary_or_generalization",
            "polarity": "boundary",
            "causal_steps": [
                strategy,
                boundary,
                f"heterogeneous effect on {outcome}",
            ],
            "retrieval_query": _compact_retrieval_query(
                object_anchor,
                strategy,
                boundary,
                "heterogeneity external validation boundary condition",
                outcome,
                fallback=fallback_query,
            ),
            "failure_scope": "boundary_or_generalization_gap",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "query_operationality": query_operationality,
            "query_readout_anchor": outcome,
            **(
                {"query_rewrite_reason": "concrete_readout_required_before_retrieval"}
                if not outcome else {}
            ),
            "source": "deterministic_required_evidence_path",
        },
        role_markers={"boundary_or_generalization", "predictive_validation"},
        polarity="boundary",
    )
    return source_paths


def _path_marker_match(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def normalize_evidence_paths(
    value: Any,
    *,
    focus: str,
    causal_chain: list[str],
    fallback_query: str,
) -> list[dict[str, Any]]:
    """Normalize complementary discovery/validation paths without field rules.

    The markers describe research responsibilities rather than a particular
    discipline.  Explicit LLM paths take precedence; a deterministic split is
    only synthesized when one causal chain clearly mixes discovery language
    with validation language.
    """

    raw_items = value if isinstance(value, list) else []
    paths: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        role = _evidence_path_role(raw.get("role") or raw.get("id") or raw.get("kind"))
        raw_id = normalize_space(str(raw.get("id") or raw.get("name") or role or "")).lower().replace("-", "_").replace(" ", "_")
        path_id = raw_id[:80] or role
        if not role or any(path.get("id") == path_id and path.get("role") == role for path in paths):
            continue
        steps = normalize_text_list(raw.get("causal_steps"))
        retrieval_query = normalize_space(str(raw.get("retrieval_query") or raw.get("query") or ""))
        can_falsify = (
            raw.get("can_independently_falsify_sh")
            if isinstance(raw.get("can_independently_falsify_sh"), bool)
            else _path_role_core_falsification_capable(role, path_id)
        )
        failure_scope = normalize_space(str(raw.get("failure_scope") or ""))
        if not failure_scope:
            failure_scope = (
                "whole_sh_core_falsification"
                if can_falsify
                else "supporting_gap_or_mechanism_weakening"
            )
        polarity = _evidence_path_polarity(role, path_id, raw.get("polarity"))
        paths.append(
            {
                "id": path_id,
                "role": role,
                "polarity": polarity,
                "causal_steps": steps,
                "retrieval_query": retrieval_query,
                "failure_scope": failure_scope,
                "can_independently_falsify_sh": bool(can_falsify),
                "missing_path_blocks_sh": bool(raw.get("missing_path_blocks_sh") is True and can_falsify),
                "component_anchor_group": normalize_text_list(raw.get("component_anchor_group")),
                "component_evidence_counts_as_core": raw.get("component_evidence_counts_as_core"),
                "component_evidence_counts_as_panel_core": raw.get("component_evidence_counts_as_panel_core"),
                "direct_core_disallowed_by_object_maturity": bool(
                    raw.get("direct_core_disallowed_by_object_maturity")
                ),
                "source": "llm_explicit",
            }
        )
    if paths:
        return paths

    discovery_indexes = [
        index for index, step in enumerate(causal_chain)
        if _path_marker_match(step, _DISCOVERY_EVIDENCE_PATH_MARKERS)
    ]
    validation_indexes = [
        index for index, step in enumerate(causal_chain)
        if _path_marker_match(step, _VALIDATION_EVIDENCE_PATH_MARKERS)
    ]
    if not discovery_indexes or not validation_indexes:
        return []
    validation_start = min(validation_indexes)
    discovery_end = min(max(discovery_indexes) + 1, validation_start)
    discovery_steps = causal_chain[: max(1, discovery_end)]
    # The preceding step normally declares the candidate mechanism shared by
    # both paths, so retain it as validation context without also requiring
    # the entire discovery workflow.
    validation_steps = causal_chain[max(0, validation_start - 1):]
    if not discovery_steps or not validation_steps:
        return []
    return [
        {
            "id": "mechanism_discovery",
            "role": "mechanism_discovery",
            "polarity": "supportive",
            "causal_steps": discovery_steps,
            "retrieval_query": normalize_space(" ".join([focus, *discovery_steps])) or fallback_query,
            "failure_scope": "supporting_gap_or_mechanism_weakening",
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "source": "deterministic_composite_chain_split",
        },
        {
            "id": "causal_validation",
            "role": "causal_validation",
            "polarity": "supportive",
            "causal_steps": validation_steps,
            "retrieval_query": normalize_space(" ".join([focus, *validation_steps])) or fallback_query,
            "failure_scope": "whole_sh_core_falsification",
            "can_independently_falsify_sh": True,
            "missing_path_blocks_sh": True,
            "source": "deterministic_composite_chain_split",
        },
    ]


def normalize_evidence_window(
    value: Any,
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    mode = str(profile.get("primary_mode") or "")
    observational_mix = {
        "P_foundational": 2,
        "P_review_or_consensus": 1,
        "P_authoritative_data_release": 3,
        "P_recent_constraint": 4,
        "P_systematics_or_reanalysis": 3,
        "P_latest_preprint": 2,
    }
    formal_mix = {
        "P_foundational": 5,
        "P_review_or_consensus": 2,
        "P_authoritative_data_release": 0,
        "P_recent_constraint": 3,
        "P_systematics_or_reanalysis": 0,
        "P_latest_preprint": 1,
    }
    default_mix = observational_mix if mode == "observational_inference" else formal_mix if mode == "mathematical_proof" else {
        "P_foundational": 2, "P_review_or_consensus": 1, "P_authoritative_data_release": 0,
        "P_recent_constraint": 5, "P_systematics_or_reanalysis": 2, "P_latest_preprint": 1,
    }
    preferred_mix = dict(supplied.get("preferred_evidence_mix") or default_mix)
    return {
        "schema_version": "evidence_time_structure_v2",
        "time_policy": "evidence_lifecycle_and_data_version_not_publication_year_only",
        "P_foundational": supplied.get("P_foundational") or {"preferred": preferred_mix.get("P_foundational", 0), "max_age_years": None, "purpose": "age-unbounded defining discovery, theorem, baseline, or theory"},
        "P_review_or_consensus": supplied.get("P_review_or_consensus") or {"preferred": preferred_mix.get("P_review_or_consensus", 0), "max_age_years": None, "purpose": "authoritative synthesis or consensus"},
        "P_authoritative_data_release": supplied.get("P_authoritative_data_release") or {"preferred": preferred_mix.get("P_authoritative_data_release", 0), "latest_authoritative_release": True, "superseded_by_newer_release": False, "purpose": "mission or survey release judged by data version"},
        "P_recent_constraint": supplied.get("P_recent_constraint") or {"preferred": preferred_mix.get("P_recent_constraint", 0), "max_age_years": 4, "purpose": "recent primary constraint or joint analysis"},
        "P_systematics_or_reanalysis": supplied.get("P_systematics_or_reanalysis") or {"preferred": preferred_mix.get("P_systematics_or_reanalysis", 0), "max_age_years": None, "purpose": "calibration, systematic error, processing, or reanalysis"},
        "P_latest_preprint": supplied.get("P_latest_preprint") or {"preferred": preferred_mix.get("P_latest_preprint", 0), "max_age_months": 12, "purpose": "frontier signal only", "counts_toward_readiness": False},
        "preferred_evidence_mix": preferred_mix,
        "minimum_evidence_types": supplied.get("minimum_evidence_types") or ["claim_compatible_direct_evidence"],
        # Legacy readers can still render these, but the values are deliberately
        # non-blocking and no longer impose a universal recent-preprint quota.
        "P0_latest_preprint": supplied.get("P0_latest_preprint") or {"minimum": 0, "max_age_months": 12, "purpose": "frontier signal only"},
        "P1_recent_primary": supplied.get("P1_recent_primary") or {"minimum": 0, "max_age_years": 4, "purpose": "recent constraint signal"},
    }


def focused_subhypothesis_query(
    domain: str,
    focus: str,
    causal_chain: list[str],
    independent_variable: str,
    dependent_variables: list[str],
    *,
    evidence_mode: str = "causal_mechanism",
    moderators: list[str] | None = None,
    epistemic_profile: dict[str, Any] | None = None,
) -> str:
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    primary_mode = str(profile.get("primary_mode") or "")
    mode_terms = {
        "observational_inference": ["observation", "survey", "likelihood", "parameter constraint"],
        "theoretical_derivation": ["theoretical derivation", "equation", "stability"],
        "mathematical_proof": ["theorem", "proof", "counterexample"],
        "computational_simulation": ["numerical simulation", "convergence", "sensitivity"],
        "engineering_validation": ["performance", "benchmark", "calibration"],
        "classification_description": ["catalog", "classification", "characterization"],
        "synthesis_evaluation": ["systematic review", "evidence synthesis"],
    }
    if evidence_mode == "predictive_generalization":
        terms = [
            focus, *(moderators or [])[:1], *dependent_variables[:2],
            "external validation", "subgroup performance", "calibration", "transportability",
        ]
        return normalize_space(" ".join(item for item in terms if item))
    if primary_mode in mode_terms:
        terms = [focus, *causal_chain[:1], *dependent_variables[:2], *mode_terms[primary_mode]]
        return normalize_space(" ".join(item for item in terms if item))
    terms = [focus, independent_variable, *causal_chain[:2], *dependent_variables[:2], "mechanism", "intervention", "measurement"]
    return normalize_space(" ".join(item for item in terms if item))


def focused_query_variants(
    query: str,
    focus: str,
    domain: str,
    *,
    evidence_mode: str = "causal_mechanism",
    moderators: list[str] | None = None,
    epistemic_profile: dict[str, Any] | None = None,
) -> list[str]:
    base = normalize_space(query or f"{domain} {focus}")
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    primary_mode = str(profile.get("primary_mode") or "")
    if evidence_mode == "predictive_generalization":
        boundary = normalize_space(" ".join((moderators or [])[:1])) or "population clinical setting"
        variants = [
            base,
            normalize_space(f"{focus} {boundary} external validation calibration discrimination"),
            normalize_space(f"{focus} {boundary} subgroup performance fairness transportability domain shift"),
        ]
        return list(dict.fromkeys(item for item in variants if item))
    profile_variants = {
        "observational_inference": [
            normalize_space(f"{focus} direct observation survey catalog likelihood"),
            normalize_space(f"{focus} systematic uncertainty calibration independent dataset"),
        ],
        "theoretical_derivation": [
            normalize_space(f"{focus} theoretical derivation equation limiting case"),
            normalize_space(f"{focus} consistency stability observable prediction"),
        ],
        "mathematical_proof": [
            normalize_space(f"{focus} theorem proof lemma"),
            normalize_space(f"{focus} counterexample assumption boundary"),
        ],
        "computational_simulation": [
            normalize_space(f"{focus} numerical simulation convergence benchmark"),
            normalize_space(f"{focus} sensitivity analysis uncertainty propagation"),
        ],
        "engineering_validation": [
            normalize_space(f"{focus} performance benchmark calibration"),
            normalize_space(f"{focus} robustness reliability fault mode"),
        ],
    }
    if primary_mode in profile_variants:
        return list(dict.fromkeys(item for item in [base, *profile_variants[primary_mode]] if item))
    variants = [
        base,
        normalize_space(f"{domain} {focus} causal mechanism experimental evidence"),
        normalize_space(f"{focus} intervention observable outcome preprint"),
    ]
    return list(dict.fromkeys(item for item in variants if item))


def default_falsification_condition(
    focus: str,
    dependent_variables: list[str],
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> str:
    outcome = ", ".join(dependent_variables) if dependent_variables else "the proposed observable outcome"
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    primary_mode = str(profile.get("primary_mode") or "")
    profile_defaults = {
        "observational_inference": (
            f"The claim is challenged if direct observations or parameter constraints for {focus} are inconsistent with the stated model, uncertainty treatment, or predicted {outcome}."
        ),
        "theoretical_derivation": (
            f"The claim is challenged if the derivation for {focus} fails under its stated assumptions, violates a consistency condition, or does not yield {outcome}."
        ),
        "mathematical_proof": (
            f"The claim is refuted by a valid counterexample to {focus}, an invalid proof step, or failure of a stated assumption required for {outcome}."
        ),
        "computational_simulation": (
            f"The claim is challenged if simulations of {focus} fail convergence or benchmark validation, or if {outcome} is not robust to stated sensitivity analyses."
        ),
        "engineering_validation": (
            f"The claim is challenged if {focus} fails its declared performance, calibration, robustness, or fault-mode criterion for {outcome}."
        ),
        "classification_description": (
            f"The claim is challenged if the stated sample, catalog, or classification evidence for {focus} does not support {outcome} under the declared definition."
        ),
        "synthesis_evaluation": (
            f"The claim is challenged if the evidence synthesis for {focus} becomes inconsistent after source-quality, heterogeneity, or alternative-evidence assessment of {outcome}."
        ),
    }
    if primary_mode in profile_defaults:
        return profile_defaults[primary_mode]
    return f"Matched interventions on {focus} do not produce a reproducible directional change in {outcome}, or a competing mechanism explains the result better."


def validate_combination_hypothesis(
    value: Any,
    sub_hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate an LLM-proposed multi-SH integration before it is persisted."""

    payload = value if isinstance(value, dict) else {}
    valid_ids = {
        str(item.get("id") or "")
        for item in sub_hypotheses
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    requested = [
        str(item).strip()
        for item in (payload.get("required_sub_hypothesis_ids") or [])
        if str(item).strip()
    ]
    required = list(dict.fromkeys(item for item in requested if item in valid_ids))
    invalid_ids = [item for item in requested if item not in valid_ids]
    statement = normalize_space(str(payload.get("statement") or ""))
    integration_test = normalize_space(str(payload.get("integration_test") or ""))
    reasons: list[str] = []
    if len(required) < 2:
        reasons.append("requires_at_least_two_valid_component_shs")
    if invalid_ids:
        reasons.append("contains_unknown_component_sh_ids")
    if len(statement) < 16:
        reasons.append("missing_specific_combination_statement")
    if len(integration_test) < 16:
        reasons.append("missing_specific_integration_test")
    return {
        "schema_version": "combination_hypothesis_validation_v1",
        "valid": not reasons,
        "reasons": reasons,
        "required_sub_hypothesis_ids": required,
        "invalid_sub_hypothesis_ids": invalid_ids,
        "statement": statement,
        "integration_test": integration_test,
    }


def normalize_combination_hypothesis(value: Any, sub_hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    valid_ids = [item["id"] for item in sub_hypotheses]
    required = [str(item) for item in payload.get("required_sub_hypothesis_ids", []) if str(item) in valid_ids]
    return {
        "statement": normalize_space(str(payload.get("statement") or "")) or "Synthesize a multi-mechanism conclusion only after the component causal hypotheses have independent evidence.",
        "required_sub_hypothesis_ids": required or valid_ids,
        "integration_test": normalize_space(str(payload.get("integration_test") or "")) or "Compare single-factor interventions, joint interventions, and matched controls to distinguish additive from coupled effects.",
        "status": "blocked_on_component_evidence",
    }


def normalize_execution_constraints(value: Any) -> dict[str, list[str]]:
    payload = value if isinstance(value, dict) else {}
    return {
        name: normalize_text_list(payload.get(name))
        for name in ("retrieval", "gap_detection", "hypothesis", "verification")
    }

def list_literature_providers() -> str:
    try:
        from .config import SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED
        from ._literature_retrieval_foundation import list_literature_provider_capabilities
        from ._models import LITERATURE_PROVIDERS
    except ImportError:
        from config import SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED
        from _literature_retrieval_foundation import list_literature_provider_capabilities
        from _models import LITERATURE_PROVIDERS
    registered = {item["provider"]: item for item in list_literature_provider_capabilities()}
    providers = {
        name: {**dict(spec), "capabilities": registered.get(name, {})}
        for name, spec in LITERATURE_PROVIDERS.items()
    }
    if "pubmed" in providers and not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED:
        providers["pubmed"]["runtime_status"] = "disabled_by_policy"
        providers["pubmed"]["runtime_reason"] = (
            "PubMed specialized retrieval is disabled; OpenAlex is the broad discovery source."
        )
    return json.dumps(providers, ensure_ascii=False, indent=2)


def literature_provider_doctor() -> str:
    """Inspect provider readiness locally without sending a retrieval query."""
    try:
        from .config import (
            OPENALEX_API_KEY,
            SCIENCEDIRECT_API_KEY,
            SCIENCE_OPENALEX_ENABLED,
            SCIENCE_OPENALEX_MAILTO,
            SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED,
            SCIENCE_SCIENCEDIRECT_ENABLED,
            SEMANTIC_SCHOLAR_API_KEY,
        )
        from ._literature_retrieval_foundation import provider_doctor_snapshot
        from . import _literature_search, _openalex, _sciencedirect
    except ImportError:
        from config import (
            OPENALEX_API_KEY,
            SCIENCEDIRECT_API_KEY,
            SCIENCE_OPENALEX_ENABLED,
            SCIENCE_OPENALEX_MAILTO,
            SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED,
            SCIENCE_SCIENCEDIRECT_ENABLED,
            SEMANTIC_SCHOLAR_API_KEY,
        )
        from _literature_retrieval_foundation import provider_doctor_snapshot
        import _literature_search
        import _openalex
        import _sciencedirect
    now = time.monotonic()
    runtime_state = {
        "sciencedirect": {
            "enabled": bool(SCIENCE_SCIENCEDIRECT_ENABLED),
            "run_budget": _sciencedirect.sciencedirect_run_budget_status(),
            "max_qps": _sciencedirect.sciencedirect_max_qps(),
        },
        "openalex": {
            "enabled": bool(SCIENCE_OPENALEX_ENABLED),
            "run_budget": _openalex.openalex_run_budget_status(),
            "max_qps": _openalex.openalex_max_qps(),
        },
        "semantic_scholar": {
            "run_budget": _literature_search.semantic_scholar_run_budget_status(),
            "cooldown_remaining_seconds": round(
                max(0.0, float(_literature_search.SEMANTIC_SCHOLAR_COOLDOWN_UNTIL) - now),
                3,
            ),
        },
        "pubmed": {
            "enabled": bool(SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED),
            "status": (
                "disabled_by_policy"
                if not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED
                else "enabled"
            ),
        },
        "arxiv": {
            "cooldown_remaining_seconds": round(
                max(0.0, float(_literature_search.ARXIV_COOLDOWN_UNTIL) - now),
                3,
            ),
        },
    }
    payload = provider_doctor_snapshot(
        configuration_presence={
            "SCIENCEDIRECT_API_KEY": bool(SCIENCEDIRECT_API_KEY),
            "SCIENCE_SCIENCEDIRECT_ENABLED": bool(SCIENCE_SCIENCEDIRECT_ENABLED),
            "OPENALEX_API_KEY": bool(OPENALEX_API_KEY),
            "SCIENCE_OPENALEX_MAILTO": bool(SCIENCE_OPENALEX_MAILTO),
            "SCIENCE_OPENALEX_ENABLED": bool(SCIENCE_OPENALEX_ENABLED),
            "SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED": bool(SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED),
            "SEMANTIC_SCHOLAR_API_KEY": bool(SEMANTIC_SCHOLAR_API_KEY),
        },
        runtime_state=runtime_state,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def literature_provider_smoke(
    provider: str = "openalex",
    query: str = "controlled causal mechanism evidence",
    live: bool = False,
) -> str:
    """Check one provider contract locally, with an explicit opt-in live probe."""
    try:
        from ._literature_retrieval_foundation import (
            compile_provider_query,
            get_literature_provider_capabilities,
        )
    except ImportError:
        from _literature_retrieval_foundation import (
            compile_provider_query,
            get_literature_provider_capabilities,
        )
    capability = get_literature_provider_capabilities(provider)
    compilation = compile_provider_query(capability.provider, query)
    response: dict[str, Any] = {
        "schema_version": "literature_provider_smoke_v1",
        "provider": capability.provider,
        "mode": "live" if live else "offline",
        "query_compilation": compilation,
        "capability": {
            "status": capability.status,
            "allowed_layers": list(capability.allowed_layers),
            "allows_socrates_direct_evidence": capability.allows_socrates_direct_evidence,
        },
        "live_smoke_executed": False,
    }
    if not live:
        response["status"] = "ready_for_opt_in_live_smoke" if compilation.get("valid") else "invalid_query"
        response["next_step"] = "Set live=true only when a one-result provider request is intended."
        return json.dumps(response, ensure_ascii=False, indent=2)
    if not compilation.get("valid"):
        response["status"] = "invalid_query"
        response["next_step"] = "Repair the query locally before allowing a live provider smoke request."
        return json.dumps(response, ensure_ascii=False, indent=2)
    try:
        from ._literature_search import search_literature_provider_block
    except ImportError:
        from _literature_search import search_literature_provider_block
    block = search_literature_provider_block(
        capability.provider,
        str(compilation.get("compiled_query") or query),
        1,
    )
    response.update(
        {
            "live_smoke_executed": True,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(block.get("results") or []),
            "cache_hit": block.get("cache_hit"),
            "error": block.get("error", ""),
            "next_step": "This smoke result is an operational check only; it is not PaperGraph evidence.",
        }
    )
    return json.dumps(response, ensure_ascii=False, indent=2)

def live_literature_provider_names() -> set[str]:
    try:
        from ._models import LITERATURE_PROVIDERS
    except ImportError:
        from _models import LITERATURE_PROVIDERS
    return {name for name, spec in LITERATURE_PROVIDERS.items() if spec.get("status") == "live"}

def default_literature_providers(domain: str = "", query: str = "") -> list[str]:
    try:
        from .config import SCIENCEDIRECT_API_KEY, SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED, SCIENCE_SCIENCEDIRECT_ENABLED
        from ._models import recommended_literature_providers
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from config import SCIENCEDIRECT_API_KEY, SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED, SCIENCE_SCIENCEDIRECT_ENABLED
        from _models import recommended_literature_providers
        from _utils import normalize_space, unique_preserve_order
    text = normalize_space(f"{domain} {query}")
    providers = recommended_literature_providers(text)
    if not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED:
        providers = [provider for provider in providers if provider != "pubmed"]
    # The paid ScienceDirect source is opt-in by credential presence.  It is
    # intentionally appended as a supplemental discovery source rather than
    # displacing the OpenAlex-first discovery policy.
    if SCIENCE_SCIENCEDIRECT_ENABLED and SCIENCEDIRECT_API_KEY:
        providers.append("sciencedirect")
    return unique_preserve_order([provider for provider in providers if provider in live_literature_provider_names()])

def explore_domain_subspaces(
    domain: str,
    max_subspaces: int = 12,
    probe_depth: int = 5,
    use_llm: bool = True,
    providers: list[str] | None = None,
    user_hints: list[str] | None = None,
) -> str:
    try:
        from ._literature_search import database_to_provider
        from ._utils import clamp_int, new_id, normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import database_to_provider
        from _utils import clamp_int, new_id, normalize_space, unique_preserve_order
    domain_text = normalize_space(domain)
    if not domain_text:
        raise ValueError("domain is required")
    selected_providers = [database_to_provider(item) for item in (providers or default_literature_providers(domain=domain_text))]
    selected_providers = unique_preserve_order([item for item in selected_providers if item in live_literature_provider_names()])
    if not selected_providers:
        selected_providers = default_literature_providers(domain=domain_text) or ["openalex"]
    subspaces = generate_domain_subspaces(domain_text, max_subspaces=max_subspaces, use_llm=use_llm, user_hints=user_hints)
    probe_reports: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    probe_budget = build_subspace_probe_budget(selected_providers)
    for subspace in subspaces[: clamp_int(max_subspaces, 1, 30)]:
        report = probe_domain_subspace(
            subspace,
            providers=selected_providers,
            probe_depth=probe_depth,
            provider_budget=probe_budget,
        )
        probe_reports.append(report)
        enriched.append(enrich_subspace_with_probe(subspace, report))
    generated_sources = {str(item.get("generated_by") or "") for item in enriched}
    generated_by = "llm" if generated_sources == {"llm"} else "hybrid" if "llm" in generated_sources else "heuristic"
    subspace_map = {
        "subspace_map_id": new_id("subspace"),
        "domain": domain_text,
        "generated_by": generated_by,
        "confidence": domain_subspace_map_confidence(enriched, use_llm=generated_by in {"llm", "hybrid"}),
        "createdAt": time.time(),
        "providers": selected_providers,
        "user_hints": user_hints or [],
        "subspaces": enriched,
        "probe_results": probe_reports,
    }
    subspace_map["coverage_plan"] = build_subspace_coverage_plan(subspace_map)
    subspace_map["query_plan"] = query_plan_from_subspace_map(subspace_map)
    subspace_map["user_interaction"] = build_subspace_selection_interaction(subspace_map)
    save_subspace_map(subspace_map)
    log_event(
        "SCIENCE",
        "domain_subspaces_explored",
        subspace_map_id=subspace_map["subspace_map_id"],
        domain=domain_text,
        subspaces=len(enriched),
    )
    response = dict(subspace_map)
    response["next_step"] = (
        "Use selected subspaces to revise the V3 research objective or contracts, then "
        "resume run_autogen_groupchat; subspaces do not define an independent retrieval budget."
    )
    return json.dumps(response, ensure_ascii=False, indent=2)

def generate_domain_subspaces(
    domain: str,
    max_subspaces: int,
    use_llm: bool,
    user_hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._literature_scoring import domain_topic_profile
        from ._literature_search import query_terms
        from ._utils import clamp_int, string_list
    except ImportError:
        from _literature_scoring import domain_topic_profile
        from _literature_search import query_terms
        from _utils import clamp_int, string_list
    if use_llm:
        llm_subspaces = generate_domain_subspaces_with_llm(domain, max_subspaces=max_subspaces, user_hints=user_hints)
        if llm_subspaces:
            return llm_subspaces
    profile = domain_topic_profile(domain, query=domain, use_llm=use_llm)
    subspaces: list[dict[str, Any]] = []
    for topic in profile.get("core_topics", []):
        keywords = string_list(topic.get("expected_terms")) or query_terms(str(topic.get("query") or ""))[:8]
        subspaces.append(
            normalize_domain_subspace(
                {
                    "name": str(topic.get("branch") or "subspace"),
                    "aliases": [],
                    "description": str(topic.get("rationale") or ""),
                    "keywords": keywords,
                    "seed_papers": [],
                    "maturity": "unknown",
                    "strategic_importance": int(topic.get("min_hits") or 5),
                    "search_strategy": "must_include",
                    "generated_by": "profile",
                },
                domain=domain,
            )
        )
    if not subspaces:
        for hint in user_hints or []:
            subspaces.append(normalize_domain_subspace({"name": hint, "keywords": query_terms(hint)}, domain=domain))
    if not subspaces:
        subspaces.append(
            normalize_domain_subspace(
                {
                    "name": "Field map and major subfields",
                    "keywords": query_terms(domain) + ["review", "survey", "roadmap"],
                    "description": "Fallback subspace for building an initial field map when no validated ontology is available.",
                    "maturity": "unknown",
                    "strategic_importance": 7,
                    "search_strategy": "must_include",
                    "generated_by": "heuristic",
                },
                domain=domain,
            )
        )
    return subspaces[: clamp_int(max_subspaces, 1, 30)]

def generate_domain_subspaces_with_llm(
    domain: str,
    max_subspaces: int,
    user_hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._llm import call_llm_json
        from ._utils import clamp_int, trim_text
    except ImportError:
        from _llm import call_llm_json
        from _utils import clamp_int, trim_text
    max_items = clamp_int(max_subspaces, 1, 30)
    compact_domain = compact_domain_label(domain)
    try:
        payload = call_llm_json(
            system=(
                "You are a domain-agnostic research cartographer. You map a broad scientific domain "
                "into substantive research subspaces before literature review. Work across all sciences, "
                "engineering, medicine, agriculture, AI, mathematics, social-science-adjacent empirical fields, "
                "and interdisciplinary topics. Return JSON only."
            ),
            prompt=(
                "Decompose the domain into major substantive subspaces. Do not output generic facets such as "
                "'methods', 'applications', or 'benchmarks' unless they are real named subfields in this domain.\n"
                "Return strict JSON with key subspaces. Each subspace must contain:\n"
                "- name: English concise name\n"
                "- aliases: aliases in English/Chinese/acronyms if useful\n"
                "- description: 1-2 sentence scope\n"
                "- parent: optional parent category\n"
                "- keywords: 5-10 retrieval keywords/phrases\n"
                "- seed_papers: 0-3 representative reviews or seed papers if you know them; leave empty if unsure\n"
                "- maturity: emerging | growing | mature | saturated | unknown\n"
                "- strategic_importance: integer 1-10\n"
                "- search_strategy: must_include | nice_to_have | exploratory\n\n"
                f"Domain label: {compact_domain}\n"
                f"Full user domain: {trim_text(domain, 500)}\n"
                f"User hints: {', '.join(user_hints or [])}\n"
                f"Maximum subspaces: {max_items}\n"
                "Keep descriptions concise. Prefer 8-12 high-signal subspaces over verbose prose.\n"
            ),
            max_tokens=max(4200, min(8000, 700 + max_items * 520)),
            fallback_list_key="subspaces",
        )
    except Exception as exc:
        log_event("WARN", "domain_subspace_llm_failed", error=str(exc))
        return []
    raw = payload.get("subspaces") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    subspaces = [normalize_domain_subspace(item, domain=domain) for item in raw if isinstance(item, dict)]
    for item in subspaces:
        item["generated_by"] = "llm"
    return [item for item in subspaces if item.get("name") and item.get("keywords")]

def compact_domain_label(domain: str) -> str:
    try:
        from ._utils import normalize_space, trim_text, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, trim_text, unique_preserve_order
    clean = normalize_space(domain)
    if len(clean) <= 180:
        return clean
    phrases = re.split(r"\s*(?:/|,|;| and | with | for | of )\s*", clean, flags=re.IGNORECASE)
    useful = [phrase.strip() for phrase in phrases if len(phrase.strip()) >= 4]
    compact = "; ".join(unique_preserve_order(useful)[:6])
    return trim_text(compact or clean, 180)

def normalize_domain_subspace(raw: dict[str, Any], domain: str) -> dict[str, Any]:
    try:
        from ._literature_scoring import slug_label
        from ._literature_search import query_terms
        from ._utils import clamp_int, new_id, normalize_key, normalize_space, scalar, string_list, unique_preserve_order
    except ImportError:
        from _literature_scoring import slug_label
        from _literature_search import query_terms
        from _utils import clamp_int, new_id, normalize_key, normalize_space, scalar, string_list, unique_preserve_order
    name = scalar(raw.get("name")) or scalar(raw.get("name_en")) or "Unnamed subspace"
    keywords = string_list(raw.get("keywords")) or query_terms(" ".join([name, domain]))[:8]
    aliases = string_list(raw.get("aliases"))
    seed_papers = string_list(raw.get("seed_papers")) or string_list(raw.get("representative_reviews"))
    maturity = normalize_space(str(raw.get("maturity") or raw.get("estimated_density") or "unknown")).lower()
    if maturity not in {"emerging", "growing", "mature", "saturated", "unknown"}:
        maturity = "unknown"
    importance = clamp_int(raw.get("strategic_importance", raw.get("hotness", 5)), 1, 10)
    strategy = normalize_key(str(raw.get("search_strategy") or "must_include"))
    if strategy not in {"must_include", "nice_to_have", "exploratory"}:
        strategy = "must_include" if importance >= 7 else "nice_to_have"
    return {
        "subspace_id": slug_label(name) or new_id("subspace_item"),
        "name": name,
        "aliases": aliases[:8],
        "description": scalar(raw.get("description")),
        "parent": scalar(raw.get("parent")),
        "keywords": unique_preserve_order(keywords)[:12],
        "seed_papers": seed_papers[:5],
        "maturity": maturity,
        "estimated_density": "unknown",
        "strategic_importance": importance,
        "search_strategy": strategy,
        "generated_by": str(raw.get("generated_by") or "heuristic"),
    }

def probe_domain_subspace(
    subspace: dict[str, Any],
    providers: list[str],
    probe_depth: int = 5,
    provider_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_scoring import is_recent_paper
        from ._literature_search import arxiv_skip_block, dedupe_literature_results, flatten_literature_results, milestone_citation_threshold, rank_literature_results, search_arxiv, search_literature_provider_block, search_preprint_api, search_pubmed, search_semantic_scholar, summarize_literature_result, summarize_provider_blocks
        from ._utils import clamp_int, normalize_space, numeric_value, string_list, unique_preserve_order
    except ImportError:
        from _literature_scoring import is_recent_paper
        from _literature_search import arxiv_skip_block, dedupe_literature_results, flatten_literature_results, milestone_citation_threshold, rank_literature_results, search_arxiv, search_literature_provider_block, search_preprint_api, search_pubmed, search_semantic_scholar, summarize_literature_result, summarize_provider_blocks
        from _utils import clamp_int, normalize_space, numeric_value, string_list, unique_preserve_order
    keywords = string_list(subspace.get("keywords"))
    name = str(subspace.get("name") or "")
    query = normalize_space(" ".join(keywords[:6]) or name)
    probe_queries = unique_preserve_order(
        [
            normalize_space(f"{name} {' '.join(keywords[:4])}"),
            query,
            normalize_space(f"{name} {' '.join(keywords[:3])} review survey"),
        ]
    )
    probe_queries = probe_queries[: clamp_int(SCIENCE_SEMANTIC_SCHOLAR_PROBE_VARIANTS, 1, 3)]
    blocks: list[dict[str, Any]] = []
    per_query_depth = max(1, min(clamp_int(probe_depth, 1, 20), 3))
    for probe_query in probe_queries:
        if not probe_query:
            continue
        for provider in providers:
            try:
                if provider_budget is not None and provider_budget.get(provider, 0) <= 0:
                    blocks.append(
                        {
                            "provider": provider,
                            "query": probe_query,
                            "status": "probe_budget_exhausted",
                            "results": [],
                        }
                    )
                    continue
                if provider == "openalex":
                    if provider_budget is not None:
                        provider_budget[provider] = provider_budget.get(provider, 0) - 1
                    block = search_literature_provider_block(provider, probe_query, per_query_depth)
                elif provider == "semantic_scholar":
                    if provider_budget is not None:
                        provider_budget[provider] = provider_budget.get(provider, 0) - 1
                    block = search_semantic_scholar(probe_query, max_results=per_query_depth)
                elif provider == "arxiv":
                    skipped = arxiv_skip_block(probe_query)
                    if skipped:
                        blocks.append(skipped)
                        continue
                    if provider_budget is not None:
                        provider_budget[provider] = provider_budget.get(provider, 0) - 1
                    block = search_arxiv(probe_query, max_results=per_query_depth)
                elif provider == "pubmed":
                    if provider_budget is not None:
                        provider_budget[provider] = provider_budget.get(provider, 0) - 1
                    block = search_pubmed(probe_query, max_results=per_query_depth)
                elif provider in {"biorxiv", "medrxiv", "chemrxiv"}:
                    if provider_budget is not None:
                        provider_budget[provider] = provider_budget.get(provider, 0) - 1
                    block = search_preprint_api(provider, probe_query, max_results=per_query_depth)
                else:
                    continue
                block["probe_query_variant"] = probe_query
                blocks.append(block)
            except Exception as exc:
                blocks.append({"provider": provider, "query": probe_query, "status": "error", "error": str(exc), "results": []})
    ranked = rank_literature_results(query, dedupe_literature_results(flatten_literature_results(blocks)))
    recent_count = sum(1 for item in ranked if is_recent_paper(item, max_age=3))
    high_impact_count = sum(1 for item in ranked if numeric_value(item.get("citation_count")) >= milestone_citation_threshold(item))
    return {
        "subspace_id": subspace.get("subspace_id"),
        "name": subspace.get("name"),
        "query": query,
        "probe_queries": probe_queries,
        "provider_blocks": summarize_provider_blocks(blocks),
        "hit_count": len(ranked),
        "recent_count": recent_count,
        "high_impact_count": high_impact_count,
        "top_seed_papers": [summarize_literature_result(item) for item in ranked[: clamp_int(probe_depth, 1, 10)]],
    }

def enrich_subspace_with_probe(subspace: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(subspace)
    hit_count = int(probe.get("hit_count") or 0)
    recent_count = int(probe.get("recent_count") or 0)
    high_impact_count = int(probe.get("high_impact_count") or 0)
    enriched["probe_query"] = probe.get("query", "")
    enriched["probe_hit_count"] = hit_count
    enriched["recent_hit_count"] = recent_count
    enriched["high_impact_hit_count"] = high_impact_count
    enriched["estimated_density"] = estimate_subspace_density(hit_count, recent_count, high_impact_count)
    if not enriched.get("seed_papers"):
        enriched["seed_papers"] = [
            str(item.get("title") or item.get("citation") or "")
            for item in probe.get("top_seed_papers", [])[:3]
            if str(item.get("title") or item.get("citation") or "")
        ]
    enriched["suggested_quota"] = suggested_subspace_quota(enriched)
    enriched["coverage_status"] = "uncovered" if hit_count <= 0 else "probe_covered"
    return enriched

def build_subspace_probe_budget(providers: list[str]) -> dict[str, int]:
    max_calls = max(0, int(SCIENCE_SUBSPACE_PROBE_MAX_CALLS_PER_PROVIDER))
    return {provider: max_calls for provider in providers}

def estimate_subspace_density(hit_count: int, recent_count: int, high_impact_count: int) -> str:
    if hit_count >= 5 and (recent_count >= 2 or high_impact_count >= 1):
        return "high"
    if hit_count >= 3:
        return "medium"
    if hit_count >= 1:
        return "low"
    return "unknown"

def suggested_subspace_quota(subspace: dict[str, Any]) -> int:
    importance = int(subspace.get("strategic_importance") or 5)
    density = str(subspace.get("estimated_density") or "unknown")
    strategy = str(subspace.get("search_strategy") or "")
    if strategy == "must_include" or importance >= 8:
        return 3 if density in {"high", "medium"} else 2
    if strategy == "exploratory" or density == "low":
        return 1
    return 2

def domain_subspace_map_confidence(subspaces: list[dict[str, Any]], use_llm: bool) -> float:
    if not subspaces:
        return 0.0
    with_keywords = sum(1 for item in subspaces if item.get("keywords"))
    with_probe = sum(1 for item in subspaces if int(item.get("probe_hit_count") or 0) > 0)
    base = 0.35 + (0.2 if use_llm else 0.0)
    score = base + 0.25 * (with_keywords / len(subspaces)) + 0.2 * (with_probe / len(subspaces))
    return round(max(0.0, min(1.0, score)), 3)

def build_subspace_coverage_plan(subspace_map: dict[str, Any]) -> dict[str, Any]:
    subspaces = [item for item in subspace_map.get("subspaces", []) if isinstance(item, dict)]
    total = len(subspaces)
    covered = [item for item in subspaces if int(item.get("probe_hit_count") or 0) > 0]
    missing = [item for item in subspaces if int(item.get("probe_hit_count") or 0) <= 0]
    insufficient = [
        item
        for item in subspaces
        if int(item.get("probe_hit_count") or 0) > 0 and int(item.get("probe_hit_count") or 0) < int(item.get("suggested_quota") or 1)
    ]
    return {
        "total_subspaces": total,
        "covered": len(covered),
        "missing": len(missing),
        "insufficient": len(insufficient),
        "coverage_rate": round(len(covered) / max(1, total), 3),
        "missing_details": [
            {
                "name": item.get("name"),
                "keywords": item.get("keywords", [])[:6],
                "suggested_action": "supplemental_search" if int(item.get("strategic_importance") or 0) >= 6 else "lower_priority_or_confirm",
            }
            for item in missing
        ],
        "recommendation": "Confirm priority subspaces with the user before running ZhiZhi, then search selected subspaces independently.",
    }

def query_plan_from_subspace_map(subspace_map: dict[str, Any], selected_subfields: list[str] | None = None) -> list[dict[str, Any]]:
    try:
        from ._literature_scoring import slug_label
        from ._utils import normalize_key, normalize_space, string_list
    except ImportError:
        from _literature_scoring import slug_label
        from _utils import normalize_key, normalize_space, string_list
    selected = {normalize_key(item) for item in (selected_subfields or []) if normalize_space(item)}
    plan: list[dict[str, Any]] = []
    matched_selected: set[str] = set()
    for subspace in subspace_map.get("subspaces", []):
        if not isinstance(subspace, dict):
            continue
        name = str(subspace.get("name") or "")
        subspace_id = str(subspace.get("subspace_id") or "")
        if selected and normalize_key(name) not in selected and normalize_key(subspace_id) not in selected:
            continue
        if normalize_key(name) in selected:
            matched_selected.add(normalize_key(name))
        if normalize_key(subspace_id) in selected:
            matched_selected.add(normalize_key(subspace_id))
        keywords = string_list(subspace.get("keywords"))
        if not keywords:
            continue
        maturity = str(subspace.get("maturity") or "")
        suffix = "review survey" if maturity in {"mature", "saturated"} else "latest recent" if maturity in {"emerging", "growing"} else ""
        plan.append(
            {
                "branch": subspace_id or slug_label(name),
                "name": name,
                "query": normalize_space(" ".join(keywords[:8] + ([suffix] if suffix else []))),
                "quota": int(subspace.get("suggested_quota") or 1),
                "estimated_density": subspace.get("estimated_density"),
                "strategic_importance": subspace.get("strategic_importance"),
                "search_strategy": subspace.get("search_strategy"),
            }
        )
    for raw in selected:
        if raw in matched_selected:
            continue
        label = normalize_space(raw.replace("_", " "))
        if not label:
            continue
        plan.append(
            {
                "branch": slug_label(label),
                "name": label,
                "query": label,
                "quota": 2,
                "estimated_density": "unknown",
                "strategic_importance": 7,
                "search_strategy": "custom_user_subspace",
                "custom": True,
            }
        )
    return plan


def build_serial_subspace_query_plan(
    domain: str,
    retrieval_brief: str = "",
    *,
    max_core_rounds: int = 8,
    boundary_extension_rounds: int = 3,
    use_llm: bool = False,
    focus_branches: list[str] | None = None,
    subspace_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an auditable serial plan from the full research brief.

    The brief is deliberately retained for decomposition, while provider calls
    later receive only the concise keyword query for one subspace at a time.
    """
    try:
        from ._utils import clamp_int, normalize_space, unique_preserve_order
    except ImportError:
        from _utils import clamp_int, normalize_space, unique_preserve_order
    core_limit = clamp_int(max_core_rounds, 6, 10)
    boundary_limit = clamp_int(boundary_extension_rounds, 3, 4)
    brief = normalize_space("\n".join(part for part in (domain, retrieval_brief) if normalize_space(part)))
    if subspace_map:
        all_branches = query_plan_from_subspace_map(subspace_map, selected_subfields=focus_branches)
        generated_by = str(subspace_map.get("generated_by") or "subspace_map")
        # Older DSE maps commonly contain ten entries. When the user has not
        # narrowed the selection, enrich that map just enough to preserve the
        # requested 3-4 post-core boundary probes.
        if not focus_branches and len(all_branches) < core_limit + boundary_limit:
            generated = query_plan_from_subspace_map(
                {"subspaces": generate_domain_subspaces(
                    brief or domain,
                    max_subspaces=core_limit + boundary_limit,
                    use_llm=use_llm,
                )}
            )
            known = {normalize_space(str(item.get("query") or "")).lower() for item in all_branches}
            all_branches.extend(
                item for item in generated
                if normalize_space(str(item.get("query") or "")).lower() not in known
            )
    else:
        # Ask the cartographer to read the full user brief, not the later
        # compact retrieval query. User-specified coverage areas survive here.
        subspaces = generate_domain_subspaces(
            brief or domain,
            max_subspaces=core_limit + boundary_limit,
            use_llm=use_llm,
            user_hints=focus_branches,
        )
        transient_map = {"subspaces": subspaces}
        all_branches = query_plan_from_subspace_map(transient_map)
        generated_by = "full_brief_llm" if use_llm else "full_brief_profile"
    seen: set[str] = set()
    branches: list[dict[str, Any]] = []
    for item in all_branches:
        key = normalize_space(str(item.get("query") or "")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        branches.append(dict(item))
    # Explicit user focus terms are never silently discarded, even when the
    # subspace generator chooses a different label for the same science.
    for raw in focus_branches or []:
        label = normalize_space(str(raw))
        key = label.lower()
        if label and key not in seen:
            seen.add(key)
            branches.insert(0, {"branch": label.replace(" ", "_"), "name": label, "query": label, "custom": True})
    # Governance, markets, supply/logistics, policy and techno-economic work
    # can be essential context, but they rarely provide the direct causal
    # evidence needed by a mechanism hypothesis.  Keep them as planned boundary
    # extensions unless the user explicitly selected the branch.
    explicit_focus = {normalize_space(str(item)).lower() for item in (focus_branches or []) if normalize_space(str(item))}
    mechanism_first = [item for item in branches if not _is_system_boundary_branch(item, explicit_focus)]
    system_boundary = [item for item in branches if _is_system_boundary_branch(item, explicit_focus)]
    core = mechanism_first[:core_limit]
    # Do not promote a system-context branch to core merely because the
    # generated plan happened to contain fewer than ``core_limit`` mechanism
    # branches. Extra mechanism branches are still preferred before boundary
    # context when the extension budget is limited.
    boundary = (mechanism_first[core_limit:] + system_boundary)[:boundary_limit]
    for item in core:
        item["phase"] = "core_subspace"
    for item in boundary:
        item["phase"] = "boundary_extension"
    return {
        "strategy": "serial_subspace_cascade",
        "generated_by": generated_by,
        "retrieval_brief": retrieval_brief,
        "core_rounds_requested": core_limit,
        "boundary_rounds_requested": boundary_limit,
        "core_branches": core,
        "boundary_extensions": boundary,
        "all_branches": core + boundary,
        "unplanned_subspaces": max(0, len(branches) - len(core) - len(boundary)),
    }


def _is_system_boundary_branch(item: dict[str, Any], explicit_focus: set[str]) -> bool:
    """Classify generic system-context branches without hard-coding a science field."""
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    label = normalize_space(" ".join(str(item.get(key) or "") for key in ("branch", "name", "query"))).lower()
    if not label or item.get("custom") or any(focus and focus in label for focus in explicit_focus):
        return False
    context_markers = (
        "supply chain", "logistics", "procurement", "market", "econom", "policy", "governance",
        "management", "finance", "cost", "lifecycle", "life cycle", "techno-economic", "social acceptance",
    )
    return any(marker in label for marker in context_markers)

def build_subspace_selection_interaction(subspace_map: dict[str, Any]) -> dict[str, Any]:
    options: list[dict[str, Any]] = []
    for item in subspace_map.get("subspaces", [])[:12]:
        if not isinstance(item, dict):
            continue
        options.append(
            {
                "label": str(item.get("name") or item.get("subspace_id")),
                "subspace_id": str(item.get("subspace_id") or ""),
                "description": str(item.get("description") or ""),
                "keywords": item.get("keywords", [])[:8],
                "probe_hit_count": int(item.get("probe_hit_count") or 0),
                "estimated_density": item.get("estimated_density", "unknown"),
                "strategic_importance": item.get("strategic_importance", 5),
                "recommended": item.get("search_strategy") == "must_include" or int(item.get("strategic_importance") or 0) >= 7,
            }
        )
    return {
        "needed": True,
        "type": "pre_retrieval_subspace_selection",
        "question": "Select the subspaces to prioritize before ZhiZhi imports papers. You can also add custom subspaces.",
        "options": options,
        "custom_subspace_input": {
            "enabled": True,
            "placeholder": "e.g. Demand Response; EV Charging Coordination; Building Energy Management",
            "instructions": "If your target subfield is not listed, provide one subspace per line or semicolon-separated. These will be converted into custom retrieval branches.",
        },
        "continue_with": "Apply the selected scope to the V3 research objective or contracts, then resume run_autogen_groupchat.",
    }

def post_retrieval_subspace_coverage(
    subspace_map: dict[str, Any],
    selected_subfields: list[str] | None,
    imported_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._utils import clamp_int
    except ImportError:
        from _literature_search import query_terms
        from _utils import clamp_int
    plan = query_plan_from_subspace_map(subspace_map, selected_subfields=selected_subfields)
    records = []
    for item in imported_records:
        if not isinstance(item, dict):
            continue
        record = item.get("record") or item.get("existing_record") or {}
        if isinstance(record, dict):
            records.append(record)
    coverage: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    for branch in plan:
        terms = query_terms(" ".join([str(branch.get("name") or ""), str(branch.get("query") or "")]))[:16]
        target = clamp_int(branch.get("quota", 2), 1, 10)
        matches = [
            summarize_imported_record_for_subspace(record)
            for record in records
            if record_matches_terms(record, terms)
        ]
        status = "sufficient" if len(matches) >= target else "missing" if len(matches) == 0 else "insufficient"
        entry = {
            "subspace": branch.get("name") or branch.get("branch"),
            "branch": branch.get("branch"),
            "target": target,
            "actual": len(matches),
            "status": status,
            "terms": terms,
            "matched_papers": matches[:5],
            "suggested_query": branch.get("query"),
            "custom": bool(branch.get("custom")),
        }
        coverage.append(entry)
        if status != "sufficient":
            insufficient.append(entry)
    return {
        "total_selected_subspaces": len(plan),
        "sufficient": len([item for item in coverage if item["status"] == "sufficient"]),
        "insufficient": len(insufficient),
        "coverage": coverage,
        "needs_second_alignment": bool(insufficient),
        "user_interaction": build_post_retrieval_alignment_interaction(insufficient),
    }

def record_matches_terms(record: dict[str, Any], terms: list[str]) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    if not terms:
        return False
    text = normalize_space(
        " ".join(
            str(record.get(key) or "")
            for key in ("title", "citation", "abstract", "method", "scenario", "benchmark", "contribution", "limitation")
        )
    ).lower()
    hits = [term for term in terms if term in text]
    return len(hits) >= max(1, min(2, len(terms)))

def summarize_imported_record_for_subspace(record: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    return {
        "paper_id": record.get("paper_id"),
        "title": trim_text(str(record.get("title") or ""), 140),
        "citation": trim_text(str(record.get("citation") or ""), 120),
        "method": record.get("method"),
        "scenario": record.get("scenario"),
    }

def build_post_retrieval_alignment_interaction(insufficient: list[dict[str, Any]]) -> dict[str, Any]:
    if not insufficient:
        return {"needed": False}
    return {
        "needed": True,
        "type": "post_retrieval_subspace_alignment",
        "question": "Some selected subspaces are missing or under-covered after import. Should ZhiZhi run supplemental searches before TanXi treats gaps as real?",
        "options": [
            {
                "label": str(item.get("subspace")),
                "status": item.get("status"),
                "target": item.get("target"),
                "actual": item.get("actual"),
                "suggested_query": item.get("suggested_query"),
            }
            for item in insufficient[:8]
        ],
        "actions": [
            "supplemental_search_selected_subspaces",
            "adjust_query_terms",
            "continue_without_supplement",
        ],
        "continue_with": "Revise the affected V3 slot queries and resume run_autogen_groupchat.",
    }

def list_research_projects() -> str:
    projects = [load_project(path.stem) for path in sorted(projects_dir().glob("sci_*.json"))]
    if not projects:
        return "(no science projects)"
    return "\n".join(
        f"{project['project_id']} [{project.get('phase', '')}] {project.get('domain', '')} - {project.get('title', '')}"
        for project in projects
    )

def get_research_project(project_id: str) -> str:
    return json.dumps(load_project(project_id), ensure_ascii=False, indent=2)

def list_science_agents() -> str:
    try:
        from ._models import SCIENCE_AGENTS
    except ImportError:
        from _models import SCIENCE_AGENTS
    return json.dumps(SCIENCE_AGENTS, ensure_ascii=False, indent=2)

def get_science_agent_prompt(agent: str) -> str:
    try:
        from ._debate import run_socratic_hypothesis_debate
        from ._gap_detection import build_knowledge_map, detect_knowledge_gaps, run_tanxi_gap_exploration
        from ._hypothesis import design_experiment, finalize_idea, generate_idea, run_mingli_hypothesis_evolution
        from ._literature_search import extract_structured_info, search_literature, search_papers, search_papers_stratified
        from ._models import BIANLUN_FULL_PROMPT, BOXUE_FULL_PROMPT, DUZHI_FULL_PROMPT, Hypothesis, MINGLI_FULL_PROMPT, SCIENCE_AGENTS, SOCRATES_FULL_PROMPT, TANXI_FULL_PROMPT, YANZHEN_FULL_PROMPT, ZHIZHI_FULL_PROMPT
        from ._pipeline import assess_novelty, create_science_delegation_tasks, create_science_pipeline_tasks, verify_uniqueness
        from ._utils import normalize_key
        from ._verification import ask_critical_questions, ask_socratic_questions, causal_chain_audit, check_data_consistency, check_internal_consistency, detect_selective_citation, extract_emergent_method, find_counterexamples, moderate_round, regime_shift_test, run_yanzhen_mechanism_verification, stress_test_assumptions, summarize_positions
    except ImportError:
        from _debate import run_socratic_hypothesis_debate
        from _gap_detection import build_knowledge_map, detect_knowledge_gaps, run_tanxi_gap_exploration
        from _hypothesis import design_experiment, finalize_idea, generate_idea, run_mingli_hypothesis_evolution
        from _literature_search import extract_structured_info, search_literature, search_papers, search_papers_stratified
        from _models import BIANLUN_FULL_PROMPT, BOXUE_FULL_PROMPT, DUZHI_FULL_PROMPT, Hypothesis, MINGLI_FULL_PROMPT, SCIENCE_AGENTS, SOCRATES_FULL_PROMPT, TANXI_FULL_PROMPT, YANZHEN_FULL_PROMPT, ZHIZHI_FULL_PROMPT
        from _pipeline import assess_novelty, create_science_delegation_tasks, create_science_pipeline_tasks, verify_uniqueness
        from _utils import normalize_key
        from _verification import ask_critical_questions, ask_socratic_questions, causal_chain_audit, check_data_consistency, check_internal_consistency, detect_selective_citation, extract_emergent_method, find_counterexamples, moderate_round, regime_shift_test, run_yanzhen_mechanism_verification, stress_test_assumptions, summarize_positions
    key = normalize_key(agent)
    spec = SCIENCE_AGENTS.get(key)
    if spec is None:
        raise ValueError(f"Unknown science agent: {agent}")
    if key == "boxue":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": BOXUE_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Assess project state, dependencies, output quality, gap lifecycle, and delegation risk.",
                "action_tools": [
                    "run_autogen_groupchat",
                ],
                "observation": "Track specialist deliverables, gate shared project writes, synthesize conclusions, and decide advance/revise/finalize.",
            },
            "output_schema": {
                "schema_version": "autogen_run_summary_v1",
                "project_id": "string",
                "run_id": "string",
                "groupchat_id": "string",
                "final_decision": "string",
                "stop_reason": "string",
                "run_detail_ref": "string",
            },
            "global_constraints": [
                "Boxue coordinates; specialist agents execute domain work.",
                "Use run_autogen_groupchat as the only Boxue execution path.",
                "Never create persistent Boxue tasks or mirror GroupChat turns into task state.",
                "Do not advance TanXi while any selected sub-hypothesis is below its evidence gate.",
                "Do not treat unsupported or unreviewed evidence as a validated knowledge gap.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "zhizhi":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": ZHIZHI_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Analyze search strategy, source quality, evidence coverage, blind spots, migration opportunities, and pseudo-gap risk.",
                "action_tools": [
                    "search_papers_stratified",
                    "search_papers",
                    "extract_structured_info",
                    "build_knowledge_map",
                    "detect_knowledge_gaps",
                    "assess_novelty",
                    "verify_uniqueness",
                    "run_zhizhi_subhypothesis_analysis",
                ],
                "observation": "Update PaperGraph, benchmark-aware knowledge map, novelty checks, and valid innovation flags.",
            },
            "output_schema": zhizhi_output_schema(),
            "global_constraints": [
                "Never invent or substitute papers when retrieval fails.",
                "Every methodological claim must be grounded in a retrieved/imported source or marked as unsupported.",
                "Classify evidence as empirical_result, theoretical_claim, methodological_description, or author_opinion.",
                "Return structured JSON matching the ZhiZhi output schema.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "tanxi":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": TANXI_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Scan PaperGraph density, unresolved problems, unconnected cross-field pairs, strategic value, and pseudo-gap risk.",
                "action_tools": [
                    "run_tanxi_gap_exploration",
                    "detect_knowledge_gaps",
                    "check_semantic_plausibility",
                    "assess_novelty",
                    "verify_uniqueness",
                ],
                "observation": "Return coverage_analysis, cross_disciplinary_unconnected_pairs, suspended_problems, and ranked_gaps.",
            },
            "output_schema": {
                "thought": "string",
                "action": {},
                "coverage_analysis": {"dense_areas": [], "density_holes": []},
                "cross_disciplinary_unconnected_pairs": [],
                "suspended_problems": [],
                "ranked_gaps": [],
            },
            "global_constraints": [
                "Every gap must be backed by at least one PaperGraph reference.",
                "Rank no more than 10 gaps per scan.",
                "Avoid trivial gaps and already-saturated areas.",
                "Prioritize scientific significance, tractability, strategic value, and downstream impact.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "socrates":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": SOCRATES_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Audit mechanism fields against PaperGraph citations and identify the smallest unresolved evidence question.",
                "action_tools": ["run_socrates_mechanism_enrichment", "extract_paper_keynote"],
                "observation": "Store field-level source excerpts, report unresolved fields, and stop rather than inventing a mechanism.",
            },
            "output_schema": {
                "gap_id": "string",
                "mechanism_contract": {"evidence": {}},
                "verdict": "COMPLETE | INSUFFICIENT_EVIDENCE",
                "remaining_unresolved": [],
                "next_step": "string",
            },
            "global_constraints": [
                "Use existing PaperGraph records before running a new literature search.",
                "Every resolved field must contain a citation and a direct evidence excerpt.",
                "Do not claim that missing evidence proves the mechanism false or true.",
                "Respect the configured iteration, query, and import limits.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "mingli":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": MINGLI_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Evaluate whether a hypothesis is gap-traceable, PaperGraph-grounded, novel, feasible, and structurally distinct from prior candidates.",
                "action_tools": [
                    "generate_idea",
                    "design_experiment",
                    "check_semantic_plausibility",
                    "verify_uniqueness",
                    "search_literature",
                    "finalize_idea",
                    "run_mingli_hypothesis_evolution",
                ],
                "observation": "Inspect uniqueness evidence, overlap risk, experiment feasibility, lineage, and final JSON completeness before finalization.",
            },
            "output_schema": mingli_output_schema(),
            "global_constraints": [
                "Every finalized idea must reference a real project gap_id.",
                "At least one uniqueness or literature verification check is mandatory before finalize_idea succeeds.",
                "Every experiment must include setup, metrics, and baselines.",
                "Tournament mutations must introduce structural changes and preserve parent lineage.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "duzhi":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": DUZHI_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Extract key claims, implicit assumptions, measurement gaps, causal gaps, and possible counterexamples.",
                "action_tools": [
                    "ask_socratic_questions",
                    "ask_critical_questions",
                    "find_counterexamples",
                    "stress_test_assumptions",
                    "check_internal_consistency",
                    "regime_shift_test",
                ],
                "observation": "Return categorized questions, required revisions, severity, and whether the hypothesis must be revised.",
            },
            "output_schema": duzhi_output_schema(),
            "global_constraints": [
                "Ask questions that can change the hypothesis, not generic objections.",
                "Every critique must target a concrete claim, missing measurement, missing causal link, or missing boundary condition.",
                "Use domain-general scientific constraints and avoid field-specific hardcoding.",
                "If evidence is missing, mark it as missing instead of inventing a refutation.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "bianlun":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": BIANLUN_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Check safety gates, compare MingLi claim, DuZhi objections, YanZhen reports, and PaperGraph evidence.",
                "action_tools": [
                    "run_socratic_hypothesis_debate",
                    "moderate_round",
                    "summarize_positions",
                    "extract_emergent_method",
                    "run_yanzhen_mechanism_verification",
                ],
                "observation": "Return round-by-round verdicts, adopted revisions, unresolved disputes, and final decision.",
            },
            "output_schema": bianlun_output_schema(),
            "global_constraints": [
                "Do not accept unsupported hypothesis revisions.",
                "Enforce role-prompt independence as an auditable safety gate.",
                "If YanZhen reports CAWM_DETECTED, the debate cannot accept the hypothesis without revision.",
                "If two rounds produce no substantive revision, terminate with best current hypothesis plus unresolved issues.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    if key == "yanzhen":
        prompt = {
            "agent": key,
            **spec,
            "full_system_prompt": YANZHEN_FULL_PROMPT,
            "tao_workflow": {
                "thought": "Extract mechanism, causal chain, cited evidence, hidden assumptions, and regime-shift stress cases.",
                "action_tools": [
                    "check_internal_consistency",
                    "check_data_consistency",
                    "regime_shift_test",
                    "detect_selective_citation",
                    "causal_chain_audit",
                    "run_yanzhen_mechanism_verification",
                ],
                "observation": "Return layer verdicts, detailed reasoning, CAWM risk, selective citation risk, and human-review flags.",
            },
            "output_schema": yanzhen_output_schema(),
            "global_constraints": [
                "All three layers must be executed.",
                "Regime shift testing must include at least two shifted conditions.",
                "Do not pass hypotheses with missing evidence, unstated assumptions, or brittle mechanisms.",
                "The audit must be domain-general and avoid field-specific hardcoding.",
            ],
        }
        return json.dumps(prompt, ensure_ascii=False, indent=2)
    prompt = {
        "agent": key,
        **spec,
        "operating_protocol": "Use a TAO loop: Thought -> Action -> Observation. Return structured JSON only.",
        "global_constraints": [
            "Every claim must be backed by evidence or marked as a hypothesis.",
            "Every deliverable needs explicit acceptance criteria.",
            "Knowledge gaps must be scientifically meaningful, not merely untried combinations.",
            "Mechanism claims require internal consistency, data consistency, and regime-shift checks.",
        ],
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)

def zhizhi_output_schema() -> dict[str, Any]:
    return {
        "thought": "string",
        "action": "object",
        "knowledge_map_summary": {
            "main_methods": ["string"],
            "method_scenario_coverage": {"method": ["scenario"]},
            "method_scenario_benchmark_triples": [
                {"method": "string", "scenario": "string", "benchmark": "string", "references": ["string"]}
            ],
        },
        "knowledge_gaps": [
            {
                "gap_id": "string",
                "gap_type": "combinatorial | improvement | migration | problem",
                "description": "string",
                "supporting_references": ["string"],
                "novelty_score": "integer 1-10",
                "application_value": "high | medium | low",
                "feasibility": "high | medium | low",
                "suggested_research_path": "string",
            }
        ],
    }

def mingli_output_schema() -> dict[str, Any]:
    try:
        from ._models import Hypothesis
    except ImportError:
        from _models import Hypothesis
    return {
        "title": "Research Title",
        "hypothesis": "Core Hypothesis",
        "abstract": "Abstract",
        "related_work": "Comparison with Related Work",
        "experiments": {
            "setup": "Experimental Setup",
            "metrics": "Evaluation Metrics",
            "baselines": "Baseline Methods",
        },
        "risks": "Risk Factors and Limitations",
        "tournament_generation": 1,
        "parent_hypothesis_id": "string | null",
    }

def duzhi_output_schema() -> dict[str, Any]:
    try:
        from ._verification import ask_socratic_questions
    except ImportError:
        from _verification import ask_socratic_questions
    return {
        "thought": "Socratic critique reasoning",
        "action": {"type": "ask_socratic_questions", "params": {}},
        "questions": [
            {
                "question_type": "conceptual_clarification | constraint_check | causal_probe | counterexample_challenge",
                "question": "string",
                "target_claim": "string",
                "why_it_matters": "string",
                "required_revision": "string",
                "severity": "low | medium | high | fatal",
            }
        ],
        "overall_severity": "low | medium | high | fatal",
        "must_revise": True,
    }

def bianlun_output_schema() -> dict[str, Any]:
    try:
        from ._debate import run_socratic_hypothesis_debate
    except ImportError:
        from _debate import run_socratic_hypothesis_debate
    return {
        "thought": "Structured debate moderation reasoning",
        "action": {"type": "run_socratic_hypothesis_debate", "params": {}},
        "debate_report": {
            "rounds": [],
            "safety_gates": {},
            "refined_hypothesis": {},
            "unresolved_issues": [],
            "final_decision": "accept_for_experiment | revise | human_review | reject",
        },
    }

def yanzhen_output_schema() -> dict[str, Any]:
    return {
        "thought": "Mechanism verification reasoning process",
        "action": {},
        "mechanism_fidelity_report": {
            "hypothesis_id": "string",
            "layer_1_internal_consistency": {
                "logical_chain_intact": True,
                "formula_application_correct": True,
                "issues_found": [],
                "verdict": "PASS | FAIL",
            },
            "layer_2_data_consistency": {
                "mechanism_matches_data": True,
                "selective_citation_detected": False,
                "original_text_alignment": "high | medium | low",
                "verdict": "PASS | FAIL",
            },
            "layer_3_regime_shift_test": {
                "shifted_conditions_tested": ["condition1", "condition2"],
                "mechanism_stability": "stable | degrades_gracefully | collapses_unexpectedly",
                "cawm_risk_level": "LOW | MEDIUM | HIGH",
                "verdict": "PASS | FAIL",
            },
            "overall_verdict": "MECHANISM_VERIFIED | CAWM_DETECTED | REQUIRES_HUMAN_REVIEW",
            "detailed_reasoning": "string",
        },
    }

def load_project(project_id: str) -> dict[str, Any]:
    return science_state_manager().get_project(project_id)

def save_project(project: dict[str, Any], expected_version: int | None = None) -> None:
    science_state_manager().save_project(project, expected_version=expected_version)


def adopt_science_project_store(project_id: str, source_store_id: str) -> dict[str, Any]:
    """Adopt a project JSON deliberately copied from another science store."""
    return science_state_manager().adopt_project_copy(project_id, source_store_id)


def normalized_science_project_layout(project_id: str) -> dict[str, Any]:
    """Describe the future artifact layout without creating directories."""
    return science_state_manager().normalized_project_layout(project_id)


def prepare_normalized_science_project_layout(project_id: str) -> dict[str, Any]:
    """Create a dormant normalized directory skeleton for a canonical project."""
    return science_state_manager().prepare_normalized_project_layout(project_id)


def preview_normalized_gap_artifacts(
    project_id: str,
    gap_id: str,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Build reference-only gap artifacts without writing or activating them."""
    return science_state_manager().preview_normalized_gap_artifacts(
        project_id,
        gap_id,
        run_id=run_id,
    )


def activate_normalized_science_project_storage(
    project_id: str,
    *,
    expected_version: int | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Explicitly migrate a legacy snapshot using a manifest-last transaction."""
    return science_state_manager().activate_normalized_project_storage(
        project_id,
        expected_version=expected_version,
        run_id=run_id,
    )


def get_science_project_manifest(project_id: str) -> dict[str, Any]:
    return science_state_manager().get_project_manifest(project_id)


def repair_science_artifact_json_v2(project_id: str, target: str) -> dict[str, Any]:
    """Explicitly repair one persisted JSON artifact without retrieval work.

    ``target`` is either a normalized artifact path relative to the project's
    artifact root (for example ``papers/paper_123.json``), or the exact token
    ``legacy_snapshot``.  This maintenance API is intentionally not exposed
    as a model-facing research tool.
    """
    return science_state_manager().repair_artifact_json_v2(project_id, target)


def get_science_fragment(project_id: str, fragment_id: str) -> dict[str, Any]:
    return science_state_manager().get_fragment(project_id, fragment_id)


def science_state_manager():
    global _SCIENCE_STATE_MANAGER
    if _SCIENCE_STATE_MANAGER is None:
        try:
            from ._science_state import ScienceStateManager
        except ImportError:
            from _science_state import ScienceStateManager
        _SCIENCE_STATE_MANAGER = ScienceStateManager(
            project_path,
            lambda path, missing_message: _read_json_store(path, missing_message),
            lambda path, payload: _write_json_store(path, payload),
        )
    return _SCIENCE_STATE_MANAGER

def load_search(search_id: str) -> dict[str, Any]:
    path = search_path(search_id)
    return _read_json_store(path, f"Literature search not found: {search_id}")

def save_search(search: dict[str, Any]) -> None:
    _write_json_store(search_path(str(search["search_id"])), search)

def load_subspace_map(subspace_map_id: str) -> dict[str, Any]:
    path = subspace_map_path(subspace_map_id)
    return _read_json_store(path, f"Domain subspace map not found: {subspace_map_id}")

def save_subspace_map(subspace_map: dict[str, Any]) -> None:
    _write_json_store(subspace_map_path(str(subspace_map["subspace_map_id"])), subspace_map)

def search_path(search_id: str) -> Path:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    safe = normalize_key(search_id)
    return searches_dir() / f"{safe}.json"

def searches_dir() -> Path:
    return SCIENCE_DIR / "searches"

def subspace_map_path(subspace_map_id: str) -> Path:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    safe = normalize_key(subspace_map_id)
    return subspaces_dir() / f"{safe}.json"

def subspaces_dir() -> Path:
    return SCIENCE_DIR / "subspaces"

def project_path(project_id: str) -> Path:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    safe = normalize_key(project_id)
    return projects_dir() / f"{safe}.json"

def projects_dir() -> Path:
    return SCIENCE_DIR / "projects"
