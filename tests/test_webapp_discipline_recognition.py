from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.llm.json_call import RequiredJsonLLMError
from src.webapp.api import create_app


def test_model_recognition_uses_flash_and_validates_supported_catalog(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def build_callback(**options):
        calls.append(options)

        def respond(messages, **kwargs):
            assert messages[0]["role"] == "system"
            content = json.loads(messages[1]["content"])
            assert content["topic"] == "电催化材料中的界面电荷如何影响反应速率"
            assert len(content["catalog"]) == 20
            assert kwargs["response_format"] == {"type": "json_object"}
            return {"status": "resolved", "suggested_catalog_ids": ["25", "16"], "reason": "研究材料界面及其化学反应机制。"}

        return respond

    monkeypatch.setattr("src.webapp.discipline_service.build_web_json_llm_call", build_callback)
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    response = client.post("/api/disciplines/resolve", json={
        "topic": "电催化材料中的界面电荷如何影响反应速率", "method": "model",
    })
    assert response.status_code == 200, response.text
    assert response.json()["suggested_catalog_ids"] == ["25", "16"]
    assert response.json()["model_name"] == "qwen3.8-flash"
    assert calls[0]["model"] == "qwen3.8-flash"
    assert calls[0]["timeout"] == 45


@pytest.mark.parametrize("suggestion", [
    {"status": "resolved", "suggested_catalog_ids": ["999"], "reason": "未知学科"},
    {"status": "resolved", "suggested_catalog_ids": ["25", "25"], "reason": "重复学科"},
    {"status": "resolved", "suggested_catalog_ids": [], "reason": "空选择"},
    {"status": "out_of_scope", "suggested_catalog_ids": ["25"], "reason": "不支持的课题"},
    {"status": "resolved", "suggested_catalog_ids": ["25", "16", "17"], "reason": "过多学科"},
])
def test_invalid_model_suggestions_are_not_applied(tmp_path: Path, monkeypatch, suggestion) -> None:
    monkeypatch.setattr(
        "src.webapp.discipline_service.build_web_json_llm_call",
        lambda **_options: lambda *_args, **_kwargs: suggestion,
    )
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    response = client.post("/api/disciplines/resolve", json={"topic": "一个需要识别的科研课题", "method": "model"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INVALID_DISCIPLINE_SUGGESTION"


def test_model_failure_keeps_manual_selection_available(tmp_path: Path, monkeypatch) -> None:
    def unavailable(**_options):
        raise RequiredJsonLLMError("Provider unavailable")

    monkeypatch.setattr("src.webapp.discipline_service.build_web_json_llm_call", unavailable)
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    response = client.post("/api/disciplines/resolve", json={"topic": "一个需要识别的科研课题", "method": "model"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DISCIPLINE_MODEL_UNAVAILABLE"
    assert len(client.get("/api/disciplines").json()["disciplines"]) == 20
    local = client.post("/api/disciplines/resolve", json={"topic": "Machine learning image analysis"})
    assert local.status_code == 200
    assert "17" in local.json()["suggested_catalog_ids"]


@pytest.mark.parametrize("preference", [{"privacy_mode": "local-only"}, {"network_access": "never"}])
def test_remote_recognition_respects_workspace_preferences(tmp_path: Path, monkeypatch, preference) -> None:
    calls = []
    monkeypatch.setattr("src.webapp.api.recognize_disciplines", lambda *_args, **_kwargs: calls.append(True))
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    current = client.get("/api/preferences").json()["preferences"]
    assert client.put("/api/preferences", json={**current, **preference}).status_code == 200
    response = client.post("/api/disciplines/resolve", json={"topic": "一个需要识别的科研课题", "method": "model"})
    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize("status", ["unresolved", "out_of_scope"])
def test_model_can_decline_classification(tmp_path: Path, monkeypatch, status) -> None:
    monkeypatch.setattr(
        "src.webapp.discipline_service.build_web_json_llm_call",
        lambda **_options: lambda *_args, **_kwargs: {"status": status, "suggested_catalog_ids": [], "reason": "请补充研究对象和方法，或手动核对支持范围。"},
    )
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    response = client.post("/api/disciplines/resolve", json={"topic": "一个需要识别的课题", "method": "model"})
    assert response.status_code == 200
    assert response.json()["suggested_catalog_ids"] == []
    assert response.json()["status"] == status
