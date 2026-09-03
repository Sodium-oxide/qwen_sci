from __future__ import annotations

import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src.llm.structured_output import StructuredOutputError
from src.llm.vision import QwenVisionClient
from src.pipeline.multimodal_evidence.contract import (
    MultimodalInputError,
    MultimodalInputSpec,
    MultimodalSettings,
    ValidatedMultimodalRecord,
    validate_multimodal_evidence,
)
from src.pipeline.multimodal_evidence.service import (
    build_local_multimodal_input_context,
    build_multimodal_evidence,
)
from src.pipeline.multimodal_evidence.perception import OBSERVATION_SCHEMA
from src.pipeline.multimodal_evidence.runtime_logging import safe_exception_summary


def _config(*, multimodal_model: str = "qwen3-vl-plus", vision_model: str = "qwen3-vl-plus"):
    return OmegaConf.create(
        {
            "llm": {
                "default_provider": "qwen",
                "providers": {
                    "qwen": {
                        "api_key": "test-key",
                        "base_url": "https://dashscope.example/compatible-mode/v1",
                    }
                },
            },
            "vision": {"provider": "qwen", "quality_model": vision_model, "max_tokens": 512},
            "survey": {
                "multimodal_evidence": {
                    "quality_model": multimodal_model,
                    "max_data_anchored_sh": 3,
                    "max_vl_calls": 2,
                    "max_preview_pixels": 100_000,
                    "max_preview_bytes": 200_000,
                }
            },
        }
    )


def _image_spec(path: Path) -> MultimodalInputSpec:
    return MultimodalInputSpec(
        dataset_id="demo",
        input_mode="explicit_files",
        records=(
            ValidatedMultimodalRecord(
                record_id="image-1",
                modality="image",
                source_path=path.resolve(),
                source_name=path.name,
                file_size_bytes=path.stat().st_size,
                metadata={},
                input_index=0,
            ),
        ),
    )


def _observation() -> dict[str, object]:
    return {
        "finding": "A bounded color gradient is visible in the preview.",
        "candidate_explanation": "A spatially varying material state may be compatible with the pattern.",
        "alternative_explanations": ["Illumination variation may produce a similar pattern."],
        "discriminating_prediction": "A calibrated measurement would retain the gradient if the material state explains it.",
        "falsifier": "The gradient disappears after calibrated imaging under matched conditions.",
        "claim_limits": "The preview is a representative bounded sample and does not establish a general relation.",
        "confidence": "low",
        "focus": "mechanism",
    }


def test_no_explicit_input_does_not_construct_runtime_evidence(monkeypatch) -> None:
    from src.pipeline.multimodal_evidence import service

    monkeypatch.setattr(
        service,
        "run_remote_perception",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must stay disabled")),
    )
    assert build_multimodal_evidence(input_spec=None, config=_config()) is None


@pytest.mark.parametrize("forbidden_key", ["source_path", "preview_base64", "raw_response_text"])
def test_runtime_evidence_contract_rejects_media_and_provider_leaks(forbidden_key) -> None:
    evidence = {
        "schema_version": "multimodal_evidence_v1",
        "perception": {"mode": "local_only"},
        "native_findings": [],
        "observations": [],
        "claims": [],
        "limitations": [],
        forbidden_key: "C:/private/input.png",
    }
    with pytest.raises(MultimodalInputError):
        validate_multimodal_evidence(evidence)


def test_local_only_evidence_cannot_be_injected_with_claims() -> None:
    evidence = {
        "schema_version": "multimodal_evidence_v1",
        "perception": {"mode": "local_only"},
        "native_findings": [],
        "observations": [],
        "claims": [{"claim_id": "mme:claim:001"}],
        "limitations": [],
    }
    with pytest.raises(MultimodalInputError, match="Local-only"):
        validate_multimodal_evidence(evidence)


def test_runtime_evidence_accepts_omegaconf_containers() -> None:
    evidence = OmegaConf.create(
        {
            "schema_version": "multimodal_evidence_v1",
            "perception": {
                "mode": "remote_perception",
                "provider": "qwen",
                "model": "qwen3-vl-plus",
            },
            "native_findings": [{"record_id": "image-1", "status": "success"}],
            "observations": [],
            "claims": [],
            "limitations": [],
        }
    )

    normalized = validate_multimodal_evidence(evidence)

    assert isinstance(normalized["native_findings"], list)
    assert isinstance(normalized["observations"], list)


def test_local_only_mode_never_invokes_remote_perception(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(spec, settings=MultimodalSettings())
    from src.pipeline.multimodal_evidence import service

    monkeypatch.setattr(
        service,
        "run_remote_perception",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must stay local")),
    )
    evidence = build_multimodal_evidence(
        input_spec=spec,
        config=_config(),
        local_context=local_context,
    )

    assert evidence["perception"] == {"mode": "local_only"}
    assert evidence["observations"] == []
    assert evidence["claims"] == []


def test_remote_perception_uses_only_sanitized_png_and_stores_claims(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (64, 32), (20, 30, 40)).save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(
        spec,
        settings=MultimodalSettings(remote_perception_authorized=True),
    )
    calls: list[dict[str, object]] = []

    class FakeVision:
        def __init__(self, **kwargs) -> None:
            assert kwargs["model"] == "qwen3-vl-plus"

        def describe_json(self, preview, **kwargs):
            assert preview.startswith(b"\x89PNG\r\n\x1a\n")
            assert kwargs["media_type"] == "image/png"
            assert kwargs["schema"]["type"] == "object"
            calls.append(kwargs)
            return _observation()

    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(perception, "QwenVisionClient", FakeVision)
    evidence = build_multimodal_evidence(
        input_spec=spec,
        config=_config(),
        local_context=local_context,
    )

    serialized = json.dumps(evidence, ensure_ascii=False)
    assert calls
    assert '"finding"' in str(calls[0]["prompt"])
    assert '"alternative_explanations"' in str(calls[0]["prompt"])
    assert evidence["perception"] == {
        "mode": "remote_perception",
        "provider": "qwen",
        "model": "qwen3-vl-plus",
        "record_ids": ["image-1"],
    }
    assert evidence["observations"][0]["observation_id"] == "mme:obs:001"
    assert evidence["claims"][0]["claim_id"] == "mme:claim:001"
    assert str(tmp_path.resolve()) not in serialized
    assert "base64" not in serialized.casefold()
    assert "raw_response" not in serialized.casefold()


def test_remote_perception_emits_safe_runtime_progress_logs(monkeypatch, tmp_path, capsys) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "private-sample.png"
    Image.new("RGB", (16, 12), (20, 30, 40)).save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(
        spec,
        settings=MultimodalSettings(remote_perception_authorized=True),
    )

    class FakeVision:
        def __init__(self, **_kwargs) -> None:
            pass

        def describe_json(self, _preview, **_kwargs):
            return _observation()

    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(perception, "QwenVisionClient", FakeVision)
    build_multimodal_evidence(
        input_spec=spec,
        config=_config(),
        local_context=local_context,
    )

    console_output = capsys.readouterr().err
    assert "Local multimodal analysis started" in console_output
    assert "Sending sanitized PNG preview" in console_output
    assert "Remote perception response received" in console_output
    assert "qwen3-vl-plus" in console_output
    assert str(image_path) not in console_output
    assert "test-key" not in console_output


def test_qwen_describe_json_prefers_native_json_schema() -> None:
    client = object.__new__(QwenVisionClient)
    calls: list[dict[str, object]] = []

    def describe(_image_bytes, **kwargs):
        calls.append(kwargs)
        return json.dumps(_observation())

    client.describe = describe
    result = client.describe_json(
        b"png",
        prompt="Return the observation.",
        schema=OBSERVATION_SCHEMA,
    )

    assert result["alternative_explanations"]
    response_format = calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == OBSERVATION_SCHEMA


def test_qwen_describe_json_falls_back_only_when_schema_format_is_unsupported() -> None:
    client = object.__new__(QwenVisionClient)
    calls: list[dict[str, object]] = []

    def describe(_image_bytes, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("response_format json_schema is unsupported")
        return json.dumps(_observation())

    client.describe = describe
    client.describe_json(
        b"png",
        prompt="Return the observation.",
        schema=OBSERVATION_SCHEMA,
    )

    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"] == {"type": "json_object"}


def test_remote_perception_repair_budget_is_independent_of_primary_budget(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (16, 16), "white").save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(
        spec,
        settings=MultimodalSettings(remote_perception_authorized=True),
    )
    calls: list[dict[str, object]] = []

    class FakeVision:
        def __init__(self, **_kwargs) -> None:
            pass

        def describe_json(self, _preview, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise StructuredOutputError(
                    "$ is missing required fields: alternative_explanations"
                )
            return _observation()

    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(perception, "QwenVisionClient", FakeVision)
    observations, limitations, metadata = perception.run_remote_perception(
        input_spec=spec,
        local_context=local_context,
        config=_config(),
        max_calls=1,
        max_repair_attempts=1,
        max_preview_pixels=100_000,
        max_preview_bytes=200_000,
    )

    assert len(calls) == 2
    assert observations
    assert not limitations
    assert metadata["record_ids"] == ["image-1"]
    assert "repairing one observation" in calls[1]["prompt"]


def test_runtime_log_exception_summary_redacts_credentials() -> None:
    summary = safe_exception_summary(
        RuntimeError("Authorization: Bearer credential-value api_key=another-secret")
    )

    assert "credential-value" not in summary
    assert "another-secret" not in summary
    assert "RuntimeError" in summary


def test_remote_perception_rejects_causal_observation_language(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(
        spec,
        settings=MultimodalSettings(remote_perception_authorized=True),
    )

    class FakeVision:
        def __init__(self, **_kwargs) -> None:
            pass

        def describe_json(self, _preview, **_kwargs):
            observation = _observation()
            observation["finding"] = "The preview demonstrates that humidity drives crack propagation."
            observation["candidate_explanation"] = "Humidity drives crack propagation."
            return observation

    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(perception, "QwenVisionClient", FakeVision)
    evidence = build_multimodal_evidence(
        input_spec=spec,
        config=_config(),
        local_context=local_context,
    )

    assert evidence["observations"] == []
    assert evidence["claims"] == []
    assert any("non-causal claim policy" in item for item in evidence["limitations"])


def test_remote_perception_budget_round_robins_modalities(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    signal_path = tmp_path / "signal.npy"
    Image.new("RGB", (8, 8), "white").save(image_path)
    signal_path.write_bytes(b"local-only-placeholder")
    records = (
        ValidatedMultimodalRecord("image-1", "image", image_path, "sample.png", image_path.stat().st_size, {}, 0),
        ValidatedMultimodalRecord("image-2", "image", image_path, "sample.png", image_path.stat().st_size, {}, 1),
        ValidatedMultimodalRecord("signal-1", "signal", signal_path, "signal.npy", signal_path.stat().st_size, {}, 2),
    )
    spec = MultimodalInputSpec(dataset_id="mixed", records=records, input_mode="explicit_files")
    local_context = {
        "remote_perception_authorized": True,
        "selected_record_ids": ["image-1", "image-2", "signal-1"],
        "native_findings": [
            {"record_id": record.record_id, "status": "success", "metrics": {}}
            for record in records
        ],
    }
    seen_prompts: list[str] = []

    class FakeVision:
        def __init__(self, **_kwargs) -> None:
            pass

        def describe_json(self, _preview, **kwargs):
            seen_prompts.append(kwargs["prompt"])
            return _observation()

    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(perception, "QwenVisionClient", FakeVision)
    observations, limitations, metadata = perception.run_remote_perception(
        input_spec=spec,
        local_context=local_context,
        config=_config(),
        max_calls=2,
        max_preview_pixels=100_000,
        max_preview_bytes=200_000,
    )

    assert len(observations) == 2
    assert metadata["record_ids"] == ["image-1", "signal-1"]
    assert any("image record" in prompt for prompt in seen_prompts)
    assert any("signal record" in prompt for prompt in seen_prompts)
    assert any("image-2" in item for item in limitations)


@pytest.mark.parametrize(
    ("multimodal_model", "vision_model"),
    [("qwen3-vl-flash", "qwen3-vl-plus"), ("qwen3-vl-plus", "qwen3-vl-flash")],
)
def test_remote_perception_rejects_any_model_other_than_qwen3_vl_plus(
    monkeypatch,
    tmp_path,
    multimodal_model,
    vision_model,
) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    spec = _image_spec(image_path)
    local_context = build_local_multimodal_input_context(
        spec,
        settings=MultimodalSettings(remote_perception_authorized=True),
    )
    from src.pipeline.multimodal_evidence import perception

    monkeypatch.setattr(
        perception,
        "QwenVisionClient",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no fallback client")),
    )
    with pytest.raises(MultimodalInputError, match="qwen3-vl-plus"):
        build_multimodal_evidence(
            input_spec=spec,
            config=_config(multimodal_model=multimodal_model, vision_model=vision_model),
            local_context=local_context,
        )
