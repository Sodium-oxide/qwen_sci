"""Generated PySCF projects and a compatible fixed single-point driver."""

from .base import PythonProjectBackend


PYSCF_DRIVER = '''import json
import os
from pathlib import Path
from pyscf import gto, scf, dft

plan = json.loads(Path("configs/experiment.json").read_text())
model, method = plan["model_spec"], plan["method_spec"]
observations = {"metrics": [], "electronic_states": [], "energies": []}
for condition in plan["comparisons"]:
    options = {**method, **condition["overrides"]}
    molecule = gto.M(atom=model["structure"], unit=model["structure_unit"], charge=model["charge"],
        spin=model["spin"], basis=options["basis"], verbose=4,
        output="/output/" + condition["condition_id"] + ".log")
    chosen = options["method"].upper()
    factory = {"RHF": scf.RHF, "UHF": scf.UHF, "RKS": dft.RKS, "UKS": dft.UKS}[chosen]
    calculation = factory(molecule)
    if chosen in {"RKS", "UKS"}:
        calculation.xc = options["xc"]
    calculation.conv_tol = float(options["scf_tolerance"])
    calculation.max_cycle = int(options["max_scf_cycles"])
    energy = float(calculation.kernel())
    observations["energies"].append({"condition_id": condition["condition_id"], "value": energy,
        "converged": bool(calculation.converged), "nelectron": molecule.nelectron,
        "spin": molecule.spin, "charge": molecule.charge, "basis": options["basis"], "method": chosen})
    for endpoint in plan["endpoints"]:
        if endpoint["estimator"] == "total_energy":
            observations["metrics"].append({"metric_id": endpoint["metric_id"],
                "condition_id": condition["condition_id"], "value": energy, "unit": endpoint["unit"]})
Path("/output/observations.json").write_text(json.dumps(observations, allow_nan=False))
'''


class PySCFBackend(PythonProjectBackend):
    backend_id = "pyscf"

    def uses_generated_code(self, plan: dict) -> bool:
        return plan["method_spec"].get("implementation_mode", "fixed") == "generated"

    def generation_guidance(self, plan: dict) -> str:
        return (
            "Use the installed PySCF Python API to implement the declared scientific task. "
            "Methods, properties, molecular/periodic models, solvent models and condition overrides are not restricted to a fixed driver. "
            "Use actual available APIs and dependencies; preserve each condition's geometry, electronic state, environment and units. "
            "Emit electronic_states records for every condition: {condition_id, charge, spin, nelectron, converged}. "
            "Take electronic state from the actual molecule/cell; take converged from the reference SCF when required. "
            "For a declared non-SCF algorithm omit converged and provide its own method diagnostics; never assert success constants. "
            "Emit post-SCF, optimization, frequency or other task diagnostics required by the protocol as raw records bound to endpoints. "
            "Save calculation logs and raw scientific outputs under /output. Do not substitute SCF convergence for correlated-method convergence."
        )

    def validate(self, plan: dict) -> list[str]:
        errors = []
        method = plan["method_spec"]
        if method.get("implementation_mode", "fixed") not in {"fixed", "generated"}:
            return ["invalid_pyscf_implementation_mode"]
        if self.uses_generated_code(plan):
            return super().validate(plan)
        if method.get("task_type") != "single_point":
            errors.append("pyscf_v1_supports_single_point_only")
        if not isinstance(plan["model_spec"].get("structure"), str):
            errors.append("pyscf_structure_must_be_atom_coordinate_string")
        if plan["model_spec"].get("environment") not in {"gas", "gas_phase", "vacuum"}:
            errors.append("pyscf_v1_supports_gas_phase_only")
        method_conditions = set()
        for condition in plan["comparisons"]:
            options = {**method, **condition["overrides"]}
            if set(condition["overrides"]) - {"method", "basis", "xc", "scf_tolerance", "max_scf_cycles"}:
                errors.append("unsupported_pyscf_condition_override")
            if options.get("method", "").upper() not in {"RHF", "UHF", "RKS", "UKS"}:
                errors.append("unsupported_pyscf_method")
            if options.get("method", "").upper() in {"RHF", "RKS"} and plan["model_spec"].get("spin") != 0:
                errors.append("restricted_pyscf_method_requires_closed_shell")
            if options.get("method", "").upper() in {"RKS", "UKS"} and not options.get("xc"):
                errors.append("missing_xc_functional")
            tolerance, cycles = options.get("scf_tolerance"), options.get("max_scf_cycles")
            if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance <= 0:
                errors.append("invalid_pyscf_condition_tolerance")
            if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles <= 0:
                errors.append("invalid_pyscf_condition_cycle_limit")
            method_conditions.add((str(options.get("method")), str(options.get("basis")), str(options.get("xc", ""))))
        if any(endpoint["estimator"] != "total_energy" or endpoint["unit"] != "hartree" for endpoint in plan["endpoints"]):
            errors.append("pyscf_v1_endpoint_must_be_total_energy_hartree")
        if not any(row["role"] == "sensitivity" for row in plan["comparisons"]) or len(method_conditions) < 2:
            errors.append("missing_method_sensitivity_condition")
        return errors

    def files(self, plan: dict) -> dict[str, str]:
        if self.uses_generated_code(plan):
            return {}
        return {"src/run_experiment.py": PYSCF_DRIVER}
