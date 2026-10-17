from __future__ import annotations

import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.llm.image_generation import ImageGenerationResult
from src.webapp.call_ledger import UnknownModelCall, _call_identity, checkpoint_image
from src.webapp.jobs import JobInputError
from src.webapp.jobs.runner import JobCancelled


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (1, 1), (20, 40, 60, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Store:
    @contextmanager
    def lease_guard(self, *_args, **_kwargs):
        yield


class _Context:
    def __init__(self, root: Path, *, attempt: int = 1, revision: int = 1) -> None:
        self.job_dir = root
        self.job = SimpleNamespace(
            job_id="job-image-recovery",
            attempt=attempt,
            revision=revision,
            prompt_hash="b" * 64,
            provider_name="qwen",
            input_manifest_sha256="a" * 64,
        )
        self.store = _Store()
        self.lease_owner = "test-worker"

    def check_cancelled(self) -> None:
        return None

    def remaining_seconds(self, _maximum: float = 30) -> float:
        return 30.0


class _Client:
    def __init__(self, *, fail_generate_once: bool = False) -> None:
        self.fail_generate_once = fail_generate_once
        self.generate_calls = 0
        self.resume_calls = 0

    def generate(self, **kwargs):
        self.generate_calls += 1
        callback = kwargs["on_task_submitted"]
        callback("task-123")
        if self.fail_generate_once:
            self.fail_generate_once = False
            raise TimeoutError("provider response was lost")
        return ImageGenerationResult(
            images=(_png(),),
            model=kwargs["model"],
            provider="qwen",
            task_id="task-123",
        )

    def resume(self, **kwargs):
        self.resume_calls += 1
        return ImageGenerationResult(
            images=(_png(),),
            model=kwargs["model"],
            provider="qwen",
            task_id=kwargs["task_id"],
        )


def _identity_paths(context: _Context, *, key: object = None, model: str = "qwen-image-3.0-pro") -> tuple[Path, Path]:
    identity = _call_identity(
        context,
        key=key,
        model=model,
        prompt="scientific schematic",
        size="2048x1536",
    )
    root = context.job_dir / "model_calls"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{identity}.json", root / f"{identity}.png"


def test_known_task_is_resumed_without_a_second_generate(tmp_path: Path) -> None:
    context = _Context(tmp_path)
    client = _Client(fail_generate_once=True)

    with pytest.raises(TimeoutError):
        checkpoint_image(
            context,
            key=None,
            client=client,
            model="qwen-image-3.0-pro",
            prompt="scientific schematic",
            size="2048x1536",
        )
    content = checkpoint_image(
        context,
        key=None,
        client=client,
        model="qwen-image-3.0-pro",
        prompt="scientific schematic",
        size="2048x1536",
    )

    assert content == _png()
    assert client.generate_calls == 1
    assert client.resume_calls == 1


def test_submitting_without_task_id_requires_provider_reconciliation(tmp_path: Path) -> None:
    context = _Context(tmp_path)
    ledger_path, _image_path = _identity_paths(context)
    ledger_path.write_text(
        json.dumps({"status": "SUBMITTING", "attempt": context.job.attempt, "model": "qwen-image-3.0-pro"}),
        encoding="utf-8",
    )

    with pytest.raises(UnknownModelCall):
        checkpoint_image(
            context,
            key=None,
            client=_Client(),
            model="qwen-image-3.0-pro",
            prompt="scientific schematic",
            size="2048x1536",
        )


def test_succeeded_image_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    context = _Context(tmp_path)
    ledger_path, image_path = _identity_paths(context)
    image_path.write_bytes(_png())
    ledger_path.write_text(
        json.dumps({
            "status": "SUCCEEDED",
            "attempt": context.job.attempt,
            "model": "qwen-image-3.0-pro",
            "sha256": "0" * 64,
        }),
        encoding="utf-8",
    )

    with pytest.raises(JobInputError, match="no longer matches"):
        checkpoint_image(
            context,
            key=None,
            client=_Client(),
            model="qwen-image-3.0-pro",
            prompt="scientific schematic",
            size="2048x1536",
        )


def test_worker_recovery_reuses_completed_image_from_previous_attempt(tmp_path: Path) -> None:
    first_context = _Context(tmp_path, attempt=1)
    client = _Client()
    checkpoint_image(
        first_context,
        key=None,
        client=client,
        model="qwen-image-3.0-pro",
        prompt="scientific schematic",
        size="2048x1536",
    )

    second_context = _Context(tmp_path, attempt=2)
    checkpoint_image(
        second_context,
        key=None,
        client=client,
        model="qwen-image-3.0-pro",
        prompt="scientific schematic",
        size="2048x1536",
    )

    assert client.generate_calls == 1
    assert client.resume_calls == 0


def test_worker_recovery_resumes_remote_task_from_previous_attempt(tmp_path: Path) -> None:
    client = _Client(fail_generate_once=True)
    with pytest.raises(TimeoutError):
        checkpoint_image(
            _Context(tmp_path), key=None, client=client, model="qwen-image-3.0-pro",
            prompt="scientific schematic", size="2048x1536",
        )
    content = checkpoint_image(
        _Context(tmp_path, attempt=2), key=None, client=client, model="qwen-image-3.0-pro",
        prompt="scientific schematic", size="2048x1536",
    )
    assert content == _png()
    assert client.generate_calls == 1
    assert client.resume_calls == 1


def test_user_revision_starts_a_distinct_image_operation(tmp_path: Path) -> None:
    client = _Client()
    for revision in (1, 2):
        checkpoint_image(
            _Context(tmp_path, attempt=revision, revision=revision), key=None, client=client,
            model="qwen-image-3.0-pro", prompt="scientific schematic", size="2048x1536",
        )
    assert client.generate_calls == 2


def test_submitted_task_is_saved_even_when_cancellation_arrives(tmp_path: Path) -> None:
    context = _Context(tmp_path)
    client = _Client(fail_generate_once=True)
    original_generate = client.generate

    def generate(**kwargs):
        def cancelled():
            raise JobCancelled()

        context.check_cancelled = cancelled
        return original_generate(**kwargs)

    client.generate = generate
    with pytest.raises(TimeoutError):
        checkpoint_image(
            context, key=None, client=client, model="qwen-image-3.0-pro",
            prompt="scientific schematic", size="2048x1536",
        )
    ledger_path, _image_path = _identity_paths(context)
    assert json.loads(ledger_path.read_text())["task_id"] == "task-123"
    checkpoint_image(
        _Context(tmp_path, attempt=2), key=None, client=client, model="qwen-image-3.0-pro",
        prompt="scientific schematic", size="2048x1536",
    )
    assert client.generate_calls == 1
    assert client.resume_calls == 1
