"""Hash-verified, path-safe file registry for new web Jobs."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import UploadFile
from filelock import FileLock

from .file_schemas import FileView


class FileServiceError(ValueError):
    """Raised when a shared web file cannot be accepted or read."""


_FILE_ID_PATTERN = re.compile(r"file-[a-f0-9]{32}")
_MAX_FILENAME_LENGTH = 180
_DEFAULT_MAX_FILE_BYTES = 52_428_800
_DEFAULT_MAX_PROJECT_BYTES = 1_073_741_824
_ALLOWED_SUFFIXES = frozenset(
    {
        ".c", ".cpp", ".csv", ".docx", ".gif", ".h", ".ipynb", ".jpeg", ".jpg",
        ".json", ".jl", ".latex", ".m", ".markdown", ".md", ".mol", ".mol2", ".mov",
        ".mp3", ".mp4", ".npy", ".npz", ".pdf", ".ply", ".png", ".py", ".r", ".sdf",
        ".smi", ".smiles", ".tex", ".tif", ".tiff", ".tsv", ".txt", ".wav", ".webm",
        ".webp", ".xls", ".xlsx", ".xml", ".xyz", ".yaml", ".yml", ".zip",
    }
)
_MAGIC_TYPES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpeg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"PK\x03\x04", "application/zip", "zip"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_filename(value: str | None) -> tuple[str, str]:
    original = Path(str(value or "upload").replace("\\", "/")).name
    sanitized = re.sub(r"[^A-Za-z0-9._ -]", "_", original).strip(". ") or "upload"
    suffix = Path(sanitized).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise FileServiceError(f"Unsupported upload type: {suffix or 'no extension'}")
    return sanitized[: _MAX_FILENAME_LENGTH - len(suffix)].removesuffix(suffix) + suffix, suffix


def _detect_type(prefix: bytes, suffix: str, declared_mime: str | None) -> tuple[str, str]:
    for magic, mime_type, detected_type in _MAGIC_TYPES:
        if prefix.startswith(magic):
            return mime_type, detected_type
    if suffix in {".txt", ".md", ".markdown", ".tex", ".latex", ".py", ".r", ".json", ".yaml", ".yml", ".csv", ".tsv", ".xml"}:
        return (declared_mime or mimetypes.guess_type(f"file{suffix}")[0] or "text/plain"), "text"
    if declared_mime and declared_mime != "application/octet-stream":
        return declared_mime, suffix.lstrip(".")
    guessed = mimetypes.guess_type(f"file{suffix}")[0] or "application/octet-stream"
    return guessed, suffix.lstrip(".")


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class FileService:
    """Register files under an app-owned root and never expose local paths."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_project_bytes: int = _DEFAULT_MAX_PROJECT_BYTES,
        max_uncompressed_bytes: int = 268_435_456,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_project_bytes = max(self.max_file_bytes, int(max_project_bytes))
        self.max_uncompressed_bytes = max(1, int(max_uncompressed_bytes))
        self.root.mkdir(parents=True, exist_ok=True)
        self._mutation_lock = FileLock(str(self.root / ".files.guard"), timeout=30)
        self.job_store = None

    def locked_files(self) -> FileLock:
        return self._mutation_lock

    def register_run_material(
        self, path: Path, *, original_name: str, run_id: str, material_scope: str,
        sensitive: bool, project_id: str | None = None,
    ) -> FileView:
        with self.locked_files():
            with path.open("rb") as handle:
                record = self._register_upload(
                    UploadFile(file=handle, filename=original_name), project_id=project_id, owner_id=None,
                    sensitivity="sensitive" if sensitive else "controlled", source="run_material",
                    run_id=run_id, job_id=None,
                )
            stored = self._load_record(record.file_id)
            stored["material_scope"] = material_scope
            stored["references"] = [f"run:{run_id}"]
            _atomic_write_json(self._directory(record.file_id) / "file.json", stored)
            return self._view(stored)

    def release_reference(self, file_id: str, *, run_id: str | None = None, job_id: str | None = None) -> None:
        if bool(run_id) == bool(job_id):
            raise FileServiceError("Provide exactly one Job or run reference to release.")
        with self.locked_files():
            stored = self._load_record(file_id)
            reference = f"run:{run_id}" if run_id else f"job:{job_id}"
            remaining = [value for value in stored.get("references", []) if value != reference]
            stored["references"] = remaining
            for field in ("run_id", "job_id"):
                prefix = "run:" if field == "run_id" else "job:"
                stored[field] = next((value[len(prefix):] for value in remaining if value.startswith(prefix)), None)
            _atomic_write_json(self._directory(file_id) / "file.json", stored)

    def reconcile_job_references(self) -> None:
        if self.job_store is None:
            return
        with self.locked_files():
            for file_id, job_id in self.job_store.file_references():
                try:
                    self._attach_reference(file_id, job_id=job_id, run_id=None)
                except FileServiceError:
                    continue

    def register_artifact(self, path: Path, *, metadata: dict[str, Any], project_id: str | None) -> FileView:
        with self.locked_files():
            for record_path in self.root.glob("file-*/file.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("source_artifact_id") == metadata["artifact_id"] and record.get("project_id") == project_id:
                    return self.get(str(record["file_id"]))
            sources = [self.get(str(file_id)) for file_id in metadata.get("source_file_ids", [])]
            sensitivity = "sensitive" if any(source.sensitivity == "sensitive" for source in sources) else "controlled"
            with path.open("rb") as handle:
                view = self._register_upload(
                    UploadFile(file=handle, filename=str(metadata["label"])), project_id=project_id,
                    owner_id=None, sensitivity=sensitivity, source="generated", run_id=None, job_id=metadata["job_id"],
                )
            record = self._load_record(view.file_id)
            record["source_artifact_id"] = metadata["artifact_id"]
            record["references"] = [f"job:{metadata['job_id']}"]
            if any(source.material_scope == "do_not_send" for source in sources):
                record["material_scope"] = "do_not_send"
            _atomic_write_json(self._directory(view.file_id) / "file.json", record)
            return self._view(record)

    def register_upload(
        self,
        upload: UploadFile,
        *,
        project_id: str | None = None,
        owner_id: str | None = None,
        sensitivity: Literal["public", "controlled", "sensitive"] = "controlled",
        source: Literal["upload", "run_material", "generated"] = "upload",
        run_id: str | None = None,
        job_id: str | None = None,
    ) -> FileView:
        with self._mutation_lock:
            return self._register_upload(
                upload, project_id=project_id, owner_id=owner_id, sensitivity=sensitivity,
                source=source, run_id=run_id, job_id=job_id,
            )

    def _register_upload(
        self, upload: UploadFile, *, project_id: str | None, owner_id: str | None,
        sensitivity: str, source: str, run_id: str | None, job_id: str | None,
    ) -> FileView:
        if sensitivity not in {"public", "controlled", "sensitive"}:
            raise FileServiceError("Unsupported file sensitivity.")
        original_name, suffix = _safe_filename(upload.filename)
        file_id = f"file-{uuid.uuid4().hex}"
        file_dir = self._directory(file_id, must_exist=False)
        file_dir.mkdir(parents=True, exist_ok=False)
        content_path = file_dir / "content"
        digest = hashlib.sha256()
        prefix = bytearray()
        size = 0
        try:
            with content_path.open("wb") as handle:
                while True:
                    chunk = upload.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_file_bytes:
                        raise FileServiceError(
                            f"File exceeds the maximum size of {self.max_file_bytes} bytes."
                        )
                    if len(prefix) < 64:
                        prefix.extend(chunk[: 64 - len(prefix)])
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            content_path.unlink(missing_ok=True)
            file_dir.rmdir()
            raise

        mime_type, detected_type = _detect_type(bytes(prefix), suffix, upload.content_type)
        binary_signatures = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".npy": b"\x93NUMPY"}
        expected_signature = binary_signatures.get(suffix)
        if size == 0 or (expected_signature is not None and not bytes(prefix).startswith(expected_signature)):
            content_path.unlink(missing_ok=True)
            file_dir.rmdir()
            raise FileServiceError("File content is empty or does not match its extension.")
        if detected_type == "zip":
            try:
                self._validate_zip(content_path)
            except FileServiceError:
                content_path.unlink(missing_ok=True)
                file_dir.rmdir()
                raise
        declared_mime = str(upload.content_type or "").split(";", 1)[0].strip().lower()
        magic_detected = any(bytes(prefix).startswith(magic) for magic, _mime, _detected in _MAGIC_TYPES)
        suffix_aliases = {
            "jpeg": {".jpg", ".jpeg"},
            "jpg": {".jpg", ".jpeg"},
            "tif": {".tif", ".tiff"},
            "tiff": {".tif", ".tiff"},
            "zip": {".zip", ".docx", ".xlsx", ".npz"},
        }
        valid_suffixes = suffix_aliases.get(detected_type, {f".{detected_type}"})
        if magic_detected and suffix not in valid_suffixes:
            content_path.unlink(missing_ok=True)
            file_dir.rmdir()
            raise FileServiceError("The file extension does not match its detected content type.")
        if declared_mime and declared_mime != "application/octet-stream":
            expected_mimes = {
                "pdf": {"application/pdf"},
                "png": {"image/png"},
                "jpeg": {"image/jpeg"},
                "gif": {"image/gif"},
                "zip": {"application/zip", "application/x-zip-compressed", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            }.get(detected_type)
            if expected_mimes and declared_mime not in expected_mimes:
                content_path.unlink(missing_ok=True)
                file_dir.rmdir()
                raise FileServiceError("The declared MIME type does not match the detected content type.")
        if suffix in {".docx", ".xlsx", ".npz", ".zip"} and detected_type != "zip":
            content_path.unlink(missing_ok=True)
            file_dir.rmdir()
            raise FileServiceError("The file must contain a valid ZIP container.")
        if detected_type == "zip" and suffix in {".docx", ".xlsx"}:
            with zipfile.ZipFile(content_path) as archive:
                required_member = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
                valid_office = required_member in archive.namelist()
            if not valid_office:
                content_path.unlink(missing_ok=True)
                file_dir.rmdir()
                raise FileServiceError("Office container does not match its extension.")
            mime_type = "application/vnd.openxmlformats-officedocument." + ("wordprocessingml.document" if suffix == ".docx" else "spreadsheetml.sheet")
            detected_type = suffix[1:]
        if detected_type == "text":
            try:
                text_content = content_path.read_text(encoding="utf-8-sig")
                if "\x00" in text_content:
                    raise UnicodeError("binary content")
            except UnicodeError as exc:
                content_path.unlink(missing_ok=True)
                file_dir.rmdir()
                raise FileServiceError("Text files must contain valid UTF-8 text.") from exc
            mime_type = mimetypes.guess_type(f"file{suffix}")[0] or "text/plain"
        record: dict[str, object] = {
            "file_id": file_id,
            "original_name": original_name,
            "stored_name": "content",
            "mime_type": mime_type,
            "detected_type": detected_type,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "source": source,
            "owner_id": owner_id,
            "project_id": project_id,
            "run_id": run_id,
            "job_id": job_id,
            "sensitivity": sensitivity,
            "parser_backend": None,
            "parser_version": None,
            "created_at": utc_now(),
            "retention_until": None,
            "references": [],
        }
        try:
            self._assert_project_quota(project_id, size, exclude_file_id=file_id)
        except Exception:
            content_path.unlink(missing_ok=True)
            file_dir.rmdir()
            raise
        _atomic_write_json(file_dir / "file.json", record)
        return self._view(record)

    def get(self, file_id: str) -> FileView:
        record = self._load_record(file_id)
        content = self._content_path(record)
        if not content.is_file() or self._sha256(content) != record["sha256"]:
            raise FileServiceError("Registered file is missing or no longer matches its hash.")
        return self._view(record)

    def content_path(self, file_id: str) -> Path:
        record = self._load_record(file_id)
        content = self._content_path(record)
        if not content.is_file() or self._sha256(content) != record["sha256"]:
            raise FileServiceError("Registered file is missing or no longer matches its hash.")
        return content

    def list(self, *, project_id: str | None = None, limit: int = 100) -> list[FileView]:
        views: list[FileView] = []
        for path in sorted(self.root.glob("file-*/file.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or (project_id is not None and record.get("project_id") != project_id):
                    continue
                views.append(self._view(record))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if len(views) >= max(1, min(int(limit), 1_000)):
                break
        return views

    def delete(self, file_id: str) -> None:
        with self._mutation_lock:
            self._delete(file_id)

    def _delete(self, file_id: str) -> None:
        record = self._load_record(file_id)
        references = record.get("references")
        if (
            record.get("job_id") or record.get("run_id") or (isinstance(references, list) and references)
            or (self.job_store is not None and self.job_store.file_is_referenced(file_id))
        ):
            raise FileServiceError("Files referenced by a run or Job cannot be deleted.")
        directory = self._directory(file_id)
        import shutil

        shutil.rmtree(directory)

    def attach_reference(
        self,
        file_id: str,
        *,
        job_id: str | None = None,
        run_id: str | None = None,
    ) -> FileView:
        """Record a durable reference so an input cannot disappear mid-Job."""

        with self._mutation_lock:
            return self._attach_reference(file_id, job_id=job_id, run_id=run_id)

    def _attach_reference(self, file_id: str, *, job_id: str | None, run_id: str | None) -> FileView:

        if not job_id and not run_id:
            raise FileServiceError("A Job or run reference is required.")
        record = self._load_record(file_id)
        references = record.get("references")
        normalized = [str(item) for item in references] if isinstance(references, list) else []
        for reference in ([f"job:{job_id}"] if job_id else []) + ([f"run:{run_id}"] if run_id else []):
            if reference not in normalized:
                normalized.append(reference)
        record["references"] = normalized
        if job_id:
            record["job_id"] = job_id
        if run_id:
            record["run_id"] = run_id
        _atomic_write_json(self._directory(file_id) / "file.json", record)
        return self._view(record)

    def _load_record(self, file_id: str) -> dict[str, object]:
        if not _FILE_ID_PATTERN.fullmatch(str(file_id)):
            raise FileServiceError("Unknown file.")
        path = self._directory(file_id) / "file.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileServiceError("Unknown file.") from exc
        if not isinstance(record, dict) or record.get("file_id") != file_id:
            raise FileServiceError("Unknown file.")
        return record

    def _directory(self, file_id: str, *, must_exist: bool = True) -> Path:
        if not _FILE_ID_PATTERN.fullmatch(str(file_id)):
            raise FileServiceError("Unknown file.")
        directory = (self.root / str(file_id)).resolve()
        try:
            directory.relative_to(self.root)
        except ValueError as exc:
            raise FileServiceError("Unknown file.") from exc
        if must_exist and not directory.is_dir():
            raise FileServiceError("Unknown file.")
        return directory

    def _content_path(self, record: dict[str, object]) -> Path:
        directory = self._directory(str(record["file_id"]))
        path = (directory / "content").resolve()
        try:
            path.relative_to(directory)
        except ValueError as exc:
            raise FileServiceError("Registered file is outside its file directory.") from exc
        return path

    def _assert_project_quota(self, project_id: str | None, incoming_size: int, *, exclude_file_id: str) -> None:
        existing = 0
        for path in self.root.glob("file-*/file.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("project_id") == project_id and record.get("file_id") != exclude_file_id:
                existing += int(record.get("size_bytes", 0))
        if existing + incoming_size > self.max_project_bytes:
            raise FileServiceError("Project file quota exceeded.")

    def _validate_zip(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                total = 0
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    if name.startswith("/") or ":" in name or any(part == ".." for part in name.split("/")):
                        raise FileServiceError("Archive contains a path traversal entry.")
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise FileServiceError("Archive contains a symbolic link entry.")
                    if info.flag_bits & 1:
                        raise FileServiceError("Encrypted archive entries are unsupported.")
                    total += max(0, int(info.file_size))
                    if total > self.max_uncompressed_bytes:
                        raise FileServiceError("Archive exceeds the maximum uncompressed size.")
        except zipfile.BadZipFile as exc:
            raise FileServiceError("The uploaded archive is invalid.") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _view(self, record: dict[str, object]) -> FileView:
        public_fields = {
            key: record.get(key)
            for key in (
                "file_id",
                "original_name",
                "mime_type",
                "detected_type",
                "size_bytes",
                "sha256",
                "source",
                "owner_id",
                "project_id",
                "run_id",
                "job_id",
                "sensitivity",
                "parser_backend",
                "parser_version",
                "created_at",
                "retention_until",
                "material_scope",
                "source_artifact_id",
            )
        }
        return FileView.model_validate(
            {
                **public_fields,
                "content_url": f"/api/files/{record['file_id']}/content",
            }
        )
