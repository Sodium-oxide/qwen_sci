"""Exercise real plots, provenance, branch recovery and report delivery."""

from copy import deepcopy
from pathlib import Path
import json
import math
import time

import pytest

from src.agents.computational_experiment_agent.artifacts import read_json, record
from src.pipeline.science_run import atomic_write_json, file_sha256, science_run_paths
from src.result_figures.contracts import FigureError, FigureSource
from src.result_figures.recipes import build_recipes
from src.result_figures.service import ensure_result_figures
from src.result_figures.validation import verify_figure_manifest


def source(root):
    atomic_write_json(root / "raw.json", {"saved": True})
    return FigureSource(root, {"branch": "test", "execution_id": "execution-001"}, "QUALIFIED",
        "NUMERICAL_SIMULATION", [{**record(root, root / "raw.json"), "role": "result"}],
        traces=[{"condition_id": "baseline", "state_id": "concentration", "unit": "mol/L",
            "times": [0., .5, 1.], "values": [1., .6, .36]}],
        metrics=[{"condition_id": "baseline", "metric_id": "final_concentration", "unit": "mol/L", "value": .36}])


def ensure(data, **kwargs):
    return ensure_result_figures(source=data, output_dir=data.root / "figures", **kwargs)


def test_actual_ode_exports_match_data_and_cache_repairs_only_corrupt_plot(tmp_path, monkeypatch):
    import src.result_figures.service as service

    data = source(tmp_path)
    settings = {"formats": ["png", "pdf", "svg"]}
    manifest = ensure(data, settings=settings)
    assert manifest["status"] == "SUCCEEDED", manifest
    verify_figure_manifest(manifest["manifest_path"], root=tmp_path, recompute=False)
    line = manifest["figures"][0]
    plotted = read_json(tmp_path / next(row["path"] for row in line["artifacts"] if row["role"] == "plot_data"))
    assert plotted["series"][0]["y"] == data.traces[0]["values"]
    assert {row["format"] for row in line["outputs"]} == {"png", "pdf", "svg"}
    assert line["qa"]["out_of_bounds"] == 0
    original = service.render_recipe
    calls = []

    def tracked(recipe, *args, **kwargs):
        calls.append(recipe["figure_id"])
        return original(recipe, *args, **kwargs)

    monkeypatch.setattr(service, "render_recipe", tracked)
    assert ensure(data, settings=settings)["manifest_path"] == manifest["manifest_path"]
    assert calls == []
    png = tmp_path / line["outputs"][0]["path"]
    png.write_bytes(b"corrupt")
    with pytest.raises(FigureError, match="artifact_modified"):
        verify_figure_manifest(manifest["manifest_path"], root=tmp_path, recompute=False)
    repaired = ensure(data, settings=settings)
    assert calls == [line["figure_id"]]
    assert repaired["figures"][1] == manifest["figures"][1]
    assert repaired["manifest_path"] != manifest["manifest_path"]
    verify_figure_manifest(repaired["manifest_path"], root=tmp_path, recompute=False)


def test_partial_render_failure_preserves_results_and_retries_only_failure(tmp_path, monkeypatch):
    import src.result_figures.service as service

    data = source(tmp_path)
    original = service.render_recipe

    def fail_line(recipe, *args, **kwargs):
        if recipe["chart_type"] == "line":
            raise FigureError("simulated_timeout")
        return original(recipe, *args, **kwargs)

    monkeypatch.setattr(service, "render_recipe", fail_line)
    manifest = ensure(data)
    frozen_hash = file_sha256(Path(manifest["manifest_path"]))
    assert manifest["status"] == "PARTIAL"
    assert read_json(tmp_path / "raw.json") == {"saved": True}
    calls = []

    def tracked(recipe, *args, **kwargs):
        calls.append(recipe["chart_type"])
        return original(recipe, *args, **kwargs)

    monkeypatch.setattr(service, "render_recipe", tracked)
    assert ensure(data)["status"] == "SUCCEEDED"
    assert calls == ["line"]
    assert file_sha256(Path(manifest["manifest_path"])) == frozen_hash


@pytest.mark.parametrize("kind", ["cancel", "deadline", "dependency"])
def test_plot_failure_is_recorded_without_touching_numerics(tmp_path, monkeypatch, kind):
    import src.result_figures.service as service

    data = source(tmp_path)
    before = file_sha256(tmp_path / "raw.json")
    options = {"cancel_check": lambda: True} if kind == "cancel" else {"deadline": time.monotonic() - 1}
    if kind == "dependency":
        options = {}

        def absent(name):
            raise service.importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(service.importlib.metadata, "version", absent)
    manifest = ensure(data, **options)
    assert manifest["status"] == "FAILED"
    assert all(figure["reason"] for figure in manifest["figures"])
    assert Path(manifest["manifest_path"]).is_file()
    assert file_sha256(tmp_path / "raw.json") == before


def test_units_incomplete_samples_and_invalid_group_do_not_mix(tmp_path):
    data = source(tmp_path)
    data.traces.append({**data.traces[0], "condition_id": "other", "unit": "kg"})
    data.traces.append({**data.traces[0], "state_id": "broken", "values": [1.]})
    data.notes.append("sample_distribution_skipped:raw_monte_carlo_samples_not_saved")
    recipes, notes = build_recipes(data)
    assert {row["data_binding"]["unit"] for row in recipes if row["chart_type"] == "line"} == {"kg", "mol/L"}
    assert any(note.startswith("invalid_plot_data:") for note in notes)
    assert any("samples_not_saved" in note for note in notes)
    assert not any(row["chart_type"] in {"hist", "box"} for row in recipes)


def test_pde_geometry_shared_color_range_and_real_heatmap(tmp_path):
    data = source(tmp_path)
    data.traces = data.metrics = []
    data.fields = [{"state_id": "u", "unit": "K", "condition_id": "coarse", "x": [0., 1., 2.],
        "y": [0., 1.], "time": [0., 1.], "values": [[0., 0., 0., 0., 0., 0.], [1., 2., 3., 4., 5., 6.]]},
        {"state_id": "u", "unit": "K", "condition_id": "fine", "x": [0., 1., 2.], "y": [0., 1.],
            "time": [0., 1.], "values": [[0., 0., 0., 0., 0., 0.], [2., 4., 6., 8., 10., 12.]]}]
    recipes, notes = build_recipes(data)
    assert not notes
    assert recipes[0]["data"]["z"] == [[1., 2., 3.], [4., 5., 6.]]
    assert all((row["vmin"], row["vmax"]) == (0., 12.) for row in recipes)
    assert ensure(data)["status"] == "SUCCEEDED"
    data.fields[1]["values"][-1].pop()
    recipes, notes = build_recipes(data)
    assert not recipes and any("field_grid_dimension_mismatch" in note for note in notes)


def test_pde_1d_and_convergence_require_real_positive_reference_errors(tmp_path):
    data = source(tmp_path)
    data.fields = [{"state_id": "u", "unit": "K", "condition_id": "baseline", "x": [0., .5, 1.],
        "time": [0., 1.], "values": [[0., 1., 0.], [0., .5, 0.]]}]
    data.convergence = [{"condition_id": str(step), "state_id": "u", "unit": "K", "check_id": "ref",
        "step": step, "error": step**2} for step in (.1, .05)]
    recipes, notes = build_recipes(data)
    assert any(row["chart_type"] == "heatmap" and row["data"]["y"] == [0., 1.] for row in recipes)
    assert next(row for row in recipes if row.get("log_scale"))["data"]["series"][0]["y"] == [.0025000000000000005, .010000000000000002]
    manifest = ensure(data)
    assert manifest["status"] == "SUCCEEDED", manifest
    assert all(figure["qa"]["pdf_text_geometry"]["overlap_count"] == 0 for figure in manifest["figures"])
    data.convergence[1]["error"] = 0.
    recipes, notes = build_recipes(data)
    assert not any(row.get("log_scale") for row in recipes)
    assert any(note.startswith("convergence_plot_skipped") for note in notes)


def test_saved_sample_distribution_exports_all_samples(tmp_path):
    data = source(tmp_path)
    data.traces, data.metrics = [], []
    samples = [1., 1.2, 1.4, 1.8, 2.1, 3.]
    data.samples = [{"condition_id": "baseline", "state_id": "observable", "unit": "s", "values": samples}]
    manifest = ensure(data)
    assert manifest["status"] == "SUCCEEDED", manifest
    assert {figure["chart_type"] for figure in manifest["figures"]} == {"hist", "box"}
    for figure in manifest["figures"]:
        plotted = read_json(tmp_path / next(item["path"] for item in figure["artifacts"] if item["role"] == "plot_data"))
        assert plotted["values"] == samples
        assert figure["data_binding"]["sample_count"] == len(samples)


def test_reference_convergence_separates_different_physical_conditions(tmp_path):
    from src.result_figures.adapters import _collect_reference_convergence

    data = source(tmp_path)
    plan = {"parameters": [], "validation_plan": [{"check_id": "reference", "settings": {
        "reference_expression": {"op": "constant", "value": 0.}}}], "error_analysis_plan": [],
        "comparisons": [{"condition_id": "baseline", "overrides": {"max_step": .1, "parameters": {"rate": 1.}}},
            {"condition_id": "fine", "overrides": {"max_step": .05, "parameters": {"rate": 2.}}}]}
    data.traces.append({**data.traces[0], "condition_id": "fine"})
    _collect_reference_convergence(data, plan)
    assert len({row["check_id"] for row in data.convergence}) == 2
    assert not any(row.get("log_scale") for row in build_recipes(data)[0])
    plan["comparisons"][1]["overrides"]["parameters"]["rate"] = 1.
    data.convergence.clear()
    _collect_reference_convergence(data, plan)
    assert any(row.get("log_scale") for row in build_recipes(data)[0])
    data.convergence.append(deepcopy(data.convergence[0]))
    recipes, notes = build_recipes(data)
    assert not any(row.get("log_scale") for row in recipes)
    assert any("duplicate_resolution" in note for note in notes)


def test_saved_convergence_registration_uses_actual_refinement_executions(tmp_path):
    from test_pde_execution import _one_d, _envelope, _identity, _constant
    from src.agents.quantitative_modeling.pde.convergence import build_refinement_plans
    from src.agents.quantitative_modeling.run_plan import build_simulation_run_plan
    from src.agents.quantitative_modeling.sandbox_runner import execute_simulation_run_plan
    from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
    from src.result_figures.convergence import collect_saved_convergence, register_saved_convergence_study

    document = _one_d()
    document["initial_condition"]["values"] = [math.sin(math.pi * i / 20) for i in range(21)]
    document["boundary_conditions"] = {side: {"type": "DIRICHLET", "value": _constant(0.)} for side in ("left", "right")}
    parent = build_simulation_run_plan(model_identity=_identity(), execution_ir=_envelope(document))
    directory = tmp_path / "quantitative/Q1/v0"
    atomic_write_json(directory / "simulation_run_plan.json", parent)
    records = []
    for index, plan in enumerate(build_refinement_plans(parent, grid_multipliers=(1, 2))):
        execution = execute_simulation_run_plan(plan, execute=True, confirmed_plan_identity=plan["plan_identity"])
        scenario = execution["scenario_results"][0]
        result = scenario["result"]
        state = plan["execution_ir"]["document"]["fields"][0]["id"]
        values = result["field_series"][state][-1]
        error = max(abs(value - math.exp(-.01 * math.pi**2 * result["time"][-1]) * math.sin(math.pi * x))
            for x, value in zip(result["x"], values, strict=True))
        result["verification"]["analytic_linf_error"] = error
        qualification = qualify_simulation_result(execution, required_validation_checks=plan["qualification_requirements"])
        assert qualification["result_quality"] == "QUALIFIED"
        entry = {"scenario_id": scenario["scenario_id"], "state_id": state, "axis": "x",
            "error_path": ["verification", "analytic_linf_error"], "error_norm": "Linf",
            "reference_id": "sinusoidal_heat_exact", "unit": "1"}
        result_payload = {key: execution[key] for key in ("execution_id", "plan_identity", "model_identity", "scenario_results")}
        for name, payload in (("plan", plan), ("execution", {key: value for key, value in execution.items() if key != "scenario_results"}),
                ("result", result_payload), ("qualification", qualification)):
            path = directory / "convergence" / str(index) / (name + ".json")
            atomic_write_json(path, payload)
            entry[name] = record(tmp_path, path)
        records.append(entry)
    reference = register_saved_convergence_study(root=tmp_path, version_dir=directory, records=records)
    assert register_saved_convergence_study(root=tmp_path, version_dir=directory, records=records) == reference
    data = source(tmp_path)
    collect_saved_convergence(data, directory, parent)
    recipes, _ = build_recipes(data)
    curve = next(row for row in recipes if row.get("log_scale"))
    assert len(curve["data"]["series"][0]["x"]) == 2
    assert all(row["error"] > 0 for row in data.convergence)
    assert ensure(data)["status"] == "SUCCEEDED"

    with pytest.raises(FigureError, match="duplicate_convergence_resolution"):
        register_saved_convergence_study(root=tmp_path, version_dir=directory, records=[records[0], records[0]])
    invalid = deepcopy(records)
    invalid[0]["error_path"] = ["summary", "final_mean"]
    with pytest.raises(FigureError, match="saved_verification_error"):
        register_saved_convergence_study(root=tmp_path, version_dir=directory, records=invalid)
    invalid = deepcopy(records)
    invalid[0]["unit"] = "kg"
    with pytest.raises(FigureError, match="field_or_unit_mismatch"):
        register_saved_convergence_study(root=tmp_path, version_dir=directory, records=invalid)
    execution_path = tmp_path / records[0]["execution"]["path"]
    execution = read_json(execution_path)
    execution["execution_id"] = "unrelated"
    atomic_write_json(execution_path, execution)
    invalid = deepcopy(records)
    invalid[0]["execution"] = record(tmp_path, execution_path)
    with pytest.raises(FigureError, match="execution_binding_mismatch"):
        register_saved_convergence_study(root=tmp_path, version_dir=directory, records=invalid)


def test_qualified_negative_q_results_reach_supplement_and_author(tmp_path):
    from test_quantitative_workflow import _prepare_qualified_q0_run
    from src.agents.quantitative_modeling.author_handoff import finalize_quantitative_idea, build_quantitative_author_handoff
    from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
    from src.agents.research_plan_author.quantitative_evidence_adapter import load_quantitative_evidence_capsule, append_quantitative_evidence_section
    from src.result_figures.integration import verify_figure_index
    from src.result_figures.reporting import report_result_figures
    from src.webapp.artifact_service import artifact_index

    root, identity = _prepare_qualified_q0_run(tmp_path)
    finalization = read_json(finalize_quantitative_idea(run_dir=root, quantitative_idea_id="Q1", version=0))
    index = verify_figure_index(finalization["artifacts"]["result_figures"], root=root)
    manifest = verify_figure_manifest(root / index["manifests"][0]["path"], root=root)
    assert manifest["status"] == "SUCCEEDED", manifest
    result = read_json(root / next(item["path"] for item in manifest["source_refs"] if item["role"] == "result"))
    plotted = read_json(root / next(item["path"] for item in manifest["figures"][0]["artifacts"] if item["role"] == "plot_data"))
    assert plotted["series"][0]["y"] == result["scenario_results"][0]["result"]["state_series"]["x"]
    publication = publish_quantitative_models_pdf(run_dir=root)
    assert read_json(Path(publication["validation"]))["text_geometry"]["status"] in {"PASS", "WARN"}
    tex = Path(publication["tex"]).read_text()
    assert "\\includegraphics" in tex and "Execution sim-" in tex
    _, handoff = build_quantitative_author_handoff(run_dir=root, quantitative_models_pdf_path=publication["pdf"])
    capsule = load_quantitative_evidence_capsule(handoff, expected_identity=identity)
    document = append_quantitative_evidence_section({"sections": []}, capsule)
    figures = report_result_figures(document)
    assert figures and all(Path(item["source_path"]).is_file() for item in figures)
    indexed = artifact_index(science_run_paths(root), {})
    assert any(path.suffix == ".csv" for path in indexed.values())
    assert any(path.suffix == ".png" for path in indexed.values())
    _render_author_with_figures(tmp_path, document, figures)


def test_q_finalization_retains_numerical_result_when_figure_service_is_unavailable(tmp_path, monkeypatch):
    from test_quantitative_workflow import _prepare_qualified_q0_run
    from src.agents.quantitative_modeling.author_handoff import finalize_quantitative_idea, load_finalized_quantitative_record
    import src.result_figures.integration as integration

    root, _ = _prepare_qualified_q0_run(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("figure_storage_unavailable")

    monkeypatch.setattr(integration, "ensure_quantitative_figures", unavailable)
    finalization = read_json(finalize_quantitative_idea(run_dir=root, quantitative_idea_id="Q1", version=0))
    index = integration.verify_figure_index(finalization["artifacts"]["result_figures"], root=root)
    assert index["unavailable"] == [{"execution_id": finalization["qualified_execution_ids"][0],
        "reason": "result_figure_generation_unavailable"}]
    assert load_finalized_quantitative_record(root=root,
        finalization_path=root / "quantitative/Q1/finalization.json")["qualified_entries"]


def _render_author_with_figures(tmp_path, evidence_document, figures):
    from test_research_plan_author_rendering import _document, _marker_template
    from src.agents.research_plan_author.tex_renderer import render_tex_project
    from src.agents.research_plan_author.template_profile import load_template_profile

    document = _document()
    document["sections"].extend(evidence_document["sections"])
    rendered = render_tex_project(document, template_dir=_marker_template(tmp_path / "template"),
        project_dir=tmp_path / "author-project", profile=load_template_profile("markers_v1"), visual_figures=figures)
    assert rendered.main_tex.read_text().count("\\includegraphics") == len(figures)
    for figure in figures:
        assert file_sha256(rendered.project_dir / figure["file"]) == figure["source_sha256"]


def test_computational_negative_results_seal_figures_and_author_verifies_data(tmp_path):
    from test_computational_experiments import FakeRuntime, callback, context, ode_plan
    from src.agents.computational_experiment_agent.orchestrator import ComputationalOrchestrator
    from src.agents.research_plan_author.computational_evidence_adapter import load_computational_evidence_capsule, append_computational_evidence_section
    from src.result_figures.reporting import report_result_figures
    from src.pipeline.computational_manifests import verify_manifest

    plan = ode_plan()
    plan["decision_rule"]["threshold"] = .1
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(plan), runtime=FakeRuntime())
    assert controller.start(context=context(), mode="run")["status"] == "COMPLETED"
    handoff_path = tmp_path / "computation/manifest.json"
    handoff = verify_manifest(handoff_path)
    assert handoff["results"][0]["hypothesis_relation"] == "REFUTED"
    references = [item for item in handoff["artifact_refs"] if item.get("role") == "result_figures"]
    assert references
    path = tmp_path / "computation" / references[0]["path"]
    manifest = verify_figure_manifest(path, root=tmp_path)
    assert manifest["status"] == "SUCCEEDED", manifest
    capsule = load_computational_evidence_capsule(handoff_path)
    document = append_computational_evidence_section({"sections": []}, capsule)
    figures = report_result_figures(document)
    assert figures
    _render_author_with_figures(tmp_path, document, figures)
    data_ref = next(item for item in manifest["figures"][0]["artifacts"] if item["role"] == "plot_data")
    data_path = tmp_path / data_ref["path"]
    data = read_json(data_path)
    data["series"][0]["y"][-1] = 999.
    atomic_write_json(data_path, data)
    data_ref["sha256"] = file_sha256(data_path)
    atomic_write_json(path, manifest)
    with pytest.raises(FigureError, match="data_differs_from_execution"):
        verify_figure_manifest(path, root=tmp_path)


def test_sealed_old_run_backfill_preserves_sealed_files_and_is_delivered(tmp_path):
    from test_computational_experiments import FakeRuntime, callback, context
    from src.agents.computational_experiment_agent.orchestrator import ComputationalOrchestrator
    from src.pipeline.computational_manifests import verify_manifest
    from src.result_figures.integration import ensure_computational_figures
    from src.result_figures.reporting import report_result_figures
    from src.agents.research_plan_author.computational_evidence_adapter import load_computational_evidence_capsule, append_computational_evidence_section
    from src.webapp.artifact_service import artifact_index

    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=FakeRuntime(), figure_settings={"enabled": False})
    controller.start(context=context(), mode="run")
    path = tmp_path / "computation/manifest.json"
    handoff = verify_manifest(path)
    before = {item: file_sha256(item) for item in (tmp_path / "computation").rglob("*") if item.is_file()}
    executions = list(controller.runtime.calls)
    controller.figure_settings = {"enabled": True}
    controller.resume()
    assert controller.runtime.calls == executions
    manifest = ensure_computational_figures(tmp_path, handoff["plans"][0], handoff["results"][0])
    assert manifest["status"] == "SUCCEEDED", manifest
    assert Path(manifest["manifest_path"]).is_relative_to(tmp_path / "figure_deliveries")
    assert all(file_sha256(item) == value for item, value in before.items())
    assert verify_manifest(path) == handoff
    again = ensure_computational_figures(tmp_path, handoff["plans"][0], handoff["results"][0])
    assert again["manifest_path"] == manifest["manifest_path"]
    indexed = artifact_index(science_run_paths(tmp_path), {})
    assert any(path.is_relative_to(tmp_path / "figure_deliveries") and path.suffix == ".png" for path in indexed.values())
    document = append_computational_evidence_section({"sections": []}, load_computational_evidence_capsule(path))
    assert any(Path(figure["source_path"]).is_relative_to(tmp_path / "figure_deliveries")
        for figure in report_result_figures(document))


def test_sealed_q_backfill_is_delivered_only_for_finalized_executions(tmp_path, monkeypatch):
    from test_quantitative_workflow import _prepare_qualified_q0_run
    from src.agents.quantitative_modeling.author_handoff import finalize_quantitative_idea, build_quantitative_author_handoff
    from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
    from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
    from src.agents.research_plan_author.quantitative_evidence_adapter import load_quantitative_evidence_capsule, append_quantitative_evidence_section
    from src.pipeline.quantitative_workflow import execute_quantitative_plan
    from src.result_figures.contracts import DEFAULT_SETTINGS
    from src.result_figures.integration import ensure_quantitative_figures
    from src.result_figures.reporting import report_result_figures
    from src.webapp.artifact_service import artifact_index

    with monkeypatch.context() as disabled:
        disabled.setitem(DEFAULT_SETTINGS, "enabled", False)
        root, identity = _prepare_qualified_q0_run(tmp_path)
        version_dir = root / "quantitative/Q1/v0"
        plan = read_json(version_dir / "simulation_run_plan.json")
        extra = execute_quantitative_plan(run_dir=root, quantitative_idea_id="Q1", version=0,
            execute=True, confirmed_plan_identity=plan["plan_identity"])
        extra_record = read_json(Path(extra["execution_record"]))
        extra_result = read_json(Path(extra["simulation_result"]))
        qualification = qualify_simulation_result({**extra_record, "scenario_results": extra_result["scenario_results"]},
            hypothesis_relation="REFUTED_WITHIN_MODEL", required_validation_checks=plan["qualification_requirements"])
        atomic_write_json(Path(extra["execution_record"]).parent / "result_qualification.json", qualification)
        finalization_path = finalize_quantitative_idea(run_dir=root, quantitative_idea_id="Q1", version=0)
        finalization = read_json(finalization_path)
        publication = publish_quantitative_models_pdf(run_dir=root)
        _, handoff_path = build_quantitative_author_handoff(run_dir=root, quantitative_models_pdf_path=publication["pdf"])

    before = {path: file_sha256(path) for path in (root / "quantitative").rglob("*") if path.is_file()}
    execution_id = finalization["qualified_execution_ids"][0]
    manifest = ensure_quantitative_figures(root, version_dir, execution_id)
    assert manifest["status"] == "SUCCEEDED", manifest
    assert Path(manifest["manifest_path"]).is_relative_to(root / "figure_deliveries")
    assert all(file_sha256(path) == digest for path, digest in before.items())
    assert ensure_quantitative_figures(root, version_dir, execution_id)["manifest_path"] == manifest["manifest_path"]
    document = append_quantitative_evidence_section({"sections": []},
        load_quantitative_evidence_capsule(handoff_path, expected_identity=identity))
    figures = report_result_figures(document)
    assert figures and all(Path(figure["source_path"]).is_relative_to(root / "figure_deliveries") for figure in figures)
    indexed = artifact_index(science_run_paths(root), {})
    assert any(path.is_relative_to(root / "figure_deliveries") and path.suffix == ".png" for path in indexed.values())
    _render_author_with_figures(tmp_path, document, figures)
    extra_manifest = ensure_quantitative_figures(root, version_dir, extra_record["execution_id"])
    assert extra_manifest["status"] == "SUCCEEDED", extra_manifest
    with pytest.raises(FigureError, match="detached_figure_without_report_evidence"):
        report_result_figures(document)
