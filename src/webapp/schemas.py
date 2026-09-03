"""Public request and response schemas for the web control plane."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


QuantitativeMode = Literal["off", "optional", "required"]
RunActionType = Literal[
    "start_workflow",
    "resume_science",
    "cancel_science",
    "resume_quantitative",
    "prepare_quantitative_blueprint",
    "discover_parameters",
    "fetch_open_access_fulltext",
    "register_parameter_material",
    "extract_parameters",
    "propose_parameters",
    "approve_parameters",
    "materialize_plan",
    "execute_plan",
    "qualify_result",
    "propose_refinement",
    "accept_refinement",
    "finalize_quantitative_idea",
    "publish_quantitative_models",
    "build_quantitative_author_handoff",
    "continue_author",
]
MaterialScope = Literal["survey_evidence", "parameter_source", "context_only", "do_not_send"]
MaterialModality = Literal[
    "image",
    "table",
    "signal",
    "audio",
    "video",
    "threeD",
    "trajectory",
    "text",
    "symbolic",
    "molecule",
]


class StrictModel(BaseModel):
    """Reject browser fields that are not part of the public contract."""

    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(StrictModel):
    topic: str = Field(min_length=8, max_length=8_000)
    discipline_ids: list[str] = Field(default_factory=list, min_length=1, max_length=2)
    run_id: str | None = Field(default=None, max_length=128)
    language: Literal["zh-CN", "en"] = "zh-CN"
    minimum_pages: int = Field(default=7, ge=7, le=80)
    quantitative_mode: QuantitativeMode = "off"
    allow_remote_perception: bool = False

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("topic cannot be blank")
        return normalized

    @field_validator("discipline_ids")
    @classmethod
    def normalize_disciplines(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("discipline_ids must not contain duplicates")
        return normalized


class MaterialMetadata(StrictModel):
    label: str = Field(default="", max_length=256)
    scope: MaterialScope = "context_only"
    modality: MaterialModality | None = None
    contains_sensitive_data: bool = False
    group: str = Field(default="", max_length=256)
    condition: str = Field(default="", max_length=256)
    timepoint: str = Field(default="", max_length=256)


class ScienceWorkflowAction(StrictModel):
    type: Literal["start_workflow", "resume_science"]
    until: Literal["survey", "idea", "exp_design", "author"] = "author"


class CancelScienceAction(StrictModel):
    type: Literal["cancel_science"]


class ResumeQuantitativeAction(StrictModel):
    type: Literal["resume_quantitative"]


class QuantitativeTargetAction(StrictModel):
    idea_id: Literal["Q1", "Q2"]
    version: int = Field(ge=0, le=2)


class PrepareQuantitativeBlueprintAction(QuantitativeTargetAction):
    type: Literal["prepare_quantitative_blueprint"]


class DiscoverParametersAction(QuantitativeTargetAction):
    type: Literal["discover_parameters"]
    network_authorized: Literal[True]


class FetchOpenAccessFulltextAction(QuantitativeTargetAction):
    type: Literal["fetch_open_access_fulltext"]
    network_authorized: Literal[True]


class RegisterParameterMaterialAction(QuantitativeTargetAction):
    type: Literal["register_parameter_material"]
    material_id: str = Field(min_length=8, max_length=96, pattern=r"^mat-[a-f0-9]{32}$")


class ExtractParametersAction(QuantitativeTargetAction):
    type: Literal["extract_parameters"]
    document_id: str = Field(min_length=3, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")


ParameterProvenanceStatus = Literal[
    "APPROVED_LITERATURE_SINGLE_SOURCE",
    "APPROVED_USER_INPUT",
    "APPROVED_MODEL_ASSUMPTION",
]


class ParameterSelection(StrictModel):
    parameter_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    candidate_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    provenance_status: ParameterProvenanceStatus | None = None
    selected_value: float | None = None
    selection_rationale: str = Field(min_length=3, max_length=1_500)

    @field_validator("selected_value")
    @classmethod
    def finite_selected_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("selected_value must be finite")
        return value


class ProposeParametersAction(QuantitativeTargetAction):
    type: Literal["propose_parameters"]
    selections: list[ParameterSelection] = Field(min_length=1, max_length=64)

    @field_validator("selections")
    @classmethod
    def unique_parameter_selections(cls, values: list[ParameterSelection]) -> list[ParameterSelection]:
        parameter_ids = [selection.parameter_id for selection in values]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("selections must contain one entry per parameter_id")
        return values


class ApproveParametersAction(QuantitativeTargetAction):
    type: Literal["approve_parameters"]
    approved: Literal[True]


class MaterializePlanAction(QuantitativeTargetAction):
    type: Literal["materialize_plan"]


class ExecutePlanAction(QuantitativeTargetAction):
    type: Literal["execute_plan"]
    confirmed: Literal[True]
    plan_identity: str = Field(min_length=16, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")


class QualifyResultAction(QuantitativeTargetAction):
    type: Literal["qualify_result"]
    execution_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    hypothesis_relation: Literal[
        "SUPPORTED_WITHIN_MODEL",
        "CONSTRAINED",
        "REFUTED_WITHIN_MODEL",
        "INCONCLUSIVE",
    ]
    result_summary: str = Field(min_length=8, max_length=4_000)


class ProposeRefinementAction(QuantitativeTargetAction):
    type: Literal["propose_refinement"]
    revision_reason: str = Field(min_length=8, max_length=2_000)
    hypothesis_delta: str = Field(min_length=8, max_length=2_000)
    model_delta: list[str] = Field(min_length=1, max_length=16)
    parameter_or_boundary_delta: list[str] = Field(min_length=1, max_length=16)
    expected_discriminating_result: str = Field(min_length=8, max_length=2_000)
    falsification_condition: str = Field(min_length=8, max_length=2_000)

    @field_validator("model_delta", "parameter_or_boundary_delta")
    @classmethod
    def bounded_delta_items(cls, values: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1_000 for item in values):
            raise ValueError("revision delta entries must contain at most 1,000 characters")
        return values


class AcceptRefinementAction(QuantitativeTargetAction):
    type: Literal["accept_refinement"]
    accepted: Literal[True]


class FinalizeQuantitativeIdeaAction(QuantitativeTargetAction):
    type: Literal["finalize_quantitative_idea"]


class PublishQuantitativeModelsAction(StrictModel):
    type: Literal["publish_quantitative_models"]


class BuildQuantitativeAuthorHandoffAction(StrictModel):
    type: Literal["build_quantitative_author_handoff"]


class ContinueAuthorAction(StrictModel):
    type: Literal["continue_author"]


RunActionRequest = Annotated[
    Union[
        ScienceWorkflowAction,
        CancelScienceAction,
        ResumeQuantitativeAction,
        PrepareQuantitativeBlueprintAction,
        DiscoverParametersAction,
        FetchOpenAccessFulltextAction,
        RegisterParameterMaterialAction,
        ExtractParametersAction,
        ProposeParametersAction,
        ApproveParametersAction,
        MaterializePlanAction,
        ExecutePlanAction,
        QualifyResultAction,
        ProposeRefinementAction,
        AcceptRefinementAction,
        FinalizeQuantitativeIdeaAction,
        PublishQuantitativeModelsAction,
        BuildQuantitativeAuthorHandoffAction,
        ContinueAuthorAction,
    ],
    Field(discriminator="type"),
]


class ResolveDisciplineRequest(StrictModel):
    topic: str = Field(min_length=3, max_length=8_000)

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("topic cannot be blank")
        return normalized


class RunEventView(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    payload: dict[str, object]


class RunLogView(BaseModel):
    log_id: str
    label: str
    stage: str
    attempt: int | None = None
    format: Literal["jsonl", "text"]
    size_bytes: int


class RunLogChunkView(BaseModel):
    log_id: str
    format: Literal["jsonl", "text"]
    offset: int = Field(ge=0)
    next_offset: int = Field(ge=0)
    has_more: bool
    content: str


class RepresentativeFileView(BaseModel):
    file_id: str
    label: str
    kind: Literal["image", "pdf", "log"]
    media_type: str
    size_bytes: int
    url: str


class RepresentativeProjectView(BaseModel):
    project_id: str
    title: str
    discipline: str
    summary: str
    cover_url: str | None = None
    files: list[RepresentativeFileView]
    pdf_count: int
    image_count: int
    log_count: int


class ArtifactView(BaseModel):
    artifact_id: str
    label: str
    stage: str
    media_type: str
    previewable: bool
    size_bytes: int


class RunView(BaseModel):
    run_id: str
    topic: str
    created_at: str
    last_updated_at: str
    status: str
    execution_mode: str
    discipline_ids: list[str]
    quantitative_mode: QuantitativeMode
    language: str
    remote_perception_authorized: bool
    stages: dict[str, dict[str, object]]
    materials: list[dict[str, object]]
    allowed_actions: list[RunActionType]
    next_step: str
    cancellation: dict[str, object] | None = None
    event_url: str
    artifacts: list[ArtifactView]
    quantitative: dict[str, object] | None = None


class MaterialUploadResponse(BaseModel):
    """Material records and the refreshed run snapshot consumed by the web client."""

    materials: list[dict[str, object]]
    run: RunView
