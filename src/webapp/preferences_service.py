"""Versioned single-workspace research preferences."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TypeVar

from filelock import FileLock
from pydantic import BaseModel

from src.llm.model_policy import MODEL_PROFILES

from .preferences_schemas import PreferenceEnvelope, ResearchPreferences
from .jobs.store import canonical_hash


RequestModel = TypeVar("RequestModel", bound=BaseModel)


class PreferenceConflictError(ValueError):
    """Raised when a stale preference version is submitted."""


class PreferencesService:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def defaults() -> ResearchPreferences:
        return ResearchPreferences()

    def get(self) -> PreferenceEnvelope:
        if not self.path.is_file():
            return PreferenceEnvelope(preferences=self.defaults())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            preferences = ResearchPreferences.model_validate(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise PreferenceConflictError("The workspace preference file is invalid.") from exc
        return PreferenceEnvelope(preferences=preferences)

    def update(self, preferences: ResearchPreferences) -> PreferenceEnvelope:
        with FileLock(str(self.path.with_suffix(".guard")), timeout=10):
            return self._update(preferences)

    def _update(self, preferences: ResearchPreferences) -> PreferenceEnvelope:
        current = self.get().preferences
        if preferences.version != current.version:
            raise PreferenceConflictError(
                f"Preference version conflict: expected {current.version}, received {preferences.version}."
            )
        updated = preferences.model_copy(update={"version": current.version + 1})
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return PreferenceEnvelope(preferences=updated)

    def resolve_request(self, request: RequestModel) -> tuple[RequestModel, dict[str, object]]:
        preferences = self.get().preferences
        values = preferences.model_dump(mode="json")
        defaults = {
            "language": preferences.language,
            "target_language": preferences.language,
            "discipline_ids": preferences.disciplines,
            "research_depth": preferences.default_research_depth,
            "model_name": preferences.default_text_model or MODEL_PROFILES[preferences.model_profile],
            "target_journal": preferences.target_journal or "generic",
            "citation_style": preferences.citation_style,
            "output_formats": [preferences.default_output_format],
        }
        payload = request.model_dump(mode="json")
        fields = type(request).model_fields
        for name, value in defaults.items():
            if name == "output_formats" and "target_language" not in fields:
                continue
            if name in fields and name not in request.model_fields_set:
                payload[name] = value
        for name in ("workflow_profile", "prompt_profile"):
            if name in fields and name not in request.model_fields_set:
                payload.pop(name, None)
        resolved = type(request).model_validate(payload)
        return resolved, {"version": preferences.version, "hash": canonical_hash(values), "values": values}

