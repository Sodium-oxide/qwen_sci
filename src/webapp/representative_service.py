"""Curated, read-only access to representative research outputs."""

from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .schemas import RepresentativeFileView, RepresentativeProjectView


_IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"})
_PDF_SUFFIXES = frozenset({".pdf"})
_LOG_SUFFIXES = frozenset({".log", ".jsonl"})
_ALLOWED_SUFFIXES = _IMAGE_SUFFIXES | _PDF_SUFFIXES | _LOG_SUFFIXES
_MAX_FILES_PER_PROJECT = 80
_MAX_FILE_BYTES = 64 * 1024 * 1024
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")

_PROJECT_COPY: dict[str, tuple[str, str, str]] = {
    "astr_16": (
        "脉冲星形成与演化",
        "天体物理 · 数值模型",
        "从磁偶极自旋下降、双星回收与伴星剥蚀出发，组织可检验的形成和演化机制。",
    ),
    "astr_7": (
        "黑洞存在性的多代理证据",
        "天体物理 · 观测综合",
        "把质量、致密性、环境动力学和理论种子机制连接成可审计的黑洞识别框架。",
    ),
    "bio_22": (
        "细胞拥挤环境中的生物分子组织",
        "生物学 · 多尺度机制",
        "综合冷冻荧光与冷冻电镜证据，研究细胞器和相分离如何协同控制分子定位与功能。",
    ),
    "chem_8": (
        "工程化活性材料的编程",
        "化学 · 合成生物学",
        "探索合成生物学、基因组工程与活体—非活体自组装如何共同设计材料功能。",
    ),
    "phys_3": (
        "跨尺度热传输极限",
        "物理学 · 材料科学",
        "分析声子、电子、界面热阻和高功率密度散热在纳米到工业尺度上的基本限制。",
    ),
    "high_tc_cuprate_mechanism_report": (
        "高温铜酸盐超导机制",
        "凝聚态物理 · 机制研究",
        "代表性研究报告：围绕高温铜酸盐超导的机制证据和可验证研究路径展开。",
    ),
}


@dataclass(frozen=True)
class _Project:
    project_id: str
    root: Path
    title: str
    discipline: str
    summary: str
    primary_file: str | None = None


def default_representative_root() -> Path:
    configured = os.environ.get("QWENSCI_REPRESENTATIVE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (repo_root / "representative", repo_root.parent / "representative"):
        if candidate.is_dir():
            return candidate.resolve()
    return (repo_root / "representative").resolve()


def _safe_file(root: Path, value: str) -> Path | None:
    if not _FILE_ID.fullmatch(value):
        return None
    path = (root / Path(value)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    return path


def _file_kind(path: Path) -> str:
    if path.suffix.casefold() in _IMAGE_SUFFIXES:
        return "image"
    if path.suffix.casefold() in _PDF_SUFFIXES:
        return "pdf"
    return "log"


def _label(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.name


def _project_files(project: _Project) -> list[tuple[Path, str]]:
    if not project.root.is_dir():
        return []
    try:
        candidates = sorted(path for path in project.root.rglob("*") if path.is_file() and path.suffix.casefold() in _ALLOWED_SUFFIXES)
    except OSError:
        return []
    filtered: list[tuple[Path, str]] = []
    for path in candidates:
        relative = path.relative_to(project.root).as_posix()
        if project.primary_file is not None and relative != project.primary_file:
            continue
        if path.name.casefold() == "fig1.png":
            continue
        lowered = relative.casefold()
        if any(token in lowered for token in ("ieeetran", "howto", "conference_101719", "power_system_research_report", ".author_", "latex_compile_workspace", "pdf_validation_workspace")):
            continue
        safe_path = _safe_file(project.root, relative)
        if safe_path is None:
            continue
        filtered.append((safe_path, relative))
    def sort_key(item: tuple[Path, str]) -> tuple[int, int, str]:
        path, relative = item
        kind = _file_kind(path)
        priority = {"pdf": 0, "image": 1, "log": 2}[kind]
        useful = 0 if any(token in relative.casefold() for token in ("final", "research_plan", "black-hole", "mechanism", "overview", "evidence", "survey", "events")) else 1
        return priority, useful, relative
    ordered = sorted(filtered, key=sort_key)
    selected: list[tuple[Path, str]] = []
    limits = {"pdf": 12, "image": 32, "log": 32}
    counts = {kind: 0 for kind in limits}
    for item in ordered:
        kind = _file_kind(item[0])
        if counts[kind] >= limits[kind]:
            continue
        selected.append(item)
        counts[kind] += 1
        if len(selected) >= _MAX_FILES_PER_PROJECT:
            break
    return selected


def _projects(root: Path) -> list[_Project]:
    if not root.is_dir():
        return []
    projects: list[_Project] = []
    try:
        directories = sorted(path for path in root.iterdir() if path.is_dir() and _PROJECT_ID.fullmatch(path.name))
    except OSError:
        directories = []
    for directory in directories:
        title, discipline, summary = _PROJECT_COPY.get(
            directory.name,
            (directory.name, "代表性研究", "Qwen-Sci 生成的代表性研究成果与审计材料。"),
        )
        projects.append(_Project(directory.name, directory, title, discipline, summary))
    standalone = root / "high_tc_cuprate_mechanism_report.pdf"
    if standalone.is_file():
        title, discipline, summary = _PROJECT_COPY["high_tc_cuprate_mechanism_report"]
        projects.append(_Project("high_tc_cuprate_mechanism_report", root, title, discipline, summary, primary_file=standalone.name))
    return projects


def _view_file(project_id: str, relative: str, path: Path) -> RepresentativeFileView:
    kind = _file_kind(path)
    return RepresentativeFileView(
        file_id=relative,
        label=_label(path),
        kind=kind,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        size_bytes=path.stat().st_size,
        url=f"/api/representative/{project_id}/files/{relative}",
    )


def list_representative_projects(root: Path) -> list[RepresentativeProjectView]:
    views: list[RepresentativeProjectView] = []
    for project in _projects(root):
        files = _project_files(project)
        image_files = [item for item in files if _file_kind(item[0]) == "image"]
        pdf_files = [item for item in files if _file_kind(item[0]) == "pdf"]
        log_files = [item for item in files if _file_kind(item[0]) == "log"]
        cover = image_files[0] if image_files else None
        views.append(
            RepresentativeProjectView(
                project_id=project.project_id,
                title=project.title,
                discipline=project.discipline,
                summary=project.summary,
                cover_url=f"/api/representative/{project.project_id}/files/{cover[1]}" if cover else None,
                files=[_view_file(project.project_id, relative, path) for path, relative in files],
                pdf_count=len(pdf_files),
                image_count=len(image_files),
                log_count=len(log_files),
            )
        )
    return views


def representative_file(root: Path, project_id: str, file_id: str) -> Path | None:
    if not _PROJECT_ID.fullmatch(project_id):
        return None
    project = next((item for item in _projects(root) if item.project_id == project_id), None)
    if project is None:
        return None
    path = _safe_file(project.root if project.root != root else root, file_id)
    if path is None or path.suffix.casefold() not in _ALLOWED_SUFFIXES:
        return None
    if not any(candidate == path for candidate, _relative in _project_files(project)):
        return None
    return path
