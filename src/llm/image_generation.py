"""DashScope image-generation adapters with immediate URL materialization."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

import requests

from src.llm.provider_registry import require_model_capabilities, resolve_model, resolve_provider


class ImageGenerationError(RuntimeError):
    """Raised when an image provider rejects or fails a request."""


class ImageCapabilityError(ValueError):
    """Raised before network I/O for an unsupported model operation."""


@dataclass(frozen=True)
class ImageGenerationResult:
    images: tuple[bytes, ...]
    model: str
    provider: str
    revised_prompt: Optional[str] = None
    task_id: Optional[str] = None
    source_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class DashScopeModelAdapter:
    model: str
    endpoint_style: str
    endpoint_path: str
    supports_reference: bool = False
    supports_edit: bool = False
    supports_mask: bool = False
    supports_4k: bool = False

    def validate(
        self,
        *,
        reference_images: Iterable[bytes],
        mask: Optional[bytes],
        size: str,
    ) -> None:
        references = tuple(reference_images)
        if references and not self.supports_reference:
            raise ImageCapabilityError(f"{self.model} does not declare reference-image support.")
        if references and not self.supports_edit:
            raise ImageCapabilityError(f"{self.model} does not declare image-edit support.")
        if mask is not None and not self.supports_mask:
            raise ImageCapabilityError(f"{self.model} does not declare mask-edit support.")
        dimensions = _parse_size(size)
        if dimensions and max(dimensions) > 2048 and not self.supports_4k:
            raise ImageCapabilityError(f"{self.model} does not declare 4K output support.")

    def build_payload(
        self,
        *,
        prompt: str,
        n: int,
        size: str,
        reference_images: Iterable[bytes],
        mask: Optional[bytes],
        output_format: str,
    ) -> dict[str, Any]:
        encoded_references = [
            f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"
            for image in reference_images
        ]
        encoded_mask = (
            f"data:image/png;base64,{base64.b64encode(mask).decode('ascii')}"
            if mask is not None
            else None
        )
        if self.endpoint_style == "openai_images":
            payload: dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "n": n,
                "size": size,
                "response_format": "b64_json",
                "output_format": output_format,
            }
            if encoded_references:
                payload["images"] = encoded_references
            if encoded_mask:
                payload["mask"] = encoded_mask
            return payload

        parameters: dict[str, Any] = {
            "n": n,
            "size": size,
            "output_format": output_format,
        }
        if self.endpoint_style == "dashscope_multimodal":
            content: list[dict[str, str]] = [{"text": prompt}]
            content.extend({"image": image} for image in encoded_references)
            return {
                "model": self.model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": content,
                        }
                    ]
                },
                "parameters": parameters,
            }

        input_payload: dict[str, Any] = {"prompt": prompt}
        if encoded_references:
            input_payload["reference_images"] = encoded_references
        if encoded_mask:
            input_payload["mask"] = encoded_mask
        return {
            "model": self.model,
            "input": input_payload,
            "parameters": parameters,
        }


MODEL_ADAPTERS: dict[str, DashScopeModelAdapter] = {
    "wan2.7-image-pro": DashScopeModelAdapter(
        model="wan2.7-image-pro",
        endpoint_style="dashscope_multimodal",
        endpoint_path="services/aigc/multimodal-generation/generation",
        supports_4k=True,
    ),
    "qwen-image-3.0-pro": DashScopeModelAdapter(
        model="qwen-image-3.0-pro",
        endpoint_style="dashscope_multimodal",
        endpoint_path="services/aigc/multimodal-generation/generation",
    ),
    "z-image-turbo": DashScopeModelAdapter(
        model="z-image-turbo",
        endpoint_style="dashscope_multimodal",
        endpoint_path="services/aigc/multimodal-generation/generation",
    ),
}


class DashScopeImageClient:
    """Submit, poll, and materialize DashScope image tasks."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 180.0,
        poll_interval: float = 1.0,
        session: Optional[requests.Session] = None,
        config: Any = None,
    ) -> None:
        if config is None:
            from src.config import get_config

            config = get_config()
        provider = resolve_provider(config, "qwen")
        configured = config.get("image_generation", {}) if hasattr(config, "get") else {}
        self.api_key = str(api_key or configured.get("api_key") or provider.api_key).strip()
        compatible_base = str(base_url or configured.get("base_url") or "").strip()
        if not compatible_base:
            compatible_base = os.environ.get("DASHSCOPE_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
        self.base_url = _normalize_image_base_url(compatible_base)
        self.timeout = max(1.0, float(timeout or configured.get("timeout_seconds") or 180.0))
        self.poll_interval = max(0.0, float(poll_interval or configured.get("poll_interval_seconds") or 1.0))
        self.session = session or requests.Session()
        self.config = config

    def generate(
        self,
        *,
        prompt: str,
        model: str,
        n: int = 1,
        size: str = "1024x1024",
        reference_images: Optional[Iterable[bytes]] = None,
        mask: Optional[bytes] = None,
        output_format: str = "png",
        timeout: Optional[float] = None,
    ) -> ImageGenerationResult:
        if not self.api_key:
            raise ImageGenerationError("DASHSCOPE_API_KEY is required for Qwen image generation.")
        require_model_capabilities(
            resolve_model(self.config, model, "qwen"),
            ("image_generation",),
            "DashScope image client",
        )
        adapter = self._resolve_adapter(model)
        references = tuple(reference_images or ())
        adapter.validate(reference_images=references, mask=mask, size=size)
        payload_size = (
            _format_dashscope_size(size)
            if adapter.endpoint_style.startswith("dashscope_")
            else size
        )
        payload = adapter.build_payload(
            prompt=prompt,
            n=max(1, min(int(n), 10)),
            size=payload_size,
            reference_images=references,
            mask=mask,
            output_format=output_format,
        )
        request_timeout = max(1.0, float(timeout or self.timeout))
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if adapter.endpoint_style == "dashscope_async":
            headers["X-DashScope-Async"] = "enable"
        response = self.session.post(
            f"{self.base_url}/{adapter.endpoint_path.lstrip('/')}",
            headers=headers,
            json=payload,
            timeout=request_timeout,
        )
        data = _response_json(response)
        task_id = _find_first(data, ("task_id", "taskId"))
        if task_id and not _extract_image_values(data)[0] and not _extract_image_values(data)[1]:
            data = self._poll_task(str(task_id), headers, request_timeout)

        encoded_images, source_urls = _extract_image_values(data)
        images = [base64.b64decode(value) for value in encoded_images]
        for url in source_urls:
            downloaded = self.session.get(url, timeout=request_timeout)
            if getattr(downloaded, "status_code", 200) >= 400:
                raise ImageGenerationError(
                    f"Failed to download temporary image URL: HTTP {downloaded.status_code}"
                )
            content = bytes(getattr(downloaded, "content", b""))
            if not content:
                raise ImageGenerationError("Temporary image URL returned an empty body.")
            images.append(content)
        if not images:
            raise ImageGenerationError("DashScope image response contained no images.")
        revised_prompt = _find_first(data, ("revised_prompt", "revisedPrompt"))
        return ImageGenerationResult(
            images=tuple(images),
            model=model,
            provider="qwen",
            revised_prompt=str(revised_prompt) if revised_prompt else None,
            task_id=str(task_id) if task_id else None,
            source_urls=tuple(source_urls),
        )

    def _resolve_adapter(self, model: str) -> DashScopeModelAdapter:
        base = MODEL_ADAPTERS.get(model)
        if base is None:
            raise ImageCapabilityError(f"No DashScope image adapter is registered for model '{model}'.")
        configured = self.config.get("image_generation", {}) if hasattr(self.config, "get") else {}
        overrides = configured.get("models", {}).get(model, {}) if hasattr(configured, "get") else {}
        if not overrides:
            return base
        return DashScopeModelAdapter(
            model=model,
            endpoint_style=str(overrides.get("endpoint_style") or base.endpoint_style),
            endpoint_path=str(overrides.get("endpoint_path") or base.endpoint_path),
            supports_reference=bool(overrides.get("supports_reference", base.supports_reference)),
            supports_edit=bool(overrides.get("supports_edit", base.supports_edit)),
            supports_mask=bool(overrides.get("supports_mask", base.supports_mask)),
            supports_4k=bool(overrides.get("supports_4k", base.supports_4k)),
        )

    def _poll_task(self, task_id: str, headers: Mapping[str, str], timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        task_url = f"{self.base_url}/tasks/{task_id}"
        while time.monotonic() < deadline:
            response = self.session.get(task_url, headers=dict(headers), timeout=timeout)
            data = _response_json(response)
            status = str(_find_first(data, ("task_status", "status", "taskStatus")) or "").upper()
            if status in {"SUCCEEDED", "SUCCESS", "COMPLETED", "DONE"}:
                return data
            if status in {"FAILED", "ERROR", "CANCELED", "CANCELLED", "UNKNOWN"}:
                message = _find_first(data, ("message", "error_message", "code"))
                raise ImageGenerationError(f"DashScope image task {task_id} failed: {message or status}")
            if self.poll_interval:
                time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(f"DashScope image task {task_id} timed out after {timeout:.1f}s.")


def resolve_image_generation_settings(config: Any, *, role: str = "academic_figure") -> dict[str, Any]:
    image_config = config.get("image_generation", {}) if hasattr(config, "get") else {}
    provider_name = str(image_config.get("provider") or "qwen").strip().lower()
    provider = resolve_provider(config, "qwen" if provider_name == "dashscope" else provider_name)
    role_models = image_config.get("role_models", {}) if hasattr(image_config, "get") else {}
    defaults = {
        "academic_figure": "qwen-image-3.0-pro",
        "text_rich_figure": "qwen-image-3.0-pro",
        "draft": "z-image-turbo",
    }
    model = str(role_models.get(role) or defaults.get(role) or defaults["academic_figure"]).strip()
    require_model_capabilities(
        resolve_model(config, model, provider.name),
        ("image_generation",),
        "Image generation settings",
    )
    return {
        "provider": provider.name,
        "model": model,
        "api_key": str(image_config.get("api_key") or provider.api_key).strip(),
        "base_url": str(
            image_config.get("base_url")
            or os.environ.get("DASHSCOPE_IMAGE_BASE_URL")
            or "https://dashscope.aliyuncs.com/api/v1"
        ).strip(),
        "timeout": float(image_config.get("timeout_seconds") or 180),
        "poll_interval": float(image_config.get("poll_interval_seconds") or 1),
    }


def _normalize_image_base_url(base_url: str) -> str:
    normalized = str(base_url or "").rstrip("/")
    compatible_suffix = "/compatible-mode/v1"
    if normalized.endswith(compatible_suffix):
        normalized = normalized[: -len(compatible_suffix)] + "/api/v1"
    return normalized


def _parse_size(size: str) -> Optional[tuple[int, int]]:
    normalized = str(size or "").lower().replace("*", "x")
    if "x" not in normalized:
        return None
    width, height = normalized.split("x", 1)
    try:
        return int(width), int(height)
    except ValueError:
        return None


def _format_dashscope_size(size: str) -> str:
    dimensions = _parse_size(size)
    if dimensions is None:
        return size
    width, height = dimensions
    return f"{width}*{height}"


def _response_json(response: Any) -> dict[str, Any]:
    status = int(getattr(response, "status_code", 200))
    try:
        data = response.json()
    except Exception as exc:
        text = str(getattr(response, "text", ""))[:500]
        raise ImageGenerationError(f"DashScope returned invalid JSON (HTTP {status}): {text}") from exc
    if status >= 400 or not isinstance(data, dict):
        message = _find_first(data if isinstance(data, dict) else {}, ("message", "error", "code"))
        raise ImageGenerationError(f"DashScope image request failed (HTTP {status}): {message or data}")
    code = str(_find_first(data, ("code", "error_code", "errorCode")) or "").strip()
    if code and code.lower() not in {"ok", "success", "200"}:
        raise ImageGenerationError(f"DashScope image request failed ({code}): {data.get('message') or code}")
    return data


def _find_first(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if key in value and value[key] not in (None, ""):
                return value[key]
        for child in value.values():
            found = _find_first(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first(child, keys)
            if found not in (None, ""):
                return found
    return None


def _extract_image_values(data: Any) -> tuple[list[str], list[str]]:
    encoded: list[str] = []
    urls: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized = str(key).lower()
                if normalized in {"b64_json", "base64", "image_base64"} and isinstance(child, str):
                    encoded.append(child.split(",", 1)[-1])
                elif normalized in {"url", "image_url", "image"} and isinstance(child, str):
                    if child.startswith(("http://", "https://")):
                        urls.append(child)
                    elif child.startswith("data:image/") and ";base64," in child:
                        encoded.append(child.split(";base64,", 1)[1])
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return list(dict.fromkeys(encoded)), list(dict.fromkeys(urls))
