import os
import json
import re
from datetime import datetime
from pathlib import Path
import networkx as nx

from src.pipeline.discipline_taxonomy import resolve_discipline_taxonomy


_SAFE_ARTIFACT_DOMAIN_PATTERN = re.compile(r"[^a-z0-9]+")


def _resolve_analysis_artifact_domain(topic):
    """Return one short, filesystem-safe discipline phrase for artifact names.

    Analysis artifacts used to include the complete user topic in every file
    name. A topic can be an entire research brief (or, in a malformed input,
    a generated answer), which exceeds the per-file-name limit on NTFS/WSL.
    The taxonomy resolver is local and deterministic, so it provides a concise
    domain label without sending an additional LLM request.
    """
    try:
        resolved = resolve_discipline_taxonomy(topic)
        domain = str(resolved.get("primary_discipline") or "").strip()
    except Exception:
        domain = ""

    normalized = _SAFE_ARTIFACT_DOMAIN_PATTERN.sub("_", domain.lower()).strip("_")
    return normalized or "research"


def _analysis_artifact_prefix(topic, *, is_adapter_mode=False, now=None):
    """Build ``<domain>_<HHMMSS>`` once for every analysis-artifact batch."""
    domain = "survey" if is_adapter_mode else _resolve_analysis_artifact_domain(topic)
    timestamp = (now or datetime.now()).strftime("%H%M%S")
    return f"{domain}_{timestamp}"

def write_header(eval_path):
    if not os.path.exists(eval_path):
        os.makedirs(os.path.dirname(eval_path), exist_ok=True)
    with open(eval_path, 'w') as f:
        f.write(f"\n\n=== Begin Evaluation ===\n")
        f.write('========================================\n\n\n')


def write_domain_header(eval_path, domain):
    with open(eval_path, 'a') as f:
        f.write(f"=== Domain: {domain} ===\n")
        f.write('========================================\n\n\n')

def write_topic_header(eval_path, topic):
    with open(eval_path, 'a') as f:
        f.write(f"=== TOPIC: {topic} ===\n")
        f.write('========================================\n\n\n')


def write_domain_result(eval_path, domain, results):
    with open(eval_path, 'a') as f:
        f.write(f"=== {domain} Result ===\n")
        f.write('========================================\n\n\n')
    if len(results) == 0:
        return
    final_result = {}
    results_count = len(results)
    for result in results:
        for key, value in result.items():
            if key not in final_result:
                final_result[key] = value
            else:
                final_result[key] += value
    for key in final_result:
        final_result[key] /= results_count
        
    with open(eval_path, 'a') as f:
        for key, value in final_result.items():
            f.write(f"{key}: {value}\n")

        f.write('Domain End\n\n\n')
        
    return final_result

def write_result(eval_path, description, results, reasons):
    with open(eval_path, 'a') as f:
        f.write(f"=== {description} Result ===\n")
        f.write('========================================\n')
        for key, value in results.items():
            f.write(f"{key}: {value}\n")
            if key in reasons:
                f.write(f"  Reason: {reasons[key]}\n")
        f.write('\n')


def _resolve_analysis_output_dir(save_path):
    path = Path(str(save_path or ".")).expanduser()
    if path.exists():
        return path if path.is_dir() else path.parent
    if path.suffix.lower() in {".md", ".json", ".txt"}:
        return path.parent
    return path


def save_analysis_artifacts(save_path, topic, relation_graph, relation_table, intra_analysis_results, inter_analysis_results=None, logger_instance=None, is_adapter_mode=False):
    """
    Save analysis artifacts (relation graph, relation table, intra-cluster analysis, inter-cluster analysis) to analysis directory.
    
    Args:
        save_path: Output file or directory path (from config.BasicInfo.save_path)
        topic: Topic name used only to resolve one concise discipline phrase.
        relation_graph: Relation graph dict or None
        relation_table: Relation table dict or None
        intra_analysis_results: Intra-cluster analysis results or None
        inter_analysis_results: Inter-cluster analysis results (tex format) or None
        logger_instance: Optional logger instance
        is_adapter_mode: If True, uses the generic ``survey`` domain label.
    """
    save_dir = os.path.join(_resolve_analysis_output_dir(save_path), "analysis")
    os.makedirs(save_dir, exist_ok=True)
    
    # Never use the raw topic as a filename: it may be a long research brief.
    # All artifacts from this save operation deliberately share one timestamp.
    filename_prefix = _analysis_artifact_prefix(
        topic,
        is_adapter_mode=is_adapter_mode,
    )
    
    if relation_graph is not None:
        filepath = os.path.join(save_dir, f"{filename_prefix}_relation_graph.json")
        serializable_graph = {}
        for cluster_name, g in relation_graph.items():
            if isinstance(g, nx.DiGraph):
                serializable_graph[cluster_name] = {
                    'nodes': list(g.nodes()),
                    'edges': [
                        {
                            'source': u,
                            'target': v,
                            'type': data.get('type', 'unspecified'),
                            'analysis': data.get('analysis', ''),
                            'raw': data.get('raw', '')
                        }
                        for u, v, data in g.edges(data=True)
                    ]
                }
            else:
                serializable_graph[cluster_name] = g
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serializable_graph, f, indent=2, ensure_ascii=False)
        
        if logger_instance:
            logger_instance.info(f"Relation graph saved to: {filepath}")
    
    if relation_table is not None:
        filepath = os.path.join(save_dir, f"{filename_prefix}_relation_table.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(relation_table, f, indent=2, ensure_ascii=False)
        
        if logger_instance:
            logger_instance.info(f"Relation table saved to: {filepath}")
    
    if intra_analysis_results is not None:
        filepath = os.path.join(save_dir, f"{filename_prefix}_intra_cluster_analysis.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(intra_analysis_results, f, indent=2, ensure_ascii=False)
        
        if logger_instance:
            logger_instance.info(f"Intra-cluster analysis saved to: {filepath}")
    
    if inter_analysis_results is not None:
        filepath = os.path.join(save_dir, f"{filename_prefix}_inter_cluster_analysis.tex")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(inter_analysis_results)
        
        if logger_instance:
            logger_instance.info(f"Inter-cluster analysis saved to: {filepath}")
