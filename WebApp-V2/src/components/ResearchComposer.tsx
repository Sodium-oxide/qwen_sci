import { useMemo, useState } from "react";

import type { CreateRunPayload, Discipline, MaterialDraft, QuantitativeMode, ScienceStage } from "../types";
import { MaterialTray } from "./MaterialTray";

interface ResearchComposerProps {
  catalog: Discipline[];
  busy: boolean;
  feedback: string;
  feedbackTone: "" | "error" | "success";
  onResolve: (topic: string) => Promise<{ suggested_catalog_ids?: string[]; reason?: string; primary?: { label?: string } }>;
  onStart: (payload: CreateRunPayload, drafts: MaterialDraft[], until: ScienceStage) => Promise<void>;
  onResume: (until: ScienceStage) => Promise<void>;
  canResume: boolean;
}

export function ResearchComposer({ catalog, busy, feedback, feedbackTone, onResolve, onStart, onResume, canResume }: ResearchComposerProps) {
  const [topic, setTopic] = useState("");
  const [runId, setRunId] = useState("");
  const [language, setLanguage] = useState<"zh-CN" | "en">("zh-CN");
  const [pages, setPages] = useState(7);
  const [until, setUntil] = useState<ScienceStage>("author");
  const [quantitativeMode, setQuantitativeMode] = useState<QuantitativeMode>("required");
  const [allowRemotePerception, setAllowRemotePerception] = useState(false);
  const [disciplineQuery, setDisciplineQuery] = useState("");
  const [selectedDisciplines, setSelectedDisciplines] = useState<string[]>([]);
  const [disciplineHint, setDisciplineHint] = useState("请从项目支持的自然科学、工程与健康科学范围选择（最多两项）。");
  const [drafts, setDrafts] = useState<MaterialDraft[]>([]);

  const available = useMemo(() => catalog.filter((entry) => {
    const haystack = `${entry.label} ${entry.domain} ${entry.template_family}`.toLocaleLowerCase();
    return !disciplineQuery || haystack.includes(disciplineQuery.toLocaleLowerCase());
  }), [catalog, disciplineQuery]);
  const selectedEntries = selectedDisciplines.map((id) => catalog.find((entry) => entry.id === id)).filter((entry): entry is Discipline => Boolean(entry));

  const resolve = async () => {
    if (topic.trim().length < 3) return;
    const resolution = await onResolve(topic.trim());
    const suggestions = resolution.suggested_catalog_ids?.slice(0, 2) ?? [];
    if (suggestions.length) {
      setSelectedDisciplines(suggestions);
      setDisciplineHint(`已识别：${resolution.primary?.label || "建议学科"}。开始前仍可手动调整。`);
    } else {
      setDisciplineHint(resolution.reason || "未能自动识别可靠的支持学科，请手动选择。");
    }
  };

  const start = async () => {
    if (topic.trim().length < 8 || selectedDisciplines.length === 0) return;
    await onStart({
      topic: topic.trim(),
      discipline_ids: selectedDisciplines,
      ...(runId.trim() ? { run_id: runId.trim() } : {}),
      language,
      minimum_pages: pages,
      quantitative_mode: quantitativeMode,
      allow_remote_perception: allowRemotePerception,
    }, drafts, until);
    setDrafts([]);
  };

  return (
    <section className="panel launcher" id="launcher">
      <div className="panel-head"><div><span className="eyebrow">Research composer</span><h2>创建不可变研究课题</h2></div><span className="badge">结构化启动</span></div>
      <textarea value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：如何从显微图像与公开证据中研究电极材料微结构对循环稳定性的影响？" />
      <div className="form-grid">
        <label className="discipline-field">研究学科（最多两项）
          <input value={disciplineQuery} onChange={(event) => setDisciplineQuery(event.target.value)} placeholder="搜索 20 个可研究学科" />
          <div className="discipline-selected" aria-live="polite">{selectedEntries.map((entry) => <span className="discipline-tag" key={entry.id}>{entry.label}<button type="button" onClick={() => setSelectedDisciplines((current) => current.filter((id) => id !== entry.id))}>×</button></span>)}</div>
          <div className="discipline-options" role="listbox">{available.map((entry) => {
            const checked = selectedDisciplines.includes(entry.id);
            return <label className="discipline-option" key={entry.id}><input type="checkbox" checked={checked} disabled={!checked && selectedDisciplines.length >= 2} onChange={() => setSelectedDisciplines((current) => checked ? current.filter((id) => id !== entry.id) : [...current, entry.id])} /><span>{entry.label}<br /><small>{entry.domain} · {entry.template_family}</small></span></label>;
          })}</div>
          <button className="text-button" type="button" onClick={() => void resolve()}>根据课题识别学科</button>
          <span className="field-hint">{disciplineHint}</span>
        </label>
        <label>运行 ID<input value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="留空则自动生成" /></label>
        <label>报告语言<select value={language} onChange={(event) => setLanguage(event.target.value as "zh-CN" | "en")}><option value="zh-CN">中文</option><option value="en">English</option></select></label>
        <label>目标页数<input type="number" min={7} max={80} value={pages} onChange={(event) => setPages(Number(event.target.value) || 7)} /></label>
        <label>研究终点<select value={until} onChange={(event) => setUntil(event.target.value as ScienceStage)}><option value="survey">仅生成 Survey</option><option value="idea">Survey + Idea</option><option value="exp_design">Survey + Idea + ExperimentDesign</option><option value="author">完整流程至 Author</option></select><span className="field-hint">恢复时也可重新选择终点；required 量化模式会在 Author 前进入量化审阅。</span></label>
      </div>
      <MaterialTray drafts={drafts} onDraftsChange={setDrafts} />
      <label className="check-label remote-consent"><input type="checkbox" checked={allowRemotePerception} onChange={(event) => setAllowRemotePerception(event.target.checked)} />允许本次运行在已支持、非敏感的 Survey 证据上使用受限远程视觉分析</label>
      <div className="mode-strip">
        {(["off", "optional", "required"] as const).map((mode) => <label key={mode}><input type="radio" name="qmode" value={mode} checked={quantitativeMode === mode} onChange={() => setQuantitativeMode(mode)} />{mode === "off" ? "不创建量化候选" : mode === "optional" ? "生成候选但主流程独立" : "Author 前必须完成量化审阅"}</label>)}
      </div>
      <div className="action-row"><button className="primary" type="button" disabled={busy || topic.trim().length < 8 || selectedDisciplines.length === 0} onClick={() => void start()}>开始研究</button><button className="secondary" type="button" disabled={busy || !canResume} onClick={() => void onResume(until)}>恢复当前运行</button></div>
      <p className={`action-feedback ${feedbackTone}`}>{feedback}</p>
    </section>
  );
}
