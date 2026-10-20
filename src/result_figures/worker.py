"""Standalone Matplotlib worker copied verbatim into each figure bundle."""

import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter


def main():
    spec = json.loads(Path("figure_spec.json").read_text(encoding="utf-8"))
    data = json.loads(Path("plot_data.json").read_text(encoding="utf-8"))
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 9, "pdf.fonttype": 42,
        "svg.fonttype": "none", "text.usetex": False, "text.parse_math": False,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.prop_cycle": plt.cycler(color=["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"])})
    figure, axes = plt.subplots(figsize=(7.09, 4.72), layout="constrained")
    chart = spec["chart_type"]
    if chart == "line":
        for index, series in enumerate(data["series"]):
            axes.plot(series["x"], series["y"], label=textwrap.fill(series["label"], 28),
                linestyle=["-", "--", "-.", ":"][index % 4], linewidth=1.5)
        if len(data["series"]) > 1:
            axes.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
        if spec.get("log_scale"):
            if any(value <= 0 for series in data["series"] for axis in ("x", "y") for value in series[axis]):
                raise ValueError("logarithmic_axes_require_positive_values")
            axes.set_xscale("log")
            axes.set_yscale("log")
            for axis in (axes.xaxis, axes.yaxis):
                axis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=6))
                axis.set_major_formatter(FuncFormatter(lambda value, position: f"{value:.3g}"))
                axis.set_minor_formatter(NullFormatter())
    elif chart == "bar":
        axes.bar(range(len(data["labels"])), data["values"], width=0.65)
        axes.set_xticks(range(len(data["labels"])), [textwrap.fill(label, 22) for label in data["labels"]],
            rotation=25, rotation_mode="anchor", ha="right")
    elif chart == "heatmap":
        artist = axes.pcolormesh(data["x"], data["y"], data["z"], shading="nearest",
            cmap="cividis", vmin=spec["vmin"], vmax=spec["vmax"], rasterized=True)
        if len(data["x"]) > 1:
            axes.set_xlim(data["x"][0], data["x"][-1])
        if len(data["y"]) > 1:
            axes.set_ylim(data["y"][0], data["y"][-1])
        figure.colorbar(artist, ax=axes, label=spec["z_label"])
    elif chart == "hist":
        axes.hist(data["values"], bins="auto", edgecolor="white", linewidth=0.5)
    elif chart == "box":
        axes.boxplot(data["values"], tick_labels=["All saved samples"])
    else:
        raise ValueError("unsupported_result_figure_recipe")
    axes.set_xlabel(spec["x_label"])
    axes.set_ylabel(spec["y_label"])
    axes.set_title(textwrap.fill(spec["title"], 65), fontsize=10, pad=12)
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    labels = []
    for panel in figure.axes:
        labels.extend([panel.title, panel.xaxis.label, panel.yaxis.label])
        for axis in (panel.xaxis, panel.yaxis):
            lower, upper = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks():
                if lower - 1e-10 <= tick.get_loc() <= upper + 1e-10:
                    labels.extend([tick.label1, tick.label2])
    boxes = [label.get_window_extent(renderer) for label in labels if label.get_visible() and label.get_text()]
    if axes.get_legend() is not None:
        boxes.append(axes.get_legend().get_window_extent(renderer))
    outside = sum(not figure.bbox.contains(box.x0, box.y0) or not figure.bbox.contains(box.x1, box.y1) for box in boxes)
    for output_format in spec["formats"]:
        if output_format == "png":
            figure.savefig("figure.png", dpi=300)
        elif output_format == "pdf":
            figure.savefig("figure.pdf")
        elif output_format == "svg":
            figure.savefig("figure.svg")
    Path("worker_qa.json").write_text(json.dumps({"status": "WARN" if outside else "PASS", "out_of_bounds": outside,
        "panel_alignment": "NOT_APPLICABLE_SINGLE_PANEL", "row_exclusions": 0}), encoding="utf-8")
    plt.close(figure)


if __name__ == "__main__":
    main()
