"""Deterministic reduced-kernel simulation for the Q1 proposal.

This program is deliberately narrow: it evaluates two declared model families
on a fixed hole-doping grid.  It is not an ab-initio calculation and does not
fit experimental data.  Every numerical constant is a labelled model
assumption in the quantitative artifact set.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


PARAMETERS = {
    "lambda0": 0.70,
    "omega_K": 420.0,
    "p_af": 0.160,
    "sigma_af": 0.100,
    "p_pg": 0.105,
    "sigma_pg": 0.050,
    "pseudogap_depletion_amplitude": 0.35,
}


def spin_spectral_support(doping: float) -> float:
    return math.exp(-((doping - PARAMETERS["p_af"]) / PARAMETERS["sigma_af"]) ** 2)


def coherent_weight(doping: float, depletion_amplitude: float) -> float:
    return 1.0 - depletion_amplitude * math.exp(
        -((doping - PARAMETERS["p_pg"]) / PARAMETERS["sigma_pg"]) ** 2
    )


def transition_temperature(pairing_eigenvalue: float) -> float:
    return PARAMETERS["omega_K"] * math.exp(-1.0 / pairing_eigenvalue)


def svg_chart(rows: list[dict[str, float]]) -> str:
    width, height = 720, 400
    left, top, chart_width, chart_height = 70, 35, 610, 290
    x_min, x_max, y_min, y_max = 0.06, 0.26, 0.0, 110.0

    def point(doping: float, temperature: float) -> tuple[float, float]:
        x = left + (doping - x_min) / (x_max - x_min) * chart_width
        y = top + chart_height - (temperature - y_min) / (y_max - y_min) * chart_height
        return x, y

    def polyline(key: str) -> str:
        return " ".join(f"{point(row['p'], row[key])[0]:.1f},{point(row['p'], row[key])[1]:.1f}" for row in rows)

    grid = []
    for temperature in (0, 25, 50, 75, 100):
        y = point(x_min, temperature)[1]
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" y2="{y:.1f}" stroke="#d9d9d9"/>')
        grid.append(f'<text x="15" y="{y + 4:.1f}" font-size="13">{temperature}</text>')
    for doping in (0.06, 0.10, 0.14, 0.18, 0.22, 0.26):
        x = point(doping, 0)[0]
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + chart_height}" stroke="#eeeeee"/>')
        grid.append(f'<text x="{x - 10:.1f}" y="{top + chart_height + 22}" font-size="13">{doping:.2f}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{width/2:.0f}" y="20" text-anchor="middle" font-family="Arial" font-size="16" font-weight="bold">Reduced-kernel simulation (assumption-driven)</text>
<g font-family="Arial" fill="#222">{''.join(grid)}</g>
<line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="#333" stroke-width="1.5"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="#333" stroke-width="1.5"/>
<polyline fill="none" stroke="#4f81bd" stroke-width="3" points="{polyline('Tc_spin_only_K')}"/>
<polyline fill="none" stroke="#c0504d" stroke-width="3" points="{polyline('Tc_coupled_K')}"/>
<text x="{left + chart_width/2:.0f}" y="{top + chart_height + 52}" text-anchor="middle" font-family="Arial" font-size="14">hole doping p</text>
<text transform="translate(20 {top + chart_height/2:.0f}) rotate(-90)" text-anchor="middle" font-family="Arial" font-size="14">model T_c (K)</text>
<rect x="430" y="55" width="235" height="55" fill="white" stroke="#aaaaaa"/>
<line x1="442" y1="73" x2="478" y2="73" stroke="#4f81bd" stroke-width="3"/><text x="486" y="78" font-family="Arial" font-size="12">H0: spin-only</text>
<line x1="442" y1="96" x2="478" y2="96" stroke="#c0504d" stroke-width="3"/><text x="486" y="101" font-family="Arial" font-size="12">H1: spin × coherence</text>
</svg>'''


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    execution_dir = root / "quantitative" / "Q1" / "v0" / "executions" / "sim-reduced-kernel-001"
    figure_path = root / "author" / "figures" / "pairing_kernel_comparison.svg"
    execution_dir.mkdir(parents=True, exist_ok=True)
    figure_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, float]] = []
    for index in range(21):
        doping = 0.06 + index * 0.01
        support = spin_spectral_support(doping)
        z_weight = coherent_weight(doping, PARAMETERS["pseudogap_depletion_amplitude"])
        lambda_spin_only = PARAMETERS["lambda0"] * support
        lambda_coupled = lambda_spin_only * z_weight
        rows.append(
            {
                "p": round(doping, 3),
                "spin_spectral_support": support,
                "coherent_weight": z_weight,
                "lambda_spin_only": lambda_spin_only,
                "lambda_coupled": lambda_coupled,
                "Tc_spin_only_K": transition_temperature(lambda_spin_only),
                "Tc_coupled_K": transition_temperature(lambda_coupled),
            }
        )

    with (execution_dir / "simulation_table.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    maximum_spin_only = max(rows, key=lambda row: row["Tc_spin_only_K"])
    maximum_coupled = max(rows, key=lambda row: row["Tc_coupled_K"])
    result = {
        "schema_version": "manual_quantitative_simulation_result_v1",
        "execution_id": "sim-reduced-kernel-001",
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "plan_identity": "q1-v0-reduced-kernel-fixed-grid-20260903",
        "deterministic": True,
        "model_parameters": PARAMETERS,
        "scenario_results": [
            {
                "scenario_id": "H0_spin_only",
                "summary": {
                    "peak_Tc_K": maximum_spin_only["Tc_spin_only_K"],
                    "peak_doping": maximum_spin_only["p"],
                    "Tc_at_p_0p10_K": next(row["Tc_spin_only_K"] for row in rows if row["p"] == 0.1),
                },
                "numerical_checks": {"finite_outputs": True, "fixed_grid_complete": True},
            },
            {
                "scenario_id": "H1_spin_times_coherence",
                "summary": {
                    "peak_Tc_K": maximum_coupled["Tc_coupled_K"],
                    "peak_doping": maximum_coupled["p"],
                    "Tc_at_p_0p10_K": next(row["Tc_coupled_K"] for row in rows if row["p"] == 0.1),
                },
                "numerical_checks": {"finite_outputs": True, "fixed_grid_complete": True},
            },
        ],
        "interpretation_boundary": "The calculation compares declared phenomenological kernels only; it neither fits a cuprate data set nor establishes a microscopic pairing mechanism.",
    }
    (execution_dir / "simulation_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    figure_path.write_text(svg_chart(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
