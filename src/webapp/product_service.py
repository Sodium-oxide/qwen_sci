"""Product metadata grounded in implemented API contracts and runtime capabilities."""

from __future__ import annotations

from pathlib import Path

from .representative_service import list_representative_projects


_MODULES = (
    ("full-research", "全流程科研", "文献综述、研究构思、实验设计与研究计划。", ("survey", "idea", "exp_design", "author"), ("/api/runs", "/api/runs/{run_id}/actions", "/api/runs/{run_id}/artifacts/{artifact_id}")),
    ("light-research", "轻度研究", "文献综述与可选研究构思。", ("survey", "idea"), ("/api/runs", "/api/runs/{run_id}/actions")),
    ("figure", "科研绘图", "数据图、科学示意图与人工复核。", ("data_binding", "planning", "rendering", "review"), ("/api/figure/jobs", "/api/figure/jobs/{job_id}/actions", "/api/figure/jobs/{job_id}/artifacts")),
    ("polish", "语言润色", "段落修订、科学不变量校验与逐段复核。", ("segmentation", "revision", "validation", "review", "export"), ("/api/polish/jobs", "/api/polish/jobs/{job_id}/revisions", "/api/polish/jobs/{job_id}/export")),
    ("translate", "论文翻译", "PDF 文本与页面映射、术语表和逐页复核。", ("parse", "translate", "validate", "review", "export"), ("/api/translation/jobs", "/api/translation/jobs/{job_id}/pages", "/api/translation/jobs/{job_id}/export")),
    ("preferences", "研究偏好", "工作区默认模型、语言、输出格式与隐私偏好。", ("load", "edit", "version_check", "save"), ("/api/preferences", "/api/preferences/schema")),
)


class ProductService:
    def __init__(self, capability_service, representative_root: Path):
        self.capability_service = capability_service
        self.representative_root = representative_root

    def modules(self) -> list[dict[str, object]]:
        capabilities = self.capability_service.snapshot()
        modules = []
        for identifier, title, summary, steps, evidence in _MODULES:
            capability_key = "translation" if identifier == "translate" else identifier
            enabled = capabilities.get(capability_key, {}).get("enabled", True)
            modules.append({
                "id": identifier, "title": title, "summary": summary,
                "status": "available" if identifier == "preferences" else "partial",
                "enabled": enabled, "implemented": True, "route": f"/app/{identifier}",
                "workspaceRoute": f"/app/{identifier}", "previewRoute": f"/products/qwensci?module={identifier}",
                "evidence": list(evidence), "steps": list(steps), "last_verified_at": None,
                "data_source": "static_registry", "is_live": False,
            })
        return modules

    def preview(self, module_id: str) -> dict[str, object]:
        module = next((item for item in self.modules() if item["id"] == module_id), None)
        if module is None:
            raise KeyError(module_id)
        if module_id == "full-research":
            projects = list_representative_projects(self.representative_root)
            if projects:
                return {**module, "data_source": "representative", "representative": projects[0].model_dump(mode="json")}
        return {**module, "description": "产品结构预览；创建任务后显示真实任务状态。"}
