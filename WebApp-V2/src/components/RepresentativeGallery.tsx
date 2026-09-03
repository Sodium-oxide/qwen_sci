import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import type { RepresentativeFile, RepresentativeProject } from "../types";

function formatBytes(sizeBytes: number) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KiB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function fileUrl(file: RepresentativeFile, download = false) {
  return download ? `${file.url}?download=1` : file.url;
}

function projectImages(project: RepresentativeProject) {
  return project.files.filter((file) => file.kind === "image");
}

function projectPdfs(project: RepresentativeProject) {
  return project.files.filter((file) => file.kind === "pdf");
}

function projectLogs(project: RepresentativeProject) {
  return project.files.filter((file) => file.kind === "log");
}

export function RepresentativeGallery() {
  const [projects, setProjects] = useState<RepresentativeProject[]>([]);
  const [active, setActive] = useState<RepresentativeProject | null>(null);
  const [selectedPdf, setSelectedPdf] = useState<RepresentativeFile | null>(null);
  const [selectedLog, setSelectedLog] = useState<RepresentativeFile | null>(null);
  const [logText, setLogText] = useState("");
  const [status, setStatus] = useState("正在读取代表性研究成果…");
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    void api.representative().then((result) => {
      if (mounted) {
        setProjects(result);
        setStatus(result.length ? `${result.length} 项代表性成果` : "暂未发现代表性成果目录");
      }
    }).catch((error: unknown) => {
      if (mounted) setStatus(error instanceof Error ? error.message : "无法读取代表性成果。");
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (active) return undefined;
    const timer = window.setInterval(() => {
      const element = scrollerRef.current;
      if (!element || element.scrollWidth <= element.clientWidth) return;
      const nextLeft = element.scrollLeft + Math.min(360, element.clientWidth * 0.82);
      element.scrollTo({ left: nextLeft >= element.scrollWidth - element.clientWidth ? 0 : nextLeft, behavior: "smooth" });
    }, 5_500);
    return () => window.clearInterval(timer);
  }, [active]);

  const openProject = useCallback((project: RepresentativeProject) => {
    const firstPdf = projectPdfs(project)[0] ?? null;
    setActive(project);
    setSelectedPdf(firstPdf);
    setSelectedLog(null);
    setLogText("");
  }, []);

  const closeProject = useCallback(() => {
    setActive(null);
    setSelectedPdf(null);
    setSelectedLog(null);
    setLogText("");
  }, []);

  const readLog = useCallback(async (file: RepresentativeFile) => {
    setSelectedLog(file);
    setLogText("正在读取日志…");
    try {
      const response = await fetch(file.url);
      if (!response.ok) throw new Error("日志读取失败。");
      setLogText(await response.text());
    } catch (error) {
      setLogText(error instanceof Error ? error.message : "日志读取失败。");
    }
  }, []);

  const activeImages = useMemo(() => active ? projectImages(active) : [], [active]);
  const activePdfs = useMemo(() => active ? projectPdfs(active) : [], [active]);
  const activeLogs = useMemo(() => active ? projectLogs(active) : [], [active]);

  return <>
    <section className="representative-showcase" aria-labelledby="representative-title">
      <div className="showcase-heading"><div><span className="eyebrow">Representative research</span><h2 id="representative-title">系统代表性研究成果</h2><p>从真实运行中精选的研究计划、机制图和审计日志。横向滚动浏览，点击卡片查看完整 PDF、图片与日志。</p></div><span className="showcase-status">{status}</span></div>
      <div className="showcase-toolbar"><button type="button" className="secondary compact-button" onClick={() => scrollerRef.current?.scrollBy({ left: -360, behavior: "smooth" })}>← 上一项</button><button type="button" className="secondary compact-button" onClick={() => scrollerRef.current?.scrollBy({ left: 360, behavior: "smooth" })}>下一项 →</button></div>
      {projects.length ? <div className="representative-scroller" ref={scrollerRef}>{projects.map((project) => <button className="representative-card" type="button" key={project.project_id} onClick={() => openProject(project)}><div className="representative-cover">{project.cover_url ? <img src={project.cover_url} alt={`${project.title} 代表图片`} loading="lazy" /> : <span className="cover-fallback">QS</span>}<span className="cover-open">点击查看</span></div><div className="representative-card-body"><span className="representative-discipline">{project.discipline}</span><h3>{project.title}</h3><p>{project.summary}</p><div className="representative-counts"><span>{project.pdf_count} PDF</span><span>{project.image_count} 图片</span><span>{project.log_count} 日志</span></div></div></button>)}</div> : <div className="showcase-empty">{status}</div>}
    </section>
    {active && <div className="representative-modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) closeProject(); }}><section className="representative-modal" role="dialog" aria-modal="true" aria-labelledby="representative-modal-title"><div className="modal-header"><div><span className="eyebrow">Research archive · {active.project_id}</span><h2 id="representative-modal-title">{active.title}</h2><p>{active.summary}</p></div><button type="button" className="secondary compact-button" onClick={closeProject}>关闭</button></div><div className="modal-body"><div className="modal-main-preview">{selectedPdf ? <><div className="preview-label"><strong>研究成果 PDF</strong><a className="text-button" href={fileUrl(selectedPdf, true)}>下载 PDF</a></div><iframe src={fileUrl(selectedPdf)} title={`${selectedPdf.label} PDF 预览`} /></> : activeImages[0] ? <img src={activeImages[0].url} alt={active.title} /> : <div className="modal-placeholder">该成果没有可内嵌的 PDF 或图片。</div>}</div><aside className="modal-resources"><section><h3>研究 PDF（{activePdfs.length}）</h3>{activePdfs.length ? activePdfs.map((file) => <div className={`resource-row ${selectedPdf?.file_id === file.file_id ? "selected" : ""}`} key={file.file_id}><button type="button" onClick={() => { setSelectedPdf(file); setSelectedLog(null); }}>{file.label}</button><a className="text-button" href={fileUrl(file, true)}>下载</a></div>) : <p className="field-hint">暂无 PDF</p>}</section><section><h3>相关日志（{activeLogs.length}）</h3>{activeLogs.length ? activeLogs.map((file) => <div className={`resource-row ${selectedLog?.file_id === file.file_id ? "selected" : ""}`} key={file.file_id}><button type="button" onClick={() => void readLog(file)}>查阅 {file.label}</button><a className="text-button" href={fileUrl(file, true)}>下载</a></div>) : <p className="field-hint">暂无日志</p>}</section>{selectedLog && <section className="log-reader"><div className="preview-label"><strong>{selectedLog.label}</strong><a className="text-button" href={fileUrl(selectedLog, true)}>下载日志</a></div><pre>{logText}</pre></section>}</aside></div>{activeImages.length > 0 && <section className="modal-images"><h3>研究图片（{activeImages.length}）</h3><div className="modal-image-grid">{activeImages.map((file) => <a href={file.url} target="_blank" rel="noreferrer" key={file.file_id}><img src={file.url} alt={file.label} loading="lazy" /><span>{file.label} · {formatBytes(file.size_bytes)}</span></a>)}</div></section>}</section></div>}
  </>;
}
