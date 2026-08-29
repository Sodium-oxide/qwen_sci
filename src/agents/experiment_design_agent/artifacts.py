"""Deterministic ExperimentDesign, Markdown, and Author handoff artifacts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import re
import tempfile
from collections.abc import Mapping
from typing import Any

from .contracts import validate_experiment_design


ARTIFACT_SCHEMA_VERSION = "experiment_design_artifacts_v1"
AUTHOR_HANDOFF_SCHEMA_VERSION = "research_plan_author_input_v3"
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
_TIMESTAMP_PATTERN = re.compile(r"^\d{8}-\d{6}-\d{6}$")


class ArtifactError(RuntimeError):
    """Base error for ExperimentDesign artifact generation."""


class ArtifactValidationError(ArtifactError):
    """Raised when an unvalidated design is submitted for artifact writing."""


class ArtifactWriteError(ArtifactError):
    """Raised when artifact output cannot be written atomically."""


@dataclass(frozen=True)
class ExperimentDesignArtifactPaths:
    """Paths for the three artifacts produced from one validated design."""

    timestamp: str
    collision_index: int
    experiment_design_json: Path
    experiment_design_markdown: Path
    author_json: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "collision_index": self.collision_index,
            "experiment_design_json": str(self.experiment_design_json),
            "experiment_design_markdown": str(self.experiment_design_markdown),
            "author_json": str(self.author_json),
        }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _iso_datetime(value: datetime | None = None) -> str:
    current = value or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    return current.isoformat(timespec="microseconds")


def generate_timestamp(generated_at: datetime | None = None) -> str:
    """Return the filename timestamp in local time without timezone punctuation."""

    current = generated_at or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    timestamp = current.strftime(TIMESTAMP_FORMAT)
    if not _TIMESTAMP_PATTERN.fullmatch(timestamp):
        raise ValueError(f"Generated timestamp does not match {TIMESTAMP_FORMAT}: {timestamp}")
    return timestamp


def _extract_design(payload: object) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ArtifactValidationError("Artifact input must be a JSON object")
    run_payload = dict(payload)
    nested_design = payload.get("experiment_design")
    design = dict(nested_design) if isinstance(nested_design, dict) else dict(payload)
    if "experiment_design" in design and not isinstance(nested_design, dict):
        design.pop("experiment_design", None)
    return design, run_payload


def _validated_design(payload: object) -> tuple[dict[str, Any], dict[str, Any]]:
    design, run_payload = _extract_design(payload)
    errors = validate_experiment_design(design)
    if errors:
        raise ArtifactValidationError("ExperimentDesign validation failed: " + "; ".join(errors))
    return deepcopy(design), deepcopy(run_payload)


def _canonical_item(field_path: object, status: str, reason: object) -> dict[str, str]:
    return {
        "field_path": _text(field_path),
        "status": status,
        "reason": _text(reason),
    }


def _stable_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    reasons_by_item: dict[tuple[str, str], set[str]] = {}
    for item in items:
        field_path = item["field_path"]
        status = item["status"]
        reason = item["reason"]
        if field_path and status and reason:
            reasons_by_item.setdefault((field_path, status), set()).add(reason)
    return [
        _canonical_item(field_path, status, "; ".join(sorted(reasons_by_item[(field_path, status)])))
        for field_path, status in sorted(reasons_by_item)
    ]


def _explicit_unknown_items(container: Mapping[str, Any], *, field_prefix: str) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for index, raw_item in enumerate(container.get("unknown_items") or [], start=1):
        item = _mapping(raw_item)
        if item:
            field_path = _text(item.get("field_path")) or f"{field_prefix}.unknown_items[{index}]"
            reason = _text(item.get("reason")) or "The final canonical item remains unresolved."
        else:
            field_path = f"{field_prefix}.unknown_items[{index}]"
            reason = _text(raw_item) or "The final canonical item remains unresolved."
        collected.append(_canonical_item(field_path, "needs_human_input", reason))
    return collected


def _canonical_unknown_items(design: Mapping[str, Any]) -> list[dict[str, str]]:
    """Derive Author open items exclusively from the final canonical design."""

    collected: list[dict[str, str]] = []
    for field_path, status in sorted(_mapping(design.get("field_statuses")).items()):
        if _text(status) == "needs_human_input":
            collected.append(
                _canonical_item(
                    field_path,
                    "needs_human_input",
                    "The final canonical field status requires human input.",
                )
            )
    for index, question in enumerate(design.get("open_design_questions") or [], start=1):
        item = _mapping(question)
        collected.append(
            _canonical_item(
                _text(item.get("field_path")) or f"open_design_questions[{index}]",
                "needs_human_input",
                _text(item.get("reason")) or _text(question) or "The final canonical design question remains open.",
            )
        )
    brief = _mapping(design.get("research_brief"))
    for index, known_unknown in enumerate(brief.get("known_unknowns") or [], start=1):
        if _text(known_unknown):
            collected.append(
                _canonical_item(
                    f"research_brief.known_unknowns[{index}]",
                    "needs_human_input",
                    known_unknown,
                )
            )
    collected.extend(_explicit_unknown_items(_mapping(design.get("variable_claim_model")), field_prefix="variable_claim_model"))
    collected.extend(_explicit_unknown_items(_mapping(design.get("formal_reasoning_plan")), field_prefix="formal_reasoning_plan"))
    collected.extend(_explicit_unknown_items(_mapping(design.get("counterexample_analysis")), field_prefix="counterexample_analysis"))
    return _stable_items(collected)


def _canonical_review_items(design: Mapping[str, Any]) -> list[dict[str, str]]:
    """Derive stable review requirements from final canonical review states."""

    collected: list[dict[str, str]] = []
    risk = _mapping(design.get("risk_and_human_review"))
    if risk.get("human_review_required") is True:
        collected.append(
            _canonical_item(
                "risk_and_human_review.human_review_required",
                "review_required",
                "The final canonical risk gate requires qualified human review.",
            )
        )
    for index, trigger in enumerate(risk.get("review_triggers") or [], start=1):
        if _text(trigger):
            collected.append(
                _canonical_item(
                    f"risk_and_human_review.review_triggers[{index}]",
                    "review_required",
                    trigger,
                )
            )
    for field_path in ("formal_reasoning_plan", "counterexample_analysis"):
        component = _mapping(design.get(field_path))
        if _text(component.get("status")) == "requires_human_review":
            collected.append(
                _canonical_item(
                    field_path,
                    "review_required",
                    f"The final canonical {field_path} status requires qualified human review.",
                )
            )
    return _stable_items(collected)


def _compact_source_registry(evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
    cards: dict[str, dict[str, Any]] = {}
    allowed_source_ids: list[str] = []
    citations: list[dict[str, Any]] = []
    for index, raw_card in enumerate(evidence_bundle.get("evidence_cards") or [], start=1):
        if not isinstance(raw_card, Mapping):
            continue
        card_id = _text(raw_card.get("card_id") or raw_card.get("evidence_card_id")) or f"evidence-card-{index}"
        source_id = _text(raw_card.get("source_id") or raw_card.get("canonical_paper_id"))
        record = {
            "card_id": card_id,
            "source_id": source_id,
            "citation_key": (
                f"cite_{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:16]}"
                if source_id
                else f"cite_{card_id}"
            ),
            "evidence_level": _text(raw_card.get("evidence_level")) or "metadata",
            "claim_slot": _text(raw_card.get("claim_slot")),
            "source_location": _text(raw_card.get("source_location")),
        }
        cards[card_id] = record
        if source_id and source_id not in allowed_source_ids:
            allowed_source_ids.append(source_id)
        if source_id:
            existing = next((item for item in citations if item.get("source_id") == source_id), None)
            if existing is None:
                citations.append({
                    "citation_key": record["citation_key"],
                    "source_id": source_id,
                    "evidence_level": record["evidence_level"],
                    "evidence_card_ids": [card_id],
                })
            elif card_id not in existing["evidence_card_ids"]:
                existing["evidence_card_ids"].append(card_id)
    return {
        "allowed_source_ids": allowed_source_ids,
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": cards,
        "citation_registry": citations,
    }


def _formal_reasoning_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    def records(collection: str, identifier: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in plan.get(collection) or []:
            if not isinstance(raw, Mapping):
                continue
            item = {key: deepcopy(raw[key]) for key in fields if key in raw}
            if _text(item.get(identifier)):
                output.append(item)
        return output

    forward = _mapping(plan.get("forward_derivation"))
    return {
        "schema_version": _text(plan.get("schema_version")),
        "applicability": _text(plan.get("applicability")),
        "status": _text(plan.get("status")),
        "target_proposition_id": _text(plan.get("target_proposition_id") or forward.get("target_proposition_id")),
        "final_conclusion": _text(plan.get("final_conclusion") or forward.get("final_conclusion")),
        "assumptions": records("assumptions", "assumption_id", ("assumption_id", "statement", "status", "variable_references", "symbol_references")),
        "definitions": records("definitions", "definition_id", ("definition_id", "symbol", "statement", "status", "variable_references", "symbol_references")),
        "propositions": records("propositions", "proposition_id", ("proposition_id", "statement", "status", "variable_references", "symbol_references")),
        "proof_obligations": records("proof_obligations", "obligation_id", ("obligation_id", "statement", "status", "proposition_id", "variable_references", "symbol_references")),
        "forward_derivation": {
            "status": _text(forward.get("status")),
            "steps": [
                {key: deepcopy(step[key]) for key in ("step_id", "premises", "status", "symbol_references", "variable_references", "rule_or_lemma", "derived_statement") if key in step}
                for step in forward.get("steps") or []
                if isinstance(step, Mapping) and _text(step.get("step_id"))
            ],
        },
        "unknown_items": deepcopy(plan.get("unknown_items") or []),
    }


def _counterexample_summary(analysis: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": _text(analysis.get("schema_version")),
        "applicability": _text(analysis.get("applicability")),
        "status": _text(analysis.get("status")),
        "target_claim_id": _text(analysis.get("target_claim_id")),
        "negated_conclusion": _text(analysis.get("negated_conclusion")),
        "candidate_counterexamples": [
            {
                key: deepcopy(candidate[key])
                for key in ("counterexample_id", "witness", "validity", "search_method", "assumption_checks", "conclusion_check")
                if key in candidate
            }
            for candidate in analysis.get("candidate_counterexamples") or []
            if isinstance(candidate, Mapping) and _text(candidate.get("counterexample_id"))
        ],
        "limitations": deepcopy(analysis.get("limitations") or []),
        "unknown_items": deepcopy(analysis.get("unknown_items") or []),
    }


def build_author_handoff(
    payload: object,
    *,
    generated_at: datetime | None = None,
    idea_result_path: str = "",
) -> dict[str, Any]:
    """Build a deterministic Research Plan Author input from a design package."""

    design, run_payload = _validated_design(payload)
    brief = _mapping(design.get("research_brief"))
    source = _mapping(brief.get("source"))
    intake = _mapping(run_payload.get("intake"))
    template = _mapping(design.get("template_composition"))
    validation_report = _mapping(design.get("validation_report"))
    design_id = _text(design.get("design_id"))
    observed_results = design.get("observed_results") or []
    input_path = (
        idea_result_path
        or _text(intake.get("canonical_input_path"))
        or _text(_mapping(source.get("upstream_source_paths")).get("idea_result"))
    )
    risk = _mapping(design.get("risk_and_human_review"))
    return {
        "schema_version": AUTHOR_HANDOFF_SCHEMA_VERSION,
        "generated_at": _iso_datetime(generated_at),
        "source_design_id": design_id,
        "selected_direction": deepcopy(brief.get("selected_direction") or {}),
        "research_design": deepcopy(design.get("research_design") or {}),
        "hypothesis_mapping": deepcopy(design.get("hypothesis_mapping") or []),
        "variables_and_operationalization": deepcopy(design.get("variables_and_operationalization") or {}),
        "field_statuses": deepcopy(design.get("field_statuses") or {}),
        "reasoning_context": deepcopy(_mapping(brief.get("reasoning_context"))),
        "formal_reasoning": _formal_reasoning_summary(_mapping(design.get("formal_reasoning_plan"))),
        "counterexample_analysis": _counterexample_summary(_mapping(design.get("counterexample_analysis"))),
        "outcome_branches": deepcopy(design.get("outcome_branches") or []),
        "unknown_items": _canonical_unknown_items(design),
        "review_items": _canonical_review_items(design),
        "source_registry": _compact_source_registry(_mapping(design.get("evidence_bundle"))),
        "authoring_constraints": {
            "proposal_without_observed_results": True,
            "unverified_reasoning_must_be_labeled": True,
            "unsupported_claims_forbidden": True,
            "counterexample_must_satisfy_all_assumptions": True,
            "formal_and_empirical_claims_must_remain_separate": True,
            "observed_results_are_absent": len(observed_results) == 0,
        },
        "provenance": {
            "idea_result_path": input_path,
            "audit_source_paths": deepcopy(
                intake.get("audit_source_paths")
                or _mapping(source.get("upstream_source_paths"))
            ),
            "selected_direction_id": _text(
                intake.get("selected_direction_id")
                or source.get("direction_id")
                or _mapping(brief.get("selected_direction")).get("id")
            ),
            "template_id": _text(template.get("template_id")),
            "discipline_ids": deepcopy(brief.get("discipline_ids") or []),
            "survey_binding": deepcopy(source.get("survey_binding") or {}),
            "risk_level": _text(risk.get("risk_level")),
            "validation_status": _text(
                validation_report.get("status")
                or _mapping(run_payload.get("validation")).get("status")
            ),
        },
    }


def _human_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).replace("_", " ").strip()).title()


def _markdown_scalar(value: object) -> str:
    if value is None or value == "":
        return "not provided"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _render_markdown_block(value: object, *, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}- not provided"]
        lines: list[str] = []
        for key in sorted(value):
            item = value[key]
            label = _human_label(key)
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{prefix}- **{label}:**")
                lines.extend(_render_markdown_block(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- **{label}:** {_markdown_scalar(item)}")
        return lines
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"{prefix}- not provided"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{prefix}-")
                lines.extend(_render_markdown_block(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {_markdown_scalar(item)}")
        return lines
    return [f"{prefix}- {_markdown_scalar(value)}"]


def render_markdown(
    payload: object,
    *,
    generated_at: datetime | None = None,
    timestamp: str | None = None,
) -> str:
    """Render a complete design package deterministically without an LLM."""

    design, run_payload = _extract_design(payload)
    brief = _mapping(design.get("research_brief"))
    execution_policy = _mapping(design.get("execution_policy"))
    observed_results = design.get("observed_results") or []
    effective_timestamp = timestamp or generate_timestamp(generated_at)
    effective_generated_at = _iso_datetime(generated_at)
    title = _text(_mapping(brief.get("selected_direction")).get("title")) or _text(design.get("design_id"))
    sections: list[tuple[str, object]] = [
        (
            "Run Metadata",
            {
                "artifact_timestamp": effective_timestamp,
                "generated_at": effective_generated_at,
                "run_status": _text(run_payload.get("status")) or "COMPLETED",
                "design_id": design.get("design_id", ""),
                "schema_version": design.get("schema_version", ""),
                "execution_mode": execution_policy.get("mode", "DESIGN_ONLY"),
                "observed_results": "none" if not observed_results else observed_results,
            },
        ),
        ("Selected Idea Direction", brief.get("selected_direction", {})),
        (
            "Research Scope",
            {
                "discipline_ids": brief.get("discipline_ids", []),
                "research_object": brief.get("research_object", {}),
                "intervention_or_transformation": brief.get("intervention_or_transformation", ""),
                "boundary_conditions": brief.get("boundary_conditions", []),
                "alternative_explanations": brief.get("alternative_explanations", []),
                "execution_policy": execution_policy,
            },
        ),
        ("Research Design", design.get("research_design", {})),
        ("Hypothesis-to-Observable Mapping", design.get("hypothesis_mapping", [])),
        ("Variables and Operationalization", design.get("variables_and_operationalization", {})),
        ("Sampling and Eligibility", design.get("sampling_and_eligibility", {})),
        ("Measurement and Calibration", design.get("measurement_and_calibration", {})),
        (
            "Groups, Controls, Baselines, and Comparisons",
            {
                "groups": _mapping(design.get("comparison_and_robustness")).get("groups", []),
                "controls": _mapping(design.get("comparison_and_robustness")).get("controls", []),
                "baselines": _mapping(design.get("comparison_and_robustness")).get("baselines", []),
                "comparisons": _mapping(design.get("comparison_and_robustness")).get("comparisons", []),
            },
        ),
        (
            "Ablation, Sensitivity, and Robustness",
            _mapping(design.get("comparison_and_robustness")).get("ablation_sensitivity_robustness", []),
        ),
        (
            "Randomization, Blinding, Repetition, and Batch Effects",
            {
                key: _mapping(design.get("analysis_plan")).get(key, {})
                for key in ("randomization", "blinding", "repetitions", "batch_effects")
            },
        ),
        (
            "Missing Data and Statistical Analysis",
            {
                "missing_data": _mapping(design.get("analysis_plan")).get("missing_data", {}),
                "statistical_analysis": _mapping(design.get("analysis_plan")).get("statistical_analysis", {}),
            },
        ),
        ("Data Governance and Reproducibility", design.get("data_governance_and_reproducibility", {})),
        ("Evidence Bundle and Coverage Ledger", design.get("evidence_bundle", {})),
        ("Formal Reasoning Plan", design.get("formal_reasoning_plan", {})),
        ("Counterexample Analysis", design.get("counterexample_analysis", {})),
        ("Expected Outcome Branches", design.get("outcome_branches", [])),
        ("Unknown Items", _canonical_unknown_items(design)),
        ("Human Review Requirements", design.get("risk_and_human_review", {})),
        (
            "Validation Report",
            {
                "design_validation": design.get("validation_report", {}),
                "run_validation": run_payload.get("validation", {}),
            },
        ),
    ]
    lines = [
        f"# Experiment Design: {title}",
        "",
        f"- Execution Mode: `{execution_policy.get('mode', 'DESIGN_ONLY')}`",
        f"- Observed Results: {'none' if not observed_results else 'present in input'}",
        f"- Evidence Status: `{_text(design.get('evidence_status')) or 'DESIGNED_NOT_EXECUTED'}`",
        "",
    ]
    for heading, content in sections:
        lines.append(f"## {heading}")
        lines.extend(_render_markdown_block(content))
        lines.append("")
    lines.extend(
        [
            "## Complete ExperimentDesign JSON",
            "",
            "~~~json",
            json.dumps(design, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False),
            "~~~",
            "",
        ]
    )
    return "\n".join(lines)


def _json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _write_temp_text(directory: Path, filename: str, content: str) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=str(directory),
            text=True,
        )
        temp_path = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except (OSError, UnicodeError, ValueError) as exc:
        try:
            if "temp_path" in locals():
                temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ArtifactWriteError(f"Cannot create temporary artifact for '{filename}': {exc}") from exc


def _publish_without_overwrite(temp_path: Path, target_path: Path) -> None:
    try:
        os.link(temp_path, target_path)
        temp_path.unlink(missing_ok=True)
        return
    except FileExistsError:
        raise
    except OSError as link_error:
        try:
            descriptor = os.open(
                target_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            raise
        except OSError:
            raise link_error
        else:
            os.close(descriptor)
        try:
            os.replace(temp_path, target_path)
        except OSError:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def _candidate_paths(output_dir: Path, timestamp: str, collision_index: int) -> ExperimentDesignArtifactPaths:
    suffix = "" if collision_index == 0 else f"_{collision_index}"
    stem = f"experiment_design_{timestamp}{suffix}"
    return ExperimentDesignArtifactPaths(
        timestamp=timestamp,
        collision_index=collision_index,
        experiment_design_json=output_dir / f"{stem}.json",
        experiment_design_markdown=output_dir / f"{stem}.md",
        author_json=output_dir / f"experiment_design_author_{timestamp}{suffix}.json",
    )


class ExperimentDesignArtifactWriter:
    """Validate and atomically write the three design artifacts."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()

    def write(
        self,
        payload: object,
        *,
        generated_at: datetime | None = None,
        timestamp: str | None = None,
        idea_result_path: str = "",
    ) -> ExperimentDesignArtifactPaths:
        design, run_payload = _validated_design(payload)
        effective_generated_at = generated_at or datetime.now().astimezone()
        effective_timestamp = timestamp or generate_timestamp(effective_generated_at)
        if not _TIMESTAMP_PATTERN.fullmatch(effective_timestamp):
            raise ValueError(f"timestamp must match YYYYMMDD-HHMMSS-ffffff: {effective_timestamp}")
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactWriteError(f"Cannot create artifact directory '{self.output_dir}': {exc}") from exc

        author_handoff = build_author_handoff(
            {"experiment_design": design, **run_payload},
            generated_at=effective_generated_at,
            idea_result_path=idea_result_path,
        )
        markdown = render_markdown(
            {"experiment_design": design, **run_payload},
            generated_at=effective_generated_at,
            timestamp=effective_timestamp,
        )
        contents = {
            "experiment_design_json": _json_text(design),
            "experiment_design_markdown": markdown,
            "author_json": _json_text(author_handoff),
        }

        for collision_index in range(1000):
            paths = _candidate_paths(self.output_dir, effective_timestamp, collision_index)
            targets = [
                paths.experiment_design_json,
                paths.experiment_design_markdown,
                paths.author_json,
            ]
            if any(target.exists() for target in targets):
                continue
            temporary_paths: dict[str, Path] = {}
            published: list[Path] = []
            try:
                for key, target in zip(contents, targets):
                    temporary_paths[key] = _write_temp_text(self.output_dir, target.name, contents[key])
                for key, target in zip(contents, targets):
                    _publish_without_overwrite(temporary_paths[key], target)
                    published.append(target)
                return paths
            except FileExistsError:
                for target in published:
                    target.unlink(missing_ok=True)
                continue
            except (OSError, ArtifactWriteError) as exc:
                for target in published:
                    target.unlink(missing_ok=True)
                raise ArtifactWriteError(f"Cannot publish ExperimentDesign artifacts: {exc}") from exc
            finally:
                for temporary_path in temporary_paths.values():
                    temporary_path.unlink(missing_ok=True)
        raise ArtifactWriteError(
            f"Could not find an unused artifact filename for timestamp '{effective_timestamp}'"
        )


def write_experiment_design_artifacts(
    payload: object,
    output_dir: str | Path,
    *,
    generated_at: datetime | None = None,
    timestamp: str | None = None,
    idea_result_path: str = "",
) -> ExperimentDesignArtifactPaths:
    """Convenience wrapper for writing validated ExperimentDesign artifacts."""

    return ExperimentDesignArtifactWriter(output_dir).write(
        payload,
        generated_at=generated_at,
        timestamp=timestamp,
        idea_result_path=idea_result_path,
    )


write_artifacts = write_experiment_design_artifacts


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "AUTHOR_HANDOFF_SCHEMA_VERSION",
    "ArtifactError",
    "ArtifactValidationError",
    "ArtifactWriteError",
    "ExperimentDesignArtifactPaths",
    "ExperimentDesignArtifactWriter",
    "build_author_handoff",
    "generate_timestamp",
    "render_markdown",
    "write_artifacts",
    "write_experiment_design_artifacts",
]
