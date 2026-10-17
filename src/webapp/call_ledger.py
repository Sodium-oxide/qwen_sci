"""Persist paid image-call identity before submission and recover known tasks."""

import hashlib
import json
from io import BytesIO

from filelock import FileLock

from .job_artifacts import _atomic_write_json
from .jobs import JobInputError
from .jobs.store import canonical_hash


class UnknownModelCall(JobInputError):
    code = "MODEL_CALL_OUTCOME_UNKNOWN"


def _call_identity(context, *, key, model: str, prompt: str, size: str) -> str:
    return canonical_hash(
        {
            "input": context.job.input_manifest_sha256,
            "revision": context.job.revision,
            "prompt_hash": context.job.prompt_hash,
            "provider": context.job.provider_name,
            "key": key,
            "model": model,
            "prompt": prompt,
            "size": size,
        }
    )


def _legacy_identity(context, *, attempt: int, key, model: str, prompt: str, size: str) -> str:
    return canonical_hash({
        "input": context.job.input_manifest_sha256, "attempt": attempt,
        "key": key, "model": model, "prompt": prompt, "size": size,
    })


def checkpoint_image(context, *, key, client, model: str, prompt: str, size: str) -> bytes:
    identity = _call_identity(context, key=key, model=model, prompt=prompt, size=size)
    root = context.job_dir / "model_calls"
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / f"{identity}.json"
    image_path = root / f"{identity}.png"
    with FileLock(str(root / f"{identity}.guard"), timeout=context.remaining_seconds(30)):
        context.check_cancelled()
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        if not ledger:
            for attempt in range(context.job.attempt, 0, -1):
                legacy_id = _legacy_identity(context, attempt=attempt, key=key, model=model, prompt=prompt, size=size)
                legacy_path = root / f"{legacy_id}.json"
                if legacy_path.exists():
                    ledger = json.loads(legacy_path.read_text(encoding="utf-8"))
                    ledger["revision"] = context.job.revision
                    legacy_image = root / f"{legacy_id}.png"
                    if legacy_image.exists():
                        image_path.write_bytes(legacy_image.read_bytes())
                    _atomic_write_json(ledger_path, ledger)
                    break
        if ledger.get("status") == "SUCCEEDED":
            if ledger.get("revision") not in {None, context.job.revision} or ledger.get("model") not in {None, model}:
                raise JobInputError("The saved image ledger belongs to a different content revision or model.")
            try:
                content = image_path.read_bytes()
            except OSError as exc:
                raise JobInputError("The saved image referenced by the call ledger is missing.") from exc
            if hashlib.sha256(content).hexdigest() != ledger.get("sha256"):
                raise JobInputError("The saved image no longer matches its call ledger.")
            return content
        if ledger and not ledger.get("task_id"):
            raise UnknownModelCall("A previous image request has an unknown outcome; reconcile it with the provider before creating another request.")

        def save_task(task_id):
            _atomic_write_json(ledger_path, {
                "status": "SUBMITTED", "task_id": task_id, "model": model,
                "attempt": context.job.attempt, "revision": context.job.revision,
                "operation_id": identity, "provider": context.job.provider_name,
            })

        if ledger.get("task_id"):
            result = client.resume(task_id=ledger["task_id"], model=model, timeout=context.remaining_seconds(180))
        else:
            with context.store.lease_guard(context.job.job_id, lease_owner=context.lease_owner, attempt=context.job.attempt):
                _atomic_write_json(ledger_path, {
                    "status": "SUBMITTING", "model": model, "attempt": context.job.attempt,
                    "revision": context.job.revision, "operation_id": identity,
                    "provider": context.job.provider_name,
                })
            result = client.generate(
                prompt=prompt, model=model, size=size, timeout=context.remaining_seconds(180), on_task_submitted=save_task,
            )
        if not result.images:
            raise JobInputError("The image provider returned no image.")
        content = result.images[0]
        from PIL import Image

        try:
            with Image.open(BytesIO(content)) as image:
                if image.format != "PNG":
                    raise ValueError("Expected PNG output.")
                image.verify()
        except Exception as exc:
            raise JobInputError("The image provider output is not a valid PNG.") from exc
        temporary = image_path.with_suffix(".tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(image_path)
        finally:
            temporary.unlink(missing_ok=True)
        _atomic_write_json(ledger_path, {
            "status": "SUCCEEDED", "task_id": result.task_id or ledger.get("task_id"), "model": model,
            "attempt": context.job.attempt, "revision": context.job.revision,
            "operation_id": identity, "provider": context.job.provider_name,
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        context.check_cancelled()
        return content
