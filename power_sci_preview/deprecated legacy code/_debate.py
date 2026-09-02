from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

QWEN_RESEARCH_ROLE_MODELS = frozenset({"qwen-max", "qwen-deep-research"})
import ast
import json
import re
import time
import xml.etree.ElementTree as ET

try:
    from .log import log_event
except ImportError:
    from log import log_event


def bianlun_minimal_commitment_consensus(
    controversy_matrix: list[dict[str, Any]],
    yanzhen_body: dict[str, Any],
) -> dict[str, Any]:
    """Summarize a debate by retaining only claims not overturned by evidence."""
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    retained_claims: list[dict[str, Any]] = []
    remaining_uncertainty: list[str] = []
    decisive_experiments: list[str] = []
    for item in controversy_matrix:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        conclusion = str(item.get("current_conclusion") or "").strip()
        supporting = item.get("supporting_evidence", []) if isinstance(item.get("supporting_evidence"), list) else []
        challenges = item.get("challenge_evidence", []) if isinstance(item.get("challenge_evidence"), list) else []
        alternatives = item.get("alternative_explanations", []) if isinstance(item.get("alternative_explanations"), list) else []
        experiment = str(item.get("decisive_experiment") or "").strip()
        if claim and conclusion == "NOT_REJECTED_UNDER_CURRENT_EVIDENCE" and supporting:
            retained_claims.append(
                {
                    "claim": claim,
                    "status": "NOT_REJECTED_UNDER_CURRENT_EVIDENCE",
                    "supporting_evidence_count": len(supporting),
                    "why_retained": "No reviewed project evidence currently overturns this claim in the stated context.",
                }
            )
        if claim and conclusion != "NOT_REJECTED_UNDER_CURRENT_EVIDENCE":
            remaining_uncertainty.append(f"{claim}: {conclusion or 'insufficiently resolved'}")
        remaining_uncertainty.extend(
            str(entry.get("summary") or entry.get("reason") or entry)
            for entry in challenges[:3]
            if entry
        )
        remaining_uncertainty.extend(str(entry) for entry in alternatives[:3] if entry)
        if experiment:
            decisive_experiments.append(experiment)
    overall = str(yanzhen_body.get("overall_verdict") or "") if isinstance(yanzhen_body, dict) else ""
    if overall and overall != "NOT_REJECTED_UNDER_CURRENT_EVIDENCE":
        remaining_uncertainty.append(f"YanZhen overall assessment: {overall}")
    return {
        "method": "evidence-weighted minimum commitment; not majority voting",
        "status": "NOT_REJECTED_UNDER_CURRENT_EVIDENCE" if retained_claims else "INSUFFICIENTLY_RESOLVED",
        "retained_claims": retained_claims,
        "remaining_uncertainty": unique_preserve_order(remaining_uncertainty)[:20],
        "next_discriminating_experiment": unique_preserve_order(decisive_experiments)[:6],
        "interpretation": "The consensus authorizes focused discrimination experiments; it does not establish the mechanism as fact.",
    }



def run_socratic_hypothesis_debate(
    project_id: str,
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_rounds: int = 5,
    proponent_model_family: str = "qwen-max",
    opponent_model_family: str = "qwen-max",
    judge_model_family: str = "qwen-deep-research",
    verifier_model_family: str = "qwen-deep-research",
    shifted_conditions: list[Any] | None = None,
    auto_literature_supplement: bool = True,
    supplement_providers: list[str] | None = None,
) -> str:
    try:
        from ._project import load_project, save_project
        from ._supplement import zhizhi_supplement_from_audit
        from ._utils import clamp_int, new_id
        from ._verification import extract_causal_chain, run_yanzhen_mechanism_verification, yanzhen_mechanism_text, yanzhen_sources_for_hypothesis
    except ImportError:
        from _project import load_project, save_project
        from _supplement import zhizhi_supplement_from_audit
        from _utils import clamp_int, new_id
        from _verification import extract_causal_chain, run_yanzhen_mechanism_verification, yanzhen_mechanism_text, yanzhen_sources_for_hypothesis
    project = load_project(project_id)
    record = debate_hypothesis_record(project, hypothesis_id) if hypothesis_id else {}
    hypothesis_package = debate_hypothesis_package(record)
    text = hypothesis or debate_hypothesis_text(record)
    if not text:
        raise ValueError("BianLun requires hypothesis text or hypothesis_id.")
    safety = debate_safety_gates(
        proponent_model_family=proponent_model_family,
        opponent_model_family=opponent_model_family,
        judge_model_family=judge_model_family,
        verifier_model_family=verifier_model_family,
    )
    if not safety["passed"]:
        report = {
            "thought": "BianLun stopped before debate because an ARIS-style safety gate failed.",
            "action": {"type": "run_socratic_hypothesis_debate", "status": "blocked"},
            "debate_report": {
                "debate_id": new_id("debate"),
                "hypothesis_id": hypothesis_id,
                "rounds": [],
                "safety_gates": safety,
                "refined_hypothesis": {},
                "unresolved_issues": safety["issues"],
                "final_decision": "human_review",
            },
        }
        project.setdefault("socratic_debates", []).append(report["debate_report"])
        project["phase"] = "Socratic Debate"
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(report, ensure_ascii=False, indent=2)

    rounds: list[dict[str, Any]] = []
    max_rounds = clamp_int(max_rounds, 4, 5)
    mechanism = yanzhen_mechanism_text(record) or text
    sources = yanzhen_sources_for_hypothesis(project, record)
    working_text = text
    working_mechanism = mechanism
    yanzhen_body: dict[str, Any] = {}

    # AHOIS-style quality tracking across rounds
    quality_history: list[dict[str, Any]] = []
    initial_quality = evaluate_hypothesis_quality(working_text, working_mechanism, sources)
    quality_history.append({"round": 0, "phase": "initial", **initial_quality})
    log_event("SCIENCE", "socratic_quality_baseline",
              overall=initial_quality["overall"],
              pc=initial_quality["physics_consistency"],
              hc=initial_quality["hypothesis_completeness"],
              uc=initial_quality["uncertainty_calibration"])

    round1_questions = duzhi_generate_questions(
        working_text,
        working_mechanism,
        sources,
        allowed_types=["conceptual_clarification", "constraint_check"],
        max_questions=8,
    )
    # Coverage questions are role-specific (scope, mechanism, boundary,
    # alternative, measurement, transfer, falsification, evidence).  They are
    # generated from persisted package slots rather than subject keywords, so
    # the same debate contract applies across natural-science domains.
    try:
        from ._hypothesis_coverage import package_debate_questions
    except ImportError:
        from _hypothesis_coverage import package_debate_questions
    package_questions = package_debate_questions(hypothesis_package)
    existing_requirements = {str(item.get("required_revision") or "") for item in round1_questions if isinstance(item, dict)}
    round1_questions.extend(
        item for item in package_questions
        if str(item.get("required_revision") or "") not in existing_requirements
    )
    round1_revision = mingli_revision_from_questions(
        project,
        record,
        working_text,
        working_mechanism,
        round1_questions,
        {},
        "Socratic Clarification",
    )
    working_text = str(round1_revision.get("revised_hypothesis") or working_text)
    working_mechanism = str(round1_revision.get("revised_mechanism") or working_mechanism)
    r1_quality = evaluate_hypothesis_quality(working_text, working_mechanism, sources)
    quality_history.append({"round": 1, "phase": "Socratic Clarification", **r1_quality})
    rounds.append(
        {
            "round": 1,
            "name": "Socratic Clarification",
            "proponent_position": debate_proponent_position(text, mechanism, record),
            "opponent_questions": round1_questions,
            "proponent_response": round1_revision,
            "coverage_slot_revisions": debate_round_coverage_revision(hypothesis_package, round1_questions, round1_revision),
            "quality_scores": r1_quality,
            "quality_delta": round(r1_quality["overall"] - quality_history[-2]["overall"], 2),
            "moderator_verdict": "revise" if any(q.get("severity") in {"high", "fatal"} for q in round1_questions) else "advance",
        }
    )
    if max_rounds >= 2:
        yanzhen_json = json.loads(
            run_yanzhen_mechanism_verification(
                project_id,
                hypothesis=working_text,
                reasoning_chain=extract_causal_chain(f"{working_text} {working_mechanism}"),
                original_sources=sources,
                shifted_conditions=shifted_conditions,
            )
        )
        yanzhen_body = yanzhen_json.get("mechanism_fidelity_report", {})
        round2_questions = duzhi_generate_questions(
            working_text,
            working_mechanism,
            sources,
            allowed_types=["causal_probe", "constraint_check"],
            max_questions=8,
            yanzhen_report=yanzhen_body,
        )
        round2_questions = filter_new_debate_questions(round2_questions, rounds, min_keep=3)
        round2_revision = mingli_revision_from_questions(
            project,
            record,
            working_text,
            working_mechanism,
            round2_questions,
            yanzhen_body,
            "Evidence and CAWM Layer 1-2",
        )
        working_text = str(round2_revision.get("revised_hypothesis") or working_text)
        working_mechanism = str(round2_revision.get("revised_mechanism") or working_mechanism)
        r2_quality = evaluate_hypothesis_quality(working_text, working_mechanism, sources)
        quality_history.append({"round": 2, "phase": "Evidence and CAWM Layer 1-2", **r2_quality})
        r2_delta = round(r2_quality["overall"] - quality_history[-2]["overall"], 2)
        log_event("SCIENCE", "socratic_quality_round", round=2, overall=r2_quality["overall"], delta=r2_delta)
        rounds.append(
            {
                "round": 2,
                "name": "Evidence and CAWM Layer 1-2",
                "yanzhen_report": yanzhen_body,
                "opponent_questions": round2_questions,
                "proponent_response": round2_revision,
                "coverage_slot_revisions": debate_round_coverage_revision(hypothesis_package, round2_questions, round2_revision),
                "quality_scores": r2_quality,
                "quality_delta": r2_delta,
                "moderator_verdict": "revise" if yanzhen_body.get("overall_verdict") in {"CAWM_DETECTED", "REQUIRES_HUMAN_REVIEW"} else "advance",
            }
        )
    if max_rounds >= 3:
        round3_questions = duzhi_generate_questions(
            working_text,
            working_mechanism,
            sources,
            allowed_types=["counterexample_challenge", "constraint_check"],
            max_questions=8,
            yanzhen_report=yanzhen_body,
        )
        round3_questions = filter_new_debate_questions(round3_questions, rounds, min_keep=3)
        round3_revision = mingli_revision_from_questions(
            project,
            record,
            working_text,
            working_mechanism,
            round3_questions,
            yanzhen_body,
            "Methodology and Regime Shift",
        )
        working_text = str(round3_revision.get("revised_hypothesis") or working_text)
        working_mechanism = str(round3_revision.get("revised_mechanism") or working_mechanism)
        r3_quality = evaluate_hypothesis_quality(working_text, working_mechanism, sources)
        quality_history.append({"round": 3, "phase": "Methodology and Regime Shift", **r3_quality})
        r3_delta = round(r3_quality["overall"] - quality_history[-2]["overall"], 2)
        # Convergence detection: if last 2 deltas are both < 0.1, quality has plateaued
        convergence_detected = False
        if len(quality_history) >= 3:
            prev_delta = quality_history[-2]["overall"] - quality_history[-3]["overall"]
            if r3_delta < 0.1 and prev_delta < 0.1:
                convergence_detected = True
                log_event("SCIENCE", "socratic_convergence_detected",
                          round=3, overall=r3_quality["overall"],
                          last_two_deltas=[round(prev_delta, 2), r3_delta])
        else:
            log_event("SCIENCE", "socratic_quality_round", round=3, overall=r3_quality["overall"], delta=r3_delta)
        layer3 = yanzhen_body.get("layer_3_regime_shift_test", {}) if isinstance(yanzhen_body, dict) else {}
        rounds.append(
            {
                "round": 3,
                "name": "Methodology and Regime Shift",
                "experiment_plan": record.get("test_plan") or debate_experiment_text(record),
                "regime_shift_summary": layer3,
                "opponent_questions": round3_questions,
                "proponent_response": round3_revision,
                "coverage_slot_revisions": debate_round_coverage_revision(hypothesis_package, round3_questions, round3_revision),
                "quality_scores": r3_quality,
                "quality_delta": r3_delta,
                "convergence_detected": convergence_detected,
                "moderator_verdict": "converge" if convergence_detected else ("revise" if layer3.get("cawm_risk_level") == "HIGH" or any(q.get("severity") in {"high", "fatal"} for q in round3_questions) else "advance"),
            }
        )
    if max_rounds >= 4:
        final_yanzhen_body = yanzhen_body
        if working_text != text and max_rounds >= 3:
            try:
                final_yanzhen_json = json.loads(
                    run_yanzhen_mechanism_verification(
                        project_id,
                        hypothesis=working_text,
                        reasoning_chain=extract_causal_chain(f"{working_text} {working_mechanism}"),
                        original_sources=sources,
                        shifted_conditions=shifted_conditions,
                    )
                )
                final_yanzhen_body = final_yanzhen_json.get("mechanism_fidelity_report", yanzhen_body)
            except Exception:
                final_yanzhen_body = yanzhen_body
        yanzhen_body = final_yanzhen_body
        audit_feedback = yanzhen_debate_feedback(yanzhen_body)
        literature_supplement: dict[str, Any] = {"attempted": False, "reason": "not required"}
        if auto_literature_supplement and yanzhen_body.get("verdict") != "PASS" and yanzhen_body.get("unsupported_claims"):
            literature_supplement = zhizhi_supplement_from_audit(
                project_id=project_id,
                audit_report=yanzhen_body,
                hypothesis_text=working_text,
                providers=supplement_providers,
                max_claims=2,
                per_claim_imports=1,
                use_llm=True,
            )
            if literature_supplement.get("attempted") and literature_supplement.get("imports"):
                project = load_project(project_id)
                sources = yanzhen_sources_for_hypothesis(project, record)
                try:
                    refreshed_json = json.loads(
                        run_yanzhen_mechanism_verification(
                            project_id,
                            hypothesis=working_text,
                            reasoning_chain=extract_causal_chain(f"{working_text} {working_mechanism}"),
                            original_sources=sources,
                            shifted_conditions=shifted_conditions,
                        )
                    )
                    yanzhen_body = refreshed_json.get("mechanism_fidelity_report", yanzhen_body)
                    audit_feedback = yanzhen_debate_feedback(yanzhen_body)
                except Exception:
                    pass
        if yanzhen_body.get("verdict") != "PASS" and max_rounds >= 5:
            audit_questions = duzhi_questions_from_yanzhen_actions(yanzhen_body, working_text, working_mechanism)
            audit_questions = filter_new_debate_questions(audit_questions, rounds, min_keep=2)
            round4_revision = mingli_revision_from_questions(
                project,
                record,
                working_text,
                working_mechanism,
                audit_questions,
                yanzhen_body,
                "Mechanism Audit Feedback",
            )
            working_text = str(round4_revision.get("revised_hypothesis") or working_text)
            working_mechanism = str(round4_revision.get("revised_mechanism") or working_mechanism)
            rounds.append(
                {
                    "round": 4,
                    "name": "Mechanism Audit Feedback and Literature Completion",
                    "yanzhen_report": yanzhen_body,
                    "audit_feedback": audit_feedback,
                    "literature_supplement": literature_supplement,
                    "opponent_questions": audit_questions,
                    "proponent_response": round4_revision,
                    "coverage_slot_revisions": debate_round_coverage_revision(hypothesis_package, audit_questions, round4_revision),
                    "moderator_verdict": "revise" if yanzhen_body.get("verdict") != "PASS" else "advance",
                }
            )
            try:
                final_after_revision_json = json.loads(
                    run_yanzhen_mechanism_verification(
                        project_id,
                        hypothesis=working_text,
                        reasoning_chain=extract_causal_chain(f"{working_text} {working_mechanism}"),
                        original_sources=sources,
                        shifted_conditions=shifted_conditions,
                    )
                )
                yanzhen_body = final_after_revision_json.get("mechanism_fidelity_report", yanzhen_body)
            except Exception:
                pass
        refined = debate_refined_hypothesis(project, record, working_text, working_mechanism, rounds, yanzhen_body)
        execution_validation = execution_level_validation(project, refined, yanzhen_body, rounds)
        final_decision = debate_final_decision(rounds, yanzhen_body, refined, execution_validation)
        final_round_number = 5 if max_rounds >= 5 and any(item.get("round") == 4 and item.get("name") == "Mechanism Audit Feedback and Literature Completion" for item in rounds) else 4
        rounds.append(
            {
                "round": final_round_number,
                "name": "Synthesis and Convergence",
                "refined_hypothesis": refined,
                "yanzhen_report": yanzhen_body,
                "audit_feedback": yanzhen_debate_feedback(yanzhen_body),
                "execution_validation": execution_validation,
                "final_decision": final_decision,
                "moderator_verdict": "finalize" if final_decision == "accept_for_experiment" else final_decision,
            }
        )
    else:
        refined = debate_refined_hypothesis(project, record, working_text, working_mechanism, rounds, yanzhen_body)
        execution_validation = execution_level_validation(project, refined, yanzhen_body, rounds)
        final_decision = debate_final_decision(rounds, yanzhen_body, refined, execution_validation)

    unresolved = debate_unresolved_issues(
        [q for round_item in rounds for q in round_item.get("opponent_questions", []) if isinstance(q, dict)],
        yanzhen_body,
    )
    controversy_matrix = yanzhen_body.get("controversy_matrix", []) if isinstance(yanzhen_body, dict) else []
    consensus = bianlun_minimal_commitment_consensus(controversy_matrix, yanzhen_body)
    unresolved = list(dict.fromkeys(unresolved + list(consensus.get("remaining_uncertainty", []))))[:20]
    debate_report = {
        "debate_id": new_id("debate"),
        "hypothesis_id": hypothesis_id or str(record.get("hypothesis_id") or ""),
        "model_families": {
            "proponent": proponent_model_family,
            "opponent": opponent_model_family,
            "judge": judge_model_family,
            "verifier": verifier_model_family,
        },
        "rounds": rounds,
        "debate_state": {},
        "quality_trajectory": quality_history,
        "final_quality": quality_history[-1] if quality_history else {},
        "safety_gates": safety,
        "refined_hypothesis": refined,
        "controversy_matrix": controversy_matrix,
        "consensus": consensus,
        "hypothesis_package": hypothesis_package,
        "coverage_changes": debate_package_coverage_changes(hypothesis_package, rounds),
        "unresolved_issues": unresolved,
        "final_decision": final_decision,
    }
    debate_report["debate_state"] = build_debate_state(
        hypothesis_id=debate_report["hypothesis_id"],
        rounds=rounds,
        max_rounds=max_rounds,
        unresolved=unresolved,
        final_decision=final_decision,
        coverage_changes=debate_report["coverage_changes"],
    )
    project = load_project(project_id)
    project.setdefault("socratic_debates", []).append(debate_report)
    project.setdefault("hypothesis_revisions", []).append(
        {
            "revision_id": new_id("rev"),
            "hypothesis_id": debate_report["hypothesis_id"],
            "source_debate_id": debate_report["debate_id"],
            "refined_hypothesis": refined,
            "decision": final_decision,
            "createdAt": time.time(),
        }
    )
    project["phase"] = "Socratic Debate"
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "socratic_debate_completed", project_id=project_id, hypothesis_id=debate_report["hypothesis_id"], decision=final_decision)
    return json.dumps(
        {
            "thought": "BianLun ran the triangle loop: Socratic debate, YanZhen mechanism audit, targeted literature completion when needed, MingLi revision, and final synthesis.",
            "action": {"type": "run_socratic_hypothesis_debate", "rounds": len(rounds), "max_rounds": max_rounds},
            "debate_report": debate_report,
        },
        ensure_ascii=False,
        indent=2,
    )


def debate_output_meets_hypothesis_requirements(report: dict[str, Any]) -> bool:
    """Return whether one debate iteration produced an executable hypothesis."""
    if str(report.get("final_decision") or "") != "accept_for_experiment":
        return False
    refined = report.get("refined_hypothesis") if isinstance(report.get("refined_hypothesis"), dict) else {}
    final_round = next(
        (
            item for item in reversed(report.get("rounds", []))
            if isinstance(item, dict) and isinstance(item.get("execution_validation"), dict)
        ),
        {},
    )
    execution = final_round.get("execution_validation") if isinstance(final_round.get("execution_validation"), dict) else {}
    return bool(
        str(refined.get("hypothesis") or "").strip()
        and len(refined.get("causal_chain", [])) >= 3
        and bool(refined.get("falsification_conditions"))
        and bool(refined.get("evidence_requirements"))
        and execution.get("verdict") == "PASS"
    )


def persist_mingli_debate_revision(
    project_id: str,
    source_hypothesis_id: str,
    report: dict[str, Any],
    iteration: int,
    accepted: bool,
) -> str:
    try:
        from ._project import load_project, save_project
        from ._utils import new_id
    except ImportError:
        from _project import load_project, save_project
        from _utils import new_id
    project = load_project(project_id)
    source = debate_hypothesis_record(project, source_hypothesis_id)
    refined = report.get("refined_hypothesis") if isinstance(report.get("refined_hypothesis"), dict) else {}
    statement = str(refined.get("hypothesis") or "").strip()
    if not statement:
        return ""
    hypothesis_id = new_id("hyp")
    revision = {
        "hypothesis_id": hypothesis_id,
        "project_id": project_id,
        "gap_id": str(source.get("gap_id") or ""),
        "statement": statement,
        "mechanism": " -> ".join(str(item) for item in refined.get("causal_chain", []) if item),
        "expected_value": "Debate-refined, evidence-bounded causal hypothesis.",
        "test_plan": " ".join(str(item) for item in refined.get("falsification_conditions", []) if item),
        "falsification_conditions": list(refined.get("falsification_conditions") or []),
        "evidence_requirements": list(refined.get("evidence_requirements") or []),
        "regime_shift_requirements": list(refined.get("regime_shift_requirements") or []),
        "source_hypothesis_id": source_hypothesis_id,
        "source_debate_id": str(report.get("debate_id") or ""),
        "debate_iteration": int(iteration),
        "hypothesis_status": "ACCEPTED_AFTER_DEBATE" if accepted else "MINGLI_REVISION_REQUIRED",
        "science_state_handoff": dict(source.get("science_state_handoff") or {}),
        "hypothesis_package": debate_hypothesis_package(source),
        "coverage_changes": dict(report.get("coverage_changes") or {}),
        "conclusion_scope": dict((debate_hypothesis_package(source) or {}).get("conclusion_scope") or {}),
        "createdAt": time.time(),
    }
    project.setdefault("hypotheses", []).append(revision)
    project.setdefault("hypothesis_revisions", []).append(
        {
            "revision_id": new_id("rev"),
            "hypothesis_id": hypothesis_id,
            "source_hypothesis_id": source_hypothesis_id,
            "source_debate_id": revision["source_debate_id"],
            "iteration": int(iteration),
            "decision": str(report.get("final_decision") or ""),
            "accepted": bool(accepted),
            "createdAt": time.time(),
        }
    )
    save_project(project)
    return hypothesis_id


def run_mingli_debate_iteration_loop(
    project_id: str,
    hypothesis_id: str,
    max_iterations: int = 3,
    debate_rounds_per_iteration: int = 5,
    proponent_model_family: str = "qwen-max",
    opponent_model_family: str = "qwen-max",
    judge_model_family: str = "qwen-deep-research",
    verifier_model_family: str = "qwen-deep-research",
    auto_literature_supplement: bool = True,
    supplement_providers: list[str] | None = None,
) -> str:
    """Couple one MingLi revision with each debate until acceptance or stop."""
    try:
        from ._project import load_project, save_project
        from ._utils import clamp_int, new_id, normalize_space
    except ImportError:
        from _project import load_project, save_project
        from _utils import clamp_int, new_id, normalize_space
    limit = clamp_int(max_iterations, 1, 5)
    current_hypothesis_id = str(hypothesis_id or "").strip()
    if not current_hypothesis_id:
        raise ValueError("MingLi-debate iteration requires hypothesis_id")
    loop_id = new_id("mingli_debate_loop")
    iterations: list[dict[str, Any]] = []
    accepted = False
    stop_reason = "MAX_ITERATIONS_REACHED"
    previous_statement = ""
    for iteration in range(1, limit + 1):
        debate = json.loads(
            run_socratic_hypothesis_debate(
                project_id=project_id,
                hypothesis_id=current_hypothesis_id,
                max_rounds=debate_rounds_per_iteration,
                proponent_model_family=proponent_model_family,
                opponent_model_family=opponent_model_family,
                judge_model_family=judge_model_family,
                verifier_model_family=verifier_model_family,
                auto_literature_supplement=auto_literature_supplement,
                supplement_providers=supplement_providers,
            )
        )
        report = debate.get("debate_report") if isinstance(debate.get("debate_report"), dict) else {}
        accepted = debate_output_meets_hypothesis_requirements(report)
        refined = report.get("refined_hypothesis") if isinstance(report.get("refined_hypothesis"), dict) else {}
        statement = normalize_space(str(refined.get("hypothesis") or ""))
        revision_id = persist_mingli_debate_revision(
            project_id,
            current_hypothesis_id,
            report,
            iteration,
            accepted,
        )
        iterations.append(
            {
                "iteration": iteration,
                "input_hypothesis_id": current_hypothesis_id,
                "debate_id": str(report.get("debate_id") or ""),
                "decision": str(report.get("final_decision") or ""),
                "output_hypothesis_id": revision_id,
                "accepted": accepted,
                "unresolved_issues": list(report.get("unresolved_issues") or [])[:20],
                "quality": dict(report.get("final_quality") or {}),
                "coverage_changes": dict(report.get("coverage_changes") or {}),
            }
        )
        if accepted:
            current_hypothesis_id = revision_id or current_hypothesis_id
            stop_reason = "HYPOTHESIS_ACCEPTED"
            break
        if str(report.get("final_decision") or "") == "human_review":
            stop_reason = "HUMAN_REVIEW_REQUIRED"
            break
        if not revision_id or (previous_statement and statement == previous_statement):
            stop_reason = "NO_SUBSTANTIVE_REVISION"
            break
        previous_statement = statement
        current_hypothesis_id = revision_id

    project = load_project(project_id)
    loop_report = {
        "loop_id": loop_id,
        "project_id": project_id,
        "initial_hypothesis_id": hypothesis_id,
        "final_hypothesis_id": current_hypothesis_id,
        "status": "ACCEPTED" if accepted else "REVISION_REQUIRED",
        "stop_reason": stop_reason,
        "iterations_completed": len(iterations),
        "max_iterations": limit,
        "iterations": iterations,
        "createdAt": time.time(),
    }
    project.setdefault("mingli_debate_iterations", []).append(loop_report)
    project["active_hypothesis_id"] = current_hypothesis_id
    project["hypothesis_acceptance_status"] = loop_report["status"]
    save_project(project)
    return json.dumps(loop_report, ensure_ascii=False, indent=2)

def debate_hypothesis_record(project: dict[str, Any], hypothesis_id: str) -> dict[str, Any]:
    try:
        from ._utils import find_by_id
    except ImportError:
        from _utils import find_by_id
    found = find_by_id(project.get("hypotheses", []), "hypothesis_id", hypothesis_id)
    if found is None:
        found = find_by_id(project.get("mingli_finalized_ideas", []), "hypothesis_id", hypothesis_id)
    if found is None:
        raise ValueError(f"Unknown hypothesis_id for project {project.get('project_id', '')}: {hypothesis_id}")
    return found


def debate_hypothesis_package(record: dict[str, Any]) -> dict[str, Any]:
    """Return the package that bounded the original MingLi claim, if any."""
    if not isinstance(record, dict):
        return {}
    direct = record.get("hypothesis_package")
    if isinstance(direct, dict):
        return direct
    final = record.get("mingli_final_idea") if isinstance(record.get("mingli_final_idea"), dict) else {}
    packaged = final.get("hypothesis_package") if isinstance(final.get("hypothesis_package"), dict) else {}
    return packaged


def debate_package_coverage_changes(package: dict[str, Any], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Record role-specific debate progress without pretending new evidence exists."""
    if not isinstance(package, dict):
        return {}
    try:
        from ._hypothesis_coverage import package_debate_questions
    except ImportError:
        from _hypothesis_coverage import package_debate_questions
    changes: dict[str, Any] = {}
    requirements = {
        str(question.get("coverage_role") or ""): str(question.get("required_revision") or "")
        for question in package_debate_questions(package)
        if isinstance(question, dict) and str(question.get("coverage_role") or "")
    }
    adopted = {
        str(value)
        for round_item in rounds
        if isinstance(round_item, dict)
        for value in ((round_item.get("proponent_response") or {}).get("adopted_revision_requirements") or [])
        if str(value)
    }
    for role, requirement in requirements.items():
        changes[role] = {
            "status": "REVISION_ADOPTED_PENDING_EVIDENCE" if requirement in adopted else "UNCHANGED_OR_UNRESOLVED",
            "required_revision": requirement,
        }
    return changes


def debate_round_coverage_revision(
    package: dict[str, Any],
    questions: list[dict[str, Any]],
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    """Render per-slot revision outcomes instead of a free-text debate note."""
    if not isinstance(package, dict):
        return []
    adopted = {
        str(item)
        for item in (response.get("adopted_revision_requirements") or [])
        if str(item)
    } if isinstance(response, dict) else set()
    revisions: list[dict[str, Any]] = []
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict) or not str(question.get("coverage_role") or ""):
            continue
        requirement = str(question.get("required_revision") or "")
        revisions.append(
            {
                "slot": str(question.get("coverage_role") or ""),
                "coverage_dimension": str(question.get("question_type") or "").removeprefix("coverage_"),
                "status": "REVISION_ADOPTED_PENDING_EVIDENCE" if requirement in adopted else "UNRESOLVED",
                "required_revision": requirement,
                "evidence_status": "pending_project_evidence_update",
            }
        )
    return revisions

def debate_hypothesis_text(record: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    if not record:
        return ""
    final = record.get("mingli_final_idea") if isinstance(record.get("mingli_final_idea"), dict) else {}
    return normalize_space(
        " ".join(
            str(part)
            for part in (
                final.get("title", ""),
                final.get("hypothesis", ""),
                final.get("abstract", ""),
                record.get("statement", ""),
                record.get("mechanism", ""),
            )
            if part
        )
    )

def duzhi_generate_questions(
    hypothesis_text: str,
    mechanism: str,
    sources: list[Any],
    *,
    allowed_types: list[str] | None = None,
    max_questions: int = 12,
    yanzhen_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._gap_detection import text_jaccard
        from ._utils import clamp_int, normalize_space, trim_text
        from ._verification import default_regime_shifts, extract_causal_chain, render_shift_condition, yanzhen_context_text
    except ImportError:
        from _gap_detection import text_jaccard
        from _utils import clamp_int, normalize_space, trim_text
        from _verification import default_regime_shifts, extract_causal_chain, render_shift_condition, yanzhen_context_text
    allowed = set(allowed_types or [])
    questions: list[dict[str, Any]] = []
    text = normalize_space(f"{hypothesis_text} {mechanism}")
    lowered = text.lower()
    source_text = normalize_space(" ".join(yanzhen_context_text(item) for item in sources))
    evidence_terms = socratic_evidence_terms(sources, text)
    chain = extract_causal_chain(text)

    def include(kind: str) -> bool:
        return not allowed or kind in allowed

    def add(kind: str, question: str, target: str, why: str, revision: str, severity: str) -> None:
        if not include(kind):
            return
        questions.append(
            {
                "question_type": kind,
                "question": question,
                "target_claim": trim_text(target, 220),
                "why_it_matters": why,
                "required_revision": revision,
                "severity": severity,
            }
        )

    if include("conceptual_clarification"):
        if not any(term in lowered for term in ("measure", "metric", "observable", "readout", "quantif", "primary")):
            add(
                "conceptual_clarification",
                "Which part of the hypothesis is directly measurable, and which part is inferred from those measurements?",
                hypothesis_text,
                "AHOIS-style clarification requires separating observables from inferred mechanisms before testing.",
                "Add explicit observables, inferred constructs, and the mapping between them.",
                "high",
            )
        if any(term in lowered for term in ("improve", "enhance", "better", "stable")) and not re.search(r"\b\d+(?:\.\d+)?\s*(?:%|fold|x|times|sigma|unit|score)\b", lowered):
            add(
                "conceptual_clarification",
                "What threshold converts the claimed improvement into a successful result rather than a vague positive trend?",
                hypothesis_text,
                "A falsifiable hypothesis needs a decision threshold or preregistered effect direction.",
                "Define a quantitative or ordinal success threshold and the minimum meaningful effect.",
                "medium",
            )
        if not any(term in lowered for term in ("baseline", "control", "negative control", "standard")):
            add(
                "conceptual_clarification",
                "What is the nearest domain-standard baseline or negative control that would make the claim nontrivial?",
                hypothesis_text,
                "Without a baseline, the hypothesis cannot distinguish genuine mechanism from general performance drift.",
                "Name at least one domain-standard baseline and one failure-mode or negative control.",
                "high",
            )

    if include("constraint_check"):
        if not any(term in lowered for term in ("constraint", "assumption", "boundary", "regime", "limit", "under ", "unless", "when")):
            add(
                "constraint_check",
                "Under what validity regime is the mechanism expected to hold, and where should it fail?",
                mechanism,
                "Unstated boundary conditions are a common CAWM risk under regime shift.",
                "Add explicit assumptions, validity range, and at least one expected failure condition.",
                "high",
            )
        if not any(term in lowered for term in ("data", "sample", "instrument", "simulation", "experiment", "cohort", "dataset", "measurement")):
            add(
                "constraint_check",
                "What data, instrument, simulation, or experimental platform can actually observe the claimed causal step?",
                mechanism,
                "A hypothesis can be conceptually attractive but infeasible if the decisive mechanism is not observable.",
                "Specify the observation platform and feasibility constraint for the decisive causal link.",
                "medium",
            )
        if source_text and text_jaccard(hypothesis_text, source_text) < 0.06:
            add(
                "constraint_check",
                "Which sentence or result in the imported PaperGraph evidence grounds the strongest mechanistic premise?",
                hypothesis_text,
                "ARIS-style evidence gates require claim-to-source traceability, not just thematic similarity.",
                "Map each central premise to a PaperGraph citation or mark it as speculative.",
                "high",
            )
        if evidence_terms:
            term_list = ", ".join(evidence_terms[:5])
            add(
                "constraint_check",
                f"The evidence repeatedly mentions {term_list}; which of these domain-specific constraints is actually required for the mechanism to hold?",
                mechanism,
                "A strong critique should test the hypothesis against the concrete variables found in the retrieved literature, not only generic stress tests.",
                "Name the required evidence-derived constraint, its allowed range or qualitative regime, and how it will be monitored.",
                "medium",
            )

    if include("causal_probe"):
        if len(chain) < 2:
            add(
                "causal_probe",
                "Can you rewrite the hypothesis as an explicit input -> mechanism -> output chain with evidence for each arrow?",
                hypothesis_text,
                "A single broad sentence hides missing causal links and prevents targeted revision.",
                "Provide a three-to-five-step causal chain and cite or label the evidence for each link.",
                "fatal",
            )
        if any(term in lowered for term in ("because", "therefore", "leads to", "causes", "drives")) and not source_text:
            add(
                "causal_probe",
                "What source evidence supports the causal connector rather than only the endpoint observation?",
                mechanism,
                "Causal connectors are where correct-answer/wrong-mechanism failures often enter.",
                "Add evidence for the causal link or downgrade it to a testable assumption.",
                "high",
            )
        if evidence_terms:
            add(
                "causal_probe",
                f"For the evidence-derived terms {', '.join(evidence_terms[:4])}, which exact term sits at the intervention, mediator, and output positions of the causal chain?",
                mechanism,
                "Domain-targeted causal probing forces MingLi to connect the hypothesis to field-specific entities without hardcoding the field.",
                "Rewrite the causal chain using at least two evidence-derived terms and mark unsupported links as assumptions.",
                "high",
            )
        report = yanzhen_report or {}
        layer_1 = report.get("layer_1_internal_consistency", {}) if isinstance(report, dict) else {}
        for issue in layer_1.get("issues_found", [])[:3] if isinstance(layer_1.get("issues_found"), list) else []:
            add(
                "causal_probe",
                f"How will the hypothesis be revised to address YanZhen Layer 1 issue: {issue}",
                mechanism,
                "Internal consistency issues must be resolved before evidence or experiments can rescue the claim.",
                "Revise the mechanism so the logical chain is explicit and self-consistent.",
                "fatal" if "unsupported causal link" in str(issue).lower() else "high",
            )

    if include("counterexample_challenge"):
        shifts = default_regime_shifts(text)
        for shift in shifts[:3]:
            add(
                "counterexample_challenge",
                f"What outcome should occur if {render_shift_condition(shift)}, and would that falsify the mechanism or only weaken it?",
                mechanism,
                "Counterexamples reveal whether the mechanism has real explanatory content across regimes.",
                "Add predicted behavior under this shifted condition and define pass/fail interpretation.",
                "medium",
            )
        report = yanzhen_report or {}
        layer_3 = report.get("layer_3_regime_shift_test", {}) if isinstance(report, dict) else {}
        if layer_3.get("cawm_risk_level") in {"MEDIUM", "HIGH"}:
            add(
                "counterexample_challenge",
                f"YanZhen reports {layer_3.get('cawm_risk_level')} CAWM risk; which assumption collapses first under regime shift?",
                mechanism,
                "The debate must localize the brittle assumption before accepting a refined hypothesis.",
                "Name the brittle assumption, restrict the validity regime, or propose a discriminating test.",
                "fatal" if layer_3.get("cawm_risk_level") == "HIGH" else "high",
            )

    if not questions:
        add(
            "causal_probe" if include("causal_probe") else "conceptual_clarification",
            "What single observation would most strongly change your belief in this hypothesis?",
            hypothesis_text,
            "Even apparently complete hypotheses need a belief-updating observation to remain falsifiable.",
            "Add a decisive observation and the expected update direction.",
            "low",
        )
    questions = dedupe_socratic_questions(questions)
    severity_rank = {"fatal": 4, "high": 3, "medium": 2, "low": 1}
    questions.sort(key=lambda item: (-severity_rank.get(str(item.get("severity")), 0), item.get("question_type", ""), item.get("question", "")))
    return questions[: clamp_int(max_questions, 1, 40)]

def socratic_evidence_terms(sources: list[Any], fallback_text: str = "", limit: int = 8) -> list[str]:
    try:
        from ._literature_import import is_low_information_field
        from ._literature_search import query_terms
        from ._utils import clamp_int, is_unknown_value, normalize_label, unique_preserve_order
        from ._verification import yanzhen_context_text
    except ImportError:
        from _literature_import import is_low_information_field
        from _literature_search import query_terms
        from _utils import clamp_int, is_unknown_value, normalize_label, unique_preserve_order
        from _verification import yanzhen_context_text
    records: list[dict[str, Any]] = [item for item in sources if isinstance(item, dict)]
    terms: list[str] = []
    for record in records:
        for key in ("method", "scenario", "benchmark"):
            value = normalize_label(record.get(key, ""))
            if value and not is_unknown_value(value) and not is_low_information_field(value, key):
                terms.append(value)
    if not terms:
        source_text = " ".join(yanzhen_context_text(item) for item in sources)
        terms = query_terms(source_text or fallback_text)
    return unique_preserve_order(term for term in terms if term and len(term) >= 3)[: clamp_int(limit, 1, 20)]

def dedupe_socratic_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in questions:
        key = normalize_key(str(item.get("question") or ""))[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def filter_new_debate_questions(
    questions: list[dict[str, Any]],
    previous_rounds: list[dict[str, Any]],
    *,
    min_keep: int = 2,
) -> list[dict[str, Any]]:
    previous: set[str] = set()
    for round_item in previous_rounds:
        for item in round_item.get("opponent_questions", []) if isinstance(round_item.get("opponent_questions"), list) else []:
            previous.add(question_similarity_key(str(item.get("question") or "")))
    fresh: list[dict[str, Any]] = []
    repeats: list[dict[str, Any]] = []
    for item in questions:
        key = question_similarity_key(str(item.get("question") or ""))
        if key and key in previous:
            repeated = dict(item)
            repeated["repeated_from_prior_round"] = True
            repeats.append(repeated)
            continue
        fresh.append(item)
    if len(fresh) >= min_keep:
        return fresh
    return fresh + repeats[: max(0, min_keep - len(fresh))]

def question_similarity_key(question: str) -> str:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    terms = [term for term in query_terms(question) if term not in {"hypothesis", "mechanism", "evidence", "claim"}]
    return " ".join(terms[:10])

def socratic_overall_severity(questions: list[dict[str, Any]]) -> str:
    order = ["low", "medium", "high", "fatal"]
    best = 0
    for item in questions:
        try:
            best = max(best, order.index(str(item.get("severity") or "low")))
        except ValueError:
            continue
    return order[best]


def evaluate_hypothesis_quality(hypothesis_text: str, mechanism: str = "", sources: list | None = None) -> dict[str, Any]:
    """Evaluate hypothesis on three AHOIS-inspired dimensions (0.0-5.0 each).

    Dimensions:
    - physics_consistency: absence of internal contradictions, presence of domain constraints,
      causal chain completeness.
    - hypothesis_completeness: coverage of method/scenario/benchmark components, evidence
      linkage to PaperGraph sources, causal chain length.
    - uncertainty_calibration: distinguishing established facts from assumptions and
      unresolved propositions, hedging language, falsification criteria.

    Returns dict with per-dimension scores, overall score, and convergence-ready flag.
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(f"{hypothesis_text} {mechanism}").lower()
    if not text.strip():
        return {"physics_consistency": 0.0, "hypothesis_completeness": 0.0,
                "uncertainty_calibration": 0.0, "overall": 0.0, "convergence_ready": False}

    # --- Physics Consistency (0-5) ---
    pc_score = 2.0  # baseline
    # Constraint/boundary terms → positive signal
    constraint_terms = ["constraint", "assumption", "boundary", "regime", "limit",
                        "condition", "threshold", "conservation", "equilibrium"]
    constraint_hits = sum(1 for t in constraint_terms if t in text)
    pc_score += min(constraint_hits * 0.3, 1.5)
    # Contradiction markers → negative signal
    contradiction_terms = ["contradicts", "inconsistent", "conflicts with", "paradox",
                           "however", "although", "despite", "nevertheless"]
    contradiction_hits = sum(1 for t in contradiction_terms if t in text)
    if contradiction_hits >= 3:
        pc_score -= 0.5  # many hedging terms without resolution
    elif contradiction_hits == 0:
        pc_score += 0.3  # clean logic
    # Causal chain presence
    causal_markers = ["because", "leads to", "causes", "results in", "therefore",
                      "consequently", "triggers", "mechanism"]
    causal_hits = sum(1 for t in causal_markers if t in text)
    pc_score += min(causal_hits * 0.3, 1.0)
    pc_score = max(0.0, min(5.0, pc_score))

    # --- Hypothesis Completeness (0-5) ---
    hc_score = 1.5  # baseline
    # Method/scenario/benchmark coverage
    component_terms = {
        "method": ["method", "technique", "algorithm", "model", "approach", "framework",
                    "simulation", "experiment", "measurement", "analysis"],
        "scenario": ["scenario", "system", "environment", "condition", "setup",
                      "application", "domain", "context", "case"],
        "benchmark": ["benchmark", "metric", "measure", "indicator", "criterion",
                       "accuracy", "efficiency", "performance", "yield", "rate"],
    }
    for component, terms in component_terms.items():
        hits = sum(1 for t in terms if t in text)
        hc_score += min(hits * 0.2, 0.5)
    # Evidence linkage
    source_count = len(sources) if sources else 0
    if source_count >= 3:
        hc_score += 0.5
    elif source_count >= 1:
        hc_score += 0.25
    # Numerical specificity
    if re.search(r"\b\d+\.?\d*\s*(?:%|fold|times|sigma|units|score|kV|MW|km|°C)\b", text):
        hc_score += 0.5
    # Causal chain length (from extract_causal_chain)
    chain = extract_causal_chain(text)
    chain_steps = len(chain.get("steps", []))
    if chain_steps >= 3:
        hc_score += 0.5
    elif chain_steps >= 2:
        hc_score += 0.25
    hc_score = max(0.0, min(5.0, hc_score))

    # --- Uncertainty Calibration (0-5) ---
    uc_score = 1.5  # baseline
    # Hedging/uncertainty markers → positive (distinguishes known from assumed)
    hedge_terms = ["assumed", "hypothesized", "predicted", "likely", "possible",
                   "uncertain", "unresolved", "to be determined", "pending",
                   "preliminary", "tentative", "estimated"]
    hedge_hits = sum(1 for t in hedge_terms if t in text)
    uc_score += min(hedge_hits * 0.3, 1.0)
    # Falsification criteria
    falsification_terms = ["falsif", "refut", "disprov", "test criterion",
                           "pass criterion", "fail if", "reject if"]
    falsification_hits = sum(1 for t in falsification_terms if t in text)
    uc_score += min(falsification_hits * 0.5, 1.0)
    # Established vs assumed distinction
    distinction_terms = ["established", "known", "shown", "demonstrated",
                         "we assume", "we hypothesize", "it is proposed"]
    distinction_hits = sum(1 for t in distinction_terms if t in text)
    uc_score += min(distinction_hits * 0.3, 0.5)
    uc_score = max(0.0, min(5.0, uc_score))

    overall = round((pc_score + hc_score + uc_score) / 3.0, 2)
    convergence_ready = pc_score >= 4.0 and hc_score >= 3.5 and uc_score >= 3.0

    return {
        "physics_consistency": round(pc_score, 2),
        "hypothesis_completeness": round(hc_score, 2),
        "uncertainty_calibration": round(uc_score, 2),
        "overall": overall,
        "convergence_ready": convergence_ready,
    }

def debate_safety_gates(
    *,
    proponent_model_family: str,
    opponent_model_family: str,
    judge_model_family: str,
    verifier_model_family: str,
) -> dict[str, Any]:
    # Independence comes from role prompts and adversarial structure, while the
    # model contract remains limited to the two approved Qwen research models.
    role_models = {
        "proponent": str(proponent_model_family or "").strip().lower(),
        "opponent": str(opponent_model_family or "").strip().lower(),
        "judge": str(judge_model_family or "").strip().lower(),
        "verifier": str(verifier_model_family or "").strip().lower(),
    }
    invalid_models = {
        role: model
        for role, model in role_models.items()
        if model not in QWEN_RESEARCH_ROLE_MODELS
    }
    issues = [
        f"{role} model '{model or '<missing>'}' is not an approved Qwen research model."
        for role, model in invalid_models.items()
    ]
    return {
        "passed": not issues,
        "issues": issues,
        "warnings": [],
        "independence": {
            "proponent_model_family": proponent_model_family,
            "opponent_model_family": opponent_model_family,
            "judge_model_family": judge_model_family,
            "verifier_model_family": verifier_model_family,
            "policy": "All-Qwen multi-role setup (qwen-max/qwen-deep-research). Independence is enforced by role prompts.",
        },
        "evidence_gate": "Debate revisions are adopted only if tied to PaperGraph evidence, YanZhen issue, or an explicit missing-evidence condition.",
        "convergence_gate": "If two rounds add no substantive revision, terminate with best current hypothesis and unresolved issues.",
    }

def is_qwen_model_id(value: str) -> bool:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    normalized = normalize_key(value)
    return normalized.startswith("qwen") or normalized.startswith("tongyi") or normalized.startswith("dashscope")

def debate_proponent_position(text: str, mechanism: str, record: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import trim_text
        from ._verification import extract_causal_chain, yanzhen_cited_data_for_hypothesis
    except ImportError:
        from _utils import trim_text
        from _verification import extract_causal_chain, yanzhen_cited_data_for_hypothesis
    return {
        "hypothesis": trim_text(text, 800),
        "claimed_mechanism": trim_text(mechanism, 800),
        "causal_chain": extract_causal_chain(f"{text} {mechanism}"),
        "evidence_refs": yanzhen_cited_data_for_hypothesis({"papergraph": []}, record) if record else [],
        "falsification_plan": record.get("test_plan", "") if isinstance(record, dict) else "",
    }

def debate_experiment_text(record: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    final = record.get("mingli_final_idea") if isinstance(record.get("mingli_final_idea"), dict) else {}
    experiments = final.get("experiments") if isinstance(final.get("experiments"), dict) else {}
    return normalize_space(" ".join(str(experiments.get(key) or "") for key in ("setup", "metrics", "baselines")) or str(record.get("test_plan") or ""))

def debate_refined_hypothesis(
    project: dict[str, Any],
    record: dict[str, Any],
    text: str,
    mechanism: str,
    rounds: list[dict[str, Any]],
    yanzhen_body: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ._hypothesis import hypothesis_boundary_condition, hypothesis_control_variable, infer_gap_components
        from ._utils import find_by_id, unique_preserve_order
        from ._verification import default_regime_shifts, extract_causal_chain
    except ImportError:
        from _hypothesis import hypothesis_boundary_condition, hypothesis_control_variable, infer_gap_components
        from _utils import find_by_id, unique_preserve_order
        from _verification import default_regime_shifts, extract_causal_chain
    all_questions = [q for round_item in rounds for q in round_item.get("opponent_questions", []) if isinstance(q, dict)]
    high_revisions = unique_preserve_order(
        str(item.get("required_revision") or "")
        for item in all_questions
        if item.get("severity") in {"high", "fatal"} and item.get("required_revision")
    )
    gap_id = str(record.get("gap_id") or "")
    source_gap = find_by_id(project.get("knowledge_gaps", []), "gap_id", gap_id) if gap_id else {}
    components = infer_gap_components(project, source_gap or {})
    variable = hypothesis_control_variable(source_gap or {}, components.get("method", ""), components.get("scenario", ""))
    boundary = hypothesis_boundary_condition(source_gap or {})
    causal_chain = extract_causal_chain(f"{text} {mechanism}")
    if len(causal_chain) < 2:
        causal_chain = [
            f"Input/intervention: vary {variable}",
            f"Mechanism: test whether the claimed causal pathway remains valid at {boundary}",
            f"Output: measure {components.get('benchmark') or 'the preregistered primary metric'} against baselines",
        ]
    refined_statement = (
        f"Refined hypothesis: under explicitly matched conditions, vary {variable} in "
        f"{components.get('scenario') or project.get('domain') or 'the target scenario'} and test whether "
        f"{components.get('benchmark') or 'the primary benchmark'} changes at {boundary}; "
        "the hypothesis is accepted only if the causal chain survives ablation, evidence mapping, and regime-shift checks."
    )
    layer_3 = yanzhen_body.get("layer_3_regime_shift_test", {}) if isinstance(yanzhen_body, dict) else {}
    return {
        "hypothesis": refined_statement,
        "causal_chain": causal_chain,
        "adopted_revisions": high_revisions[:10],
        "evidence_requirements": [
            "Map each central claim to a PaperGraph citation or mark it as speculative.",
            "Provide evidence for causal connectors, not only endpoint performance.",
        ],
        "falsification_conditions": [
            f"No mechanism-separating change in {components.get('benchmark') or 'the primary metric'} when {variable} crosses {boundary}.",
            "YanZhen Layer 1 or Layer 2 remains FAIL after revision.",
            "Regime-shift stability collapses unexpectedly under at least two shifted conditions.",
        ],
        "regime_shift_requirements": layer_3.get("shifted_conditions_tested", default_regime_shifts(refined_statement)[:2]),
    }

def mingli_revision_from_questions(
    project: dict[str, Any],
    record: dict[str, Any],
    hypothesis_text: str,
    mechanism: str,
    questions: list[dict[str, Any]],
    yanzhen_body: dict[str, Any],
    round_name: str,
) -> dict[str, Any]:
    try:
        from ._hypothesis import hypothesis_boundary_condition, hypothesis_control_variable, infer_gap_components
        from ._utils import find_by_id, normalize_space, trim_text, unique_preserve_order
        from ._verification import extract_causal_chain
    except ImportError:
        from _hypothesis import hypothesis_boundary_condition, hypothesis_control_variable, infer_gap_components
        from _utils import find_by_id, normalize_space, trim_text, unique_preserve_order
        from _verification import extract_causal_chain
    serious = [
        item
        for item in questions
        if item.get("severity") in {"high", "fatal"} and normalize_space(str(item.get("required_revision") or ""))
    ]
    adopted = unique_preserve_order(str(item.get("required_revision") or "") for item in serious)[:8]
    gap_id = str(record.get("gap_id") or "")
    source_gap = find_by_id(project.get("knowledge_gaps", []), "gap_id", gap_id) if gap_id else {}
    components = infer_gap_components(project, source_gap or {})
    method = components.get("method") or "the proposed intervention or method"
    scenario = components.get("scenario") or project.get("domain") or "the target scenario"
    benchmark = components.get("benchmark") or "the preregistered primary metric"
    variable = hypothesis_control_variable(source_gap or {}, method, scenario)
    boundary = hypothesis_boundary_condition(source_gap or {})
    chain = extract_causal_chain(f"{hypothesis_text} {mechanism}")
    if len(chain) < 3:
        chain = [
            f"Input/intervention: change {variable} while holding the closest baseline/control fixed.",
            f"Mechanism: test whether {method} changes the relevant state or process inside {scenario}.",
            f"Output: measure {benchmark} and compare it with baseline and failure-mode controls.",
        ]
    layer_1 = yanzhen_body.get("layer_1_internal_consistency", {}) if isinstance(yanzhen_body, dict) else {}
    layer_2 = yanzhen_body.get("layer_2_data_consistency", {}) if isinstance(yanzhen_body, dict) else {}
    layer_3 = yanzhen_body.get("layer_3_regime_shift_test", {}) if isinstance(yanzhen_body, dict) else {}
    adaptability = yanzhen_body.get("domain_adaptability_audit", {}) if isinstance(yanzhen_body, dict) else {}
    audit_requirements: list[str] = []
    if layer_1.get("verdict") == "FAIL":
        for issue in layer_1.get("issues_found", [])[:3]:
            audit_requirements.append(f"Layer 1 repair: {issue}")
    if layer_2.get("verdict") == "FAIL":
        audit_requirements.append("separate source-supported claims from speculative mechanism claims")
    if layer_3.get("verdict") == "FAIL" or layer_3.get("cawm_risk_level") in {"MEDIUM", "HIGH"}:
        audit_requirements.append("restrict the validity regime and add at least two regime-shift predictions")
    if adaptability.get("verdict") == "FAIL":
        for cond in adaptability.get("adaptation_conditions", [])[:2]:
            audit_requirements.append(f"Domain adaptability: {cond}")
    elif adaptability.get("verdict") == "WARN":
        for issue in adaptability.get("issues_found", [])[:2]:
            audit_requirements.append(f"Adaptability concern: {issue}")
    adopted = unique_preserve_order(adopted + audit_requirements)[:12]
    if adopted:
        addressed = mingli_address_questions(serious, method, scenario, benchmark, variable, boundary)
        # Build question-specific revision_delta (not a static template)
        revision_delta: list[str] = []
        revision_diff_table: list[dict[str, str]] = []
        for question in serious[:8]:
            qtext = normalize_space(str(question.get("question") or ""))
            required = normalize_space(str(question.get("required_revision") or ""))
            qtype = str(question.get("question_type") or "general")
            if required:
                revision_delta.append(f"[{qtype}] {required}")
                revision_diff_table.append({
                    "opponent_concern": trim_text(qtext, 160),
                    "revision_applied": trim_text(required, 200),
                    "question_type": qtype,
                })
        # Add audit-driven deltas
        for req in audit_requirements:
            if req not in [item.get("revision_applied") for item in revision_diff_table]:
                revision_delta.append(f"[audit] {req}")
                revision_diff_table.append({
                    "opponent_concern": req,
                    "revision_applied": req,
                    "question_type": "yanzhen_audit",
                })
        if not revision_delta:
            revision_delta = [
                f"Operationalized method/scenario/benchmark as: {method} | {scenario} | {benchmark}.",
                f"Added explicit control variable and boundary: {variable} at {boundary}.",
            ]
        # Build round-specific revised clause
        adaptability_clause = ""
        if adaptability.get("verdict") == "FAIL":
            method_family = adaptability.get("method_family", "unknown")
            adaptability_clause = (
                f" The method family '{method_family}' must satisfy its data-type prerequisites "
                f"in {scenario}; otherwise the mechanism claim is treated as unvalidated cross-domain migration."
            )
        elif adaptability.get("verdict") == "WARN":
            adaptability_clause = (
                f" Cross-domain bridging evidence is required before the mechanism claim can be accepted."
            )
        revised_clause = (
            f"Revision after {round_name}: the hypothesis is limited to {scenario}; "
            f"{variable} is varied under matched baseline/control conditions; "
            f"{benchmark} must change in the predicted direction and the causal chain must survive source mapping, "
            f"ablation, and regime-shift tests.{adaptability_clause}"
        )
        revised_hypothesis = normalize_space(f"{hypothesis_text} {revised_clause}")
        revised_mechanism = normalize_space(
            f"{mechanism} Revised mechanism: {method} must produce an observable intermediate change in {scenario}; "
            f"otherwise any endpoint change in {benchmark} is treated as correlation rather than mechanism."
        )
        # Round-specific proponent response
        n_adopted = len(adopted)
        adaptability_note = ""
        if adaptability.get("verdict") in {"FAIL", "WARN"}:
            adaptability_note = f" Domain adaptability audit flagged: {adaptability.get('verdict')}."
        response = (
            f"MingLi adopts {n_adopted} revision requirements from {round_name} "
            f"and narrows the claim to an operational, evidence-gated version.{adaptability_note}"
        )
    else:
        addressed = mingli_address_questions(questions[:3], method, scenario, benchmark, variable, boundary)
        revision_delta = ["No high-severity critique required a structural revision in this round."]
        revision_diff_table = []
        revised_hypothesis = hypothesis_text
        revised_mechanism = mechanism
        response = "MingLi keeps the current hypothesis but records the opponent questions as monitoring checks."
    return {
        "round_name": round_name,
        "proponent_response": response,
        "addressed_opponent_questions": addressed,
        "adopted_revision_requirements": adopted,
        "revision_delta": revision_delta,
        "revision_diff_table": revision_diff_table,
        "revised_hypothesis": trim_text(revised_hypothesis, 2400),
        "revised_mechanism": trim_text(revised_mechanism, 1600),
        "causal_chain_after_revision": chain,
        "remaining_speculative_claims": mingli_remaining_speculative_claims(questions, yanzhen_body),
    }

def mingli_address_questions(
    questions: list[dict[str, Any]],
    method: str,
    scenario: str,
    benchmark: str,
    variable: str,
    boundary: str,
) -> list[dict[str, Any]]:
    try:
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _utils import normalize_space, trim_text
    addressed: list[dict[str, Any]] = []
    for question in questions[:8]:
        qtext = normalize_space(str(question.get("question") or ""))
        required = normalize_space(str(question.get("required_revision") or ""))
        qtype = str(question.get("question_type") or "")
        if not qtext:
            continue
        lower = f"{qtext} {required}".lower()
        if qtype == "adaptability_challenge" or any(term in lower for term in ("incompatib", "method family", "data type", "cross-domain", "bridging", "adaptation condition")):
            response = (
                f"The method-scenario compatibility must be resolved: either (a) replace {method} with a method "
                f"compatible with {scenario}'s data types, (b) narrow the hypothesis to a sub-claim where {method} "
                f"is applicable, or (c) provide explicit bridging evidence and state all adaptation conditions."
            )
        elif any(term in lower for term in ("threshold", "metric", "measurable", "observable", "success")):
            response = f"Use {benchmark} as the primary readout and require a preregistered direction/change relative to the closest baseline."
        elif any(term in lower for term in ("boundary", "regime", "condition", "shift", "noise", "scale")):
            response = f"Restrict the claim to {boundary}; outside that regime the mechanism must be treated as uncertain and stress-tested."
        elif any(term in lower for term in ("evidence", "citation", "papergraph", "unsupported", "source")):
            response = "Attach a PaperGraph citation for the causal link, or downgrade the link to an explicit testable assumption."
        elif any(term in lower for term in ("causal", "chain", "input", "mediator", "output")):
            response = f"Rewrite the chain as intervention={variable}; mediator={method} acting in {scenario}; output={benchmark}."
        elif any(term in lower for term in ("baseline", "control", "negative")):
            response = f"Compare {variable} against a matched baseline/control so endpoint changes in {benchmark} are not over-interpreted."
        else:
            response = f"Treat this as a constraint on the {method} -> {scenario} mechanism and record it as a falsification check."
        addressed.append(
            {
                "question_type": qtype,
                "opponent_question": trim_text(qtext, 260),
                "mingli_direct_response": response,
                "adopted_revision": required,
            }
        )
    return addressed

def mingli_remaining_speculative_claims(questions: list[dict[str, Any]], yanzhen_body: dict[str, Any]) -> list[str]:
    try:
        from ._utils import trim_text, unique_preserve_order
    except ImportError:
        from _utils import trim_text, unique_preserve_order
    claims = [
        str(item.get("target_claim") or item.get("question") or "")
        for item in questions
        if item.get("severity") in {"high", "fatal"}
    ]
    if isinstance(yanzhen_body, dict):
        layer_2 = yanzhen_body.get("layer_2_data_consistency", {})
        if isinstance(layer_2, dict) and layer_2.get("verdict") == "FAIL":
            claims.append("Mechanism-data alignment remains incomplete until source quotations or structured evidence are attached.")
    return unique_preserve_order(trim_text(item, 180) for item in claims if item)[:8]

def yanzhen_debate_feedback(yanzhen_body: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._verification import yanzhen_public_verdict
    except ImportError:
        from _verification import yanzhen_public_verdict
    if not isinstance(yanzhen_body, dict) or not yanzhen_body:
        return {"verdict": "NOT_RUN", "required_actions": [], "unsupported_claims": []}
    return {
        "verdict": yanzhen_body.get("verdict") or yanzhen_public_verdict(str(yanzhen_body.get("overall_verdict") or "")),
        "overall_verdict": yanzhen_body.get("overall_verdict", ""),
        "required_actions": yanzhen_body.get("required_actions", []),
        "unsupported_claims": yanzhen_body.get("unsupported_claims", []),
        "audit_layers": {
            "internal": (yanzhen_body.get("layer_1_internal_consistency") or {}).get("verdict"),
            "data": (yanzhen_body.get("layer_2_data_consistency") or {}).get("verdict"),
            "regime_shift": (yanzhen_body.get("layer_3_regime_shift_test") or {}).get("verdict"),
            "feasibility": (yanzhen_body.get("feasibility_audit") or {}).get("verdict"),
            "domain_adaptability": (yanzhen_body.get("domain_adaptability_audit") or {}).get("verdict"),
        },
    }

def duzhi_questions_from_yanzhen_actions(
    yanzhen_body: dict[str, Any],
    hypothesis_text: str,
    mechanism: str,
) -> list[dict[str, Any]]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    questions: list[dict[str, Any]] = []
    actions = yanzhen_body.get("required_actions", []) if isinstance(yanzhen_body.get("required_actions"), list) else []
    unsupported = yanzhen_body.get("unsupported_claims", []) if isinstance(yanzhen_body.get("unsupported_claims"), list) else []
    for claim in unsupported[:4]:
        questions.append(
            {
                "question_type": "evidence_completion_challenge",
                "question": f"YanZhen marked this claim as unsupported: {claim}. Will MingLi attach a PaperGraph citation, narrow the claim, or remove it?",
                "target_claim": trim_text(str(claim), 220),
                "why_it_matters": "Unsupported links are exactly where CAWM and selective-citation failures enter the hypothesis.",
                "required_revision": "Attach evidence for the unsupported claim or downgrade it to an explicit assumption with a falsification test.",
                "severity": "high",
            }
        )
    for action in actions[:5]:
        action_name = str(action.get("action") or "")
        is_adaptability_fatal = action_name in {
            "resolve_method_scenario_incompatibility",
            "address_domain_adaptability_concerns",
        }
        is_causal_fatal = action_name in {"mingli_rewrite_causal_chain", "restrict_validity_regime_and_add_shift_tests"}
        severity = "fatal" if (is_causal_fatal or is_adaptability_fatal) else "high"
        suggested = str(action.get("suggested_revision") or action.get("reason") or action_name)
        questions.append(
            {
                "question_type": "adaptability_challenge" if is_adaptability_fatal else "audit_action_challenge",
                "question": f"YanZhen requires `{action_name}`. What concrete revision satisfies this action before the hypothesis advances?",
                "target_claim": mechanism or hypothesis_text,
                "why_it_matters": str(action.get("reason") or "Mechanism audit actions must be resolved before BianLun can accept the claim."),
                "required_revision": suggested,
                "severity": severity,
            }
        )
    if not questions:
        questions.append(
            {
                "question_type": "audit_action_challenge",
                "question": "YanZhen did not provide a concrete action; what audit evidence would make the mechanism pass rather than require review?",
                "target_claim": hypothesis_text,
                "why_it_matters": "A debate cannot close without a clear pass criterion.",
                "required_revision": "State the pass criterion and attach it to the refined hypothesis.",
                "severity": "medium",
            }
        )
    return dedupe_socratic_questions(questions)

def debate_question_adopted(question: dict[str, Any], rounds: list[dict[str, Any]]) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    requirement = normalize_space(str(question.get("required_revision") or ""))
    if not requirement:
        return False
    for round_item in rounds:
        response = round_item.get("proponent_response")
        if not isinstance(response, dict):
            continue
        adopted = [normalize_space(str(item)) for item in response.get("adopted_revision_requirements", [])]
        if requirement in adopted:
            return True
    return False

def build_debate_state(
    *,
    hypothesis_id: str,
    rounds: list[dict[str, Any]],
    max_rounds: int,
    unresolved: list[str],
    final_decision: str,
    coverage_changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._models import DebateArgument, DebateState
        from ._utils import trim_text
        from ._verification import yanzhen_public_verdict
    except ImportError:
        from _models import DebateArgument, DebateState
        from _utils import trim_text
        from _verification import yanzhen_public_verdict
    state = DebateState(
        hypothesis_id=hypothesis_id,
        round=max([int(item.get("round") or 0) for item in rounds] or [0]),
        max_rounds=max_rounds,
        unresolved_issues=list(unresolved),
        status=debate_status_from_decision(final_decision),
    )
    for round_item in rounds:
        round_no = int(round_item.get("round") or 0)
        if round_item.get("proponent_position"):
            state.arguments.append(
                asdict(
                    DebateArgument(
                        round=round_no,
                        speaker="MingLi",
                        role="proponent",
                        content=trim_text(json.dumps(round_item.get("proponent_position"), ensure_ascii=False), 900),
                        verdict=str(round_item.get("moderator_verdict") or ""),
                    )
                )
            )
        for question in round_item.get("opponent_questions", []) if isinstance(round_item.get("opponent_questions"), list) else []:
            state.arguments.append(
                asdict(
                    DebateArgument(
                        round=round_no,
                        speaker="DuZhi",
                        role="opponent",
                        content=trim_text(str(question.get("question") or ""), 900),
                        verdict=str(question.get("severity") or ""),
                    )
                )
            )
        response = round_item.get("proponent_response")
        if isinstance(response, dict):
            state.revisions.append(
                {
                    "round": round_no,
                    "adopted_revision_requirements": response.get("adopted_revision_requirements", []),
                    "revision_delta": response.get("revision_delta", []),
                    "remaining_speculative_claims": response.get("remaining_speculative_claims", []),
                    "coverage_slot_revisions": round_item.get("coverage_slot_revisions", []),
                }
            )
        if isinstance(round_item.get("yanzhen_report"), dict):
            state.mechanism_audits.append(
                {
                    "round": round_no,
                    "verdict": round_item["yanzhen_report"].get("verdict") or yanzhen_public_verdict(str(round_item["yanzhen_report"].get("overall_verdict") or "")),
                    "overall_verdict": round_item["yanzhen_report"].get("overall_verdict"),
                    "required_actions": round_item["yanzhen_report"].get("required_actions", []),
                    "unsupported_claims": round_item["yanzhen_report"].get("unsupported_claims", []),
                }
            )
        if isinstance(round_item.get("literature_supplement"), dict):
            state.literature_supplements.append(round_item["literature_supplement"])
    payload = asdict(state)
    if coverage_changes:
        payload["coverage_changes"] = coverage_changes
    return payload

def debate_status_from_decision(final_decision: str) -> str:
    if final_decision == "accept_for_experiment":
        return "CONCLUDED"
    if final_decision in {"human_review", "revise"}:
        return "ESCALATED"
    return "CONCLUDED"

def debate_unresolved_issues(questions: list[dict[str, Any]], yanzhen_body: dict[str, Any]) -> list[str]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    issues = [
        f"{item.get('question_type')}: {item.get('question')}"
        for item in questions
        if item.get("severity") in {"high", "fatal"}
    ]
    if isinstance(yanzhen_body, dict):
        if yanzhen_body.get("overall_verdict") in {"CAWM_DETECTED", "REQUIRES_HUMAN_REVIEW"}:
            issues.append(f"YanZhen overall verdict: {yanzhen_body.get('overall_verdict')}")
        for layer_key in ("layer_1_internal_consistency", "layer_2_data_consistency", "layer_3_regime_shift_test"):
            layer = yanzhen_body.get(layer_key, {})
            if isinstance(layer, dict):
                issues.extend(str(issue) for issue in layer.get("issues_found", [])[:4] if issue)
    return unique_preserve_order(issues)[:20]

def debate_final_decision(
    rounds: list[dict[str, Any]],
    yanzhen_body: dict[str, Any],
    refined: dict[str, Any],
    execution_validation: dict[str, Any] | None = None,
) -> str:
    all_questions = [q for round_item in rounds for q in round_item.get("opponent_questions", []) if isinstance(q, dict)]
    unadopted_serious = [
        item
        for item in all_questions
        if item.get("severity") in {"high", "fatal"} and not debate_question_adopted(item, rounds)
    ]
    if any(item.get("severity") == "fatal" for item in unadopted_serious):
        return "revise"
    if yanzhen_body.get("overall_verdict") == "CAWM_DETECTED":
        return "revise"
    if yanzhen_body.get("overall_verdict") == "REQUIRES_HUMAN_REVIEW":
        return "human_review"
    if len(refined.get("causal_chain", [])) < 2:
        return "revise"
    if execution_validation:
        verdict = execution_validation.get("verdict")
        if verdict == "FAIL":
            return "revise"
        if verdict == "REQUIRES_HUMAN_REVIEW":
            return "human_review"
    if any(item.get("severity") == "high" for item in unadopted_serious):
        return "revise"
    return "accept_for_experiment"

def execution_level_validation(
    project: dict[str, Any],
    refined: dict[str, Any],
    yanzhen_body: dict[str, Any],
    rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from ._utils import normalize_space
        from ._verification import yanzhen_public_verdict
    except ImportError:
        from _utils import normalize_space
        from _verification import yanzhen_public_verdict
    text = normalize_space(
        " ".join(
            [
                str(refined.get("hypothesis") or ""),
                " ".join(str(item) for item in refined.get("causal_chain", []) if item),
                " ".join(str(item) for item in refined.get("falsification_conditions", []) if item),
                " ".join(str(item) for item in refined.get("evidence_requirements", []) if item),
            ]
        )
    ).lower()
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, severity: str, reason: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "severity": severity, "reason": reason})

    causal_chain = refined.get("causal_chain", []) if isinstance(refined.get("causal_chain"), list) else []
    falsifiers = refined.get("falsification_conditions", []) if isinstance(refined.get("falsification_conditions"), list) else []
    evidence_requirements = refined.get("evidence_requirements", []) if isinstance(refined.get("evidence_requirements"), list) else []
    add_check(
        "causal_chain_operationalized",
        len(causal_chain) >= 3,
        "fatal",
        "Requires at least input/intervention, mediator/mechanism, and output/readout steps.",
    )
    add_check(
        "has_falsification_condition",
        bool(falsifiers),
        "fatal",
        "Requires explicit evidence that would falsify or weaken the hypothesis.",
    )
    add_check(
        "claim_to_evidence_plan",
        bool(evidence_requirements),
        "high",
        "Requires a plan for mapping claims to PaperGraph evidence or marking assumptions.",
    )
    add_check(
        "observable_and_baseline_declared",
        any(term in text for term in ("measure", "metric", "readout", "observable", "benchmark", "primary")) and any(term in text for term in ("baseline", "control")),
        "high",
        "Requires both an observable outcome and a baseline/control comparison.",
    )
    add_check(
        "regime_shift_ready",
        any(term in text for term in ("regime", "boundary", "shift", "stress", "condition", "outside", "under")),
        "high",
        "Requires boundary conditions or regime-shift stress tests before execution.",
    )
    unsupported = yanzhen_body.get("unsupported_claims", []) if isinstance(yanzhen_body.get("unsupported_claims"), list) else []
    supplement_rounds = [
        item.get("literature_supplement")
        for item in rounds
        if isinstance(item.get("literature_supplement"), dict) and item.get("literature_supplement", {}).get("attempted")
    ]
    supplement_resolved = not unsupported or any(
        supplement.get("imports") or any(
            imp.get("status") == "no_relevance_pass"
            for claim in supplement.get("claims", []) if isinstance(claim, dict)
            for imp in claim.get("imports", []) if isinstance(imp, dict)
        )
        for supplement in supplement_rounds
    )
    add_check(
        "unsupported_claims_handled",
        supplement_resolved,
        "high",
        "Unsupported YanZhen claims must be supported, narrowed, or recorded as no-relevant-evidence after targeted search.",
    )
    yanzhen_verdict = yanzhen_body.get("verdict") or yanzhen_public_verdict(str(yanzhen_body.get("overall_verdict") or ""))
    add_check(
        "mechanism_audit_not_failed",
        yanzhen_verdict not in {"REJECTED"},
        "fatal",
        "A rejected YanZhen mechanism audit cannot advance to execution.",
    )
    # Domain adaptability gate — method must be compatible with scenario data types
    adaptability = yanzhen_body.get("domain_adaptability_audit", {}) if isinstance(yanzhen_body, dict) else {}
    adaptability_verdict = adaptability.get("verdict", "PASS") if isinstance(adaptability, dict) else "PASS"
    add_check(
        "method_scenario_compatible",
        adaptability_verdict != "FAIL",
        "fatal",
        "Method-scenario incompatibility detected: the method's data-type requirements cannot be satisfied by the scenario.",
    )

    failed_fatal = [item for item in checks if not item["passed"] and item["severity"] == "fatal"]
    failed_high = [item for item in checks if not item["passed"] and item["severity"] == "high"]
    if failed_fatal:
        verdict = "FAIL"
    elif failed_high or yanzhen_verdict in {"REQUIRES_REVISION", "REQUIRES_HUMAN_REVIEW"} or adaptability_verdict == "WARN":
        verdict = "REQUIRES_HUMAN_REVIEW"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "checks": checks,
        "failed_checks": [item for item in checks if not item["passed"]],
        "execution_gate": "A hypothesis can enter Gewu only after it is operational, falsifiable, evidence-mapped, and stress-test-ready.",
    }

