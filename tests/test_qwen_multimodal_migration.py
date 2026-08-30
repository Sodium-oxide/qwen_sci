import asyncio
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from src.llm.image_generation import (
    DashScopeImageClient,
    ImageCapabilityError,
    ImageGenerationError,
    resolve_image_generation_settings,
)
from src.llm.vision import QwenVisionClient, resolve_vision_settings


def _config():
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
            "vision": {
                "provider": "qwen",
                "quality_model": "qwen3-vl-plus",
                "batch_model": "qwen3-vl-flash",
                "max_tokens": 512,
            },
            "image_generation": {
                "provider": "qwen",
                "base_url": "https://dashscope.example/api/v1",
                "role_models": {
                    "academic_figure": "wan2.7-image-pro",
                    "text_rich_figure": "qwen-image-3.0-pro",
                    "draft": "z-image-turbo",
                },
            },
        }
    )


class FakeChatCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeVisionClient:
    def __init__(self, content):
        completions = FakeChatCompletions(content)
        self.chat = SimpleNamespace(completions=completions)
        self.completions = completions


def test_qwen_vision_payload_uses_data_url_and_quality_model():
    fake = FakeVisionClient('{"problematic_indices":[0,99,-1],"notes":["typo"]}')
    client = QwenVisionClient(
        model="qwen3-vl-plus",
        provider="qwen",
        client=fake,
        config=_config(),
    )

    result = client.review_ocr_labels(b"image-bytes", ["label", "other"])

    assert result.problematic_indices == (0,)
    payload = fake.completions.calls[0]
    image_block = payload["messages"][0]["content"][1]
    assert image_block["type"] == "image_url"
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(image_block["image_url"]["url"].split(",", 1)[1]) == b"image-bytes"
    assert payload["model"] == "qwen3-vl-plus"
    assert payload["response_format"] == {"type": "json_object"}


def test_qwen_vision_describe_json_enforces_json_object_response_format():
    fake = FakeVisionClient('{"finding":"bounded preview"}')
    client = QwenVisionClient(
        model="qwen3-vl-plus",
        provider="qwen",
        client=fake,
        config=_config(),
    )

    result = client.describe_json(
        b"png-preview",
        prompt="return one object",
        schema={
            "type": "object",
            "properties": {"finding": {"type": "string"}},
            "required": ["finding"],
            "additionalProperties": False,
        },
    )

    assert result == {"finding": "bounded preview"}
    assert fake.completions.calls[0]["model"] == "qwen3-vl-plus"
    assert fake.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_vision_settings_select_quality_and_batch_models():
    config = _config()
    assert resolve_vision_settings(config)["model"] == "qwen3-vl-plus"
    assert resolve_vision_settings(config, batch=True)["model"] == "qwen3-vl-flash"


class FakeHttpResponse:
    def __init__(self, payload=None, *, status_code=200, content=b""):
        self._payload = payload or {}
        self.status_code = status_code
        self.content = content
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeImageSession:
    def __init__(self, *, inline=None, task_payloads=None, download=b"downloaded"):
        self.inline = inline
        self.task_payloads = list(task_payloads or [])
        self.download = download
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.inline is not None:
            return FakeHttpResponse(self.inline)
        return FakeHttpResponse({"output": {"task_id": "task-1"}})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url == "https://temporary.example/image.png":
            return FakeHttpResponse(content=self.download)
        payload = self.task_payloads.pop(0) if len(self.task_payloads) > 1 else self.task_payloads[0]
        return FakeHttpResponse(payload)


def test_dashscope_image_adapter_polls_and_downloads_temporary_url():
    session = FakeImageSession(
        task_payloads=[
            {"output": {"task_status": "RUNNING"}},
            {
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"url": "https://temporary.example/image.png"}],
                }
            },
        ]
    )
    client = DashScopeImageClient(
        api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        poll_interval=0,
        session=session,
        config=_config(),
    )

    result = client.generate(prompt="scientific figure", model="wan2.7-image-pro", size="4096x4096")

    assert result.images == (b"downloaded",)
    assert result.task_id == "task-1"
    assert result.source_urls == ("https://temporary.example/image.png",)
    assert session.posts[0][0].endswith("/api/v1/services/aigc/multimodal-generation/generation")
    assert "X-DashScope-Async" not in session.posts[0][1]["headers"]
    assert session.posts[0][1]["json"]["parameters"]["size"] == "4096*4096"
    assert session.posts[0][1]["json"]["input"]["messages"] == [
        {"role": "user", "content": [{"text": "scientific figure"}]}
    ]


def test_dashscope_image_adapter_accepts_inline_base64_response():
    encoded = base64.b64encode(b"inline-image").decode()
    session = FakeImageSession(
        inline={"output": {"results": [{"url": f"data:image/png;base64,{encoded}"}]}}
    )
    client = DashScopeImageClient(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        session=session,
        config=_config(),
    )

    result = client.generate(prompt="draft", model="z-image-turbo")

    assert result.images == (b"inline-image",)
    assert not session.gets


def test_dashscope_multimodal_response_accepts_image_field():
    encoded = base64.b64encode(b"multimodal-image").decode()
    session = FakeImageSession(
        inline={"output": {"choices": [{"message": {"content": [{"image": f"data:image/png;base64,{encoded}"}]}}]}}
    )
    client = DashScopeImageClient(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        session=session,
        config=_config(),
    )

    result = client.generate(prompt="multimodal figure", model="wan2.7-image-pro")

    assert result.images == (b"multimodal-image",)


def test_image_adapter_rejects_unsupported_reference_and_4k_before_network():
    session = FakeImageSession(inline={})
    client = DashScopeImageClient(api_key="test-key", session=session, config=_config())
    with pytest.raises(ImageCapabilityError, match="reference-image"):
        client.generate(prompt="edit", model="z-image-turbo", reference_images=[b"reference"])
    with pytest.raises(ImageCapabilityError, match="4K"):
        client.generate(prompt="large", model="z-image-turbo", size="4096x4096")
    assert not session.posts


def test_image_adapter_surfaces_content_moderation_error():
    session = FakeImageSession(inline={"code": "DataInspectionFailed", "message": "blocked"})
    client = DashScopeImageClient(api_key="test-key", session=session, config=_config())
    with pytest.raises(ImageGenerationError, match="DataInspectionFailed"):
        client.generate(prompt="blocked", model="wan2.7-image-pro")


def test_image_adapter_timeout_is_reported():
    session = FakeImageSession(task_payloads=[{"output": {"task_status": "RUNNING"}}])
    client = DashScopeImageClient(
        api_key="test-key",
        session=session,
        poll_interval=0.01,
        timeout=0.02,
        config=_config(),
    )
    with pytest.raises(TimeoutError, match="timed out"):
        client.generate(prompt="slow", model="wan2.7-image-pro")


def test_openharness_qwen_tool_writes_bytes_and_metadata(monkeypatch, tmp_path):
    harness_src = str(Path(__file__).parents[1] / "src" / "harness" / "src")
    if harness_src not in sys.path:
        sys.path.insert(0, harness_src)
    from openharness.tools.base import ToolExecutionContext
    from openharness.tools.image_generation_tool import ImageGenerationTool, ImageGenerationToolInput
    from src.llm import image_generation

    class FakeQwenImageClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate(self, **kwargs):
            return image_generation.ImageGenerationResult(
                images=(b"tool-image",),
                model=kwargs["model"],
                provider="qwen",
                task_id="task-tool",
                revised_prompt="revised",
                source_urls=("https://temporary.example/tool.png",),
            )

    monkeypatch.setattr(image_generation, "DashScopeImageClient", FakeQwenImageClient)
    tool = ImageGenerationTool()
    result = asyncio.run(
        tool.execute(
            ImageGenerationToolInput(
                provider="qwen",
                prompt="figure",
                output_dir="generated",
                overwrite=True,
            ),
            ToolExecutionContext(cwd=tmp_path, metadata={"image_generation_config": {"provider": "qwen"}}),
        )
    )

    assert not result.is_error
    assert (tmp_path / "generated" / "image.png").read_bytes() == b"tool-image"
    assert result.metadata["task_id"] == "task-tool"
    assert result.metadata["source_urls"] == ["https://temporary.example/tool.png"]
