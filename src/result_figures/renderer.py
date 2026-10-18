"""Materialize source data and run the shared trusted plotting worker."""

import csv
import json
import math
from pathlib import Path

from src.pipeline.science_run import atomic_write_json, atomic_write_text

from .runtime import execution_prelude, run_template


def render_recipe(recipe, directory, settings, *, deadline=None, cancel_check=None):
    directory.mkdir(parents=True)
    spec = {key: value for key, value in recipe.items() if key != "data"}
    spec["formats"] = list(settings["formats"])
    atomic_write_json(directory / "figure_spec.json", spec)
    atomic_write_json(directory / "plot_data.json", recipe["data"])
    data = recipe["data"]
    with (directory / "plot_data.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if "series" in data:
            writer.writerow(["series", "x", "value"])
            for series in data["series"]:
                writer.writerows((series["label"], position, value) for position, value in zip(series["x"], series["y"], strict=True))
        elif "z" in data:
            writer.writerow(["x", "y", "value"])
            for position, row in zip(data["y"], data["z"], strict=True):
                writer.writerows((coordinate, position, value) for coordinate, value in zip(data["x"], row, strict=True))
        else:
            writer.writerow(["condition", "value"])
            writer.writerows(zip(data.get("labels", ["sample"] * len(data["values"])), data["values"], strict=True))
    prelude = execution_prelude(cpu_seconds=max(1, math.ceil(settings["timeout_seconds_per_figure"])),
        memory_bytes=2_147_483_648, output_bytes=settings["max_output_bytes"])
    atomic_write_text(directory / "figure.py", prelude + Path(__file__).with_name("worker.py").read_text(encoding="utf-8"))
    run_template(directory, timeout=settings["timeout_seconds_per_figure"], deadline=deadline, cancel_check=cancel_check)
    return json.loads((directory / "worker_qa.json").read_text(encoding="utf-8"))
