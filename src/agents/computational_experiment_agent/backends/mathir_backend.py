"""Reuse audited quantitative ODE/PDE solvers inside the isolated project."""

from pathlib import Path

from .base import PythonProjectBackend


MATHIR_DRIVER = '''import copy
import json
from pathlib import Path
from qm.solver_registry import execute_mathir

plan = json.loads(Path("configs/experiment.json").read_text())
result = {"metrics": [], "solver_results": [], "traces": []}
for condition in plan["comparisons"]:
    model = copy.deepcopy(plan["model_spec"])
    document = model.get("mathir") or model.get("execution_ir", {}).get("document")
    document.setdefault("parameters", {}).update(condition["overrides"].get("parameters", {}))
    if "solver_options" in condition["overrides"]:
        document["solver_options"].update(condition["overrides"]["solver_options"])
    limits = {"max_wall_seconds": plan["resource_budget"]["max_execution_seconds"],
        "max_steps": 100000, "max_samples": 100000, "max_grid_points": 100000}
    limits.update(plan["method_spec"].get("tolerances", {}))
    if "mathir" in model:
        solved = execute_mathir(document, resource_limits=limits)
    else:
        from qm.execution_ir import execute_execution_ir
        solved = execute_execution_ir(model["execution_ir"], resource_limits=limits)
    result["solver_results"].append({"condition_id": condition["condition_id"], "result": solved})
    if "state_series" in solved:
        for state_id, values in solved["state_series"].items():
            result["traces"].append({"condition_id": condition["condition_id"], "state_id": state_id,
                "times": solved["time"], "values": values})
    for endpoint in plan["endpoints"]:
        current = solved
        for part in endpoint["estimator"].split("."):
            current = current[int(part)] if isinstance(current, list) else current[part]
        result["metrics"].append({"metric_id": endpoint["metric_id"], "condition_id": condition["condition_id"],
            "value": float(current), "unit": endpoint["unit"]})
Path("/output/observations.json").write_text(json.dumps(result, allow_nan=False))
'''


class MathIRBackend(PythonProjectBackend):
    backend_id = "mathir"

    def validate(self, plan: dict) -> list[str]:
        try:
            if "mathir" in plan["model_spec"]:
                from src.agents.quantitative_modeling.mathir import validate_mathir_document
                validate_mathir_document(plan["model_spec"]["mathir"])
            else:
                from src.agents.quantitative_modeling.execution_ir import validate_execution_ir
                validate_execution_ir(plan["model_spec"]["execution_ir"])
            return []
        except (ValueError, KeyError) as error:
            return ["invalid_quantitative_ir:" + str(error)]

    def files(self, plan: dict) -> dict[str, str]:
        package = Path(__file__).resolve().parents[2] / "quantitative_modeling"
        files = {"src/run_experiment.py": MATHIR_DRIVER, "src/__init__.py": "", "qm/__init__.py": ""}
        modules = [package / "mathir.py", package / "solver_registry.py"]
        if "execution_ir" in plan["model_spec"]:
            modules.extend(package / name for name in ("execution_ir.py", "pdeir.py", "pde_solver.py", "pde_capability_registry.py"))
            modules.extend((package / "pde").rglob("*.py"))
        for source in modules:
            files["qm/" + source.relative_to(package).as_posix()] = source.read_text(encoding="utf-8").replace("src.agents.quantitative_modeling", "qm")
        return files
