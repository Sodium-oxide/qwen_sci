import { useEffect, useState } from "react";

import type { ResearchRun } from "../types";

interface SessionListProps {
  runs: ResearchRun[];
  selectedRunId?: string;
  onSelect: (runId: string) => void;
  onRefresh: (query: string) => void;
}

function runGroup(run: ResearchRun) {
  const statuses = Object.values(run.stages).map((stage) => String(stage.status ?? ""));
  if (run.status === "ARCHIVED") return "Archived";
  if (run.status === "COMPLETED") return "Completed";
  if (run.status === "RUNNING" || statuses.includes("RUNNING")) return "Running";
  if (run.status === "FAILED" || run.status === "CANCELLED" || statuses.includes("FAILED") || run.allowed_actions.includes("resume_science")) return "Failed-resumable";
  return "Needs review";
}

const GROUPS = ["Running", "Needs review", "Completed", "Failed-resumable", "Archived"] as const;

export function SessionList({ runs, selectedRunId, onSelect, onRefresh }: SessionListProps) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => onRefresh(query), 250);
    return () => window.clearTimeout(timer);
  }, [query, onRefresh]);
  return <aside className="left-rail"><div className="rail-card"><div className="rail-title"><span>研究会话</span><button type="button" title="刷新" onClick={() => onRefresh(query)}>↻</button></div><label className="search"><span>搜索课题、run ID、领域或文件名</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：microscopy" /></label><div className="session-stack grouped-sessions">{GROUPS.map((group) => {
    const entries = runs.filter((run) => runGroup(run) === group);
    return <section className="session-group" key={group}><h3>{group}<small>{entries.length}</small></h3>{entries.length ? entries.map((run) => <button type="button" className={`session-card ${selectedRunId === run.run_id ? "active" : ""}`} key={run.run_id} onClick={() => onSelect(run.run_id)}><span className={`status ${run.status}`}>{run.status}</span><strong>{run.run_id}</strong><p>{run.topic}</p><div className="artifact-meta"><span>{run.quantitative_mode} 量化</span><span>{run.artifacts.length} 产物</span></div></button>) : <p className="field-hint">暂无会话</p>}</section>;
  })}</div></div><div className="rail-card blueprint"><span>后端边界</span><p>浏览器只能调用结构化 API；材料和成果必须已登记在当前 run，页面不会生成或执行 shell 命令。</p></div></aside>;
}
