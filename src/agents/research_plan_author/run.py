"""Batch-A preparation entrypoint for the English-only Research Plan Author."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from copy import deepcopy
from collections.abc import Callable, Mapping
from typing import Any

from .authoring_blueprint import AuthoringBlueprintError, AuthoringBlueprintPlanner
from .contract_repair import AuthorContractRepairError
from .contracts import (
    AUTHORING_LANGUAGE,
    AUTHOR_PREPARATION_SCHEMA_VERSION,
    build_research_plan_document_skeleton,
)
from .idea_evolution import (
    IdeaEvolutionError,
    disabled_idea_evolution,
    project_idea_evolution,
    unavailable_idea_evolution,
)
from .input_loader import AuthorInputLoadError, load_author_input_with_identity
from .run_logging import AuthorRunLogger
from .section_composer import SectionComposer, SectionCompositionError
from .section_router import route_author_sections
from .semantic_validator import validate_composed_research_plan
from .source_bundle import build_author_source_bundle
from .source_registry import build_frozen_source_registry, source_registry_for_blueprint_section
from .survey_source_loader import SurveyAuthorSourceError, load_verified_survey_sources


class AuthorRunError(RuntimeError):
    """Typed Author preparation failure with a stage for CLI reporting."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


class AuthorCompositionError(AuthorRunError):
    """Composition failure that preserves a private contract-repair audit."""

    def __init__(self, message: str, *, audit: Mapping[str, Any] | None = None) -> None:
        super().__init__("composition", message)
        self.audit = deepcopy(dict(audit)) if isinstance(audit, Mapping) else None


_WSL_MOUNTED_PATH = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_SURVEY_BINDING_FIELDS = (
    "survey_run_id",
    "project_id",
    "project_context_fingerprint",
)


def _resolve_optional_path(value: str | Path | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    raw_value = os.fspath(value)
    normalized = raw_value.replace("\\", "/")
    if os.name == "nt":
        wsl_match = _WSL_MOUNTED_PATH.fullmatch(normalized)
        path = Path(f"{wsl_match.group(1).upper()}:/{wsl_match.group(2) or ''}") if wsl_match else Path(raw_value)
    else:
        windows_match = _WINDOWS_DRIVE_PATH.fullmatch(normalized)
        path = Path(f"/mnt/{windows_match.group(1).lower()}/{windows_match.group(2)}") if windows_match else Path(raw_value)
    return path.expanduser().resolve()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _verify_survey_binding(
    author_input: dict[str, Any],
    survey_sources: dict[str, Any],
    *,
    strict: bool,
) -> dict[str, Any]:
    """Bind Survey identity to the design or expose the missing binding clearly."""

    provenance = _mapping(author_input.get("provenance"))
    expected = {field: _text(_mapping(provenance.get("survey_binding")).get(field)) for field in _SURVEY_BINDING_FIELDS}
    resolved = {field: _text(survey_sources.get(field)) for field in _SURVEY_BINDING_FIELDS}
    has_binding = any(expected.values())
    if not has_binding:
        if strict:
            raise AuthorRunError(
                "survey",
                "Author handoff has no provenance.survey_binding; strict Survey binding requires all identity fields",
            )
        return {
            "status": "UNBOUND_REQUIRES_HUMAN_CONFIRMATION",
            "expected": expected,
            "resolved": resolved,
            "human_confirmation_required": True,
        }
    missing = [field for field, value in expected.items() if not value]
    if missing:
        raise AuthorRunError(
            "survey",
            "Author handoff provenance.survey_binding is incomplete; missing " + ", ".join(missing),
        )
    mismatched = [field for field in _SURVEY_BINDING_FIELDS if expected[field] != resolved[field]]
    if mismatched:
        raise AuthorRunError(
            "survey",
            "Survey manifest does not match Author handoff provenance.survey_binding for " + ", ".join(mismatched),
        )
    return {
        "status": "BOUND_VERIFIED",
        "expected": expected,
        "resolved": resolved,
        "human_confirmation_required": False,
    }


def run_author_preparation(
    author_input_path: str | Path,
    *,
    survey_manifest_path: str | Path,
    idea_result_path: str | Path | None = None,
    include_idea_evolution: str = "auto",
    max_idea_iterations: int = 3,
    strict_survey_binding: bool = False,
    logger: AuthorRunLogger | None = None,
) -> dict[str, Any]:
    """Verify all Batch-A sources and produce no prose, TeX, or PDF yet."""

    mode = str(include_idea_evolution or "auto").strip().casefold()
    if mode not in {"auto", "on", "off"}:
        raise AuthorRunError("input", "include_idea_evolution must be one of auto, on, or off")
    if max_idea_iterations not in {2, 3}:
        raise AuthorRunError("input", "max_idea_iterations must be either 2 or 3")
    active_logger = logger
    try:
        if active_logger is None:
            resolved_author_input, author_input, author_input_identity = load_author_input_with_identity(author_input_path)
        else:
            with active_logger.stage("input", input_path=str(author_input_path)):
                resolved_author_input, author_input, author_input_identity = load_author_input_with_identity(author_input_path)
    except AuthorInputLoadError as error:
        raise AuthorRunError("input", str(error)) from error
    try:
        if active_logger is None:
            survey_sources = load_verified_survey_sources(survey_manifest_path)
        else:
            with active_logger.stage("survey", manifest_path=str(survey_manifest_path)):
                survey_sources = load_verified_survey_sources(survey_manifest_path)
    except SurveyAuthorSourceError as error:
        raise AuthorRunError("survey", str(error)) from error
    try:
        survey_binding = _verify_survey_binding(
            author_input,
            survey_sources,
            strict=bool(strict_survey_binding),
        )
    except AuthorRunError:
        raise
    if active_logger is not None:
        active_logger.emit(
            "survey",
            "binding_verified" if survey_binding["status"] == "BOUND_VERIFIED" else "binding_unbound",
            level="INFO" if survey_binding["status"] == "BOUND_VERIFIED" else "WARNING",
            status=survey_binding["status"],
            human_confirmation_required=survey_binding["human_confirmation_required"],
        )
    provenance = author_input.get("provenance") or {}
    selected_direction_id = str(provenance.get("selected_direction_id") or "").strip()
    requested_idea_path = _resolve_optional_path(idea_result_path)
    inherited_idea_path = _resolve_optional_path(provenance.get("idea_result_path"))
    resolved_idea_path = requested_idea_path or inherited_idea_path
    if mode == "off":
        idea_evolution = disabled_idea_evolution()
    elif resolved_idea_path is None:
        if mode == "on":
            raise AuthorRunError("idea_evolution", "--idea-result is required when --include-idea-evolution=on")
        idea_evolution = unavailable_idea_evolution("No explicit or provenance idea_result.json path is available")
    else:
        try:
            if active_logger is None:
                idea_evolution = project_idea_evolution(
                    resolved_idea_path,
                    selected_direction_id=selected_direction_id,
                    max_iterations=max_idea_iterations,
                )
            else:
                with active_logger.stage(
                    "idea_evolution",
                    idea_result_path=str(resolved_idea_path),
                    selected_direction_id=selected_direction_id,
                ):
                    idea_evolution = project_idea_evolution(
                        resolved_idea_path,
                        selected_direction_id=selected_direction_id,
                        max_iterations=max_idea_iterations,
                    )
        except IdeaEvolutionError as error:
            if "selected direction mismatch" in str(error):
                raise AuthorRunError("idea_evolution", str(error)) from error
            if mode == "auto" and requested_idea_path is None:
                idea_evolution = unavailable_idea_evolution(str(error))
                if active_logger is not None:
                    active_logger.emit(
                        "idea_evolution",
                        "unavailable",
                        level="WARNING",
                        status="UNAVAILABLE",
                        reason=str(error),
                    )
            else:
                raise AuthorRunError("idea_evolution", str(error)) from error
    source_bundle = build_author_source_bundle(
        author_input,
        author_input_path=str(resolved_author_input),
        author_input_identity=author_input_identity,
        survey_sources=survey_sources,
        survey_binding=survey_binding,
        idea_evolution=idea_evolution,
    )
    document = build_research_plan_document_skeleton(author_input, source_bundle)
    result = {
        "schema_version": AUTHOR_PREPARATION_SCHEMA_VERSION,
        "status": "PREPARED_FOR_COMPOSITION",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "language": AUTHORING_LANGUAGE,
        "source_design_id": author_input["source_design_id"],
        "selected_direction_id": selected_direction_id,
        "source_bundle": source_bundle,
        "document": document,
    }
    if active_logger is not None:
        active_logger.emit(
            "preparation",
            "completed",
            status="COMPLETED",
            source_design_id=result["source_design_id"],
            selected_direction_id=selected_direction_id,
            idea_evolution_status=idea_evolution["status"],
            survey_binding_status=survey_binding["status"],
            language=AUTHORING_LANGUAGE,
        )
    return result


def _mapping_value(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _append_unique(items: list[Any], additions: object) -> None:
    if not isinstance(additions, list):
        return
    for candidate in additions:
        if candidate not in items:
            items.append(deepcopy(candidate))


def _render_composed_document(
    preparation: Mapping[str, Any],
    *,
    blueprint: Mapping[str, Any],
    routing: Mapping[str, Any],
    source_registry: Mapping[str, Any],
    composed_sections: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
    repair_audits: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge validated routed sections without allowing them to replace provenance."""

    document = deepcopy(_mapping_value(preparation.get("document")))
    document["document_status"] = "PROPOSAL_NO_OBSERVED_RESULTS"
    metadata = _mapping_value(document.get("document_metadata"))
    metadata["title"] = str(blueprint.get("document_title") or "").strip()
    metadata["title_status"] = "english_llm_composed"
    document["document_metadata"] = metadata
    document["keywords"] = list(blueprint.get("keywords") or [])
    document["authoring_blueprint"] = deepcopy(dict(blueprint))
    document["citation_registry"] = deepcopy(list(source_registry.get("citation_registry") or []))
    document["claim_provenance"] = []
    document["sections"] = []
    document["appendices"] = []
    document["contract_repair_audit"] = [deepcopy(dict(audit)) for audit in repair_audits]
    all_open_items: list[Any] = []
    all_review_items: list[Any] = []
    for route, section in composed_sections:
        section_id = str(section.get("section_id") or "")
        _append_unique(all_open_items, section.get("open_items"))
        _append_unique(all_review_items, section.get("review_items"))
        document["claim_provenance"].extend(deepcopy(list(section.get("claim_provenance") or [])))
        if route.get("target") == "abstract":
            document["abstract"] = {
                "text": "\n\n".join(
                    str(block.get("text") or "").strip()
                    for block in section.get("blocks") or []
                    if isinstance(block, Mapping) and str(block.get("text") or "").strip()
                ),
                "claim_ids": list(
                    dict.fromkeys(
                        str(claim_id).strip()
                        for block in section.get("blocks") or []
                        if isinstance(block, Mapping)
                        for claim_id in block.get("claim_ids") or []
                        if str(claim_id).strip()
                    )
                ),
            }
            continue
        rendered = {
            "section_id": section_id,
            "title": str(section.get("title") or ""),
            "applicability": str(section.get("applicability") or ""),
            "blocks": deepcopy(list(section.get("blocks") or [])),
        }
        target = document["appendices"] if route.get("target") == "appendices" else document["sections"]
        target.append(rendered)
    document["open_items"] = all_open_items
    document["review_items"] = all_review_items
    source_manifest = _mapping_value(document.get("source_manifest"))
    bundle = _mapping_value(preparation.get("source_bundle"))
    source_manifest.update(
        {
            "author_context_sha256": _mapping_value(bundle.get("author_input_identity")).get("sha256", ""),
            "survey_binding": deepcopy(_mapping_value(bundle.get("survey_binding"))),
            "template_family": routing.get("template_family", ""),
            "theory_sampling_power_status": routing.get("theory_sampling_power_status", "route_specific"),
        }
    )
    document["source_manifest"] = source_manifest
    return document


def run_research_plan_author(
    author_input_path: str | Path,
    *,
    survey_manifest_path: str | Path,
    idea_result_path: str | Path | None = None,
    include_idea_evolution: str = "auto",
    max_idea_iterations: int = 3,
    strict_survey_binding: bool = False,
    llm_call: Callable[..., object] | None = None,
    max_contract_repairs: int = 1,
    logger: AuthorRunLogger | None = None,
) -> dict[str, Any]:
    """Run preparation, required LLM authoring, and final proposal-only validation."""

    preparation = run_author_preparation(
        author_input_path,
        survey_manifest_path=survey_manifest_path,
        idea_result_path=idea_result_path,
        include_idea_evolution=include_idea_evolution,
        max_idea_iterations=max_idea_iterations,
        strict_survey_binding=strict_survey_binding,
        logger=logger,
    )
    if max_contract_repairs < 0:
        raise AuthorRunError("input", "max_contract_repairs must not be negative")
    source_registry = build_frozen_source_registry(preparation)
    author_context = _mapping_value(_mapping_value(preparation.get("source_bundle")).get("author_context"))
    routing = route_author_sections(author_context)
    planner = AuthoringBlueprintPlanner()
    repair_budget = int(max_contract_repairs)
    repair_audits: list[Mapping[str, Any]] = []
    try:
        if logger is None:
            blueprint, blueprint_audit = planner.plan_with_audit(
                preparation,
                routing=routing,
                source_registry=source_registry,
                llm_call=llm_call,
                allow_contract_repair=repair_budget > 0,
                logger=logger,
            )
        else:
            with logger.stage("blueprint", template_family=routing["template_family"]):
                blueprint, blueprint_audit = planner.plan_with_audit(
                    preparation,
                    routing=routing,
                    source_registry=source_registry,
                    llm_call=llm_call,
                    allow_contract_repair=repair_budget > 0,
                    logger=logger,
                )
        if blueprint_audit is not None:
            repair_audits.append(blueprint_audit)
            repair_budget -= 1
    except AuthorContractRepairError as error:
        raise AuthorCompositionError(str(error), audit=error.audit) from error
    except AuthoringBlueprintError as error:
        raise AuthorCompositionError(str(error), audit=error.audit) from error
    except Exception as error:
        raise AuthorCompositionError(str(error)) from error

    blueprint_sections = {
        str(section.get("section_id") or ""): section
        for section in blueprint.get("sections") or []
        if isinstance(section, Mapping)
    }
    composer = SectionComposer()
    composed_sections: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for route in routing["routes"]:
        section_id = str(route["section_id"])
        blueprint_section = _mapping_value(blueprint_sections.get(section_id))
        section_source_registry = source_registry_for_blueprint_section(
            source_registry,
            route,
            blueprint_section,
        )
        try:
            if logger is None:
                section, audit = composer.compose(
                    preparation,
                    blueprint=blueprint,
                    route=route,
                    blueprint_section=blueprint_section,
                    source_registry=section_source_registry,
                    llm_call=llm_call,
                    allow_contract_repair=repair_budget > 0,
                )
            else:
                with logger.stage("section_composition", section_id=section_id):
                    section, audit = composer.compose(
                        preparation,
                        blueprint=blueprint,
                        route=route,
                        blueprint_section=blueprint_section,
                        source_registry=section_source_registry,
                        llm_call=llm_call,
                        allow_contract_repair=repair_budget > 0,
                    )
        except AuthorContractRepairError as error:
            raise AuthorCompositionError(str(error), audit=error.audit) from error
        except SectionCompositionError as error:
            raise AuthorCompositionError(str(error), audit=error.audit) from error
        except Exception as error:
            raise AuthorCompositionError(str(error)) from error
        if audit is not None:
            repair_audits.append(audit)
            repair_budget -= 1
        composed_sections.append((route, section))
    document = _render_composed_document(
        preparation,
        blueprint=blueprint,
        routing=routing,
        source_registry=source_registry,
        composed_sections=composed_sections,
        repair_audits=repair_audits,
    )
    errors = validate_composed_research_plan(
        document,
        preparation=preparation,
        routing=routing,
        source_registry=source_registry,
    )
    if errors:
        raise AuthorCompositionError("final semantic validation failed: " + "; ".join(errors))
    result = deepcopy(preparation)
    result["status"] = "COMPOSED_FOR_RENDERING"
    result["document"] = document
    if logger is not None:
        logger.emit(
            "composition",
            "completed",
            status="COMPLETED",
            source_design_id=result["source_design_id"],
            template_family=routing["template_family"],
            contract_repair_count=len(repair_audits),
            language=AUTHORING_LANGUAGE,
        )
    return result


__all__ = ["AuthorCompositionError", "AuthorRunError", "run_author_preparation", "run_research_plan_author"]
