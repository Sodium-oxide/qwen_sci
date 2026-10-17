import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, FilePlus2, Sparkles, X } from "lucide-react";
import { api } from "../../api";
import type {
  ComputationMode,
  CreateRunPayload,
  Discipline,
  DisciplineResolution,
  MaterialDraft,
  QuantitativeMode,
  ScienceStage,
} from "../../types";
import { Button, ErrorNotice, Field, Loading, PageHeading, Notice } from "../../shared/ui";
import { disciplineLabel } from "./disciplineLabels";

export function ResearchLaunchPage({ depth }: { depth: "full" | "light" }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const disciplines = useQuery({
    queryKey: ["disciplines"],
    queryFn: async () => (await api.disciplines()).disciplines,
  });
  const [topic, setTopic] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [language, setLanguage] = useState<"zh-CN" | "en">("zh-CN");
  const [until, setUntil] = useState<ScienceStage>(depth === "light" ? "survey" : "author");
  const [quantitative, setQuantitative] = useState<QuantitativeMode>("off");
  const [computationMode, setComputationMode] = useState<ComputationMode>("off");
  const [model, setModel] = useState("");
  const [computationModel, setComputationModel] = useState("");
  const [files, setFiles] = useState<MaterialDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [recognizing, setRecognizing] = useState(false);
  const [recognition, setRecognition] = useState<DisciplineResolution | null>(null);
  const [recognitionError, setRecognitionError] = useState<unknown>(null);
  const recognitionRequest = useRef<AbortController | null>(null);

  useEffect(() => () => recognitionRequest.current?.abort(), []);

  const catalog = disciplines.data || [];
  const supported = catalog.filter((item) => item.allowed);
  const selectedLabels = useMemo(
    () => selected.map((id) => disciplineLabel(id, catalog.find((item) => item.id === id)?.label || id)),
    [selected, catalog],
  );

  const cancelRecognition = () => {
    recognitionRequest.current?.abort();
    setRecognizing(false);
    setRecognition(null);
    setRecognitionError(null);
  };

  const recognize = async () => {
    if (topic.trim().length < 8 || supported.length === 0) return;
    recognitionRequest.current?.abort();
    const controller = new AbortController();
    recognitionRequest.current = controller;
    setRecognizing(true);
    setRecognitionError(null);
    setRecognition(null);
    try {
      const result = await api.resolveDisciplines(topic.trim(), "model", controller.signal);
      if (controller.signal.aborted) return;
      const suggestions = result.suggested_catalog_ids.filter((id) => supported.some((item) => item.id === id));
      if (result.status === "resolved" && suggestions.length === 0) throw new Error("识别结果不在当前学科目录中，请重试或手动选择。");
      setRecognition(result);
      if (suggestions.length) setSelected(suggestions.slice(0, 2));
    } catch (recognitionFailure) {
      if (!controller.signal.aborted) setRecognitionError(recognitionFailure);
    } finally {
      if (recognitionRequest.current === controller) setRecognizing(false);
    }
  };

  const toggleDiscipline = (id: string) => {
    cancelRecognition();
    setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < 2 ? [...current, id] : current);
  };

  const submit = async () => {
    if (topic.trim().length < 8 || selected.length < 1) return;
    setBusy(true);
    setError(null);
    try {
      const payload: CreateRunPayload = {
        topic: topic.trim(),
        discipline_ids: selected,
        language,
        minimum_pages: 7,
        quantitative_mode: quantitative,
        computation_mode: depth === "full" ? computationMode : "off",
        allow_remote_perception: false,
        research_depth: depth,
        workflow_profile: depth === "light" ? "light_research" : "full_research",
        prompt_profile: depth === "light" ? "research-light" : "research-default",
        ...(model ? { model_name: model } : {}),
        ...(depth === "full" && computationModel ? { computation_model: computationModel } : {}),
      };
      let run = await api.createRun(payload);
      if (files.length) run = await api.uploadMaterials(run.run_id, files);
      run = await api.action(run.run_id, { type: "start_workflow", until });
      navigate(`/app/${depth === "light" ? "light-research" : "full-research"}/${run.run_id}`);
    } catch (submitError) {
      setError(submitError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="launch-page page-container">
      <PageHeading
        title={depth === "light" ? "开始一次轻度研究" : "启动完整研究"}
        description={
          depth === "light"
            ? "先获得结构化综述与证据缺口，最多推进到研究构思。"
            : "从课题与材料出发，推进 Survey、Idea、ExperimentDesign 与 Author。"
        }
        action={<span className="launch-mode">{depth === "light" ? "LIGHT RESEARCH" : "FULL RESEARCH"}</span>}
      />
      <ErrorNotice error={error} focus={Boolean(error)} />
      <div className="launch-progress">
        <span className="active">01 课题</span>
        <i />
        <span>02 材料</span>
        <i />
        <span>03 确认启动</span>
      </div>
      <section className="launch-form panel">
        <div className="form-section">
          <p className="eyebrow">01 / QUESTION</p>
          <h2>你要研究什么？</h2>
          <Field label="科学问题" hint="至少 8 个字符；这段文字会进入服务端输入清单。">
            <textarea
              value={topic}
              onChange={(event) => { cancelRecognition(); setTopic(event.target.value); }}
              rows={5}
              placeholder="例如：在给定边界条件下，某机制如何影响系统的稳定性？"
            />
          </Field>
          <div className="discipline-recognition">
            <Button pending={recognizing} disabled={busy || topic.trim().length < 8 || supported.length === 0} onClick={() => void recognize()}>
              {!recognizing && <Sparkles size={16} aria-hidden="true" />}
              {recognizing ? "正在识别学科…" : "识别学科"}
            </Button>
            <p>由 qwen3.8-flash 根据课题识别，识别后可在下方调整。</p>
          </div>
          <ErrorNotice error={recognitionError} />
          {recognition && (
            <Notice tone={recognition.suggested_catalog_ids.length ? "success" : "warning"}>
              <div>
                <strong>{recognition.suggested_catalog_ids.length ? `已选学科：${selectedLabels.join("、")}` : "暂未识别出支持的学科"}</strong>
                <p>{recognition.reason}</p>
              </div>
            </Notice>
          )}
          <div className="field-grid">
            <Field label="研究语言">
              <select value={language} onChange={(event) => setLanguage(event.target.value as "zh-CN" | "en")}>
                <option value="zh-CN">简体中文</option>
                <option value="en">English</option>
              </select>
            </Field>
            <Field label="目标终点">
              <select value={until} onChange={(event) => setUntil(event.target.value as ScienceStage)}>
                <option value="survey">Survey · 文献综述</option>
                {depth === "light" ? (
                  <option value="idea">Idea · 综述 + 构思</option>
                ) : (
                  <>
                    <option value="idea">Idea · 研究构思</option>
                    <option value="exp_design">Experiment Design · 实验设计</option>
                    <option value="author">Author · 写作交接</option>
                  </>
                )}
              </select>
            </Field>
          </div>
        </div>

        <div className="form-section">
          <p className="eyebrow">02 / SCOPE</p>
          <h2>给问题一个范围。</h2>
          <fieldset className="discipline-fieldset" disabled={busy}>
            <legend>支持学科 <span>已选 {selected.length}/2</span></legend>
            <p className="discipline-help">可手动选择 1–2 项，也可以在课题下方点击“识别学科”。</p>
            {disciplines.isPending ? <Loading label="正在加载学科目录…" /> : disciplines.isError ? (
              <ErrorNotice error={new Error("学科目录加载失败。请检查后端服务是否启动，再重新读取。")} retry={() => void disciplines.refetch()} />
            ) : supported.length === 0 ? (
              <Notice tone="warning"><div><p>当前没有可选学科，请重新读取目录。</p><Button onClick={() => void disciplines.refetch()}>重新读取学科</Button></div></Notice>
            ) : <div className="choice-grid" role="group" aria-label="支持学科，最多选择两项">
              {supported.map((item: Discipline) => (
                  <button
                    type="button"
                    className={selected.includes(item.id) ? "choice active" : "choice"}
                    key={item.id}
                    aria-pressed={selected.includes(item.id)}
                    disabled={!selected.includes(item.id) && selected.length >= 2}
                    onClick={() => toggleDiscipline(item.id)}
                  >
                    <span>{disciplineLabel(item.id, item.label)}{selected.includes(item.id) && <Check size={14} aria-hidden="true" />}</span>
                    <small>{item.label}</small>
                  </button>
                ))}
            </div>}
          </fieldset>
          <div className="selected-chips" aria-live="polite">
            {selectedLabels.map((label, index) => (
              <button className="discipline-chip" type="button" key={selected[index]} disabled={busy} aria-label={`移除${label}`} onClick={() => toggleDiscipline(selected[index])}>{label}<X size={12} aria-hidden="true" /></button>
            ))}
            {!selected.length && <small>还没有选择学科</small>}
          </div>
          <Field label="上传参考材料" hint="材料默认受控；标记 do_not_send 的材料不会进入远程调用。">
            <label className="file-drop">
              <FilePlus2 size={19} />
              <span>{files.length ? `${files.length} 个文件已选择` : "选择 PDF、DOCX、CSV 或文本材料"}</span>
              <input
                type="file"
                multiple
                onChange={(event) =>
                  setFiles(
                    Array.from(event.target.files || []).map((file) => ({
                      file,
                      scope: "context_only",
                      contains_sensitive_data: false,
                    })),
                  )
                }
              />
            </label>
          </Field>
        </div>

        <div className="form-section advanced-section">
          <p className="eyebrow">03 / CONTROL</p>
          <h2>确认这次运行。</h2>
          <div className="field-grid">
            <Field label="量化分支" hint="参数证据、数学模型和量化审批流程。">
              <select value={quantitative} onChange={(event) => setQuantitative(event.target.value as QuantitativeMode)}>
                <option value="off">关闭</option>
                <option value="optional">可选</option>
                <option value="required">必须经过量化审批</option>
              </select>
            </Field>
            {depth === "full" ? (
              <Field label="数值计算实验" hint="独立于量化分支；在实验设计阶段规划或执行计算。">
                <select value={computationMode} onChange={(event) => setComputationMode(event.target.value as ComputationMode)}>
                  <option value="off">不进行</option>
                  <option value="plan">仅规划计算方案</option>
                  <option value="run">规划并执行数值实验</option>
                </select>
              </Field>
            ) : (
              <Field label="文本模型（可选）">
                <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="使用工作区默认模型" />
              </Field>
            )}
          </div>
          {depth === "full" && (
            <div className="field-grid">
              <Field label="文本模型（可选）">
                <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="使用工作区默认模型" />
              </Field>
              <Field label="计算实验模型（可选）" hint="不填写时使用计算分支默认模型。">
                <input
                  value={computationModel}
                  onChange={(event) => setComputationModel(event.target.value)}
                  placeholder="使用计算分支默认模型"
                />
              </Field>
            </div>
          )}
          <Notice tone="info">
            <Sparkles size={15} />
            量化分支与数值计算实验分别记录、分别审阅；提交后任务会持久化到服务端，关闭浏览器不会停止运行。
          </Notice>
          <div className="launch-submit">
            <Button
              variant="primary"
              pending={busy}
              disabled={topic.trim().length < 8 || selected.length === 0 || recognizing}
              onClick={() => void submit()}
            >
              创建并启动研究 <ArrowRight size={16} />
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
