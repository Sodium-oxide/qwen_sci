"""Plan figures with selected Qwen text models and validate data bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.llm.json_call import build_web_json_llm_call, call_required_json

from .feature_service_base import FeatureJobError
from .figure_contracts import FigureSpec
from .worker_support import checkpoint_value, revision_feedback


def table_summary(path: Path, suffix: str, *, max_rows: int) -> dict[str, Any]:
    import pandas as pd

    if suffix in {".csv", ".tsv"}:
        frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", nrows=max_rows + 1)
    elif suffix in {".xls", ".xlsx"}:
        frame = pd.read_excel(path, nrows=max_rows + 1)
    else:
        frame = pd.read_json(path)
    if frame.empty or len(frame) > max_rows or len(frame.columns) > 256:
        raise FeatureJobError("Figure data is empty or exceeds the configured table limits.")
    if not frame.columns.is_unique:
        raise FeatureJobError("Figure input has ambiguous duplicate column names.")
    return {
        "row_count": len(frame),
        "columns": [{"name": str(column), "dtype": str(frame[column].dtype),
                     "missing_count": int(frame[column].isna().sum())} for column in frame.columns],
    }


def plan_figure(context, *, config, prompt, data, summary, generation) -> FigureSpec:
    def produce():
        messages = prompt.build_messages(
            input_manifest={"table": summary, "variable_mapping": data["variable_mapping"]},
            task_context={"figure_claim": data["figure_claim"], "audience": data["audience"],
                          "chart_type": data.get("chart_type"), "figure_style": data.get("figure_style", {}),
                          "review_feedback": revision_feedback(context)},
        )
        callback = build_web_json_llm_call(
            config=config, model=context.job.model_name, provider_name=context.job.provider_name,
            timeout=context.remaining_seconds(120), temperature=generation.get("temperature", 0.2),
            max_output_tokens=generation.get("max_output_tokens", 16384),
        )
        return FigureSpec.model_validate(call_required_json(callback, messages, stage="figure_planner")).model_dump()

    def validate(candidate):
        spec = FigureSpec.model_validate(candidate)
        if spec.variable_mapping != data["variable_mapping"]:
            raise FeatureJobError("Figure planner changed the supplied data bindings.")
        if data.get("chart_type") and data["chart_type"] != spec.chart_type:
            raise FeatureJobError("Figure planner changed the requested chart type.")
        validate_figure_spec(spec, summary)

    candidate = checkpoint_value(context, {"step": "figure_plan", "table": summary}, produce, validate)
    return FigureSpec.model_validate(candidate)


def validate_figure_spec(spec: FigureSpec, summary: dict[str, Any]) -> None:
    columns = {item["name"]: item for item in summary["columns"]}
    if set(spec.variable_mapping) - {"x", "y", "group", "error"}:
        raise FeatureJobError("Figure specification contains an unsupported variable role.")
    required = {"y"} if spec.chart_type in {"hist", "box"} else {"x", "y"}
    if not required.issubset(spec.variable_mapping):
        raise FeatureJobError("Figure specification is missing required variable bindings.")
    if set(spec.variable_mapping.values()) - set(columns):
        raise FeatureJobError("A mapped figure column is missing.")
    if any(columns[column]["missing_count"] for column in spec.variable_mapping.values()):
        raise FeatureJobError("Resolve missing values before creating the figure.")
