import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { ResearchRun, RunLogChunk, RunLogSource } from "../types";

const refreshInterval = 2_000;
const maxVisibleCharacters = 1_000_000;
const systemLog: RunLogSource = {
  log_id: "system-events", label: "系统运行事件", stage: "system", attempt: null, format: "jsonl", size_bytes: 0,
};

function formatBytes(sizeBytes: number) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KiB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function preferredSource(sources: RunLogSource[], run: ResearchRun | null) {
  const stages = ["survey", "idea", "exp_design", "author"];
  const score = (source: RunLogSource) =>
    (run?.stages[source.stage]?.status === "RUNNING" ? 10_000 : 0)
    + stages.indexOf(source.stage) * 1_000
    + (source.attempt ?? 0) * 10
    + (source.log_id.endsWith("console.log") ? 1 : 0);
  return sources.reduce((preferred, source) => score(source) > score(preferred) ? source : preferred, systemLog).log_id;
}

export function RunLogsPanel({ run }: { run: ResearchRun | null }) {
  return <RunLogReader key={run?.run_id ?? ""} run={run} />;
}

function RunLogReader({ run }: { run: ResearchRun | null }) {
  const runId = run?.run_id ?? "";
  const isRunning = run?.status === "RUNNING" || Object.values(run?.stages ?? {}).some((stage) => stage.status === "RUNNING");
  const activeStage = Object.entries(run?.stages ?? {}).find(([, stage]) => stage.status === "RUNNING")?.[0];
  const [sources, setSources] = useState<RunLogSource[]>([]);
  const [selectedLogId, setSelectedLogId] = useState("");
  const [chunk, setChunk] = useState<RunLogChunk | null>(null);
  const [sourceStatus, setSourceStatus] = useState("选择运行后读取日志。");
  const [chunkStatus, setChunkStatus] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [chunkError, setChunkError] = useState("");
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [autoSync, setAutoSync] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [clipped, setClipped] = useState(false);
  const [sourceRefresh, setSourceRefresh] = useState(0);
  const [chunkRefresh, setChunkRefresh] = useState(0);
  const cursorRef = useRef<RunLogChunk | null>(null);
  const manualSelection = useRef(false);
  const runRef = useRef(run);
  runRef.current = run;
  const contentRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      setSourcesLoading(true);
      try {
        const nextSources = await api.logs(runId, controller.signal);
        if (controller.signal.aborted) return;
        const available = [systemLog, ...nextSources];
        setSources(available);
        setSelectedLogId((current) => manualSelection.current && available.some((source) => source.log_id === current)
          ? current : preferredSource(available, runRef.current));
        setSourceError("");
        setSourceStatus(nextSources.length ? `已发现 ${nextSources.length} 个阶段日志，可切换查看。` : "阶段日志尚未写入，先同步系统运行事件。");
      } catch (error) {
        if (controller.signal.aborted) return;
        setSourceError(error instanceof Error ? error.message : "无法读取日志目录，请重试。");
      } finally {
        if (!controller.signal.aborted) {
          setSourcesLoading(false);
          if (autoSync && isRunning) timer = setTimeout(load, refreshInterval);
        }
      }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, activeStage, autoSync, isRunning, sourceRefresh]);

  useEffect(() => {
    if (!runId || !selectedLogId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (cursorRef.current?.log_id !== selectedLogId) {
      cursorRef.current = null;
      setChunk(null);
      setClipped(false);
    }
    const load = async () => {
      setChunkLoading(true);
      let nextDelay = refreshInterval;
      let pending = false;
      try {
        const current = cursorRef.current;
        const offset = current?.next_offset ?? 0;
        let nextChunk: RunLogChunk;
        if (selectedLogId === systemLog.log_id) {
          const events = await api.logEvents(runId, offset, controller.signal);
          nextChunk = {
            log_id: systemLog.log_id, format: "jsonl", offset,
            next_offset: events.length ? Number(events[events.length - 1].event_id) : offset,
            has_more: false, content: events.map((event) => JSON.stringify(event, null, 2)).join("\n"),
          };
        } else {
          nextChunk = await api.logChunk(runId, selectedLogId, offset, controller.signal);
        }
        if (controller.signal.aborted) return;
        const reset = nextChunk.offset < offset;
        const previousContent = reset ? "" : current?.content ?? "";
        const separator = nextChunk.format === "jsonl" && previousContent && nextChunk.content ? "\n" : "";
        const content = previousContent + separator + nextChunk.content;
        const merged = { ...nextChunk, content: content.slice(-maxVisibleCharacters) };
        cursorRef.current = merged;
        setChunk(merged);
        setClipped((previous) => (!reset && previous) || content.length > maxVisibleCharacters);
        setChunkError("");
        pending = nextChunk.has_more && nextChunk.next_offset > offset;
        nextDelay = pending ? 100 : refreshInterval;
        setChunkStatus(nextChunk.has_more ? "正在读取新增日志。" : isRunning ? "已同步到最新内容，等待新日志。" : "已读取当前日志。");
      } catch (error) {
        if (controller.signal.aborted) return;
        setChunkError(error instanceof Error ? error.message : "日志同步失败，请重试。");
      } finally {
        if (!controller.signal.aborted) {
          setChunkLoading(false);
          if (autoSync && (isRunning || pending)) timer = setTimeout(load, nextDelay);
        }
      }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, selectedLogId, autoSync, isRunning, chunkRefresh]);

  useEffect(() => {
    if (autoScroll && contentRef.current) contentRef.current.scrollTop = contentRef.current.scrollHeight;
  }, [autoScroll, chunk?.content]);

  const selectedSource = sources.find((source) => source.log_id === selectedLogId);
  const visibleChunk = chunk?.log_id === selectedLogId ? chunk : null;
  const error = sourceError || chunkError;
  return <section className="panel run-logs-panel">
    <div className="panel-head compact"><div><h2>运行日志</h2><p className="field-hint">系统事件与当前研究的阶段日志同步显示；密钥与本机路径由服务端脱敏。</p></div><button type="button" className="button secondary compact-button" disabled={!runId || sourcesLoading} onClick={() => { setSourceRefresh((value) => value + 1); setChunkRefresh((value) => value + 1); }}>刷新日志列表</button></div>
    {sources.length > 0 && <label className="log-source-select">日志源<select value={selectedLogId} onChange={(event) => { manualSelection.current = true; setSelectedLogId(event.target.value); }}>{sources.map((source) => <option key={source.log_id} value={source.log_id}>{source.label}{source.stage !== "system" ? ` · ${formatBytes(source.size_bytes)}` : ""}</option>)}</select></label>}
    {selectedSource && <div className="log-meta"><span>{selectedSource.format.toUpperCase()}</span>{selectedSource.stage !== "system" && <span>{formatBytes(selectedSource.size_bytes)}</span>}<span>{selectedSource.stage}</span></div>}
    <div className="log-controls"><button type="button" className="button secondary compact-button" disabled={!selectedLogId || chunkLoading} onClick={() => setChunkRefresh((value) => value + 1)}>{visibleChunk?.has_more ? "加载更多" : "读取新增内容"}</button><label className="check-label"><input type="checkbox" checked={autoSync} onChange={(event) => setAutoSync(event.target.checked)} />自动同步（每 2 秒）</label><label className="check-label"><input type="checkbox" checked={autoScroll} onChange={(event) => setAutoScroll(event.target.checked)} />滚动到最新内容</label></div>
    <p className="field-hint" role="status">{error || (selectedLogId ? chunkStatus : sourceStatus)}</p>
    {selectedLogId === systemLog.log_id && <p className="field-hint">系统事件记录阶段启动、进程归属与状态变化。详细检索输出请切换到 Survey 阶段日志；更新前未保存的终端输出无法回补。</p>}
    {clipped && <p className="field-hint">页面保留最近 100 万字符，完整日志仍保存在服务器。</p>}
    {visibleChunk ? <pre className="run-log-content" ref={contentRef} tabIndex={0} aria-label="运行日志内容">{visibleChunk.content || "正在等待新的日志记录。"}</pre> : <p className="empty-log">{runId ? "正在连接运行日志…" : "选择运行后读取日志。"}</p>}
  </section>;
}
