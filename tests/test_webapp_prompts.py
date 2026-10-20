from __future__ import annotations

import json

import pytest

from src.config import reload_config
from src.webapp.prompts import build_default_prompt_registry
from src.webapp.prompts.registry import TEXT_MODEL_CHOICES, resolve_text_model


def test_prompt_registry_is_allow_listed_and_hashable() -> None:
    registry = build_default_prompt_registry()
    spec = registry.resolve(job_kind="figure", profile="figure-ai-schematic")
    snapshot = spec.snapshot()

    assert "nature-figure" in spec.skill_ids
    assert snapshot["prompt_hash"] == spec.prompt_hash
    assert spec.image_model_role == "academic_figure"
    assert all(isinstance(value, str) for value in snapshot["source_hashes"].values())

    with pytest.raises(ValueError, match="cannot be used"):
        registry.resolve(job_kind="polish", profile="figure-ai-schematic")


def test_prompt_messages_are_json_contract_messages() -> None:
    spec = build_default_prompt_registry().resolve(
        job_kind="translation", profile="translation-text-preserving"
    )
    messages = spec.build_messages(
        input_manifest={"file_id": "file-1", "sha256": "a" * 64},
        task_context={"page": 3},
    )

    assert messages[0]["role"] == "system"
    payload = json.loads(str(messages[1]["content"]))
    assert payload["task_context"] == {"page": 3}
    assert payload["output_schema"]["required"]


def test_text_model_selection_is_limited_to_supported_qwen_models() -> None:
    config = reload_config()
    spec = build_default_prompt_registry().get("polish-generic")

    for model_name in TEXT_MODEL_CHOICES:
        assert resolve_text_model(config, spec, model_name=model_name).name == model_name

    with pytest.raises(ValueError, match="Unsupported text model"):
        resolve_text_model(config, spec, model_name="gpt-5.5")


def test_prompt_schema_and_nested_values_cannot_change_registered_content():
    registry = build_default_prompt_registry()
    spec = registry.get("polish-generic")
    digest = spec.prompt_hash
    with pytest.raises(TypeError):
        spec.output_schema["properties"]["schema_version"]["type"] = "integer"
    snapshot = spec.snapshot()
    snapshot["output_schema"]["properties"]["schema_version"]["type"] = "integer"
    assert spec.prompt_hash == digest
    assert registry.get("polish-generic").snapshot()["output_schema"]["properties"]["schema_version"]["type"] == "string"


@pytest.mark.parametrize("profile", ["research-default", "research-light"])
def test_research_policy_distinguishes_design_values_and_preserves_frozen_versions(profile: str) -> None:
    registry = build_default_prompt_registry()
    current = registry.get(profile)
    previous = registry.get(profile, prompt_version="1.0.0")
    rules = current.build_messages(input_manifest={}, task_context={})[0]["content"]
    previous_rules = previous.build_messages(input_manifest={}, task_context={})[0]["content"]

    assert current.prompt_version == "1.1.0"
    assert "Explicitly proposed design values" in rules
    assert "observed experimental results" in rules
    assert "The original user task defines the objective" in rules
    assert "Do not invent data, numerical values" not in rules
    assert "Do not invent data, numerical values" in previous_rules
    assert previous.prompt_hash != current.prompt_hash
