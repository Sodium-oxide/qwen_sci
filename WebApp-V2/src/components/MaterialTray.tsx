import { useRef } from "react";

import { api } from "../api";
import type { MaterialDraft, MaterialRecord, ResearchRun } from "../types";

const MAX_FILE_BYTES = 50 * 1024 * 1024;
const SCOPES: Array<{ value: MaterialRecord["scope"]; label: string }> = [
  { value: "survey_evidence", label: "Survey evidence（综述证据）" },
  { value: "context_only", label: "Context only（背景参考）" },
  { value: "parameter_source", label: "Parameter source（参数来源）" },
  { value: "do_not_send", label: "Do not send（仅保管）" },
];

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(1)} MiB`;
}

function materialProcessingState(material: MaterialRecord, run: ResearchRun) {
  if (material.scope === "do_not_send") return "仅安全保管；未发送给模型";
  if (material.contains_sensitive_data) return "含敏感数据；禁止远程感知";
  if (material.scope === "survey_evidence") {
    return run.remote_perception_authorized
      ? "受控 Survey 证据；仅在支持该模态时可进行已授权远程感知"
      : "受控 Survey 证据；未授权远程感知，仅可进行有限本地分析";
  }
  return "Stored for review; not consumed by this stage";
}

function materialIsMutable(run: ResearchRun) {
  return Object.values(run.stages).every((stage) => ["PENDING", "FAILED", ""].includes(String(stage.status ?? "PENDING")));
}

interface MaterialTrayProps {
  drafts?: MaterialDraft[];
  onDraftsChange?: (drafts: MaterialDraft[]) => void;
  run?: ResearchRun | null;
  onDelete?: (material: MaterialRecord) => Promise<void>;
  onReplace?: (material: MaterialRecord, file: File) => Promise<void>;
}

export function MaterialTray({ drafts = [], onDraftsChange, run, onDelete, onReplace }: MaterialTrayProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const canEditSaved = Boolean(run && materialIsMutable(run));

  const addFiles = (files: FileList | File[]) => {
    if (!onDraftsChange) return;
    const known = new Set(drafts.map((draft) => `${draft.file.name}:${draft.file.size}:${draft.file.lastModified}`));
    const accepted = Array.from(files).filter((file) => file.size <= MAX_FILE_BYTES && !known.has(`${file.name}:${file.size}:${file.lastModified}`));
    onDraftsChange([...drafts, ...accepted.map((file) => ({ file, scope: "context_only" as const, contains_sensitive_data: false }))]);
  };

  const updateDraft = (index: number, patch: Partial<MaterialDraft>) => {
    onDraftsChange?.(drafts.map((draft, current) => current === index ? { ...draft, ...patch } : draft));
  };

  return (
    <section className="material-tray" aria-labelledby="materialTitle">
      <div className="material-heading">
        <div>
          <span className="eyebrow">Research materials</span>
          <h3 id="materialTitle">图片、表格与参考资料</h3>
        </div>
        <span className="badge">受控材料</span>
      </div>
      {onDraftsChange && (
        <label
          className="drop-zone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }}
        >
          <strong>选择文件，或将文件拖放到此处</strong>
          <span>支持图片、PDF、DOCX、CSV/XLSX、Markdown、TXT、JSON 和代码；每个文件不超过 50 MiB。</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={(event) => {
              if (event.currentTarget.files) addFiles(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
          />
        </label>
      )}
      {onDraftsChange && drafts.length > 0 && (
        <div className="material-queue" aria-live="polite">
          {drafts.map((draft, index) => (
            <article className="material-card" key={`${draft.file.name}-${draft.file.lastModified}-${index}`}>
              <div><strong>{draft.file.name}</strong><span>{formatBytes(draft.file.size)} · 待登记</span></div>
              <label>用途<select value={draft.scope} onChange={(event) => updateDraft(index, { scope: event.target.value as MaterialRecord["scope"] })}>
                {SCOPES.map((scope) => <option value={scope.value} key={scope.value}>{scope.label}</option>)}
              </select></label>
              <label className="check-label"><input type="checkbox" checked={draft.contains_sensitive_data} onChange={(event) => updateDraft(index, { contains_sensitive_data: event.target.checked })} />含敏感数据</label>
              <button className="text-button danger-text" type="button" onClick={() => onDraftsChange(drafts.filter((_, current) => current !== index))}>移除</button>
            </article>
          ))}
        </div>
      )}
      {run && (
        <div className="material-queue saved-materials" aria-live="polite">
          <p className="field-hint">{canEditSaved ? "研究尚未开始，可替换或删除材料；每次改动都会重写受控清单。" : "研究已经开始：材料清单已冻结。替换请创建新的运行或明确的版本化修订。"}</p>
          {run.materials.length === 0 ? <p className="field-hint">当前运行没有已登记材料。</p> : run.materials.map((material) => (
            <article className="material-card saved" key={material.material_id}>
              <div>
                <strong>{material.metadata?.label || material.original_name}</strong>
                <span>{material.original_name} · {material.modality || "文件"} · {formatBytes(material.file_size_bytes)}</span>
              </div>
              <div className="material-facts">
                <span>用途：{SCOPES.find((scope) => scope.value === material.scope)?.label || material.scope}</span>
                <span>外部模型：{material.scope === "survey_evidence" && !material.contains_sensitive_data && run.remote_perception_authorized ? "仅受控、已授权" : "未发送"}</span>
                <span>敏感：{material.contains_sensitive_data ? "是" : "否"}</span>
              </div>
              <p>{materialProcessingState(material, run)}</p>
              <div className="material-actions">
                <a className="text-button" href={api.materialUrl(run.run_id, material.material_id)} target="_blank" rel="noreferrer">预览 / 下载</a>
                {canEditSaved && onReplace && <label className="text-button">替换<input className="material-replace-input" type="file" onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) void onReplace(material, file);
                  event.currentTarget.value = "";
                }} /></label>}
                {canEditSaved && onDelete && <button className="text-button danger-text" type="button" onClick={() => void onDelete(material)}>删除</button>}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
