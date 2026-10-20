"""Select fixed figure recipes from measured data and declared units."""

import math
import re
from collections import defaultdict
from dataclasses import replace

from .contracts import FigureError, digest


def _vector(values, *, ordered=False):
    if not isinstance(values, list) or not values or any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in values):
        raise FigureError("nonfinite_or_empty_plot_data")
    if ordered and any(later <= earlier for earlier, later in zip(values, values[1:])):
        raise FigureError("unordered_plot_coordinates")
    return values


def _recipe(source, kind, name, data, binding, *, xlabel, ylabel, zlabel="", **options):
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:50] or "result"
    identity = {"chart_type": kind, "name": name, "data_binding": binding}
    figure_id = label + "-" + digest(identity)[:10]
    scope = "Numerical simulation; model outputs." if source.result_kind == "NUMERICAL_SIMULATION" else "Results for the declared dataset or benchmark."
    caption = f"{name}. {scope} Execution {source.identity['execution_id']}; validation {source.quality}."
    if binding.get("selection"):
        caption += " " + binding["selection"]
    return {"figure_id": figure_id, "chart_type": kind, "title": name,
        "x_label": xlabel, "y_label": ylabel, "z_label": zlabel, "data_binding": binding,
        "caption": caption, "data": data, **options}


def _build_recipes(source):
    recipes, notes = [], list(source.notes)
    traces = defaultdict(list)
    seen = set()
    for trace in source.traces:
        key = (trace["condition_id"], trace["state_id"])
        if key in seen:
            raise FigureError("duplicate_plot_trace")
        seen.add(key)
        times, values = _vector(trace["times"], ordered=True), _vector(trace["values"])
        if len(times) != len(values):
            raise FigureError("plot_trace_length_mismatch")
        traces[trace["state_id"], trace["unit"]].append({"label": trace["condition_id"], "x": times, "y": values})
    for (state, unit), series in sorted(traces.items()):
        recipes.append(_recipe(source, "line", "Trajectory " + state, {"series": series},
            {"state_id": state, "unit": unit, "conditions": [row["label"] for row in series], "selection": "All saved time points."},
            xlabel="Time (as recorded)", ylabel=f"{state} [{unit}]"))
    grouped_fields = defaultdict(list)
    for item in source.fields:
        grouped_fields[item["state_id"], item["unit"]].append(item)
    for (state, unit), fields in sorted(grouped_fields.items()):
        all_values = []
        for item in fields:
            if "z" in item:
                notes.append("field_plot_skipped:three_dimensional_field_requires_declared_slice:" + state)
                continue
            _vector(item["x"], ordered=True)
            _vector(item["time"], ordered=True)
            if len(item["values"]) != len(item["time"]):
                raise FigureError("field_time_dimension_mismatch")
            expected = len(item["x"]) * len(item.get("y", [0]))
            for snapshot in item["values"]:
                if len(_vector(snapshot)) != expected:
                    raise FigureError("field_grid_dimension_mismatch")
                all_values.extend(snapshot)
        if not all_values:
            continue
        lower, upper = min(all_values), max(all_values)
        for item in fields:
            if "z" in item:
                continue
            condition = item["condition_id"]
            binding = {"state_id": state, "unit": unit, "conditions": [condition], "color_range": [lower, upper]}
            if "y" not in item:
                indices = sorted({0, len(item["time"]) // 2, len(item["time"]) - 1})
                series = [{"label": f"t={item['time'][index]:.6g}", "x": item["x"], "y": item["values"][index]} for index in indices]
                recipes.append(_recipe(source, "line", f"Spatial profiles {state} {condition}", {"series": series},
                    {**binding, "time_indices": indices, "selection": "Profiles at first, middle and last saved times (duplicates removed)."},
                    xlabel="x (as recorded)", ylabel=f"{state} [{unit}]"))
                recipes.append(_recipe(source, "heatmap", f"Time-space {state} {condition}",
                    {"x": item["x"], "y": item["time"], "z": item["values"]},
                    {**binding, "selection": "All saved spatial and time coordinates."},
                    xlabel="x (as recorded)", ylabel="Time (as recorded)", zlabel=f"{state} [{unit}]", vmin=lower, vmax=upper))
            else:
                _vector(item["y"], ordered=True)
                width = len(item["x"])
                final = item["values"][-1]
                grid = [final[offset:offset + width] for offset in range(0, len(final), width)]
                recipes.append(_recipe(source, "heatmap", f"Final field {state} {condition}",
                    {"x": item["x"], "y": item["y"], "z": grid},
                    {**binding, "time_index": len(item["time"]) - 1, "time": item["time"][-1],
                        "selection": "Final saved time; x is the fastest varying flattened coordinate."},
                    xlabel="x (as recorded)", ylabel="y (as recorded)", zlabel=f"{state} [{unit}]", vmin=lower, vmax=upper))
    metrics = defaultdict(list)
    for row in source.metrics:
        _vector([row["value"]])
        metrics[row["metric_id"], row["unit"]].append(row)
    for (metric, unit), rows in sorted(metrics.items()):
        conditions = [row["condition_id"] for row in rows]
        if len(conditions) != len(set(conditions)):
            raise FigureError("duplicate_plot_metric_condition")
        recipes.append(_recipe(source, "bar", "Metric " + metric,
            {"labels": conditions, "values": [row["value"] for row in rows]},
            {"metric_id": metric, "unit": unit, "conditions": conditions, "uncertainty": "not plotted; no bound uncertainty declared"},
            xlabel="Condition", ylabel=f"{metric} [{unit}]"))
    for sample in source.samples:
        values = _vector(sample["values"])
        binding = {"state_id": sample["state_id"], "unit": sample["unit"], "conditions": [sample["condition_id"]],
            "sample_count": len(values), "selection": "All saved samples; no inferred samples."}
        for chart in ("hist", "box"):
            recipes.append(_recipe(source, chart, f"{chart} {sample['state_id']} {sample['condition_id']}", {"values": values},
                binding, xlabel=f"{sample['state_id']} [{sample['unit']}]" if chart == "hist" else "Sample group",
                ylabel="Count" if chart == "hist" else f"{sample['state_id']} [{sample['unit']}]"))
    convergence = defaultdict(list)
    for row in source.convergence:
        _vector([row["step"], row["error"]])
        convergence[row["state_id"], row["unit"], row["check_id"]].append(row)
    for (state, unit, check), rows in sorted(convergence.items()):
        rows = sorted(rows, key=lambda row: row["step"])
        if len({row["step"] for row in rows}) != len(rows):
            notes.append("convergence_plot_skipped:duplicate_resolution:" + check)
            continue
        if len({row["step"] for row in rows}) < 2 or any(row["step"] <= 0 or row["error"] <= 0 for row in rows):
            notes.append("convergence_plot_skipped:requires_distinct_positive_steps_and_positive_reference_errors:" + check)
            continue
        recipes.append(_recipe(source, "line", "Reference convergence " + state,
            {"series": [{"label": check, "x": [row["step"] for row in rows], "y": [row["error"] for row in rows]}]},
            {"state_id": state, "unit": unit, "check_id": check, "conditions": [row["condition_id"] for row in rows],
                "selection": rows[0].get("selection", "Maximum absolute error against the declared reference at all saved times.")},
            xlabel=rows[0].get("axis_label", "Declared maximum step"), ylabel=f"Reference error [{unit}]", log_scale=True))
    return recipes, list(dict.fromkeys(notes))


def build_recipes(source):
    """Reject malformed data groups while preserving unrelated usable figures."""
    recipes, notes = [], list(source.notes)
    for attribute, keys in (("traces", ("state_id", "unit")), ("fields", ("state_id", "unit")),
            ("metrics", ("metric_id", "unit")), ("samples", ("state_id", "condition_id", "unit")),
            ("convergence", ("state_id", "unit", "check_id"))):
        groups = defaultdict(list)
        for item in getattr(source, attribute):
            groups[tuple(item.get(key) for key in keys)].append(item)
        for key, rows in sorted(groups.items(), key=lambda pair: str(pair[0])):
            isolated = replace(source, traces=[], fields=[], metrics=[], samples=[], convergence=[], notes=[])
            setattr(isolated, attribute, rows)
            try:
                selected, reasons = _build_recipes(isolated)
                recipes.extend(selected)
                notes.extend(reasons)
            except (FigureError, KeyError, TypeError, ValueError) as error:
                notes.append(f"invalid_plot_data:{attribute}:{key}:{error}")
    return recipes, list(dict.fromkeys(notes))
