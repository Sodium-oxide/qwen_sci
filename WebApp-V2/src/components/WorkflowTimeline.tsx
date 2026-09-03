import { useMemo, useState } from "react";

import { RunLogsPanel } from "./RunLogsPanel";
import type { ActionPayload, ResearchRun, RunEvent, ScienceStage } from "../types";

const STAGES: Array<[string, string, string]> = [
  ["survey", "综述 Survey", "检索可追溯证据，并在允许时吸收受控的多模态证据。"],
  ["idea", "想法 Idea", "从已验证综述交接生成受证据约束的研究问题与假设。"],
  ["exp_design", "设计 ExperimentDesign", "根据学科范围生成 design-only 研究方案。"],
  ["author", "写作 Author", "只组织上游已验证的证据、想法和设计形成报告。"],
];

type EventFilter = "all" | "errors" | "current_stage";

function eventSummary(event: RunEvent) {
  if (event.event_type === "MATERIALS_REGISTERED") return `已登记 ${event.payload.material_count ?? 0} 份研究材料。`;
  if (event.payload.stage) return `${String(event.payload.stage)} · 第 ${event.payload.attempt ?? "-"} 次尝试`;
  return "状态已持久化更新。";
}

function isErrorEvent(event: RunEvent) {
  return event.event_type.includes("FAILED") || "error" in event.payload || "failure" in event.payload;
}

function stageFor(event: RunEvent) {
  return typeof event.payload.stage === "string" ? event.payload.stage : "";
}

function activeStage(run: ResearchRun | null) {
  return Object.entries(run?.stages ?? {}).find(([, stage]) => stage.status === "RUNNING")?.[0] ?? "";
}

function payloadText(payload: Record<string, unknown>) {
  return JSON.stringify(payload, null, 2);
}

export function WorkflowTimeline({ run, events, connection, onAction }: { run: ResearchRun | null; events: RunEvent[]; connection: string; onAction: (payload: ActionPayload) => void }) {
  const canResume = Boolean(run?.allowed_actions.includes("resume_science"));
  const canCancel = Boolean(run?.allowed_actions.includes("cancel_science"));
  const [resumeUntil, setResumeUntil] = useState<ScienceStage>("author");
  const [eventFilter, setEventFilter] = useState<EventFilter>("all");
  const currentStage = activeStage(run);
  const visibleEvents = useMemo(() => events.filter((event) => {
    if (eventFilter === "errors") return isErrorEvent(event);
    if (eventFilter === "current_stage") return Boolean(currentStage) && stageFor(event) === currentStage;
    return true;
  }).slice().reverse(), [currentStage, eventFilter, events]);

  return <>
    <section className="panel workflow" id="workflow">
      <div className="panel-head"><div><span className="eyebrow">Auditable pipeline</span><h2>主流程状态</h2></div><span className="badge blue">Survey → Idea → Design → Author</span></div>
      <div className="stage-map">{STAGES.map(([key, title, copy]) => {
        const stage = run?.stages[key];
        return <article className="stage-node" key={key}><span className={`status ${stage?.status ?? "PENDING"}`}>{stage?.status ?? "PENDING"}</span><h3>{title}</h3><p>{copy}</p><p>第 {stage?.attempt ?? 0} 次尝试</p>{stage?.failure?.message && <p className="stage-failure">{stage.failure.message}</p>}</article>;
      })}</div>
      {run?.cancellation && <p className="field-hint">{run.cancellation.acknowledged_at ? "研究已在安全边界停止；已完成的成果仍可查看并可选择终点恢复。" : "正在请求安全停止：当前阶段会先完成持久化，再停止后续阶段。"}</p>}
      {canResume && <div className="action-row"><label>恢复终点<select value={resumeUntil} onChange={(event) => setResumeUntil(event.target.value as ScienceStage)}><option value="survey">Survey</option><option value="idea">Survey + Idea</option><option value="exp_design">Survey + Idea + ExperimentDesign</option><option value="author">完整流程至 Author</option></select></label><button type="button" className="secondary" onClick={() => onAction({ type: "resume_science", until: resumeUntil })}>恢复当前科学流程</button></div>}
      {canCancel && <div className="action-row"><button type="button" className="secondary danger-text" onClick={() => onAction({ type: "cancel_science" })}>在当前阶段后中止研究</button><span className="field-hint">不会删除已完成成果，也不会强杀正在写入的阶段。</span></div>}
    </section>
    <section className="panel event-panel">
      <div className="panel-head compact"><div><h2>完整运行事件</h2><p className="field-hint">事件来自持久化记录；展开后可查看已脱敏的完整事件数据。</p></div><span className="event-state">{connection}</span></div>
      <div className="event-filter"><label>筛选<select value={eventFilter} onChange={(event) => setEventFilter(event.target.value as EventFilter)}><option value="all">全部事件（{events.length}）</option><option value="errors">仅错误事件</option><option value="current_stage" disabled={!currentStage}>当前阶段{currentStage ? `（${currentStage}）` : "（暂无运行阶段）"}</option></select></label><span className="field-hint">显示 {visibleEvents.length} 条</span></div>
      <div className="event-timeline" aria-live="polite">{visibleEvents.length ? visibleEvents.map((event) => <article className="event-item" key={event.event_id}><div className="event-item-head"><strong>{event.event_type}</strong><time>{event.timestamp}</time></div><span>{eventSummary(event)}</span><details className="event-payload"><summary>查看事件数据</summary><pre>{payloadText(event.payload)}</pre></details></article>) : <p className="field-hint">事件从当前运行的持久化日志读取。</p>}</div>
    </section>
    <RunLogsPanel run={run} />
  </>;
}
