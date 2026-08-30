from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from omegaconf import OmegaConf
except Exception:  # pragma: no cover - optional runtime fallback
    OmegaConf = None

from src.memory.api.faiss_memory_system_api import FAISSMemorySystem
from src.memory.api.slot_process_api import SlotProcess
from src.memory.api.symbolic_memory_system_api import SymbolicMemorySystem
from src.memory.memory_system import FaissVectorStore
from src.memory.memory_system.models import EpisodicRecord, ProceduralRecord, SemanticRecord
from src.memory.memory_system.utils import _multi_thread_run, _safe_dump_str
from src.agents.idea_agent.utils.core.json_utils import pretty_json
from src.agents.idea_agent.utils.core.progress import iter_with_progress
from src.agents.idea_agent.utils.core.response_parsing import parse_json_response
from src.agents.idea_agent.utils.core.logger import LoguruCompatLogger, get_logger
from src.agents.idea_agent.utils.mcts.component_novelty import ComponentNoveltyScorer
from src.agents.idea_agent.utils.mcts.mcts_helpers import (
    _dedupe_keep_order_strings,
    _format_root_domains_for_prompt,
    _normalize_root_domains,
    _safe_float_default,
    apply_normalized_score_weights,
    clip_metric_score,
    clip_text,
    coerce_integer_metric_score,
    parent_centers_control_surface,
    format_mechanism_commit_references,
    format_theory_transfer_references,
    component_inventory_payload,
    format_analysis_blob,
    normalize_mechanism_commit_query_payload,
    normalize_theory_transfer_query_payload,
    normalize_component_explanations,
    text_uses_forbidden_query_terms,
)
from src.pipeline.discipline_taxonomy import (
    canonicalize_discipline_key,
    format_taxonomy_catalog_for_prompt,
    resolve_discipline_taxonomy,
)
from src.agents.idea_agent.utils.prompting.prompt_views import (
    format_idea_prompt_view,
)
from src.agents.idea_agent.utils.papers.paper_graph_vector_store import (
    PaperGraphComponentVectorStore,
)
from src.agents.idea_agent.agent.prompts.root_domain_classification import (
    ROOT_DOMAIN_CLASSIFICATION_PROMPT,
)
from src.agents.idea_agent.agent.prompts.skill_instantiation import (
    get_skill_instantiation_prompt,
)
from src.agents.idea_agent.agent.prompts.mechanism_commit_query import (
    get_mechanism_commit_query_prompt,
)
from src.agents.idea_agent.agent.prompts.theory_transfer_query import (
    get_theory_transfer_query_prompt,
)
from src.agents.idea_agent.agent.prompts.component_extraction import (
    render_component_extraction_prompt,
)
from src.agents.idea_agent.utils.core.config_loader import (
    load_idea_agent_config,
    resolve_workspace_path,
)
from src.agents.idea_agent.utils.mcts.idea_taste_presets import (
    IdeaTastePreset,
    SCORE_WEIGHT_FIELDS,
    get_idea_taste_preset,
)
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    build_scientific_intervention_payload,
    normalize_project_context_discipline_resolution,
    resolve_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.mcts.scientific_rubric import (
    PROFILE_NOVELTY_AXES,
    profile_score_weights,
)
from src.agents.idea_agent.utils.workflow.gap_hypothesis_bridge import (
    build_gap_hypothesis_seeds,
    build_gap_seed_context,
    build_gap_seed_status,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_mature_idea
from src.agents.idea_agent.utils.mcts.mcts_runtime import (
    EditPlan,
    MemoryBundle,
    MemorySnippet,
    SkillCatalog,
    SkillUsagePrior,
    best_candidate,
    build_symbolic_eval_hints,
    build_root_state,
    compute_protocol_score_from_plan,
    extract_mature_idea_components_via_llm,
    instantiate_skill_plan_for_node,
    log_message,
    materialize_child_state,
    memory_bundle_log_payload,
    new_node,
    pareto_candidates,
    path_summary,
    backpropagate_rollout,
    expand_node_with_skills,
    reset_search_state,
    select_leaf_for_rollout,
    simulate_log_payload,
    simulate_node_value,
    update_skill_prior_from_evaluation,
)


UNIFORM_CLIP_TEXT_LIMIT = 10000
MAX_LIST_ENTRIES = 16
MIN_COMPONENTS = 1
MAX_COMPONENTS = 5
HYPOTHESIS_PAYLOAD_FIELDS = (
    "direction_mode",
    "direction_summary",
    "central_hypothesis",
    "scientific_object",
    "mechanism_or_relation",
    "intervention_or_transformation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "target_gap_ids",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
)
INTEGER_EVALUATION_FIELDS = (
    "novelty",
    "surprise",
    "feasibility",
    "clarity",
    "impact",
    "risk",
    "conciseness",
    "alignment_score",
    "complexity_penalty",
    "protocol_score",
    "explanatory_power",
    "identifiability",
    "boundary_calibration",
    "claim_overreach_penalty",
)

module_logger = get_logger()


def _load_mcts_defaults() -> Dict[str, Any]:
    if OmegaConf is None:
        return {}
    config = load_idea_agent_config()
    mcts_config = config.get("mcts") if hasattr(config, "get") else None
    if mcts_config is None:
        return {}
    try:
        return OmegaConf.to_container(mcts_config, resolve=True) or {}
    except Exception:
        return dict(mcts_config) if isinstance(mcts_config, dict) else {}


_MCTS_DEFAULTS = _load_mcts_defaults()


def _mcts_default(key: str, fallback: Any) -> Any:
    value = _MCTS_DEFAULTS.get(key, fallback)
    if key in {"generation_model", "evaluation_model", "component_novelty_eval_model"}:
        if not str(value or "").strip():
            role = {
                "generation_model": "idea_generation",
                "evaluation_model": "idea_evaluation",
                "component_novelty_eval_model": "idea_evaluation",
            }[key]
            try:
                from src.llm.provider_registry import resolve_role_model

                return resolve_role_model(None, role).name
            except Exception:
                return fallback
    return fallback if value is None else value


@dataclass
class IdeaState:
    title: str
    abstract: str
    core_contribution: str
    method: str
    risks: str
    tags: List[str]
    operator: str
    target_defects: List[str]
    rationale: str
    memory_refs: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    component_explanations: Dict[str, str] = field(default_factory=dict)
    root_domains: List[str] = field(default_factory=list)
    discipline_resolution: Dict[str, Any] = field(default_factory=dict)
    scientific_intervention: Dict[str, Any] = field(default_factory=dict)
    paper_graph_context: str = ""
    edit_plan: Optional[Dict[str, Any]] = None
    skill_metrics: Dict[str, Any] = field(default_factory=dict)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        self.title = clip_text(self.title, UNIFORM_CLIP_TEXT_LIMIT)
        self.abstract = clip_text(self.abstract, UNIFORM_CLIP_TEXT_LIMIT)
        self.core_contribution = clip_text(self.core_contribution, UNIFORM_CLIP_TEXT_LIMIT)
        self.method = clip_text(self.method, UNIFORM_CLIP_TEXT_LIMIT)
        self.risks = clip_text(self.risks, UNIFORM_CLIP_TEXT_LIMIT)
        self.rationale = clip_text(self.rationale, UNIFORM_CLIP_TEXT_LIMIT)
        self.paper_graph_context = clip_text(self.paper_graph_context, UNIFORM_CLIP_TEXT_LIMIT)

        self.tags = _dedupe_keep_order_strings(
            [clip_text(tag, UNIFORM_CLIP_TEXT_LIMIT) for tag in self.tags[:MAX_LIST_ENTRIES]]
        )
        self.target_defects = _dedupe_keep_order_strings(
            [clip_text(tag, UNIFORM_CLIP_TEXT_LIMIT) for tag in self.target_defects[:MAX_LIST_ENTRIES]]
        )
        self.memory_refs = _dedupe_keep_order_strings(
            [clip_text(ref, UNIFORM_CLIP_TEXT_LIMIT) for ref in self.memory_refs[:MAX_LIST_ENTRIES]]
        )
        self.components = _dedupe_keep_order_strings(
            [clip_text(comp, UNIFORM_CLIP_TEXT_LIMIT) for comp in self.components[: 2 * MAX_LIST_ENTRIES]]
        )
        self.component_explanations = normalize_component_explanations(
            self.components,
            self.component_explanations,
        )
        self.root_domains = _normalize_root_domains(self.root_domains)
        self.discipline_resolution = (
            dict(self.discipline_resolution)
            if isinstance(self.discipline_resolution, dict)
            else {}
        )
        self.scientific_intervention = (
            dict(self.scientific_intervention)
            if isinstance(self.scientific_intervention, dict)
            else {}
        )

        canonical = "|".join(
            [
                self.title.lower(),
                self.core_contribution.lower(),
                self.method.lower(),
                ",".join(sorted(self.tags)),
                ",".join(self.root_domains),
                str(self.scientific_intervention.get("profile_id") or ""),
                str(self.scientific_intervention.get("contribution_mode") or ""),
                ",".join(sorted(self.components)),
                "|".join(
                    f"{component}:{self.component_explanations.get(component, '').lower()}"
                    for component in self.components
                ),
            ]
        )
        self.signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def describe(self) -> str:
        return self.to_prompt_view(heading="Parent Idea")

    def to_prompt_view(self, heading: str = "Idea Snapshot") -> str:
        return format_idea_prompt_view(self, heading=heading)

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "title": self.title,
            "abstract": self.abstract,
            "core_contribution": self.core_contribution,
            "method": self.method,
            "risks": self.risks,
            "tags": self.tags,
            "operator": self.operator,
            "target_defects": self.target_defects,
            "memory_refs": self.memory_refs,
            "rationale": self.rationale,
            "components": self.components,
            "component_explanations": self.component_explanations,
            "root_domains": self.root_domains,
            "discipline_resolution": self.discipline_resolution,
            "scientific_intervention": self.scientific_intervention,
            "components_with_explanations": self.component_inventory(),
            "paper_graph_context": self.paper_graph_context,
        }
        hypothesis_contract = self.scientific_intervention.get("hypothesis_contract")
        if isinstance(hypothesis_contract, dict):
            for field_name in HYPOTHESIS_PAYLOAD_FIELDS:
                value = hypothesis_contract.get(field_name)
                if value not in (None, "", [], {}):
                    payload[field_name] = value
        direction_mode = self.scientific_intervention.get("direction_mode")
        if direction_mode and not payload.get("direction_mode"):
            payload["direction_mode"] = direction_mode
        direction_summary = self.scientific_intervention.get("direction_summary")
        if direction_summary and not payload.get("direction_summary"):
            payload["direction_summary"] = direction_summary
        if self.edit_plan:
            payload["edit_plan"] = self.edit_plan
        if self.skill_metrics:
            payload["skill_metrics"] = self.skill_metrics
        return payload

    def component_inventory(self) -> List[Dict[str, str]]:
        return component_inventory_payload(self.components, self.component_explanations)


@dataclass
class IdeaEvaluation:
    novelty: float
    surprise: float
    feasibility: float
    clarity: float
    impact: float
    risk: float
    conciseness: float
    alignment_score: float
    complexity_penalty: float
    protocol_score: float
    confidence: float
    failure_modes: List[str]
    fairness_protocol: str
    feedback: str
    defect_fix_summary: str
    detected_defects: List[str]
    explanatory_power: float = 0.0
    identifiability: float = 0.0
    boundary_calibration: float = 0.0
    claim_overreach_penalty: float = 0.0
    novelty_axes: Dict[str, float] = field(default_factory=dict)
    profile_id: str = ""
    novelty_weight: float = 0.20
    surprise_weight: float = 0.10
    impact_weight: float = 0.18
    feasibility_weight: float = 0.11
    clarity_weight: float = 0.06
    conciseness_weight: float = 0.03
    risk_weight: float = 0.09
    alignment_weight: float = 0.15
    complexity_weight: float = 0.05
    protocol_weight: float = 0.03
    explanatory_power_weight: float = 0.06
    identifiability_weight: float = 0.06
    boundary_calibration_weight: float = 0.04
    claim_overreach_weight: float = 0.10

    def __post_init__(self) -> None:
        self.failure_modes = [
            clip_text(mode, UNIFORM_CLIP_TEXT_LIMIT)
            for mode in (self.failure_modes or [])[:MAX_LIST_ENTRIES]
        ]
        self.fairness_protocol = clip_text(self.fairness_protocol, UNIFORM_CLIP_TEXT_LIMIT)
        self.feedback = clip_text(self.feedback, UNIFORM_CLIP_TEXT_LIMIT)
        self.defect_fix_summary = clip_text(self.defect_fix_summary, UNIFORM_CLIP_TEXT_LIMIT)
        self.detected_defects = [
            clip_text(tag, UNIFORM_CLIP_TEXT_LIMIT)
            for tag in (self.detected_defects or [])[:MAX_LIST_ENTRIES]
        ]
        self.profile_id = str(self.profile_id or "").strip().lower()
        allowed_axes = None
        if self.profile_id:
            allowed_axes = set(
                PROFILE_NOVELTY_AXES.get(
                    self.profile_id,
                    PROFILE_NOVELTY_AXES["generic_scientific"],
                )
            )
            allowed_axes.add("scientific_novelty")
        normalized_axes: Dict[str, float] = {}
        if isinstance(self.novelty_axes, dict):
            for key, value in self.novelty_axes.items():
                normalized_key = str(key).strip()
                if not normalized_key:
                    continue
                if allowed_axes is not None and normalized_key not in allowed_axes:
                    continue
                try:
                    normalized_axes[normalized_key] = max(0.0, min(5.0, float(value)))
                except (TypeError, ValueError):
                    continue
        if not normalized_axes:
            normalized_axes = {"scientific_novelty": float(self.novelty)}
        normalized_axes.setdefault("scientific_novelty", float(self.novelty))
        self.novelty_axes = normalized_axes
        for field_name in INTEGER_EVALUATION_FIELDS:
            setattr(
                self,
                field_name,
                coerce_integer_metric_score(getattr(self, field_name, 0)),
            )
        self.confidence = max(0.0, min(1.0, _safe_float_default(self.confidence, 0.0)))
        apply_normalized_score_weights(self, SCORE_WEIGHT_FIELDS)

    @classmethod
    def from_payload(
        cls,
        payload: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
        profile_id: str = "",
    ) -> "IdeaEvaluation":
        def _num(key: str, default: float = 0.0) -> float:
            return _safe_float_default(payload.get(key, default), default)

        def _list(key: str) -> List[str]:
            raw = payload.get(key, [])
            if isinstance(raw, list):
                return [str(x) for x in raw]
            if isinstance(raw, str):
                return [raw]
            return []

        if weights is not None:
            w = dict(weights)
        elif profile_id:
            w = profile_score_weights(
                profile_id,
                {
                    "novelty_weight": 0.20,
                    "surprise_weight": 0.10,
                    "impact_weight": 0.18,
                    "feasibility_weight": 0.11,
                    "clarity_weight": 0.06,
                    "conciseness_weight": 0.03,
                    "risk_weight": 0.09,
                    "alignment_weight": 0.15,
                    "complexity_weight": 0.05,
                    "protocol_weight": 0.03,
                    "explanatory_power_weight": 0.06,
                    "identifiability_weight": 0.06,
                    "boundary_calibration_weight": 0.04,
                    "claim_overreach_weight": 0.10,
                },
            )
        else:
            w = {}
        return cls(
            novelty=_num("novelty"),
            surprise=_num("surprise"),
            feasibility=_num("feasibility"),
            clarity=_num("clarity"),
            impact=_num("impact"),
            risk=_num("risk"),
            conciseness=_num("conciseness"),
            alignment_score=_num("alignment_score"),
            complexity_penalty=_num("complexity_penalty"),
            protocol_score=_num("protocol_score"),
            explanatory_power=_num("explanatory_power"),
            identifiability=_num("identifiability"),
            boundary_calibration=_num("boundary_calibration"),
            claim_overreach_penalty=_num("claim_overreach_penalty"),
            novelty_axes=(
                payload.get("novelty_axes")
                if isinstance(payload.get("novelty_axes"), dict)
                else {}
            ),
            profile_id=profile_id or str(payload.get("profile_id") or ""),
            confidence=_num("confidence", 0.0),
            failure_modes=_list("failure_modes"),
            fairness_protocol=str(payload.get("fairness_protocol", "")),
            feedback=str(payload.get("feedback", "")),
            defect_fix_summary=str(payload.get("defect_fix_summary", "")),
            detected_defects=_list("detected_defects"),
            novelty_weight=w.get("novelty_weight", 0.20),
            surprise_weight=w.get("surprise_weight", 0.10),
            impact_weight=w.get("impact_weight", 0.18),
            feasibility_weight=w.get("feasibility_weight", 0.11),
            clarity_weight=w.get("clarity_weight", 0.06),
            conciseness_weight=w.get("conciseness_weight", 0.03),
            risk_weight=w.get("risk_weight", 0.09),
            alignment_weight=w.get("alignment_weight", 0.15),
            complexity_weight=w.get("complexity_weight", 0.05),
            protocol_weight=w.get("protocol_weight", 0.03),
            explanatory_power_weight=w.get("explanatory_power_weight", 0.06),
            identifiability_weight=w.get("identifiability_weight", 0.06),
            boundary_calibration_weight=w.get("boundary_calibration_weight", 0.04),
            claim_overreach_weight=w.get("claim_overreach_weight", 0.10),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "novelty": self.novelty,
            "surprise": self.surprise,
            "feasibility": self.feasibility,
            "clarity": self.clarity,
            "impact": self.impact,
            "risk": self.risk,
            "conciseness": self.conciseness,
            "alignment_score": self.alignment_score,
            "complexity_penalty": self.complexity_penalty,
            "protocol_score": self.protocol_score,
            "explanatory_power": self.explanatory_power,
            "identifiability": self.identifiability,
            "boundary_calibration": self.boundary_calibration,
            "claim_overreach_penalty": self.claim_overreach_penalty,
            "novelty_axes": self.novelty_axes,
            "profile_id": self.profile_id,
            "confidence": self.confidence,
            "failure_modes": self.failure_modes,
            "fairness_protocol": self.fairness_protocol,
            "feedback": self.feedback,
            "defect_fix_summary": self.defect_fix_summary,
            "detected_defects": self.detected_defects,
        }

    @property
    def composite(self) -> float:
        allowed_axes = None
        if self.profile_id:
            allowed_axes = set(
                PROFILE_NOVELTY_AXES.get(
                    self.profile_id,
                    PROFILE_NOVELTY_AXES["generic_scientific"],
                )
            )
            allowed_axes.add("scientific_novelty")
        novelty_values = [
            score for key, score in self.novelty_axes.items()
            if key != "retrieval_similarity"
            and (allowed_axes is None or key in allowed_axes)
        ]
        scientific_novelty = (
            sum(novelty_values) / len(novelty_values)
            if novelty_values
            else self.novelty
        )
        weighted_scores = {
            "novelty_weight": clip_metric_score(scientific_novelty),
            "surprise_weight": clip_metric_score(self.surprise),
            "impact_weight": clip_metric_score(self.impact),
            "feasibility_weight": clip_metric_score(self.feasibility),
            "clarity_weight": clip_metric_score(self.clarity),
            "conciseness_weight": clip_metric_score(self.conciseness),
            "alignment_weight": clip_metric_score(self.alignment_score),
            "protocol_weight": clip_metric_score(self.protocol_score),
            "risk_weight": 5.0 - clip_metric_score(self.risk),
            "complexity_weight": 5.0 - clip_metric_score(self.complexity_penalty),
            "explanatory_power_weight": clip_metric_score(self.explanatory_power),
            "identifiability_weight": clip_metric_score(self.identifiability),
            "boundary_calibration_weight": clip_metric_score(self.boundary_calibration),
            "claim_overreach_weight": 5.0 - clip_metric_score(self.claim_overreach_penalty),
        }
        return sum(
            getattr(self, field_name) * score
            for field_name, score in weighted_scores.items()
        )


@dataclass
class OperatorApplication:
    operator: str
    defects: List[str]
    rationale: str
    memory_refs: List[str]

    def __post_init__(self) -> None:
        self.operator = clip_text(self.operator, UNIFORM_CLIP_TEXT_LIMIT)
        self.defects = [clip_text(defect, UNIFORM_CLIP_TEXT_LIMIT) for defect in self.defects[:MAX_LIST_ENTRIES]]
        self.rationale = clip_text(self.rationale, UNIFORM_CLIP_TEXT_LIMIT)
        self.memory_refs = [clip_text(ref, UNIFORM_CLIP_TEXT_LIMIT) for ref in self.memory_refs[:MAX_LIST_ENTRIES]]


@dataclass
class IdeaNode:
    node_id: int
    state: IdeaState
    depth: int
    parent: Optional["IdeaNode"]
    transformation: OperatorApplication
    children: List["IdeaNode"] = field(default_factory=list)
    visits: int = 0
    value_sum: float = 0.0
    expanded: bool = False
    evaluation: Optional[IdeaEvaluation] = None
    latest_path_summary: str = ""

    def uct_value(self, parent_visits: int, exploration_constant: float) -> float:
        if self.visits == 0:
            return float("inf")
        exploit = self.value_sum / self.visits
        explore = exploration_constant * math.sqrt(math.log(max(1, parent_visits)) / self.visits)
        return exploit + explore

    def path(self) -> List["IdeaNode"]:
        chain: List[IdeaNode] = []
        node: Optional[IdeaNode] = self
        while node:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def path_summary(self) -> str:
        if self.latest_path_summary:
            return self.latest_path_summary
        steps: List[str] = []
        for hop in self.path():
            steps.append(
                f"{hop.state.title} [{hop.transformation.operator}] -> defects {hop.transformation.defects}"
            )
        return " | ".join(steps)


@dataclass
class MCTSConfig:
    max_iterations: int = _mcts_default("exploration_budget", _mcts_default("max_iterations", 128))
    max_depth: int = _mcts_default("max_depth", 4)
    branching_factor: int = _mcts_default("branching_factor", 3)
    exploration_constant: float = _mcts_default("exploration_constant", 1.15)
    idea_taste_mode: Optional[str] = _mcts_default("idea_taste_mode", None)
    seed_id: Optional[str] = None
    route_id: Optional[str] = None
    prompt_mode: str = _mcts_default("prompt_mode", "default")
    generation_model: str = _mcts_default("generation_model", "gpt-5-mini")
    evaluation_model: str = _mcts_default("evaluation_model", "gpt-5.2")
    generation_temperature: float = _mcts_default("generation_temperature", 0.2)
    evaluation_temperature: float = _mcts_default("evaluation_temperature", 0.01)
    generation_max_tokens: int = _mcts_default("generation_max_tokens", 8192)
    evaluation_max_tokens: int = _mcts_default("evaluation_max_tokens", 8192)
    component_novelty_model_path: str = _mcts_default(
        "component_novelty_model_path", "models/bge-m3"
    )
    component_novelty_index_dir: Optional[str] = _mcts_default(
        "component_novelty_index_dir", None
    )
    component_novelty_retrieval_top_k: int = _mcts_default(
        "component_novelty_retrieval_top_k", 50
    )
    component_novelty_evidence_top_k: int = _mcts_default(
        "component_novelty_evidence_top_k", 5
    )
    component_novelty_eval_model: Optional[str] = _mcts_default(
        "component_novelty_eval_model", None
    )
    component_novelty_eval_temperature: float = _mcts_default(
        "component_novelty_eval_temperature",
        _mcts_default("evaluation_temperature", 0.01),
    )
    component_novelty_eval_max_tokens: int = _mcts_default(
        "component_novelty_eval_max_tokens", 4096
    )
    mechanism_commit_retrieval_top_k: int = _mcts_default(
        "mechanism_commit_retrieval_top_k", 3
    )
    mechanism_commit_similarity_threshold: float = _mcts_default(
        "mechanism_commit_similarity_threshold", 0.6
    )
    theory_transfer_retrieval_top_k: int = _mcts_default(
        "theory_transfer_retrieval_top_k", 3
    )
    theory_transfer_similarity_threshold: float = _mcts_default(
        "theory_transfer_similarity_threshold", 0.4
    )
    enable_vector_memory: bool = _mcts_default("enable_vector_memory", True)
    enable_symbolic_memory: bool = _mcts_default("enable_symbolic_memory", True)
    min_confidence_for_memory: float = _mcts_default("min_confidence_for_memory", 0.6)
    pareto_top_k: int = _mcts_default("pareto_top_k", 5)
    alignment_weight: float = _mcts_default("alignment_weight", 0.15)
    complexity_weight: float = _mcts_default("complexity_weight", 0.05)
    novelty_weight: float = _mcts_default("novelty_weight", 0.20)
    surprise_weight: float = _mcts_default("surprise_weight", 0.10)
    impact_weight: float = _mcts_default("impact_weight", 0.18)
    feasibility_weight: float = _mcts_default("feasibility_weight", 0.11)
    clarity_weight: float = _mcts_default("clarity_weight", 0.06)
    conciseness_weight: float = _mcts_default("conciseness_weight", 0.03)
    risk_weight: float = _mcts_default("risk_weight", 0.09)
    protocol_weight: float = _mcts_default("protocol_weight", 0.03)
    explanatory_power_weight: float = _mcts_default("explanatory_power_weight", 0.06)
    identifiability_weight: float = _mcts_default("identifiability_weight", 0.06)
    boundary_calibration_weight: float = _mcts_default("boundary_calibration_weight", 0.04)
    claim_overreach_weight: float = _mcts_default("claim_overreach_weight", 0.10)

    symbolic_memory_path: str = _mcts_default(
        "symbolic_memory_path",
        _mcts_default("skill_prior_memory_path", "output/idea_skill_priors"),
    )
    skill_prior_success_threshold: float = _mcts_default(
        "skill_prior_success_threshold", 0.6
    )

def apply_idea_taste_preset(config: MCTSConfig) -> Optional[IdeaTastePreset]:
    raw_mode = getattr(config, "idea_taste_mode", None)
    preset = get_idea_taste_preset(raw_mode)
    if preset is None:
        apply_normalized_score_weights(config, SCORE_WEIGHT_FIELDS)
        config.idea_taste_mode = None
        return None

    for field_name in SCORE_WEIGHT_FIELDS:
        setattr(config, field_name, float(preset.weights[field_name]))
    apply_normalized_score_weights(config, SCORE_WEIGHT_FIELDS)
    config.idea_taste_mode = preset.mode
    return preset


@dataclass
class SearchCandidate:
    node: IdeaNode
    evaluation: IdeaEvaluation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea": self.node.state.to_payload(),
            "evaluation": self.evaluation.to_dict(),
            "score": self.evaluation.composite,
            "path": self.node.path_summary(),
        }


@dataclass
class SearchResult:
    best: Optional[SearchCandidate]
    pareto: Dict[str, Optional[SearchCandidate]]
    trace: List[Dict[str, Any]]
    cache_size: int
    experiences: List[Dict[str, Any]]
    retrieved_core_titles: List[str]


class VectorMemoryAccessor:
    def __init__(
        self,
        semantic_cfg: Optional[Dict[str, Any]] = None,
        episodic_cfg: Optional[Dict[str, Any]] = None,
        procedural_cfg: Optional[Dict[str, Any]] = None,
        llm_name: str = "gpt-5-mini",
        llm_backend: str = "openai",
        llm_provider: Optional[str] = None,
        logger: Optional[LoguruCompatLogger] = None,
    ) -> None:
        self.semantic_cfg = semantic_cfg or {}
        self.episodic_cfg = episodic_cfg or {}
        self.procedural_cfg = procedural_cfg or {}
        self.llm_name = str(llm_name or "gpt-5-mini")
        self.llm_backend = str(llm_backend or "openai")
        self.llm_provider = str(llm_provider or "").strip() or None
        self.logger = logger or module_logger
        self._stores: Dict[str, Optional[FAISSMemorySystem]] = {
            "semantic": None,
            "episodic": None,
            "procedural": None,
        }
        self._embedding_models: Dict[str, Any] = {}

    def _get_embedding_model(self, cfg: Dict[str, Any]) -> Any:
        model_path = str((cfg or {}).get("model_path") or ".cache/all-MiniLM-L6-v2").strip()
        resolved_model_path = resolve_workspace_path(model_path)
        cached_model = self._embedding_models.get(resolved_model_path)
        if cached_model is not None:
            return cached_model

        from sentence_transformers import SentenceTransformer

        embedding_model = SentenceTransformer(resolved_model_path)
        self._embedding_models[resolved_model_path] = embedding_model
        return embedding_model

    def _get_store(self, memory_type: str) -> Optional[FAISSMemorySystem]:
        if memory_type not in self._stores:
            return None
        if self._stores[memory_type] is None:
            cfg = {
                "semantic": self.semantic_cfg,
                "episodic": self.episodic_cfg,
                "procedural": self.procedural_cfg,
            }.get(memory_type, {})
            try:
                embedding_model = self._get_embedding_model(cfg)
                store_cfg = dict(cfg)
                if self.llm_provider and "llm_provider" not in store_cfg:
                    store_cfg["llm_provider"] = self.llm_provider
                self._stores[memory_type] = FAISSMemorySystem(
                    embedding_model=embedding_model,
                    memory_type=memory_type,
                    llm_name=self.llm_name,
                    llm_backend=self.llm_backend,
                    **store_cfg,
                )
            except Exception as exc:
                log_message(
                    self.logger,
                    None,
                    "warning",
                    "⚠️  Unable to initialize %s memory store: %s",
                    memory_type,
                    exc,
                )
                self._stores[memory_type] = None
        return self._stores[memory_type]

    def _query_store(
        self,
        store: FAISSMemorySystem,
        query: str,
        limit: int,
        prefix: str,
    ) -> List[MemorySnippet]:
        snippets: List[MemorySnippet] = []
        try:
            records_with_scores = store.query(
                query_text=query,
                method="embedding",
                limit=limit,
                agent_id="idea_agent",
                threshold=0.4,
            )
        except Exception as exc:
            log_message(
                self.logger,
                None,
                "warning",
                "⚠️  Memory query failed (%s): %s",
                prefix,
                exc,
            )
            return snippets

        for idx, (_, record) in enumerate(records_with_scores, start=1):
            if not record:
                continue
            identifier = f"{prefix}#{idx}"

            if isinstance(record, SemanticRecord):
                title = record.summary
                detail = record.detail
            elif isinstance(record, EpisodicRecord):
                title = record.summary
                detail = _safe_dump_str(record.detail)
            else:
                title = record.name
                detail = record.description

            snippets.append(
                MemorySnippet(
                    identifier=identifier,
                    title=(title or ""),
                    detail=str(detail),
                    tags=list(getattr(record, "tags", []) or []),
                )
            )
        return snippets

    def retrieve_bundle(self, query: str, limit: int = 3) -> MemoryBundle:
        bundle = MemoryBundle()
        semantic = self._get_store("semantic")
        episodic = self._get_store("episodic")
        procedural = self._get_store("procedural")

        if semantic:
            bundle.field_knowledge = self._query_store(semantic, query, limit, prefix="Field")
        if episodic:
            bundle.anti_patterns = self._query_store(episodic, query, limit, prefix="Pattern")
        if procedural:
            bundle.fix_recipes = self._query_store(procedural, query, limit, prefix="Recipe")

        return bundle

    def persist_experience(self, experience: Dict[str, Any], max_workers: int = 20) -> None:
        if not experience:
            return

        semantic = self._get_store("semantic")
        episodic = self._get_store("episodic")
        procedural = self._get_store("procedural")
        if not semantic and not episodic and not procedural:
            log_message(
                self.logger,
                None,
                "info",
                "ℹ️ Skipping persistence because semantic store is unavailable.",
            )
            return

        slot_process = SlotProcess(
            llm_name=self.llm_name,
            llm_backend=self.llm_backend,
            llm_provider=self.llm_provider,
        )
        try:
            working_slots = slot_process.transfer_idea_agent_context_to_working_slots(experience)
            log_message(
                self.logger,
                None,
                "info",
                "[MCTS] Transferred experience to working slots (count=%d)",
                len(working_slots),
            )
            _multi_thread_run(
                slot_process._multi_thread_filter_and_route_slot,
                working_slots,
                max_workers,
                show_progress=False,
            )
            _multi_thread_run(
                slot_process._multi_thread_transfer_slot_to_memory,
                slot_process.routed_slot_container,
                max_workers,
                show_progress=False,
            )
        except Exception as exc:
            log_message(
                self.logger,
                None,
                "warning",
                "⚠️  Failed to persist experience: %s",
                exc,
            )
            return

        semantic_records: List[SemanticRecord] = []
        episodic_records: List[EpisodicRecord] = []
        procedural_records: List[ProceduralRecord] = []
        for memory in slot_process.memory_dict:
            if memory["memory_type"] == "semantic" and semantic:
                semantic_records.append(semantic.instantiate_sem_record(**memory["input"]))
            elif memory["memory_type"] == "episodic" and episodic:
                episodic_records.append(episodic.instantiate_epi_record(**memory["input"]))
            elif memory["memory_type"] == "procedural" and procedural:
                procedural_records.append(procedural.instantiate_proc_record(**memory["input"]))

        if semantic and semantic_records:
            try:
                semantic.add(semantic_records, agent_id="idea_agent")
            except Exception as exc:
                log_message(self.logger, None, "warning", "⚠️  Failed to persist semantic records: %s", exc)
        if episodic and episodic_records:
            try:
                episodic.add(episodic_records, agent_id="idea_agent")
            except Exception as exc:
                log_message(self.logger, None, "warning", "⚠️  Failed to persist episodic records: %s", exc)
        if procedural and procedural_records:
            try:
                procedural.add(procedural_records, agent_id="idea_agent")
            except Exception as exc:
                log_message(self.logger, None, "warning", "⚠️  Failed to persist procedural records: %s", exc)


class MemoryGuidedMCTS:
    def __init__(
        self,
        chat_fn: Callable[..., str],
        evaluation_prompt: str,
        config: Optional[MCTSConfig] = None,
        memory_accessor: Optional[VectorMemoryAccessor] = None,
        paper_graph_vector_store: Optional[PaperGraphComponentVectorStore] = None,
        logger: Optional[LoguruCompatLogger] = None,
        log_sink: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.chat_fn = chat_fn
        self.evaluation_prompt = evaluation_prompt

        self.config = config or MCTSConfig()
        self.logger = logger or module_logger
        self.log_sink = log_sink
        self.enable_vector_memory = bool(self.config.enable_vector_memory)
        self.enable_symbolic_memory = bool(self.config.enable_symbolic_memory)
        self.memory_accessor = memory_accessor or VectorMemoryAccessor(logger=self.logger)
        component_model_path = resolve_workspace_path(
            self.config.component_novelty_model_path
        )
        self.paper_graph_vector_store = paper_graph_vector_store or PaperGraphComponentVectorStore(
            model_name_or_path=component_model_path,
            index_dir=self.config.component_novelty_index_dir or None,
        )
        self.component_novelty_scorer = ComponentNoveltyScorer(
            model_name_or_path=component_model_path,
            index_dir=self.config.component_novelty_index_dir or None,
            retrieval_top_k=self.config.component_novelty_retrieval_top_k,
            evidence_node_top_k=self.config.component_novelty_evidence_top_k,
            evaluation_model=(
                self.config.component_novelty_eval_model or self.config.evaluation_model
            ),
            evaluation_temperature=self.config.component_novelty_eval_temperature,
            evaluation_max_tokens=self.config.component_novelty_eval_max_tokens,
            chat_fn=self.chat_fn,
            logger=self.logger,
            log_sink=self.log_sink,
            vector_store=self.paper_graph_vector_store,
        )

        self.skill_catalog = SkillCatalog()
        self.symbolic_memory = SymbolicMemorySystem()
        self.symbolic_memory_path = Path(self.config.symbolic_memory_path)

        self._id_iter = itertools.count()
        self.signature_nodes: Dict[str, IdeaNode] = {}
        self.evaluation_cache: Dict[str, Dict[str, IdeaEvaluation]] = {}
        self.experience_cache: Set[str] = set()
        self.trace: List[Dict[str, Any]] = []
        self.retrieved_core_titles: List[str] = []

        self.topic: str = ""
        self.seed_id: str = str(getattr(self.config, "seed_id", "") or "").strip()
        self.route_id: str = str(getattr(self.config, "route_id", "") or "").strip()
        self.route_policy: Dict[str, Any] = {}
        self.mature_idea_record: Dict[str, Any] = {}
        self.analysis_blob: str = ""
        self.paper_context: str = ""
        self.mature_idea: str = ""
        self.refinement_scope: str = ""
        self.scientific_intervention_profile: Dict[str, Any] = {}
        self.gap_hypothesis_seeds: List[Dict[str, Any]] = []
        self.gap_seed_status: Dict[str, Any] = {}
        self.gap_seed_context: str = ""
        self.multimodal_evidence_projection: Dict[str, Any] = {}
        self.idea_taste_preset: Optional[IdeaTastePreset] = get_idea_taste_preset(
            getattr(self.config, "idea_taste_mode", None)
        )
        self._mature_idea_components: List[str] = []
        self._mature_idea_component_explanations: Dict[str, str] = {}
        self._component_novelty_fallback_logged = False
        self._mechanism_commit_retrieval_unavailable = False
        self.persist_symbolic_memory = True

        if self.enable_symbolic_memory:
            self.reload_symbolic_memory()

    def reload_symbolic_memory(self) -> None:
        """Reload the symbolic memory store from disk.

        The store is populated externally (e.g. from experiment ablation
        results or paper-graph conclusions) — not from within MCTS. Reloading
        clears the current in-memory store first so the active process always
        reflects the latest on-disk state.
        """
        if not self.enable_symbolic_memory:
            return
        self.symbolic_memory = SymbolicMemorySystem()
        try:
            if not self.symbolic_memory_path.exists():
                return
            self.symbolic_memory.load(str(self.symbolic_memory_path))
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Unable to load symbolic memory store: %s",
                exc,
            )

    def _skill_prior_for_prompt(self, skill_name: str) -> Dict[str, Any]:
        prior = self.skill_catalog.priors.get(skill_name, SkillUsagePrior())
        return prior.to_dict()

    def _compute_protocol_score(self, plan: Optional[Dict[str, Any]]) -> float:
        return compute_protocol_score_from_plan(plan)

    def _memory_bundle_log_payload(self, bundle: MemoryBundle) -> Dict[str, Any]:
        return memory_bundle_log_payload(bundle)

    def _simulate_log_payload(self, evaluation: IdeaEvaluation) -> Dict[str, Any]:
        return simulate_log_payload(evaluation)

    def _score_component_novelty(self, state: IdeaState) -> Optional[float]:
        try:
            return self.component_novelty_scorer.score(state=state, topic=self.topic)
        except Exception as exc:
            if not self._component_novelty_fallback_logged:
                log_message(
                    self.logger,
                    self.log_sink,
                    "warning",
                    "⚠️  Component novelty scorer unavailable (%s); falling back to LLM novelty.",
                    exc,
                )
                self._component_novelty_fallback_logged = True
            return None

    def _classify_root_discipline_resolution(
        self,
        topic: str,
        root_state: IdeaState,
    ) -> Dict[str, Any]:
        root_text = "\n".join(
            [
                root_state.title,
                root_state.abstract,
                root_state.core_contribution,
                root_state.method,
            ]
        )
        fallback = resolve_discipline_taxonomy(topic, query=root_text)
        if fallback.get("status") == "out_of_scope":
            return fallback
        prompt = ROOT_DOMAIN_CLASSIFICATION_PROMPT.format(
            topic=topic or "Unknown topic",
            root_idea=root_state.to_prompt_view(heading="Root Idea"),
            discipline_catalog=format_taxonomy_catalog_for_prompt(),
        )
        try:
            response = self.chat_fn(
                prompt,
                model=self.config.generation_model,
                temperature=0.01,
                max_output_tokens=65536,
            )
            payload = parse_json_response(response)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            if not isinstance(payload, dict):
                return fallback
            raw_domains = [payload.get("primary_discipline")]
            adjacent = payload.get("adjacent_disciplines")
            if isinstance(adjacent, list):
                raw_domains.extend(adjacent)
            legacy_domains = payload.get("domains")
            if isinstance(legacy_domains, list):
                raw_domains.extend(legacy_domains)
            normalized = _normalize_root_domains(raw_domains)
            allowed = set(fallback.get("discipline_ids") or [])
            allowed.update(fallback.get("adjacent_disciplines") or [])
            selected = [domain for domain in normalized if domain in allowed]
            if not selected:
                return fallback
            resolution = resolve_discipline_taxonomy(selected[0], query=root_text)
            if len(selected) > 1 and str(payload.get("status") or "").strip() == "ambiguous":
                resolution["status"] = "ambiguous"
                resolution["discipline_ids"] = selected[:2]
                resolution["adjacent_disciplines"] = [
                    domain for domain in selected[1:] if domain != selected[0]
                ]
            resolution["llm_selection"] = {
                "status": str(payload.get("status") or "").strip(),
                "confidence": payload.get("confidence"),
                "matched_terms": payload.get("matched_terms")
                if isinstance(payload.get("matched_terms"), list)
                else [],
            }
            return resolution
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Root-domain classification failed; using heuristic fallback: %s",
                exc,
            )
            return fallback

    def _classify_root_domains(self, topic: str, root_state: IdeaState) -> List[str]:
        resolution = self._classify_root_discipline_resolution(topic, root_state)
        return _normalize_root_domains(resolution.get("discipline_ids") or [])

    def _build_theory_transfer_query(
        self,
        plan: EditPlan,
        parent_state: IdeaState,
    ) -> Optional[Dict[str, str]]:
        prompt = get_theory_transfer_query_prompt(self.config.prompt_mode).format(
            topic=self.topic or "Unknown topic",
            root_domains=_format_root_domains_for_prompt(parent_state.root_domains),
            refinement_scope=self.refinement_scope or "None",
            idea=parent_state.to_prompt_view(heading="Current Idea"),
            edit_plan=pretty_json(plan.to_dict()),
        )
        empty_payload = {"query": "", "needed_content": "", "expected_role": ""}
        try:
            response = self.chat_fn(
                prompt,
                model=self.config.generation_model,
                temperature=0.2,
                max_output_tokens=65536,
            )
            payload = parse_json_response(response)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            normalized = normalize_theory_transfer_query_payload(
                payload,
                fallback=empty_payload,
                clip_limit=UNIFORM_CLIP_TEXT_LIMIT,
            )
            if not str(normalized.get("query") or "").strip():
                return None
            if self._query_payload_uses_forbidden_terms(normalized):
                return None
            return normalized
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Theory-transfer query generation failed; skipping paper-graph retrieval: %s",
                exc,
            )
            return None

    def _build_mechanism_commit_query(
        self,
        plan: EditPlan,
        parent_state: IdeaState,
    ) -> Optional[Dict[str, str]]:
        prompt = get_mechanism_commit_query_prompt(self.config.prompt_mode).format(
            topic=self.topic or "Unknown topic",
            root_domains=_format_root_domains_for_prompt(parent_state.root_domains),
            refinement_scope=self.refinement_scope or "None",
            idea=parent_state.to_prompt_view(heading="Current Idea"),
            edit_plan=pretty_json(plan.to_dict()),
        )
        empty_payload = {"query": "", "mechanism_gap": "", "expected_role": ""}
        try:
            response = self.chat_fn(
                prompt,
                model=self.config.generation_model,
                temperature=0.2,
                max_output_tokens=65536,
            )
            payload = parse_json_response(response)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            normalized = normalize_mechanism_commit_query_payload(
                payload,
                fallback=empty_payload,
                clip_limit=UNIFORM_CLIP_TEXT_LIMIT,
            )
            if not str(normalized.get("query") or "").strip():
                return None
            if self._query_payload_uses_forbidden_terms(normalized):
                return None
            return normalized
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Mechanism-commit query generation failed; skipping paper-graph retrieval: %s",
                exc,
            )
            return None

    def _query_payload_uses_forbidden_terms(self, payload: Dict[str, str]) -> bool:
        return any(
            text_uses_forbidden_query_terms(str(payload.get(field_name) or ""))
            for field_name in ("query", "mechanism_gap", "needed_content", "expected_role")
        )

    def _record_retrieved_core_titles(self, hits: List[Dict[str, Any]]) -> None:
        seen = {str(title).strip().lower() for title in self.retrieved_core_titles if str(title).strip()}
        for hit in hits:
            core_node = hit.get("core_node") if isinstance(hit.get("core_node"), dict) else {}
            title = str(
                core_node.get("paper_title")
                or core_node.get("title")
                or core_node.get("full_name")
                or core_node.get("label")
                or hit.get("node_id")
                or ""
            ).strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            self.retrieved_core_titles.append(title)

    def _retrieve_theory_transfer_references(
        self,
        query_payload: Dict[str, str],
        root_domains: List[str],
    ) -> List[Dict[str, Any]]:
        query = str(query_payload.get("query") or "").strip()
        if not query:
            return []
        try:
            search_pool = max(int(self.config.theory_transfer_retrieval_top_k) * 6, 12)
            hits = self.paper_graph_vector_store.search(
                query=query,
                top_k=search_pool,
                component_hits_per_core=2,
            )
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Theory-transfer paper-graph retrieval unavailable: %s",
                exc,
            )
            return []

        threshold = float(self.config.theory_transfer_similarity_threshold)
        blocked_domains = set(_normalize_root_domains(root_domains))
        filtered: List[Dict[str, Any]] = []
        for hit in hits:
            core_node = hit.get("core_node") if isinstance(hit.get("core_node"), dict) else {}
            paper_domain = str(core_node.get("paper_domain") or "").strip()
            paper_domain_key = canonicalize_discipline_key(paper_domain)
            if not paper_domain or (
                paper_domain_key and paper_domain_key in blocked_domains
            ):
                continue
            if float(hit.get("score") or 0.0) < threshold:
                continue
            filtered.append(hit)
            if len(filtered) >= int(self.config.theory_transfer_retrieval_top_k):
                break
        if filtered:
            rendered_hits: List[str] = []
            for idx, hit in enumerate(filtered, start=1):
                core_node = hit.get("core_node") if isinstance(hit.get("core_node"), dict) else {}
                paper_domain = str(core_node.get("paper_domain") or "").strip() or "unknown"
                label = (
                    str(core_node.get("full_name") or "").strip()
                    or str(core_node.get("label") or "").strip()
                    or str(core_node.get("node_id") or "").strip()
                    or f"core_{idx}"
                )
                paper_title = clip_text(str(core_node.get("paper_title") or "").strip(), 400)
                summary = clip_text(str(core_node.get("summary") or "").strip(), 1000)
                insight = clip_text(str(core_node.get("insight") or "").strip(), 1000)
                rendered_hits.append(
                    f"{idx}. {label} | domain={paper_domain} | score={float(hit.get('score') or 0.0):.3f}"
                )
                if paper_title:
                    rendered_hits.append(f"   title: {paper_title}")
                if summary:
                    rendered_hits.append(f"   summary: {summary}")
                if insight:
                    rendered_hits.append(f"   insight: {insight}")
            log_message(
                self.logger,
                self.log_sink,
                "info",
                "[MCTS] Theory-transfer eligible core nodes for query=%s\n%s",
                clip_text(query, 1000),
                "\n".join(rendered_hits),
            )
            self._record_retrieved_core_titles(filtered)
        return filtered

    def _retrieve_mechanism_commit_references(
        self,
        query_payload: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        query = str(query_payload.get("query") or "").strip()
        if not query:
            return []
        if getattr(self, "_mechanism_commit_retrieval_unavailable", False):
            return []
        try:
            search_pool = max(int(self.config.mechanism_commit_retrieval_top_k) * 6, 12)
            hits = self.paper_graph_vector_store.search(
                query=query,
                top_k=search_pool,
                component_hits_per_core=2,
            )
        except Exception as exc:
            log_message(
                self.logger,
                self.log_sink,
                "warning",
                "⚠️  Mechanism-commit paper-graph retrieval unavailable (%s); "
                "continuing without paper-graph grounding.",
                exc,
            )
            self._mechanism_commit_retrieval_unavailable = True
            return []
        threshold = float(self.config.mechanism_commit_similarity_threshold)
        filtered: List[Dict[str, Any]] = []
        for hit in hits:
            if float(hit.get("score") or 0.0) < threshold:
                continue
            filtered.append(hit)
            if len(filtered) >= int(self.config.mechanism_commit_retrieval_top_k):
                break
        if filtered:
            rendered_hits: List[str] = []
            for idx, hit in enumerate(filtered, start=1):
                core_node = hit.get("core_node") if isinstance(hit.get("core_node"), dict) else {}
                paper_domain = str(core_node.get("paper_domain") or "").strip() or "unknown"
                label = (
                    str(core_node.get("full_name") or "").strip()
                    or str(core_node.get("label") or "").strip()
                    or str(core_node.get("node_id") or "").strip()
                    or f"core_{idx}"
                )
                paper_title = clip_text(str(core_node.get("paper_title") or "").strip(), 400)
                summary = clip_text(str(core_node.get("summary") or "").strip(), 1000)
                insight = clip_text(str(core_node.get("insight") or "").strip(), 1000)
                rendered_hits.append(
                    f"{idx}. {label} | domain={paper_domain} | score={float(hit.get('score') or 0.0):.3f}"
                )
                if paper_title:
                    rendered_hits.append(f"   title: {paper_title}")
                if summary:
                    rendered_hits.append(f"   summary: {summary}")
                if insight:
                    rendered_hits.append(f"   insight: {insight}")
            log_message(
                self.logger,
                self.log_sink,
                "info",
                "[MCTS] Mechanism-commit grounding core nodes for query=%s\n%s",
                clip_text(query, 1000),
                "\n".join(rendered_hits),
            )
            self._record_retrieved_core_titles(filtered)
        return filtered

    def _materialize_child_state(
        self,
        parent_state: IdeaState,
        plan: EditPlan,
        instantiated: Optional[Dict[str, Any]] = None,
        selection_metadata: Optional[Dict[str, Any]] = None,
    ) -> IdeaState:
        return materialize_child_state(
            self,
            parent_state,
            plan,
            instantiated,
            selection_metadata=selection_metadata,
            idea_state_cls=IdeaState,
        )

    def _select(self, node: IdeaNode) -> Tuple[IdeaNode, List[IdeaNode]]:
        return select_leaf_for_rollout(self, node)

    def _instantiate_skill_plan(
        self,
        plan: EditPlan,
        parent_state: IdeaState,
        bundle: MemoryBundle,
    ) -> Optional[Dict[str, Any]]:
        root_domains_text = _format_root_domains_for_prompt(parent_state.root_domains)
        additional_retrieval_context = ""
        skip_payload: Optional[Dict[str, Any]] = None

        if plan.skill_name == "mechanism-commit-innovation":
            query_payload = self._build_mechanism_commit_query(plan, parent_state)
            if query_payload is not None:
                hits = self._retrieve_mechanism_commit_references(query_payload)
                if hits:
                    additional_retrieval_context = "\n".join(
                        [
                            "Mechanism-grounding retrieval query:",
                            query_payload.get("query") or "None",
                            format_mechanism_commit_references(
                                query_payload,
                                hits,
                                clip_limit=UNIFORM_CLIP_TEXT_LIMIT,
                            ),
                        ]
                    )
        elif plan.skill_name == "theory-transfer-injection":
            query_payload = self._build_theory_transfer_query(plan, parent_state)
            if query_payload is not None:
                hits = self._retrieve_theory_transfer_references(query_payload, parent_state.root_domains)
                if not hits:
                    skip_payload = {
                        "_skip_child_creation": True,
                        "_skip_reason": (
                            "theory-transfer-injection retrieved no eligible cross-domain core nodes "
                            f"(threshold={self.config.theory_transfer_similarity_threshold}, "
                            f"excluded_domains={parent_state.root_domains})"
                        ),
                    }
                else:
                    additional_retrieval_context = "\n".join(
                        [
                            "Cross-domain transfer query:",
                            query_payload.get("query") or "None",
                            format_theory_transfer_references(
                                query_payload,
                                hits,
                                clip_limit=UNIFORM_CLIP_TEXT_LIMIT,
                            ),
                        ]
                    )

        if skip_payload is not None:
            return skip_payload

        payload = instantiate_skill_plan_for_node(
            self,
            plan,
            parent_state,
            bundle,
            prompt_template=get_skill_instantiation_prompt(
                self.config.prompt_mode,
                profile_id=str(
                    (getattr(parent_state, "scientific_intervention", {}) or {}).get("profile_id")
                    or "generic_scientific"
                ),
            ),
            root_domains_text=root_domains_text,
            additional_retrieval_context=additional_retrieval_context,
        )
        if plan.skill_name == "theory-transfer-injection":
            if not isinstance(payload, dict):
                return {
                    "_skip_child_creation": True,
                    "_skip_reason": "theory-transfer-injection instantiation returned no structured payload",
                }
            payload.pop("_paper_graph_context", None)
            payload["_paper_graph_context"] = additional_retrieval_context
        if (
            plan.skill_name == "mechanism-commit-innovation"
            and isinstance(payload, dict)
            and not parent_centers_control_surface(parent_state)
        ):
            rendered = "\n".join(
                str(payload.get(field_name) or "")
                for field_name in ("title", "abstract", "core_contribution", "method", "rationale")
            )
            if text_uses_forbidden_query_terms(rendered):
                return {
                    "_skip_child_creation": True,
                    "_skip_reason": (
                        "mechanism-commit-innovation instantiated a threshold/gating/suppression/quota-style "
                        "patch for a parent idea that is not control-centered"
                    ),
                }
        if plan.skill_name == "mechanism-commit-innovation" and isinstance(payload, dict):
            payload.pop("_paper_graph_context", None)
            payload["_paper_graph_context"] = additional_retrieval_context
        return payload

    def _expand(self, node: IdeaNode, path: List[IdeaNode]) -> Tuple[Optional[IdeaNode], List[IdeaNode]]:
        return expand_node_with_skills(
            self,
            node,
            path,
            min_components=MIN_COMPONENTS,
            max_components=MAX_COMPONENTS,
        )


    def _build_symbolic_eval_hints(self, node: IdeaNode) -> str:
        return build_symbolic_eval_hints(self, node)

    def _simulate(
        self,
        node: IdeaNode,
        path: List[IdeaNode],
        experiences: List[Dict[str, Any]],
    ) -> Optional[IdeaEvaluation]:
        return simulate_node_value(
            self,
            node,
            path,
            experiences,
            idea_evaluation_cls=IdeaEvaluation,
        )

    def _update_skill_prior(self, node: IdeaNode, evaluation: IdeaEvaluation) -> None:
        update_skill_prior_from_evaluation(self, node, evaluation)

    def _backpropagate(self, path: List[IdeaNode], evaluation: IdeaEvaluation) -> None:
        backpropagate_rollout(path, evaluation)

    def _extract_mature_idea_components(
        self,
        mature_idea: str,
        topic: str,
        *,
        prior_components: Optional[List[str]] = None,
        prior_component_explanations: Optional[Dict[str, str]] = None,
        component_decisions: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[str], Dict[str, str]]:
        return extract_mature_idea_components_via_llm(
            self,
            mature_idea,
            topic,
            prompt_template=render_component_extraction_prompt(
                str(self.scientific_intervention_profile.get("profile_id") or "")
            ),
            max_components=MAX_COMPONENTS,
            prior_components=prior_components,
            prior_component_explanations=prior_component_explanations,
            component_decisions=component_decisions,
        )

    def _resolve_prior_component_context(
        self,
        prepared: Dict[str, Any],
    ) -> Tuple[List[str], Dict[str, str], List[Dict[str, Any]]]:
        prior_components = (
            [str(component).strip() for component in prepared.get("prior_components", []) if str(component).strip()]
            if isinstance(prepared.get("prior_components"), list)
            else []
        )
        prior_component_explanations = (
            prepared.get("prior_component_explanations")
            if isinstance(prepared.get("prior_component_explanations"), (dict, list))
            else {}
        )
        component_decisions = (
            [decision for decision in prepared.get("component_decisions", []) if isinstance(decision, dict)]
            if isinstance(prepared.get("component_decisions"), list)
            else []
        )
        if not prior_components:
            for entry_key in ("latest_candidate", "root_idea"):
                entry = prepared.get(entry_key)
                if not isinstance(entry, dict):
                    continue
                raw_components = entry.get("components")
                if not isinstance(raw_components, list):
                    continue
                prior_components = [
                    str(component).strip()
                    for component in raw_components
                    if str(component).strip()
                ]
                if prior_components:
                    if not prior_component_explanations:
                        raw_explanations = entry.get("component_explanations")
                        if isinstance(raw_explanations, (dict, list)):
                            prior_component_explanations = raw_explanations
                    break
        normalized_prior_explanations = normalize_component_explanations(
            prior_components,
            prior_component_explanations,
        )
        return prior_components, normalized_prior_explanations, component_decisions

    def prepare_root_context(self, topic: str, context: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(context or {})
        self.multimodal_evidence_projection = (
            dict(prepared.get("multimodal_evidence_projection"))
            if isinstance(prepared.get("multimodal_evidence_projection"), dict)
            else {}
        )
        survey_handoff = prepared.get("survey_idea_handoff")
        self.survey_idea_handoff = (
            dict(survey_handoff) if isinstance(survey_handoff, dict) else {}
        )
        gap_triage = (
            dict(self.survey_idea_handoff.get("gap_triage") or {})
            if isinstance(self.survey_idea_handoff.get("gap_triage"), dict)
            else {}
        )
        triage_rows = [
            row for row in (gap_triage.get("gaps", []) if gap_triage else [])
            if isinstance(row, dict) and str(row.get("gap_id") or "").strip()
        ]
        triage_by_id = {str(row["gap_id"]).strip(): row for row in triage_rows}
        active_gap_ids = {
            gap_id for gap_id, row in triage_by_id.items()
            if str(row.get("eligibility_route") or "") in {
                "core_hypothesis", "provisional_hypothesis", "exploratory_frontier"
            }
        }
        prepared["gap_triage"] = gap_triage
        prepared["active_gaps"] = [
            row for row in triage_rows if str(row.get("gap_id")) in active_gap_ids
        ]
        prepared["provisional_gaps"] = [
            row for row in triage_rows
            if str(row.get("eligibility_route") or "") in {"provisional_hypothesis", "exploratory_frontier"}
        ]
        prepared["supporting_constraints"] = [
            row for row in triage_rows if str(row.get("eligibility_route") or "") == "supporting_constraint"
        ]
        prepared["verification_only_gaps"] = [
            row for row in triage_rows if str(row.get("eligibility_route") or "") == "verification_only"
        ]
        prepared["future_work_seeds"] = [
            row for row in triage_rows if str(row.get("eligibility_route") or "") == "future_work_seed"
        ]
        prepared["excluded_gaps"] = [
            row for row in triage_rows if str(row.get("eligibility_route") or "") == "exclude"
        ]
        handoff_gap_by_id = {
            str(gap.get("gap_id") or "").strip(): gap
            for gap in (self.survey_idea_handoff.get("gaps", []) if self.survey_idea_handoff else [])
            if isinstance(gap, dict) and str(gap.get("gap_id") or "").strip()
        }
        routing_labels = (
            ("active_gaps", "Core or active hypothesis gaps"),
            ("provisional_gaps", "Provisional exploratory gaps"),
            ("supporting_constraints", "Supporting scientific constraints"),
            ("verification_only_gaps", "Verification-only gaps"),
            ("future_work_seeds", "Future-work hypothesis seeds"),
        )
        routing_lines = ["== Survey Gap Routing (authoritative) =="]
        for key, label in routing_labels:
            rows = prepared.get(key, [])
            statements = [
                str(handoff_gap_by_id.get(str(row.get("gap_id") or ""), {}).get("statement") or "").strip()
                for row in rows[:5]
                if isinstance(row, dict)
            ]
            if statements:
                routing_lines.append(f"{label}: " + " | ".join(statement for statement in statements if statement))
        routing_lines.append("Do not turn verification-only or supporting constraints into primary novelty. Future-work items are exploratory seeds, not established evidence.")
        prepared["gap_routing_context"] = "\n".join(routing_lines)
        handoff_profile_resolution = (
            dict(self.survey_idea_handoff.get("profile_resolution") or {})
            if self.survey_idea_handoff
            and isinstance(self.survey_idea_handoff.get("profile_resolution"), dict)
            else {}
        )
        profile_hint = str(handoff_profile_resolution.get("profile_id_hint") or "").strip()
        if profile_hint:
            handoff_profile_resolution["profile_id"] = profile_hint
        handoff_defect_tags = []
        raw_handoff_gaps = (
            self.survey_idea_handoff.get("gaps", [])
            if self.survey_idea_handoff
            else []
        )
        for raw_gap in raw_handoff_gaps:
            if not isinstance(raw_gap, dict):
                continue
            gap_id = str(raw_gap.get("gap_id") or "").strip()
            route = str(triage_by_id.get(gap_id, {}).get("eligibility_route") or "")
            if route in {"supporting_constraint", "verification_only", "exclude"}:
                continue
            raw_tags = raw_gap.get("candidate_defect_tags", [])
            values = raw_tags if isinstance(raw_tags, list) else [raw_tags]
            handoff_defect_tags.extend(str(tag).strip() for tag in values if str(tag).strip())
        if handoff_defect_tags:
            existing_tags = prepared.get("defect_tags", [])
            existing_values = existing_tags if isinstance(existing_tags, list) else [existing_tags]
            prepared["defect_tags"] = _dedupe_keep_order_strings(
                [*existing_values, *handoff_defect_tags]
            )
        elif raw_handoff_gaps and not gap_triage and not prepared.get("active_gaps"):
            # Fail-open floor: a deterministic open gap must remain available
            # even when triage cannot establish a stronger route.
            fallback_gap = next(
                (gap for gap in raw_handoff_gaps if isinstance(gap, dict)), None
            )
            if fallback_gap:
                prepared["defect_tags"] = _dedupe_keep_order_strings(
                    [
                        *([str(value) for value in (prepared.get("defect_tags") or [])] if isinstance(prepared.get("defect_tags"), list) else []),
                        *([str(value) for value in (fallback_gap.get("candidate_defect_tags") or [])] if isinstance(fallback_gap.get("candidate_defect_tags"), list) else []),
                        str(fallback_gap.get("gap_kind") or "unexplored_gap"),
                    ]
                )
        base_paper_context = prepared.get("paper_context") or "No curated papers available yet."
        self.paper_context = str(base_paper_context) + "\n\n" + prepared["gap_routing_context"]
        prepared["paper_context"] = self.paper_context
        prepared["refinement_scope"] = str(prepared.get("refinement_scope") or "").strip()
        project_context = (
            prepared.get("project_context")
            if isinstance(prepared.get("project_context"), dict)
            else None
        )
        project_resolution = normalize_project_context_discipline_resolution(project_context)
        if project_resolution:
            prepared["project_context_discipline_resolution"] = project_resolution
        early_root_domains = _normalize_root_domains(prepared.get("root_domains") or [])
        explicit_handoff_fields = handoff_profile_resolution.get("openalex_field_ids") or handoff_profile_resolution.get(
            "paperseek_field_ids"
        )
        early_resolution = (
            handoff_profile_resolution
            if handoff_profile_resolution and explicit_handoff_fields
            else prepared.get("discipline_resolution")
        )
        early_profile = resolve_scientific_intervention_profile(
            early_resolution if isinstance(early_resolution, dict) else {},
            root_domains=early_root_domains,
            project_context=project_context,
        )
        if early_profile is not None:
            self.scientific_intervention_profile = early_profile.to_payload()
        mature_record = prepared.get("mature_idea_record")
        if isinstance(mature_record, dict):
            self.mature_idea_record = normalize_mature_idea(mature_record)
            prepared["mature_idea_record"] = dict(self.mature_idea_record)
        else:
            self.mature_idea_record = {}
        mature_idea_value = prepared.get("mature_idea")
        if isinstance(mature_idea_value, dict):
            self.mature_idea_record = normalize_mature_idea(mature_idea_value)
            prepared["mature_idea_record"] = dict(self.mature_idea_record)
            mature_idea = str(
                self.mature_idea_record.get("hypothesis")
                or self.mature_idea_record.get("abstract")
                or self.mature_idea_record.get("title")
                or ""
            ).strip()
        else:
            mature_idea = str(mature_idea_value or "").strip()
        if mature_idea:
            prepared["mature_idea"] = mature_idea
        components = prepared.get("components")
        prior_components, prior_component_explanations, component_decisions = (
            self._resolve_prior_component_context(prepared)
        )
        if mature_idea and not isinstance(components, list):
            components, explanations = self._extract_mature_idea_components(
                mature_idea,
                topic,
                prior_components=prior_components,
                prior_component_explanations=prior_component_explanations,
                component_decisions=component_decisions,
            )
            if components:
                prepared["components"] = components
                prepared["component_explanations"] = explanations

        handoff_root_domains = _normalize_root_domains(
            handoff_profile_resolution.get("discipline_ids") or []
        )
        project_root_domains = _normalize_root_domains(
            project_resolution.get("discipline_ids") or []
        )
        handoff_has_explicit_scope = bool(explicit_handoff_fields or handoff_root_domains)
        project_has_explicit_scope = bool(
            project_resolution.get("paperseek_openalex_field_ids")
            or project_root_domains
        )
        root_domains = handoff_root_domains or project_root_domains or _normalize_root_domains(
            prepared.get("root_domains") or []
        )
        if handoff_has_explicit_scope:
            resolution = dict(handoff_profile_resolution)
            resolution["discipline_ids"] = root_domains
            if root_domains:
                resolution["primary_discipline"] = root_domains[0]
        elif project_has_explicit_scope:
            resolution = dict(project_resolution)
            resolution["discipline_ids"] = project_root_domains
            if project_root_domains:
                resolution["primary_discipline"] = project_root_domains[0]
        elif not root_domains:
            draft_root_state = build_root_state(topic, prepared, IdeaState)
            resolution = self._classify_root_discipline_resolution(topic, draft_root_state)
            root_domains = _normalize_root_domains(resolution.get("discipline_ids") or [])
        else:
            resolution = resolve_discipline_taxonomy(
                root_domains[0],
                query="\n".join(
                    [
                        topic,
                        str(prepared.get("mature_idea") or ""),
                        str(prepared.get("paper_context") or ""),
                    ]
                ),
            )
            resolution["discipline_ids"] = root_domains
        prepared["root_domains"] = root_domains
        prepared["discipline_resolution"] = resolution
        profile_resolution = dict(resolution)
        existing_intervention = prepared.get("scientific_intervention")
        if isinstance(existing_intervention, dict) and existing_intervention.get("profile_id"):
            profile_resolution.setdefault("profile_id", existing_intervention.get("profile_id"))
        profile = resolve_scientific_intervention_profile(
            profile_resolution,
            root_domains=root_domains,
            project_context=project_context,
        )
        prepared["scientific_intervention_profile"] = (
            profile.to_payload()
            if profile is not None
            else {"schema_version": "scientific_intervention_profile_v1", "status": "out_of_scope"}
        )
        self.scientific_intervention_profile = dict(prepared["scientific_intervention_profile"])
        gap_hypothesis_seeds = build_gap_hypothesis_seeds(
            self.survey_idea_handoff,
            gap_triage,
            profile_resolution=prepared["scientific_intervention_profile"],
            scope=prepared.get("scope") if isinstance(prepared.get("scope"), dict) else None,
            topic=topic,
            multimodal_evidence_projection=self.multimodal_evidence_projection,
        )
        gap_seed_status = build_gap_seed_status(gap_hypothesis_seeds)
        gap_seed_context = build_gap_seed_context(gap_hypothesis_seeds)
        prepared["gap_hypothesis_seeds"] = gap_hypothesis_seeds
        prepared["gap_seed_status"] = gap_seed_status
        prepared["gap_seed_context"] = gap_seed_context
        self.gap_hypothesis_seeds = gap_hypothesis_seeds
        self.gap_seed_status = gap_seed_status
        self.gap_seed_context = gap_seed_context
        return prepared

    def search(self, topic: str, context: Dict[str, Any]) -> SearchResult:
        reset_search_state(self)
        context = self.prepare_root_context(topic, context)
        self.topic = topic
        self.analysis_blob = format_analysis_blob(context.get("analysis", []))
        self.paper_context = context.get("paper_context") or "No curated papers available yet."
        mature_value = context.get("mature_idea")
        if isinstance(mature_value, dict):
            self.mature_idea_record = normalize_mature_idea(mature_value)
            self.mature_idea = str(
                self.mature_idea_record.get("hypothesis")
                or self.mature_idea_record.get("abstract")
                or self.mature_idea_record.get("title")
                or ""
            ).strip()
        else:
            self.mature_idea = str(mature_value or "").strip()
        self.seed_id = str(context.get("seed_id") or context.get("idea_id") or self.seed_id or "").strip()
        self.route_id = str(context.get("route_id") or self.route_id or "").strip()
        self.route_policy = (
            dict(context.get("route_policy"))
            if isinstance(context.get("route_policy"), dict)
            else {}
        )
        self.refinement_scope = (context.get("refinement_scope") or "").strip()
        self._mature_idea_components = list(context.get("components") or [])
        self._mature_idea_component_explanations = dict(context.get("component_explanations") or {})
        raw_iteration_budget = context.get("mcts_iteration_budget")
        try:
            effective_iterations = int(raw_iteration_budget)
        except (TypeError, ValueError):
            effective_iterations = self.config.max_iterations
        effective_iterations = max(0, min(self.config.max_iterations, effective_iterations))
        try:
            depth_multiplier = float(context.get("data_anchored_mcts_depth_multiplier", 1.0))
        except (TypeError, ValueError):
            depth_multiplier = 1.0
        effective_max_depth = max(
            1,
            int(math.ceil(self.config.max_depth * max(1.0, depth_multiplier))),
        )
        root_domains = context.get("root_domains") or []
        log_message(
            self.logger,
            self.log_sink,
            "info",
            "[MCTS] Root-domain classification: %s",
            _format_root_domains_for_prompt(root_domains),
        )

        root_state = build_root_state(topic, context, IdeaState)
        root = new_node(
            root_state,
            depth=0,
            parent=None,
            signature_nodes=self.signature_nodes,
            id_iter=self._id_iter,
            idea_node_cls=IdeaNode,
            operator_application_cls=OperatorApplication,
        )
        experiences: List[Dict[str, Any]] = []

        # Prime root defects via one evaluator pass before the first expand so
        # initial skill selection is not forced to rely on the placeholder
        # "unexplored_gap" defect tag.
        root_eval = self._simulate(root, [root], experiences)
        if root_eval and root_eval.detected_defects:
            inferred_defects = _dedupe_keep_order_strings(
                [str(tag) for tag in root_eval.detected_defects if str(tag).strip()]
            )
            if inferred_defects:
                previous_defects = list(root.state.target_defects)
                root.state.target_defects = _dedupe_keep_order_strings(
                    [*previous_defects, *inferred_defects]
                )
                root.transformation.defects = list(root.state.target_defects)
                root.latest_path_summary = ""

        def _record_rollout(iteration: int, target: IdeaNode, rollout_path: List[IdeaNode], evaluation: IdeaEvaluation) -> None:
            self._backpropagate(rollout_path, evaluation)
            self._update_skill_prior(target, evaluation)

            rollout_summary = path_summary(rollout_path)
            transformation = target.transformation
            defects = list(transformation.defects) if transformation and transformation.defects else []
            operator = transformation.operator if transformation else "unknown"
            action_summary = f"{operator} -> {', '.join(defects) if defects else 'unspecified_defect'}"

            self.trace.append(
                {
                    "iteration": iteration,
                    "node_id": target.node_id,
                    "depth": len(rollout_path) - 1,
                    "title": target.state.title,
                    "operator": operator,
                    "defects": defects,
                    "memory_refs": list(transformation.memory_refs) if transformation else [],
                    "rationale": transformation.rationale if transformation else "",
                    "score": evaluation.composite,
                    "visits": target.visits,
                    "path": rollout_summary,
                    "action_summary": action_summary,
                    "evaluation": {**evaluation.to_dict(), "composite": evaluation.composite},
                    "signature": target.state.signature,
                    "edit_plan": target.state.edit_plan,
                    "skill_metrics": target.state.skill_metrics,
                    "data_anchored_coverage_branch": (
                        dict(
                            target.state.scientific_intervention.get(
                                "data_anchored_coverage_branch"
                            )
                            or {}
                        )
                        if isinstance(target.state.scientific_intervention, dict)
                        else {}
                    ),
                }
            )

        for iteration in iter_with_progress(
            range(effective_iterations),
            description="MCTS search",
            total=effective_iterations,
        ):
            leaf, path = self._select(root)
            depth = len(path) - 1
            rollout_targets: List[Tuple[IdeaNode, List[IdeaNode]]] = []

            if depth >= effective_max_depth:
                rollout_targets = [(leaf, path)]
            else:
                target, rollout_path = self._expand(leaf, path)
                if depth <= 1:
                    rollout_targets = [
                        (child, path + [child])
                        for child in leaf.children
                        if child.visits == 0
                    ]
                elif target is not None:
                    rollout_targets = [(target, rollout_path)]

            for target, rollout_path in rollout_targets:
                evaluation = self._simulate(target, rollout_path, experiences)
                if evaluation is None:
                    continue
                _record_rollout(iteration, target, rollout_path, evaluation)

        best = best_candidate(root, SearchCandidate)
        pareto = pareto_candidates(root, SearchCandidate)
        cache_entries = sum(len(entries) for entries in self.evaluation_cache.values())

        # Persist injected symbolic priors to disk so they survive across runs
        if self.enable_symbolic_memory and self.persist_symbolic_memory:
            try:
                self.symbolic_memory_path.parent.mkdir(parents=True, exist_ok=True)
                self.symbolic_memory.save(str(self.symbolic_memory_path))

            except Exception as exc:
                log_message(
                    self.logger,
                    self.log_sink,
                    "warning",
                    "⚠️  Failed to save symbolic memory: %s",
                    exc,
                )

        return SearchResult(
            best=best,
            pareto=pareto,
            trace=self.trace,
            cache_size=cache_entries,
            experiences=experiences,
            retrieved_core_titles=list(self.retrieved_core_titles),
        )
