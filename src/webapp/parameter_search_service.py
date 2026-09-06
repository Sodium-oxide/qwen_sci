"""Run-scoped interactive academic search for quantitative parameters."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from src.agents.quantitative_modeling.parameter_evidence.providers import AcademicMetadataProviders, ParameterEvidenceSettings
from src.pipeline.science_run import atomic_write_json, append_science_event, locked_science_run, science_run_paths


def _text(value: object) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _year(value: object) -> int | None:
    try:
        year = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return year if year > 0 else None


def _doi(value: object) -> str:
    doi = _text(value)
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.casefold().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip().rstrip("/.,;").casefold()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _title(value: object) -> str:
    return " ".join("".join(char.casefold() if char.isalnum() else " " for char in _text(value)).split())


def _merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for record in records:
        title = _text(record.get("title"))
        if not title:
            continue
        doi = _doi(record.get("doi"))
        year = _year(record.get("year"))
        match: dict[str, Any] | None = None
        match_method = "provider_id"
        for candidate in merged:
            if doi and doi == _doi(candidate.get("doi")):
                match = candidate
                match_method = "doi"
                break
            if not doi and not _text(candidate.get("doi")):
                candidate_year = _year(candidate.get("year"))
                if year and candidate_year and year != candidate_year:
                    continue
                if SequenceMatcher(None, _title(title), _title(candidate.get("title"))).ratio() >= 0.92:
                    match = candidate
                    match_method = "title_year"
                    break
        if match is None:
            match = {
                "paper_id": f"PS-{len(merged) + 1:03d}",
                "title": title,
                "doi": doi,
                "year": year,
                "sources": [],
                "provider_records": [],
                "oa_locations": [],
                "cross_validated": False,
                "match_method": match_method,
            }
            merged.append(match)
        provider = _text(record.get("provider"))
        if provider and provider not in match["sources"]:
            match["sources"].append(provider)
        provider_record = {
            "provider": provider,
            "provider_paper_id": _text(record.get("provider_paper_id")),
        }
        if provider_record not in match["provider_records"]:
            match["provider_records"].append(provider_record)
        for raw_location in record.get("oa_locations") or []:
            location = _mapping(raw_location)
            if location and location not in match["oa_locations"]:
                match["oa_locations"].append(location)
        if not match.get("abstract") and _text(record.get("abstract")):
            match["abstract"] = _text(record.get("abstract"))[:4_000]
        match["cross_validated"] = len(match["sources"]) >= 2
        if match_method == "doi" or match.get("match_method") == "provider_id":
            match["match_method"] = match_method
    return merged


class ParameterSearchService:
    """Submit bounded provider searches and persist their durable job state."""

    def __init__(
        self,
        *,
        config_path: Path,
        submit_task: Callable[[str, Callable[[], object]], None],
    ) -> None:
        self.config_path = config_path
        self._submit_task = submit_task

    @staticmethod
    def job_directory(run_dir: Path, idea_id: str, version: int) -> Path:
        return run_dir / "quantitative" / idea_id / "parameter_evidence" / f"v{version}" / "interactive_search"

    def start(
        self,
        *,
        run_id: str,
        run_dir: Path,
        idea_id: str,
        version: int,
        parameter_id: str,
        query: str,
        providers: tuple[str, ...],
        limit: int,
        parameter_request: dict[str, Any],
        blueprint_identity: str,
    ) -> dict[str, Any]:
        job_id = f"psearch-{uuid.uuid4().hex[:20]}"
        path = self.job_directory(run_dir, idea_id, version) / f"{job_id}.json"
        initial = {
            "schema_version": "parameter_search_job_v1",
            "job_id": job_id,
            "run_id": run_id,
            "idea_id": idea_id,
            "version": version,
            "parameter_id": parameter_id,
            "parameter_request": parameter_request,
            "blueprint_identity": blueprint_identity,
            "query": query,
            "providers": list(providers),
            "limit": limit,
            "status": "QUEUED",
            "created_at": _now(),
            "updated_at": _now(),
            "provider_runs": [],
            "papers": [],
            "evidence_boundary": "Search metadata and snippets are not numerical parameter evidence.",
        }
        paths = science_run_paths(run_dir)
        with locked_science_run(paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, initial)
            append_science_event(
                paths,
                event_type="PARAMETER_SEARCH_STARTED",
                job_id=job_id,
                idea_id=idea_id,
                version=version,
                parameter_id=parameter_id,
            )

        def task() -> None:
            self._execute(
                run_id=run_id,
                run_dir=run_dir,
                path=path,
                job_id=job_id,
                idea_id=idea_id,
                version=version,
                parameter_id=parameter_id,
                query=query,
                providers=providers,
                limit=limit,
                parameter_request=parameter_request,
                blueprint_identity=blueprint_identity,
            )

        self._submit_task(run_id=run_id, task=task)
        return initial

    def _execute(self, **kwargs: Any) -> None:
        run_dir = Path(kwargs["run_dir"])
        path = Path(kwargs["path"])
        job_id = _text(kwargs["job_id"])
        try:
            from src.config import load_config

            settings = ParameterEvidenceSettings.from_runtime_config(load_config(str(self.config_path)))
            provider_client = AcademicMetadataProviders(settings)
            self._update(run_dir, path, {"status": "RUNNING", "updated_at": _now()})
            methods = {
                "openalex": provider_client.search_openalex,
                "anysearch": provider_client.search_anysearch,
            }
            provider_runs: list[dict[str, Any]] = []
            records: list[dict[str, Any]] = []
            selected = [name for name in kwargs["providers"] if name in methods]
            with ThreadPoolExecutor(max_workers=max(1, len(selected))) as executor:
                futures = {executor.submit(methods[name], kwargs["query"]): name for name in selected}
                for future in as_completed(futures):
                    provider = futures[future]
                    try:
                        result = list(future.result() or [])[: int(kwargs["limit"])]
                    except Exception as error:
                        provider_runs.append({"provider": provider, "status": "FAILED", "record_count": 0, "error": str(error)[:500]})
                        self._event(run_dir, "PARAMETER_SEARCH_PROVIDER_COMPLETED", job_id=job_id, provider=provider, status="FAILED", record_count=0)
                        continue
                    records.extend(result)
                    provider_runs.append({"provider": provider, "status": "COMPLETED" if result else "NO_RESULTS", "record_count": len(result)})
                    self._event(
                        run_dir,
                        "PARAMETER_SEARCH_PROVIDER_COMPLETED",
                        job_id=job_id,
                        provider=provider,
                        status="COMPLETED" if result else "NO_RESULTS",
                        record_count=len(result),
                    )
            self._update(
                run_dir,
                path,
                {
                    "status": "COMPLETED",
                    "updated_at": _now(),
                    "provider_runs": sorted(provider_runs, key=lambda item: item["provider"]),
                    "papers": sorted(_merge_records(records), key=lambda item: str(item.get("paper_id", ""))),
                },
            )
            self._event(run_dir, "PARAMETER_SEARCH_COMPLETED", job_id=job_id, idea_id=kwargs["idea_id"], version=kwargs["version"], parameter_id=kwargs["parameter_id"])
        except Exception as error:
            self._update(run_dir, path, {"status": "FAILED", "updated_at": _now(), "error": str(error)[:1_000]})
            self._event(run_dir, "PARAMETER_SEARCH_FAILED", job_id=job_id, error=str(error)[:500])

    @staticmethod
    def _event(run_dir: Path, event_type: str, **fields: Any) -> None:
        paths = science_run_paths(run_dir)
        with locked_science_run(paths):
            append_science_event(paths, event_type=event_type, **fields)

    @staticmethod
    def _update(run_dir: Path, path: Path, patch: dict[str, Any]) -> None:
        try:
            import json

            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        current.update(patch)
        with locked_science_run(science_run_paths(run_dir)):
            atomic_write_json(path, current)


__all__ = ["ParameterSearchService"]
