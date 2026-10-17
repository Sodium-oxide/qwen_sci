import { useEffect, useState } from "react";
import { ArrowRight, ExternalLink } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { modules, findModule } from "../app/catalog";
import { client } from "../shared/api";
import type { ProductPreview } from "../shared/contracts";
import { ErrorNotice, Loading, StatusBadge } from "../shared/ui";

export function QwenSciProductPage() {
  const [params, setParams] = useSearchParams();
  const selected = findModule(params.get("module") || "full-research") || modules[0];
  const query = client.preview;
  const [data, setData] = useState<Awaited<ReturnType<typeof query>> | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {const controller = new AbortController(); setError(null); setData(null); void query(selected.id, controller.signal).then(setData).catch(error => {if (error.name !== "AbortError") setError(error);}); return () => controller.abort();}, [selected.id]);
  const fallback: ProductPreview = {id: selected.id, title: selected.title, summary: selected.description, status: "partial", enabled: true, implemented: false, workspaceRoute: selected.id === "full-research" ? "/app/full-research" : `/app/${selected.id}`, previewRoute: `/products/qwensci?module=${selected.id}`, evidence: ["本地产品目录"], steps: selected.steps, data_source: "static_registry", is_live: false, last_verified_at: null};
  const preview = data ?? fallback;
  const previewSummary = String(preview.representative?.summary || preview.description || preview.summary);
  return <div className="product-page page-container"><header className="product-hero editorial-heading"><p className="eyebrow">QWENSCI / INTERACTIVE PRODUCT PREVIEW</p><h1>研究问题，<br /><em>进入一条可恢复的路径。</em></h1><p>选择一个模块，查看它如何记录输入、状态、人工确认与最终产物。</p></header><section className="preview-layout"><aside className="preview-nav" aria-label="产品模块">{modules.map(item => <button type="button" className={item.id === selected.id ? "active" : ""} key={item.id} onClick={() => setParams({module: item.id})}><span>{item.short}</span><strong>{item.title}</strong></button>)}</aside><div className="preview-stage"><div className="preview-stage-head"><div><p className="eyebrow">{selected.steps.join(" → ")}</p><h2>{selected.title}</h2><p>{selected.description}</p></div>{data && <StatusBadge status={data.status} />}</div>{error ? <ErrorNotice error={error} retry={() => {setError(null); void query(selected.id).then(setData).catch(setError);}} /> : null}{!data && !error ? <Loading label="正在读取预览契约…" /> : <><div className="preview-structure"><div className="preview-timeline">{selected.steps.map((step, i) => <div className={`preview-step ${i === 1 ? "current" : ""}`} key={step}><span>{String(i + 1).padStart(2, "0")}</span><strong>{step}</strong><small>{i === 0 ? "输入已登记" : i === 1 ? "下一步由用户确认" : "保留为产物"}</small></div>)}</div><div className="preview-insight"><span className="insight-label">{preview.data_source === "representative" ? "REPRESENTATIVE PROJECT" : "STATIC STRUCTURE PREVIEW"}</span>{preview.representative?.cover_url ? <img src={preview.representative.cover_url} alt="代表性科研成果" /> : <div className="insight-graphic"><div className="graphic-node">{selected.short}</div>{selected.steps.map((step, i) => <i key={step} style={{"--step": i} as React.CSSProperties}>{step}</i>)}</div>}<p>{previewSummary}</p><small>is_live = false · data_source = {preview.data_source}</small></div></div><div className="preview-actions"><Link className="button primary" to={selected.id === "full-research" ? "/app/full-research/new" : `/app/${selected.id}/new`}>打开真实工作区 <ArrowRight size={16} /></Link>{preview.representative?.files?.[0] && <a className="button secondary" href={preview.representative.files[0].url} target="_blank" rel="noreferrer">查看代表性文件 <ExternalLink size={15} /></a>}</div></>}</div></section></div>;
}
