import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { ArtifactInspector } from "../../components/ArtifactInspector";
import { MaterialTray } from "../../components/MaterialTray";
import { QuantitativeReviewWorkspace } from "../../components/QuantitativeReviewWorkspace";
import { ParameterSearchPanel } from "../../components/ParameterSearchPanel";
import { WorkflowTimeline } from "../../components/WorkflowTimeline";
import { useRunEvents } from "../../hooks/useRunEvents";
import type { ActionPayload, MaterialRecord, ResearchRun } from "../../types";
import { ConnectionBadge, ErrorNotice, PageHeading, StatusBadge } from "../../shared/ui";

const quantitativeLabels: Record<ResearchRun["quantitative_mode"], string> = {off: "关闭", optional: "可选", required: "必须审批"};
const computationLabels: Record<ResearchRun["computation_mode"], string> = {off: "不进行", plan: "仅规划", run: "规划并执行"};

export function ResearchDetailPage() {
  const {runId = ""} = useParams(); const query = useQuery({queryKey: ["run", runId], queryFn: () => api.run(runId), enabled: Boolean(runId)}); const [busy, setBusy] = useState(false); const [actionError, setActionError] = useState<unknown>(null);
  const refresh = useCallback(() => {void query.refetch();}, [query]); const live = useRunEvents(query.data || null, refresh);
  const submit = async (payload: ActionPayload) => {if (!query.data) return; setBusy(true); setActionError(null); try {await api.action(query.data.run_id, payload); await query.refetch();} catch (error) {setActionError(error);} finally {setBusy(false);}};
  const deleteMaterial = async (material: MaterialRecord) => {if (!query.data) return; setBusy(true); try {await api.removeMaterial(query.data.run_id, material.material_id); await query.refetch();} catch (error) {setActionError(error);} finally {setBusy(false);}};
  if (query.isLoading) return <div className="page-container"><div className="loading">正在读取研究运行…</div></div>;
  if (query.error || !query.data) return <div className="page-container"><ErrorNotice error={query.error || new Error("研究运行不存在。")} retry={() => void query.refetch()} /></div>;
  const run = query.data;
  return <div className="research-detail page-container"><PageHeading title={run.topic} description={`${run.run_id} · ${run.research_depth === "light" ? "轻度研究" : "完整研究"}`} action={<><StatusBadge status={run.status} /><ConnectionBadge connection={live.connection} /></>} /><ErrorNotice error={actionError} focus={Boolean(actionError)} /><section className="detail-summary"><div><span>下一步</span><strong>{run.next_step}</strong></div><div><span>模型</span><strong>{run.model_name || "工作区默认"}</strong></div><div><span>量化分支</span><strong>{quantitativeLabels[run.quantitative_mode]}</strong></div><div><span>数值计算实验</span><strong>{computationLabels[run.computation_mode]}</strong></div><div><span>成果</span><strong>{run.artifacts.length} 个</strong></div><div><span>受控材料</span><strong>{run.materials.length} 个</strong></div></section><WorkflowTimeline run={run} events={live.events as never[]} connection={live.connection} onAction={payload => void submit(payload)} /><QuantitativeReviewWorkspace run={run} busy={busy} onAction={payload => void submit(payload)} /><ParameterSearchPanel run={run} /><div className="detail-columns"><section className="panel"><MaterialTray run={run} onDelete={deleteMaterial} onReplace={async () => undefined} /></section><ArtifactInspector run={run} /></div><Link className="back-link" to="/app">返回工作区首页</Link></div>;
}
