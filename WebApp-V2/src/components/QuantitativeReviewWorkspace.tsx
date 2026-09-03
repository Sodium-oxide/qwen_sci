import { useMemo, useState } from "react";

import type { ActionPayload, ParameterRequest, QuantitativeState, ResearchRun, RunActionType } from "../types";

const LABELS: Partial<Record<RunActionType, string>> = {
  resume_quantitative: "初始化 Q1 / Q2 工作区", prepare_quantitative_blueprint: "生成模型蓝图",
  discover_parameters: "授权检索参数证据", fetch_open_access_fulltext: "授权获取开放全文",
  register_parameter_material: "登记上传的参数资料", extract_parameters: "提取参数候选",
  propose_parameters: "提交参数选择方案", approve_parameters: "批准完整参数集",
  materialize_plan: "物化模型与执行计划", execute_plan: "确认并执行精确计划",
  qualify_result: "进行结果资格审查", propose_refinement: "提出模型修订", accept_refinement: "批准修订版本",
  finalize_quantitative_idea: "冻结当前 Q 版本", publish_quantitative_models: "生成量化补充 PDF",
  build_quantitative_author_handoff: "创建 Author 证据交接", continue_author: "携带量化交接继续 Author",
};

type ParameterForm = Record<string, { candidate_id: string; selected_value: string; selection_rationale: string }>;
type RefinementForm = {
  revision_reason: string;
  hypothesis_delta: string;
  model_delta: string;
  parameter_or_boundary_delta: string;
  expected_discriminating_result: string;
  falsification_condition: string;
};

function activeTarget(quantitative: QuantitativeState | null | undefined) {
  return quantitative?.active ? { idea_id: quantitative.active.idea_id, version: quantitative.active.version } : null;
}

function planIdentity(quantitative: QuantitativeState | null | undefined) {
  const active = activeTarget(quantitative);
  return active ? quantitative?.ideas?.[active.idea_id]?.versions?.[`v${active.version}`]?.plan_identity || "" : "";
}

const TARGET_ACTIONS = new Set<RunActionType>([
  "prepare_quantitative_blueprint", "discover_parameters", "fetch_open_access_fulltext", "register_parameter_material",
  "extract_parameters", "propose_parameters", "approve_parameters", "materialize_plan", "execute_plan",
  "qualify_result", "propose_refinement", "accept_refinement", "finalize_quantitative_idea",
]);

export function QuantitativeReviewWorkspace({ run, busy, onAction }: { run: ResearchRun | null; busy: boolean; onAction: (payload: ActionPayload) => void }) {
  const quantitative = run?.quantitative;
  const actions = quantitative?.allowed_actions ?? run?.allowed_actions.filter((action) => action !== "resume_science") ?? [];
  const target = activeTarget(quantitative);
  const [networkAuthorized, setNetworkAuthorized] = useState(false);
  const [selectedMaterial, setSelectedMaterial] = useState("");
  const [selectedDocument, setSelectedDocument] = useState("");
  const [parameters, setParameters] = useState<ParameterForm>({});
  const [parameterApproved, setParameterApproved] = useState(false);
  const [confirmedIdentity, setConfirmedIdentity] = useState("");
  const [executeConfirmed, setExecuteConfirmed] = useState(false);
  const [executionId, setExecutionId] = useState("");
  const [relation, setRelation] = useState("INCONCLUSIVE");
  const [resultSummary, setResultSummary] = useState("");
  const [refinement, setRefinement] = useState({ revision_reason: "", hypothesis_delta: "", model_delta: "", parameter_or_boundary_delta: "", expected_discriminating_result: "", falsification_condition: "" });
  const [revisionAccepted, setRevisionAccepted] = useState(false);
  const identity = planIdentity(quantitative);
  const activeVersion = target ? quantitative?.ideas?.[target.idea_id]?.versions?.[`v${target.version}`] : undefined;

  const send = (type: RunActionType, extras: Record<string, unknown> = {}) => {
    if (TARGET_ACTIONS.has(type) && !target) return;
    onAction({ type, ...(TARGET_ACTIONS.has(type) ? target! : {}), ...extras });
  };
  const requests = quantitative?.parameter_requests ?? [];
  const candidatesByRequest = useMemo(() => new Map(requests.map((request) => [request.parameter_id, (quantitative?.candidates ?? []).filter((candidate) => candidate.parameter_id === request.parameter_id)])), [quantitative?.candidates, requests]);
  const updateParameter = (id: string, patch: Partial<ParameterForm[string]>) => setParameters((current) => {
    const currentValue = current[id] ?? { candidate_id: "", selected_value: "", selection_rationale: "" };
    return { ...current, [id]: { ...currentValue, ...patch } };
  });
  const submitParameters = () => {
    const selections = requests.map((request) => {
      const form = parameters[request.parameter_id] ?? { candidate_id: "", selected_value: "", selection_rationale: "" };
      return form.candidate_id ? { parameter_id: request.parameter_id, candidate_id: form.candidate_id, selection_rationale: form.selection_rationale } : { parameter_id: request.parameter_id, candidate_id: "", selected_value: Number(form.selected_value), provenance_status: "APPROVED_MODEL_ASSUMPTION", selection_rationale: form.selection_rationale };
    });
    if (selections.some((selection) => selection.selection_rationale.trim().length < 3 || (!selection.candidate_id && !Number.isFinite(selection.selected_value)))) return;
    send("propose_parameters", { selections });
  };

  const steps = ["研究问题", "模型蓝图", "参数证据", "计划物化", "结果资格审查"];
  return <section className="panel quant" id="quant"><div className="panel-head"><div><span className="eyebrow">Quantitative governance</span><h2>数学建模审批链</h2></div><span className="badge amber">执行授权由后端核验</span></div><div className="quant-layout"><div className="quant-steps">{steps.map((step, index) => <article className="quant-step" key={step}><span className="step-index">{index + 1}</span><div><strong>{step}</strong><p>{["选择 Q1 / Q2，并核对模型家族、变量与可证伪条件。", "将方程、边界条件和参数清单写入不可变版本。", "文献检索、全文与参数批准逐项获得授权。", "生成 simulation_run_plan 与可核对的 plan identity。", "人工限定结果与假设的关系，并决定冻结或修订。 "][index]}</p></div></article>)}</div><div className="model-card"><span>当前量化状态</span>{!run ? <p>选择运行后展示持久化的量化审批链。</p> : run.quantitative_mode === "off" ? <p>此运行未启用量化分支；主科学流程仍可独立完成。</p> : <><strong>{quantitative?.status || "等待 Idea / Design"}</strong><IdeaCards quantitative={quantitative} />{identity && <><p>已物化计划身份；执行时必须逐字确认。</p><code className="plan-identity">{identity}</code></>}<QuantitativeActionForm actions={actions} quantitative={quantitative} target={target} busy={busy} networkAuthorized={networkAuthorized} setNetworkAuthorized={setNetworkAuthorized} selectedMaterial={selectedMaterial} setSelectedMaterial={setSelectedMaterial} selectedDocument={selectedDocument} setSelectedDocument={setSelectedDocument} requests={requests} candidatesByRequest={candidatesByRequest} parameters={parameters} updateParameter={updateParameter} submitParameters={submitParameters} parameterApproved={parameterApproved} setParameterApproved={setParameterApproved} confirmedIdentity={confirmedIdentity} setConfirmedIdentity={setConfirmedIdentity} executeConfirmed={executeConfirmed} setExecuteConfirmed={setExecuteConfirmed} executionId={executionId} setExecutionId={setExecutionId} relation={relation} setRelation={setRelation} resultSummary={resultSummary} setResultSummary={setResultSummary} activeVersion={activeVersion} refinement={refinement} setRefinement={setRefinement} revisionAccepted={revisionAccepted} setRevisionAccepted={setRevisionAccepted} send={send} /></>}</div></div></section>;
}

function IdeaCards({ quantitative }: { quantitative?: QuantitativeState | null }) {
  return <div className="quant-ideas">{["Q1", "Q2"].map((ideaId) => {
    const idea = quantitative?.ideas?.[ideaId];
    return <article className={`quant-idea ${quantitative?.active?.idea_id === ideaId ? "active" : ""} ${idea ? "" : "disabled"}`} key={ideaId}><strong>{ideaId}</strong><span>{idea?.title || "等待 Idea 阶段生成"}</span><small>{idea?.status || "等待"} · v{idea?.current_version ?? 0}</small></article>;
  })}</div>;
}

interface FormProps {
  actions: RunActionType[]; quantitative?: QuantitativeState | null; target: { idea_id: "Q1" | "Q2"; version: number } | null; busy: boolean;
  networkAuthorized: boolean; setNetworkAuthorized: (value: boolean) => void; selectedMaterial: string; setSelectedMaterial: (value: string) => void; selectedDocument: string; setSelectedDocument: (value: string) => void;
  requests: ParameterRequest[]; candidatesByRequest: Map<string, QuantitativeState["candidates"]>; parameters: ParameterForm; updateParameter: (id: string, patch: Partial<ParameterForm[string]>) => void; submitParameters: () => void;
  parameterApproved: boolean; setParameterApproved: (value: boolean) => void; confirmedIdentity: string; setConfirmedIdentity: (value: string) => void; executeConfirmed: boolean; setExecuteConfirmed: (value: boolean) => void;
  executionId: string; setExecutionId: (value: string) => void; relation: string; setRelation: (value: string) => void; resultSummary: string; setResultSummary: (value: string) => void; activeVersion?: { execution_ids?: string[]; unqualified_execution_ids?: string[] };
  refinement: RefinementForm; setRefinement: (value: RefinementForm) => void; revisionAccepted: boolean; setRevisionAccepted: (value: boolean) => void; send: (type: RunActionType, extras?: Record<string, unknown>) => void;
}

function ActionButton({ action, busy, onClick }: { action: RunActionType; busy: boolean; onClick: () => void }) { return <button className="secondary quant-action" type="button" disabled={busy} onClick={onClick}>{LABELS[action] || action}</button>; }

function QuantitativeActionForm(props: FormProps) {
  const { actions, quantitative, busy, send } = props;
  if (!actions.length) return <p className="field-hint">当前没有需要网页授权的量化操作。后台任务完成后会自动刷新此处。</p>;
  if (actions.includes("resume_quantitative")) return <ActionButton action="resume_quantitative" busy={busy} onClick={() => send("resume_quantitative")} />;
  if (actions.some((action) => action === "discover_parameters" || action === "fetch_open_access_fulltext")) return <div className="quant-form"><label className="check-label"><input type="checkbox" checked={props.networkAuthorized} onChange={(event) => props.setNetworkAuthorized(event.target.checked)} />我明确授权本次操作访问学术元数据或开放获取全文</label><div className="action-row">{actions.filter((action) => action === "discover_parameters" || action === "fetch_open_access_fulltext").map((action) => <ActionButton key={action} action={action} busy={busy || !props.networkAuthorized} onClick={() => send(action, { network_authorized: true })} />)}</div></div>;
  if (actions.includes("register_parameter_material")) return <div className="quant-form"><label>已上传的参数资料<select value={props.selectedMaterial} onChange={(event) => props.setSelectedMaterial(event.target.value)}><option value="">选择资料</option>{quantitative?.available_parameter_materials?.map((item) => <option key={item.material_id} value={item.material_id}>{item.title || item.original_name || item.material_id}</option>)}</select></label><ActionButton action="register_parameter_material" busy={busy || !props.selectedMaterial} onClick={() => send("register_parameter_material", { material_id: props.selectedMaterial })} /></div>;
  if (actions.includes("extract_parameters")) return <div className="quant-form"><label>待提取证据文档<select value={props.selectedDocument} onChange={(event) => props.setSelectedDocument(event.target.value)}><option value="">选择文档</option>{quantitative?.documents?.map((item) => <option key={item.document_id} value={item.document_id}>{item.document_id} · {item.title || item.source || "证据"}</option>)}</select></label><ActionButton action="extract_parameters" busy={busy || !props.selectedDocument} onClick={() => send("extract_parameters", { document_id: props.selectedDocument })} /></div>;
  if (actions.includes("propose_parameters")) return <div className="quant-form parameter-form">{props.requests.map((request) => <ParameterField key={request.parameter_id} request={request} candidates={props.candidatesByRequest.get(request.parameter_id) ?? []} form={props.parameters[request.parameter_id]} update={(patch) => props.updateParameter(request.parameter_id, patch)} />)}<ActionButton action="propose_parameters" busy={busy} onClick={props.submitParameters} /></div>;
  if (actions.includes("approve_parameters")) return <div className="quant-form"><p>方案身份：{quantitative?.proposal?.proposal_identity || "等待读取"}</p><label className="check-label"><input type="checkbox" checked={props.parameterApproved} onChange={(event) => props.setParameterApproved(event.target.checked)} />我已人工核对全部参数来源、单位、条件和选择理由</label><ActionButton action="approve_parameters" busy={busy || !props.parameterApproved} onClick={() => send("approve_parameters", { approved: true })} /></div>;
  if (actions.includes("execute_plan")) return <div className="quant-form execution-form"><p>后端会在入队前及执行时再次核对当前计划身份与批准参数。</p><label>计划身份<input value={props.confirmedIdentity} onChange={(event) => props.setConfirmedIdentity(event.target.value)} autoComplete="off" spellCheck={false} /></label><label className="check-label"><input type="checkbox" checked={props.executeConfirmed} onChange={(event) => props.setExecuteConfirmed(event.target.checked)} />我确认开始这一次数值模拟</label><ActionButton action="execute_plan" busy={busy || !props.executeConfirmed || !props.confirmedIdentity} onClick={() => send("execute_plan", { confirmed: true, plan_identity: props.confirmedIdentity })} /></div>;
  if (actions.includes("qualify_result")) { const executions = props.activeVersion?.unqualified_execution_ids || props.activeVersion?.execution_ids || []; return <div className="quant-form"><label>执行记录<select value={props.executionId} onChange={(event) => props.setExecutionId(event.target.value)}><option value="">选择执行记录</option>{executions.map((id) => <option value={id} key={id}>{id}</option>)}</select></label><label>与假设的关系<select value={props.relation} onChange={(event) => props.setRelation(event.target.value)}><option value="SUPPORTED_WITHIN_MODEL">模型内支持</option><option value="CONSTRAINED">受到约束</option><option value="REFUTED_WITHIN_MODEL">模型内反驳</option><option value="INCONCLUSIVE">不确定</option></select></label><label>结果摘要<textarea value={props.resultSummary} onChange={(event) => props.setResultSummary(event.target.value)} placeholder="仅总结本次数值模拟的结果、边界和局限" /></label><ActionButton action="qualify_result" busy={busy || !props.executionId || props.resultSummary.trim().length < 8} onClick={() => send("qualify_result", { execution_id: props.executionId, hypothesis_relation: props.relation, result_summary: props.resultSummary.trim() })} /></div>; }
  if (actions.includes("propose_refinement")) return <div className="quant-form">{([ ["revision_reason", "修订原因"], ["hypothesis_delta", "假设变化"], ["model_delta", "模型变化（每行一项）"], ["parameter_or_boundary_delta", "参数或边界变化（每行一项）"], ["expected_discriminating_result", "预期区分性结果"], ["falsification_condition", "可证伪条件"] ] as Array<[keyof RefinementForm, string]>).map(([key, label]) => <label key={key}>{label}<textarea value={props.refinement[key]} onChange={(event) => props.setRefinement({ ...props.refinement, [key]: event.target.value })} /></label>)}<ActionButton action="propose_refinement" busy={busy} onClick={() => send("propose_refinement", { ...props.refinement, model_delta: props.refinement.model_delta.split("\n").map((item) => item.trim()).filter(Boolean), parameter_or_boundary_delta: props.refinement.parameter_or_boundary_delta.split("\n").map((item) => item.trim()).filter(Boolean) })} />{actions.includes("finalize_quantitative_idea") && <ActionButton action="finalize_quantitative_idea" busy={busy} onClick={() => send("finalize_quantitative_idea")} />}</div>;
  if (actions.includes("accept_refinement")) return <div className="quant-form"><label className="check-label"><input type="checkbox" checked={props.revisionAccepted} onChange={(event) => props.setRevisionAccepted(event.target.checked)} />我确认创建下一不可变 Q 版本</label><ActionButton action="accept_refinement" busy={busy || !props.revisionAccepted} onClick={() => send("accept_refinement", { accepted: true })} />{actions.includes("finalize_quantitative_idea") && <ActionButton action="finalize_quantitative_idea" busy={busy} onClick={() => send("finalize_quantitative_idea")} />}</div>;
  return <div className="quant-form"><div className="action-row">{actions.map((action) => <ActionButton action={action} busy={busy} key={action} onClick={() => send(action)} />)}</div></div>;
}

function ParameterField({ request, candidates, form, update }: { request: ParameterRequest; candidates: NonNullable<QuantitativeState["candidates"]>; form?: ParameterForm[string]; update: (patch: Partial<ParameterForm[string]>) => void }) {
  const current = form ?? { candidate_id: "", selected_value: "", selection_rationale: "" };
  return <fieldset><legend>{request.parameter_id} · {request.mathir_symbol || ""}</legend><p>{request.meaning || ""} · {request.unit || ""} · {request.evidence_requirement || ""}</p><label>候选值<select value={current.candidate_id} onChange={(event) => update({ candidate_id: event.target.value })}><option value="">使用明确声明的模型假设</option>{candidates.map((candidate) => <option value={candidate.candidate_id} key={candidate.candidate_id}>{candidate.candidate_id} = {candidate.normalized_value} {candidate.normalized_unit} · {candidate.source?.title || candidate.source?.document_id || "证据"}</option>)}</select></label>{!current.candidate_id && <label>模型假设值<input type="number" step="any" value={current.selected_value} onChange={(event) => update({ selected_value: event.target.value })} /></label>}<label>选择理由<textarea value={current.selection_rationale} onChange={(event) => update({ selection_rationale: event.target.value })} placeholder="说明候选值或模型假设为何适合此模型边界" /></label></fieldset>;
}
