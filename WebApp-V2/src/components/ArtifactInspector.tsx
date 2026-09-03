import { useMemo, useState } from "react";

import { api } from "../api";
import type { Artifact, ResearchRun } from "../types";

type ArtifactFilter = "all" | "research-pdf" | "quantitative-pdf" | "documents" | "figures" | "quantitative";

function formatBytes(value: number) {
  return value < 1024 ** 2 ? `${Math.max(1, Math.ceil(value / 1024))} KiB` : `${(value / 1024 ** 2).toFixed(1)} MiB`;
}

function isTextArtifact(artifact: Artifact) {
  return artifact.media_type === "application/json" || artifact.media_type === "text/markdown" || artifact.media_type === "text/plain";
}

export function ArtifactInspector({ run }: { run: ResearchRun | null }) {
  const [filter, setFilter] = useState<ArtifactFilter>("all");
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [text, setText] = useState("");
  const [previewError, setPreviewError] = useState("");
  const artifacts = useMemo(() => (run?.artifacts ?? []).filter((artifact) => {
    if (filter === "all") return true;
    if (filter === "research-pdf") return artifact.media_type === "application/pdf" && artifact.stage !== "quantitative";
    if (filter === "quantitative-pdf") return artifact.media_type === "application/pdf" && artifact.stage === "quantitative";
    if (filter === "documents") return isTextArtifact(artifact);
    if (filter === "figures") return artifact.media_type.startsWith("image/");
    return artifact.stage === "quantitative";
  }), [filter, run]);

  const select = async (artifact: Artifact) => {
    setSelected(artifact);
    setText("");
    setPreviewError("");
    if (!run || !isTextArtifact(artifact)) return;
    if (artifact.size_bytes > 2 * 1024 * 1024) {
      setPreviewError("该文本产物超过 2 MiB，只提供安全下载，不在浏览器内加载。");
      return;
    }
    try {
      setText(await api.artifactText(run.run_id, artifact.artifact_id));
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "无法读取产物。");
    }
  };

  const researchPdfs = (run?.artifacts ?? []).filter((artifact) => artifact.media_type === "application/pdf" && artifact.stage !== "quantitative");
  const quantitativePdfs = (run?.artifacts ?? []).filter((artifact) => artifact.media_type === "application/pdf" && artifact.stage === "quantitative");
  return <><section className="panel artifact-panel" id="artifacts"><div className="panel-head compact"><h2>成果与日志</h2><select value={filter} onChange={(event) => setFilter(event.target.value as ArtifactFilter)}><option value="all">全部</option><option value="research-pdf">主研究 PDF</option><option value="quantitative-pdf">数学建模 PDF</option><option value="documents">Markdown / JSON</option><option value="figures">Figure</option><option value="quantitative">Quantitative</option></select></div><div className="artifact-summary"><span>主研究 PDF：{researchPdfs.length}</span><span>数学建模 PDF：{quantitativePdfs.length}</span></div><div className="artifact-list">{artifacts.length ? artifacts.slice(0, 64).map((artifact) => <article className={`artifact-item ${selected?.artifact_id === artifact.artifact_id ? "active" : ""}`} key={artifact.artifact_id}><button type="button" onClick={() => void select(artifact)}>{artifact.label}</button><div className="artifact-meta"><span>{artifact.stage === "quantitative" && artifact.media_type === "application/pdf" ? "数学建模 PDF" : artifact.stage}</span><span>{formatBytes(artifact.size_bytes)}</span></div></article>) : <p className="field-hint">当前没有可显示的已登记产物。</p>}</div></section><section className="panel preview-panel"><div className="panel-head compact"><h2>产物预览</h2><span>{selected?.label || "选择可预览产物"}</span></div>{selected && run ? <ArtifactPreview artifact={selected} run={run} text={text} error={previewError} /> : <p className="field-hint">JSON、Markdown 与 TXT 只读渲染；PDF 在受控产物端点内嵌预览。</p>}</section></>;
}

function ArtifactPreview({ artifact, run, text, error }: { artifact: Artifact; run: ResearchRun; text: string; error: string }) {
  const url = api.artifactUrl(run.run_id, artifact.artifact_id);
  if (error) return <><p className="field-hint">{error}</p><a className="secondary inline-action" href={url} target="_blank" rel="noreferrer">下载已登记产物</a></>;
  if (artifact.media_type === "application/pdf") return <iframe src={url} title={`${artifact.label} 预览`} />;
  if (isTextArtifact(artifact)) return <pre className="artifact-text-preview">{text || "正在读取只读产物…"}</pre>;
  if (artifact.media_type.startsWith("image/")) return <img className="artifact-image-preview" src={url} alt={artifact.label} />;
  return <a className="secondary inline-action" href={url} target="_blank" rel="noreferrer">下载已登记产物</a>;
}
