import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { ArtifactInspector } from "./components/ArtifactInspector";
import { MaterialTray } from "./components/MaterialTray";
import { QuantitativeReviewWorkspace } from "./components/QuantitativeReviewWorkspace";
import { ResearchComposer } from "./components/ResearchComposer";
import { RepresentativeGallery } from "./components/RepresentativeGallery";
import { SessionList } from "./components/SessionList";
import { WorkflowTimeline } from "./components/WorkflowTimeline";
import { useRunEvents } from "./hooks/useRunEvents";
import type { ActionPayload, CreateRunPayload, Discipline, MaterialDraft, MaterialRecord, ResearchRun, ScienceStage } from "./types";

type FeedbackTone = "" | "error" | "success";

function updateRunInList(runs: ResearchRun[], updated: ResearchRun) {
  return [updated, ...runs.filter((run) => run.run_id !== updated.run_id)];
}

function activeStage(run: ResearchRun | null) {
  if (!run) return "Survey";
  return Object.entries(run.stages).find(([, stage]) => stage.status !== "COMPLETED")?.[0] || "author";
}

export function App() {
  const [catalog, setCatalog] = useState<Discipline[]>([]);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [selected, setSelected] = useState<ResearchRun | null>(null);
  const [health, setHealth] = useState("连接后端中");
  const [feedback, setFeedback] = useState("正在连接真实科研后端…");
  const [feedbackTone, setFeedbackTone] = useState<FeedbackTone>("");
  const [technical, setTechnical] = useState("尚无服务端活动。");
  const [busy, setBusy] = useState(false);

  const refreshSelected = useCallback(async () => {
    if (!selected) return;
    try {
      const snapshot = await api.run(selected.run_id);
      setSelected((current) => current?.run_id === snapshot.run_id ? snapshot : current);
      setRuns((current) => updateRunInList(current, snapshot));
    } catch (error) {
      setTechnical(error instanceof Error ? error.message : "无法刷新运行状态。");
    }
  }, [selected?.run_id]);

  const { events, connection } = useRunEvents(selected, refreshSelected);

  const loadRuns = useCallback(async (query = "") => {
    try {
      setRuns(await api.runs(query));
    } catch (error) {
      setFeedback(`无法读取真实研究会话：${error instanceof Error ? error.message : "未知错误"}`);
      setFeedbackTone("error");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [healthResult, catalogResult, runResult] = await Promise.all([api.health(), api.disciplines(), api.runs()]);
        setCatalog(catalogResult.disciplines);
        setRuns(runResult);
        setHealth(`API 在线 · ${healthResult.runs_detected} 个运行`);
        setFeedback(runResult.length ? "已读取真实科研运行。" : "后端已连接。填写课题后即可创建第一个研究运行。");
        if (runResult[0]) setSelected(await api.run(runResult[0].run_id));
      } catch (error) {
        const message = error instanceof Error ? error.message : "未知错误";
        setHealth("后端不可用");
        setFeedback(`无法连接真实科研后端：${message}`);
        setFeedbackTone("error");
        setTechnical(message);
      }
    })();
  }, []);

  const selectRun = useCallback(async (runId: string) => {
    try {
      const snapshot = await api.run(runId);
      setSelected(snapshot);
      setRuns((current) => updateRunInList(current, snapshot));
      setFeedback("已连接到真实运行及其事件日志。");
      setFeedbackTone("success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法选择运行。";
      setFeedback(message);
      setFeedbackTone("error");
      setTechnical(message);
    }
  }, []);

  const applySnapshot = useCallback((snapshot: ResearchRun, message: string, tone: FeedbackTone = "success") => {
    setSelected(snapshot);
    setRuns((current) => updateRunInList(current, snapshot));
    setFeedback(message);
    setFeedbackTone(tone);
  }, []);

  const submitAction = useCallback(async (payload: ActionPayload) => {
    if (!selected) return;
    setBusy(true);
    try {
      const snapshot = await api.action(selected.run_id, payload);
      applySnapshot(snapshot, `已提交：${payload.type}。后台状态会通过事件流更新。`);
      setTechnical(JSON.stringify({ action: payload.type, run_id: snapshot.run_id }, null, 2));
    } catch (error) {
      const message = error instanceof Error ? error.message : "操作未完成。";
      setFeedback(message);
      setFeedbackTone("error");
      setTechnical(message);
    } finally {
      setBusy(false);
    }
  }, [applySnapshot, selected]);

  const startRun = useCallback(async (payload: CreateRunPayload, drafts: MaterialDraft[], until: ScienceStage) => {
    setBusy(true);
    try {
      const effectiveUntil = payload.quantitative_mode === "required" && until === "author" ? "exp_design" : until;
      let snapshot = await api.createRun(payload);
      applySnapshot(snapshot, "运行已创建；正在登记材料…");
      if (drafts.length) {
        snapshot = await api.uploadMaterials(snapshot.run_id, drafts);
        applySnapshot(snapshot, "材料已登记；正在启动主流程…");
      }
      snapshot = await api.action(snapshot.run_id, { type: "start_workflow", until });
      applySnapshot(snapshot, `研究已在后台启动，计划执行至 ${effectiveUntil}。关闭或刷新浏览器不会丢失运行。`, "success");
      setTechnical(JSON.stringify({ run_id: snapshot.run_id, materials_registered: drafts.length, workflow_until: effectiveUntil }, null, 2));
    } catch (error) {
      const message = error instanceof Error ? error.message : "未能启动研究。";
      setFeedback(`未能启动研究：${message}`);
      setFeedbackTone("error");
      setTechnical(message);
    } finally {
      setBusy(false);
    }
  }, [applySnapshot]);

  const resume = useCallback(async (until: ScienceStage) => {
    await submitAction({ type: "resume_science", until });
  }, [submitAction]);

  const resolveDisciplines = useCallback(async (topic: string) => {
    try {
      return await api.resolveDisciplines(topic);
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法识别学科。";
      setFeedback(message);
      setFeedbackTone("error");
      throw error;
    }
  }, []);

  const deleteMaterial = useCallback(async (material: MaterialRecord) => {
    if (!selected) return;
    setBusy(true);
    try {
      const snapshot = await api.removeMaterial(selected.run_id, material.material_id);
      applySnapshot(snapshot, `已从未启动的研究运行中移除 ${material.original_name}。`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法删除材料。";
      setFeedback(message);
      setFeedbackTone("error");
    } finally {
      setBusy(false);
    }
  }, [applySnapshot, selected]);

  const replaceMaterial = useCallback(async (material: MaterialRecord, file: File) => {
    if (!selected) return;
    if (file.size > 50 * 1024 * 1024) {
      setFeedback("替换文件超过 50 MiB 限制。");
      setFeedbackTone("error");
      return;
    }
    setBusy(true);
    try {
      const uploaded = await api.uploadMaterials(selected.run_id, [{ file, scope: material.scope, contains_sensitive_data: material.contains_sensitive_data }]);
      const snapshot = await api.removeMaterial(uploaded.run_id, material.material_id);
      applySnapshot(snapshot, `已以 ${file.name} 替换 ${material.original_name}；新的受控清单已生成。`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "材料替换未完成。";
      setFeedback(message);
      setFeedbackTone("error");
    } finally {
      setBusy(false);
    }
  }, [applySnapshot, selected]);

  const metrics = useMemo(() => ({ runCount: runs.length, artifactCount: selected?.artifacts.length ?? 0, quantMode: selected?.quantitative_mode ?? "off", stage: activeStage(selected) }), [runs.length, selected]);
  return <div className="shell"><header className="global-header"><div className="product"><span className="mark">QS</span><div><strong>Qwen-Sci V2</strong><span>科研智能体指挥舱</span></div></div><nav className="top-nav"><a href="#launcher">新建研究</a><a href="#workflow">流程编排</a><a href="#quant">量化状态</a><a href="#artifacts">成果归档</a></nav><div className="system-health"><span className="pulse"></span><span>{health}</span></div></header><section className="hero-console"><div className="hero-text"><span className="eyebrow">Evidence-bound AI Scientist</span><h1>把科研流程变成可恢复、可审计、可授权的智能工作台</h1><p>从课题输入、材料登记到综述、Idea、实验设计和报告输出；页面只呈现服务端已持久化的运行状态、审阅节点与成果。</p><div className="hero-actions"><a className="primary inline-action" href="#launcher">启动研究</a><a className="secondary inline-action" href="#sessions">查看运行记录</a></div></div></section><RepresentativeGallery /><main className="workspace-grid"><div id="sessions"><SessionList runs={runs} selectedRunId={selected?.run_id} onSelect={(runId) => void selectRun(runId)} onRefresh={loadRuns} /></div><section className="center-stage"><ResearchComposer catalog={catalog} busy={busy} feedback={feedback} feedbackTone={feedbackTone} onResolve={resolveDisciplines} onStart={startRun} onResume={resume} canResume={Boolean(selected?.allowed_actions.includes("resume_science"))} /><section className="panel metrics"><div className="metric"><span>检测到运行</span><strong>{metrics.runCount}</strong></div><div className="metric"><span>归档产物</span><strong>{metrics.artifactCount}</strong></div><div className="metric"><span>量化模式</span><strong>{metrics.quantMode}</strong></div><div className="metric"><span>当前阶段</span><strong>{metrics.stage}</strong></div></section><WorkflowTimeline run={selected} events={events} connection={connection} onAction={(payload) => void submitAction(payload)} /><QuantitativeReviewWorkspace run={selected} busy={busy} onAction={(payload) => void submitAction(payload)} /><details className="technical-details"><summary>技术详情</summary><pre>{technical}</pre></details></section><aside className="right-rail"><section className="panel run-card"><span className={`status ${selected?.status ?? "PENDING"}`}>{selected?.status ?? "未选择"}</span><h2>{selected?.run_id || "选择研究运行"}</h2><p>{selected?.topic || "创建或选择真实研究运行后，这里显示服务端当前状态。"}</p>{selected && <><div className="artifact-meta"><span>{selected.discipline_ids.join(" · ")}</span><span>{selected.execution_mode}</span></div><p>{selected.next_step}</p></>}</section>{selected && <section className="panel"><MaterialTray run={selected} onDelete={deleteMaterial} onReplace={replaceMaterial} /></section>}<ArtifactInspector run={selected} /></aside></main></div>;
}
