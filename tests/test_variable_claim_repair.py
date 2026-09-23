from io import StringIO

import pytest

from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
from src.agents.experiment_design_agent.variable_claim_extractor import VariableClaimExtractor


def model():
    return {
        "schema_version": "variable_claim_model_v1",
        "status": "complete_or_requires_input",
        "claims": [{"claim_id": "C1", "statement": "Candidate", "scope": "Declared scope",
                    "assumption_ids": [], "falsifier_ids": [], "hypothesis_links": [],
                    "status": "candidate_extracted"}],
        "variables": [{"variable_id": "V1", "name": "timescale", "role": "formal_parameter",
                       "formal_or_empirical": "formal", "construct": "timescale", "observable": "",
                       "operational_definition": {"value": "", "status": "needs_formal_definition"},
                       "unit_or_domain": {"value": "", "status": "needs_formal_definition"},
                       "hypothesis_links": [], "claim_links": ["C1"],
                       "source_path": "research_brief.variables[0]", "status": "needs_formal_definition"}],
        "unknown_items": [],
    }


def test_invalid_batch_logs_reason_and_recovers_once():
    logger = ExperimentDesignRunLogger("variable-recovery", console_stream=StringIO())
    prompts = []

    def llm(prompt, **kwargs):
        prompts.append(prompt)
        candidate = model()
        if "repairing a failed" not in prompt.lower():
            candidate["variables"][0]["role"] = "unknown_role"
        return candidate

    result = VariableClaimExtractor().extract({"brief_id": "B1"}, reasoning_context={"scope": "test"}, llm_call=llm, logger=logger, brief_id="B1")
    assert result["variables"][0]["role"] == "formal_parameter"
    assert len(prompts) == 2
    failed = next(record for record in logger.records if record["event"] == "contract_validation_failed")
    assert failed["validation_error_count"] == 1
    assert "invalid_role" in failed["validation_errors"][0]
    assert any(record["event"] == "contract_repaired" for record in logger.records)


def test_failed_repair_logs_detailed_reason():
    logger = ExperimentDesignRunLogger("variable-recovery-failed", console_stream=StringIO())

    def llm(prompt, **kwargs):
        candidate = model()
        candidate["variables"][0]["role"] = "unknown_role"
        return candidate

    with pytest.raises(ValueError, match="initial contract errors.*repaired contract errors"):
        VariableClaimExtractor().extract({"brief_id": "B1"}, reasoning_context={"scope": "test"}, llm_call=llm, logger=logger, brief_id="B1")
    failure = next(record for record in logger.records if record["event"] == "contract_repair_failed")
    assert failure["validation_error_count"] == 1
    assert "invalid_role" in failure["validation_errors"][0]
