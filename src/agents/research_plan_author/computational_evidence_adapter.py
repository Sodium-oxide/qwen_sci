"""Turn a verified computation handoff into a deterministic Author section."""

from copy import deepcopy
from pathlib import Path


class ComputationalEvidenceLoadError(ValueError):
    pass


def load_computational_evidence_capsule(path: str | Path, *, expected_identity: dict | None = None) -> dict:
    from src.pipeline.computational_manifests import verify_manifest
    try:
        handoff = verify_manifest(Path(path).expanduser().resolve(), expected_identity=expected_identity)
    except Exception as error:
        raise ComputationalEvidenceLoadError(str(error)) from error
    return {"schema_version": "computational_author_evidence_capsule_v1", "branch_status": handoff["branch_status"],
        "source_binding": handoff["source_binding"], "plans": handoff["plans"], "results": handoff["results"],
        "unresolved_items": handoff["unresolved_items"], "manifest_path": str(Path(path).resolve())}


def append_computational_evidence_section(document: dict, capsule: dict) -> dict:
    result = deepcopy(document)
    blocks = []
    for index, plan in enumerate(capsule.get("plans", []), 1):
        import json
        methods = json.dumps({"model": plan["model_spec"], "method": plan["method_spec"],
            "parameters": plan["parameters"], "comparisons": plan["comparisons"], "endpoints": plan["endpoints"],
            "validation": plan["validation_plan"], "error_analysis": plan["error_analysis_plan"]}, ensure_ascii=False, sort_keys=True)
        blocks.append({"block_id": f"computational-methods-{index:02d}", "kind": "computational_evidence",
            "heading": "Computational Methods: " + plan["title"], "claim_ids": [],
            "text": f"Protocol {plan['experiment_id']} v{plan['protocol_version']}. Research question: {plan['research_question']}. "
                f"Method family: {plan['method_family']}; backend: {plan['backend_id']}. "
                f"Declared model, settings, controls and diagnostics: {methods}"})
    for index, item in enumerate(capsule.get("results", []), 1):
        metrics = "; ".join(f"{row['metric_id']}={row['value']} {row['unit']} ({row['condition_id']})" for row in item.get("metrics", []))
        checks = "; ".join(f"{row['check_id']}={'PASS' if row['passed'] else 'FAIL'}" for row in item.get("checks", []))
        diagnostics = "; ".join(f"{row['check_id']}: {row['value']} ({row['method']})" for row in item["error_analysis"])
        evidence_scope = "Computational model outputs; not empirical observations." if item["result_kind"] == "NUMERICAL_SIMULATION" else "Results apply to the declared dataset or benchmark and its sampling assumptions."
        text = (f"Experiment {item['experiment_id']} produced computational result status "
            f"{item['validation_status']} and hypothesis relation {item['hypothesis_relation']}. "
            f"Metrics: {metrics or 'none'}. Checks: {checks or 'none'}. "
            f"Numerical and method diagnostics: {diagnostics or 'none'}. "
            f"Claim scope: {item['claim_scope']}. "
            f"Unresolved items: {'; '.join(item.get('unresolved_items', [])) or 'none'}. "
            + evidence_scope)
        blocks.append({"block_id": f"computational-evidence-{index:02d}", "kind": "computational_evidence",
            "heading": "Computational Results and Error Analysis", "text": text, "claim_ids": []})
        if item.get("interpretation", {}).get("discussion"):
            blocks.append({"block_id": f"computational-discussion-{index:02d}", "kind": "computational_evidence",
                "heading": "Computational Discussion", "text": item["interpretation"]["discussion"], "claim_ids": []})
    blocks.append({"block_id": "computational-branch-status", "kind": "computational_evidence", "claim_ids": [],
        "text": "Computational branch status: " + capsule["branch_status"] + ". Unresolved: " +
            ("; ".join(capsule["unresolved_items"]) or "none")})
    result["sections"] = [*[section for section in result.get("sections", []) if section["section_id"] != "computational_experiment_evidence"], {"section_id": "computational_experiment_evidence",
        "title": "Computational Evidence", "applicability": "required", "blocks": blocks}]
    manifest = dict(result.get("source_manifest") or {})
    manifest["computational_evidence"] = {"schema_version": capsule["schema_version"],
        "branch_status": capsule["branch_status"], "manifest_path": capsule["manifest_path"],
        "result_count": len(capsule["results"]), "evidence_scope": "DECLARED_MODEL_OR_DATASET"}
    result["source_manifest"] = manifest
    return result

