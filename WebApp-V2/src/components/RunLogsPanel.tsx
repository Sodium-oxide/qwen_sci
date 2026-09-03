import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { ResearchRun, RunLogChunk, RunLogSource } from "../types";

function formatBytes(sizeBytes: number) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KiB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function RunLogsPanel({ run }: { run: ResearchRun | null }) {
  const runId = run?.run_id ?? "";
  const isStageRunning = Object.values(run?.stages ?? {}).some((stage) => stage.status === "RUNNING");
  const [sources, setSources] = useState<RunLogSource[]>([]);
  const [selectedLogId, setSelectedLogId] = useState("");
  const [chunk, setChunk] = useState<RunLogChunk | null>(null);
  const [status, setStatus] = useState("选择运行后读取阶段日志。");
  const [loading, setLoading] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const contentRef = useRef<HTMLPreElement>(null);

  const loadSources = useCallback(async () => {
    if (!runId) {
      setSources([]);
      setSelectedLogId("");
      setChunk(null);
      setStatus("选择运行后读取阶段日志。");
      return;
    }
    setLoading(true);
    try {
      const nextSources = await api.logs(runId);
      setSources(nextSources);
      setSelectedLogId((current) => nextSources.some((source) => source.log_id === current) ? current : nextSources[0]?.log_id ?? "");
      setStatus(nextSources.length ? `已发现 ${nextSources.length} 个受控阶段日志。` : "当前运行尚未生成可读取的阶段日志。");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "无法读取阶段日志目录。");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    if (!runId || !selectedLogId) {
      setChunk(null);
      return undefined;
    }
    let active = true;
    setLoading(true);
    void api.logChunk(runId, selectedLogId).then((nextChunk) => {
      if (active) {
        setChunk(nextChunk);
        setStatus(nextChunk.has_more ? "已读取首个日志分块；可继续加载完整记录。" : "已读取完整日志。");
      }
    }).catch((error: unknown) => {
      if (active) setStatus(error instanceof Error ? error.message : "无法读取该日志。");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [runId, selectedLogId]);

  useEffect(() => {
    if (autoScroll && contentRef.current) contentRef.current.scrollTop = contentRef.current.scrollHeight;
  }, [autoScroll, chunk?.content]);

  const appendChunk = useCallback(async () => {
    if (!runId || !chunk || chunk.log_id !== selectedLogId) return;
    setLoading(true);
    try {
      const nextChunk = await api.logChunk(runId, chunk.log_id, chunk.next_offset);
      setChunk((current) => current?.log_id === nextChunk.log_id ? {
        ...nextChunk,
        content: `${current.content}${current.content && nextChunk.content ? "\n" : ""}${nextChunk.content}`,
      } : current);
      setStatus(nextChunk.content ? (nextChunk.has_more ? "已追加日志；仍有未读取内容。" : "已读取完整日志。") : "没有新增日志内容。");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "无法继续读取日志。");
    } finally {
      setLoading(false);
    }
  }, [chunk, runId, selectedLogId]);

  useEffect(() => {
    if (!runId || !isStageRunning) return undefined;
    const timer = window.setInterval(() => void loadSources(), 5_000);
    return () => window.clearInterval(timer);
  }, [isStageRunning, loadSources, runId]);

  useEffect(() => {
    if (!runId || !isStageRunning || !autoScroll || !chunk) return undefined;
    const timer = window.setInterval(() => void appendChunk(), 5_000);
    return () => window.clearInterval(timer);
  }, [appendChunk, autoScroll, chunk, isStageRunning, runId]);

  const selectedSource = sources.find((source) => source.log_id === selectedLogId);
  return <section className="panel run-logs-panel">
    <div className="panel-head compact"><div><span className="eyebrow">Stage diagnostics</span><h2>完整阶段日志</h2></div><button type="button" className="secondary compact-button" disabled={!runId || loading} onClick={() => void loadSources()}>刷新日志列表</button></div>
    <p className="field-hint">仅展示本研究运行的 Survey、Idea、ExperimentDesign 和 Author 日志；密钥与本机路径会在服务端脱敏。</p>
    {sources.length > 0 && <label className="log-source-select">日志源<select value={selectedLogId} onChange={(event) => setSelectedLogId(event.target.value)}>{sources.map((source) => <option key={source.log_id} value={source.log_id}>{source.label} · {formatBytes(source.size_bytes)}</option>)}</select></label>}
    {selectedSource && <div className="log-meta"><span>{selectedSource.format.toUpperCase()}</span><span>{formatBytes(selectedSource.size_bytes)}</span><span>{selectedSource.stage}</span></div>}
    <div className="log-controls"><button type="button" className="secondary compact-button" disabled={!chunk || loading} onClick={() => void appendChunk()}>{chunk?.has_more ? "加载更多" : "读取新增内容"}</button><label className="check-label"><input type="checkbox" checked={autoScroll} onChange={(event) => setAutoScroll(event.target.checked)} />自动读取并滚到最新内容</label><span className="field-hint">{status}</span></div>
    {chunk ? <pre className="run-log-content" ref={contentRef}>{chunk.content || "（当前分块没有新内容。）"}</pre> : <p className="empty-log">尚未选择可读取日志。</p>}
  </section>;
}
