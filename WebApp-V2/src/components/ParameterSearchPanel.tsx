import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import type { ParameterSearchResult, ResearchRun } from "../types";

export function ParameterSearchPanel({ run }: { run: ResearchRun | null }) {
  const quantitative = run?.quantitative;
  const target = quantitative?.active;
  const requests = quantitative?.parameter_requests ?? [];
  const [parameterId, setParameterId] = useState(requests[0]?.parameter_id ?? "");
  const [query, setQuery] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [job, setJob] = useState<ParameterSearchResult | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");

  const parameter = useMemo(() => requests.find((item) => item.parameter_id === parameterId), [parameterId, requests]);
  const visible = Boolean(target && ["WAITING_FOR_PARAMETER_EVIDENCE", "WAITING_FOR_PARAMETER_REVIEW"].includes(target.status || ""));

  useEffect(() => {
    if (!parameterId && requests[0]) setParameterId(requests[0].parameter_id);
    if (parameter && !query) setQuery([parameter.parameter_id, parameter.mathir_symbol, parameter.meaning, parameter.unit].filter(Boolean).join(" "));
  }, [parameter, parameterId, query, requests]);

  useEffect(() => {
    if (!run || !target || !job || !["QUEUED", "RUNNING"].includes(job.status)) return undefined;
    const timer = window.setInterval(() => {
      void api.parameterSearchJob(run.run_id, target.idea_id, target.version, job.job_id).then(setJob).catch((error) => setMessage(error instanceof Error ? error.message : "搜索状态读取失败。"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job, run, target]);

  useEffect(() => {
    const latest = quantitative?.search_jobs?.[0];
    if (!run || !target || job || !latest || latest.parameter_id !== parameterId) return;
    void api.parameterSearchJob(run.run_id, target.idea_id, target.version, latest.job_id).then(setJob).catch(() => undefined);
  }, [job, parameterId, quantitative?.search_jobs, run, target]);

  if (!run || run.quantitative_mode === "off") return null;

  const search = async () => {
    if (!target || !parameterId || query.trim().length < 3 || !authorized) return;
    setMessage("正在并行查询 OpenAlex 与 AnySearch…");
    setSelected([]);
    try {
      const started = await api.parameterSearch(run.run_id, {
        idea_id: target.idea_id,
        version: target.version,
        parameter_id: parameterId,
        query: query.trim(),
        providers: ["openalex", "anysearch"],
        limit: 8,
        network_authorized: true,
      });
      setJob({ ...started, query: query.trim(), providers: ["openalex", "anysearch"], provider_runs: [], papers: [], evidence_boundary: "" });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "参数搜索未提交。 ");
    }
  };

  const selectSources = async () => {
    if (!job || !target || !selected.length) return;
    try {
      await api.selectParameterSearchSources(run.run_id, job.job_id, { idea_id: target.idea_id, version: target.version, paper_ids: selected });
      setMessage(`已登记 ${selected.length} 篇论文；请继续获取全文并执行参数抽取。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "论文来源登记失败。 ");
    }
  };

  return <section className={`panel parameter-search-panel ${visible ? "active" : ""}`} id="parameter-search">
    <div className="panel-head"><div><span className="eyebrow">Evidence discovery</span><h2>实时参数搜索器</h2></div><span className="badge">OpenAlex + AnySearch</span></div>
    {!visible ? <p className="field-hint">进入参数证据或参数审阅阶段后，可为当前 Q 版本搜索论文。</p> : <>
      <div className="parameter-search-form">
        <label>参数<select value={parameterId} onChange={(event) => { setParameterId(event.target.value); setQuery(""); }}><option value="">选择参数</option>{requests.map((item) => <option value={item.parameter_id} key={item.parameter_id}>{item.parameter_id} · {item.mathir_symbol || ""}</option>)}</select></label>
        <label className="search-query">查询词<input value={query} onChange={(event) => setQuery(event.target.value)} maxLength={512} placeholder="参数名、机制、模型或领域术语" /></label>
      </div>
      <label className="check-label"><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} />我明确授权本次搜索访问 OpenAlex 和 AnySearch</label>
      <button className="secondary" type="button" disabled={!authorized || query.trim().length < 3 || !parameterId || ["QUEUED", "RUNNING"].includes(job?.status || "")} onClick={() => void search()}>搜索参数证据</button>
      {message && <p className="field-hint">{message}</p>}
      {job && <div className="parameter-search-results"><div className="search-meta"><strong>{job.status}</strong><span>{job.provider_runs.map((item) => `${item.provider}: ${item.status}`).join(" · ")}</span></div>{job.papers.map((paper) => <label className="paper-result" key={paper.paper_id}><input type="checkbox" checked={selected.includes(paper.paper_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, paper.paper_id] : current.filter((id) => id !== paper.paper_id))} disabled={job.status !== "COMPLETED"} /><span><strong>{paper.title}</strong><small>{paper.year || "年份未知"} · {paper.doi || "无 DOI"} · {paper.sources.join(" + ")}{paper.cross_validated ? " · 交叉验证" : ""}</small>{paper.abstract && <em>{paper.abstract.slice(0, 280)}</em>}</span></label>)}{job.status === "COMPLETED" && <button className="secondary" type="button" disabled={!selected.length} onClick={() => void selectSources()}>登记选中文献为证据来源</button>}</div>}
    </>}
  </section>;
}
