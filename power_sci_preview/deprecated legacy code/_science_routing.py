from __future__ import annotations

import re
from typing import Iterable


_EXPLICIT_SETUP_ONLY_EN = (
    "decompose only",
    "only decompose",
    "just decompose",
    "split only",
    "create project only",
    "only create",
    "just create",
    "setup only",
    "do not run",
    "don't run",
    "dont run",
    "skip run_autogen_groupchat",
    "skip literature",
    "no literature",
    "without literature",
    "no search",
    "without search",
    "no groupchat",
    "without groupchat",
)

_EXPLICIT_SETUP_ONLY_ZH = (
    "只分解",
    "仅分解",
    "只做分解",
    "仅做分解",
    "只创建",
    "仅创建",
    "只创建项目",
    "仅创建项目",
    "不要运行",
    "不用运行",
    "不要继续运行",
    "不跑后续",
    "跳过文献",
    "不用文献",
    "不要文献",
    "不进行文献",
    "不用搜索",
    "不要搜索",
    "不要群聊",
    "不用groupchat",
)

_SETUP_MARKERS_EN = (
    "decompose",
    "subhypothesis",
    "sub-hypothesis",
    "create research project",
)
_SETUP_MARKERS_ZH = ("分解", "子课题", "子假设", "创建科研项目")

_EXECUTION_MARKERS_EN = (
    "run",
    "execute",
    "end-to-end",
    "closed loop",
    "literature",
    "search",
    "gap",
    "hypothesis",
    "debate",
    "autogen",
    "groupchat",
    "scientist",
)
_EXECUTION_MARKERS_ZH = (
    "运行",
    "执行",
    "全流程",
    "闭环",
    "文献",
    "搜索",
    "检索",
    "缺口",
    "假设",
    "辩论",
    "科研",
)

_EXPLICIT_WORKFLOW_MARKERS = (
    "boxue",
    "ai scientist",
    "scientific workflow",
    "research workflow",
    "research project",
    "research brief",
    "scientific hypothesis",
    "literature review",
    "literature search",
    "knowledge gap",
    "run_autogen_groupchat",
    "create_research_project",
    "autogen",
    "groupchat",
    "博学",
    "科研闭环",
    "科研流程",
    "研究项目",
    "研究目标",
    "学术文段",
    "文献检索",
    "知识缺口",
    "科学假设",
    "子课题",
    "子假设",
)

# These are intentionally broad natural-science object and process families,
# not a fixed list of supported domains. Requiring multiple independent hits
# prevents a lone programming/UI word such as "cell" or "model" from routing a
# coding question into the research workflow.
_SCIENCE_MARKERS_EN = (
    "artificial cell",
    "synthetic cell",
    "synthetic biology",
    "cell",
    "membrane",
    "genome",
    "gene",
    "protein",
    "enzyme",
    "molecule",
    "biomolecule",
    "organism",
    "tissue",
    "organoid",
    "disease",
    "antibiotic",
    "antimicrobial",
    "pathogen",
    "resistance",
    "drug",
    "therapy",
    "mutation",
    "crispr",
    "material",
    "polymer",
    "hydrogel",
    "catalyst",
    "reaction",
    "battery",
    "electrolyte",
    "energy",
    "climate",
    "ecosystem",
    "species",
    "agriculture",
    "quantum",
    "particle",
    "physics",
    "chemistry",
    "biology",
    "medicine",
    "ecology",
    "experiment",
    "assay",
    "synthesis",
    "synthesize",
    "synthesized",
    "synthesise",
    "synthesised",
)

_SCIENCE_MARKERS_ZH = (
    "人工细胞",
    "合成细胞",
    "合成生物学",
    "细胞",
    "细胞膜",
    "膜结构",
    "基因组",
    "基因",
    "蛋白",
    "酶",
    "分子",
    "生物分子",
    "生物体",
    "组织",
    "类器官",
    "疾病",
    "抗生素",
    "抗菌",
    "病原体",
    "耐药",
    "药物",
    "治疗",
    "突变",
    "材料",
    "聚合物",
    "水凝胶",
    "催化",
    "反应",
    "电池",
    "电解质",
    "能源",
    "气候",
    "生态",
    "物种",
    "农业",
    "量子",
    "粒子",
    "物理",
    "化学",
    "生物",
    "医学",
    "实验",
    "测定",
    "合成",
)

_INQUIRY_MARKERS_EN = (
    "can ",
    "could ",
    "whether ",
    "why ",
    "how ",
    "what causes",
    "mechanism",
    "effect of",
    "influence of",
    "feasibility",
    "investigate",
    "evaluate",
    "compare",
    "determine",
    "test whether",
    "evidence for",
    "prove",
    "falsify",
    "research",
    "study",
)

_INQUIRY_MARKERS_ZH = (
    "能不能",
    "能否",
    "是否",
    "为什么",
    "为何",
    "如何",
    "什么原因",
    "机制",
    "影响",
    "作用",
    "可行性",
    "研究",
    "探究",
    "评估",
    "比较",
    "验证",
    "证明",
    "证伪",
    "证据",
)


def _contains_ascii_term(text: str, term: str) -> bool:
    value = str(term or "").strip().lower()
    if not value:
        return False
    if " " in value or any(char in value for char in "-_/"):
        return value in text
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(value)}(?![a-z0-9_])", text))


def _matched_terms(text: str, terms: Iterable[str]) -> set[str]:
    lowered = str(text or "").lower()
    matches: set[str] = set()
    for term in terms:
        value = str(term or "").strip()
        if not value:
            continue
        if value.isascii():
            if _contains_ascii_term(lowered, value):
                matches.add(value.lower())
        elif value in text:
            matches.add(value)
    return matches


def science_setup_only_requested(user_input: str) -> bool:
    text = str(user_input or "").strip()
    lowered = text.lower()
    if any(marker in lowered for marker in _EXPLICIT_SETUP_ONLY_EN):
        return True
    if any(marker in text for marker in _EXPLICIT_SETUP_ONLY_ZH):
        return True

    wants_setup = bool(
        _matched_terms(text, _SETUP_MARKERS_EN)
        or _matched_terms(text, _SETUP_MARKERS_ZH)
    )
    wants_execution = bool(
        _matched_terms(text, _EXECUTION_MARKERS_EN)
        or _matched_terms(text, _EXECUTION_MARKERS_ZH)
    )
    return wants_setup and not wants_execution


def science_workflow_requested(user_input: str) -> bool:
    """Route every non-empty CLI prompt into the canonical research flow.

    This repository is a dedicated AI-scientist runtime, not a general chat
    assistant. Topic classifiers are still useful downstream for domain and
    retrieval planning, but they must never decide whether research runs at
    all. In particular, unfamiliar disciplines and academic passages must not
    silently fall through to a zero-tool plain-text answer.
    """

    text = str(user_input or "").strip()
    return bool(text)
