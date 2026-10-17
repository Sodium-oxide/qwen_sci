import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, ShieldCheck } from "lucide-react";
import { client } from "../../shared/api";
import type { Preferences } from "../../shared/contracts";
import { ApiError } from "../../shared/api/http";
import { Button, ErrorNotice, Field, Loading, Notice, PageHeading } from "../../shared/ui";

const localDefaults: Preferences = {
  version: 1,
  language: "zh-CN",
  disciplines: [],
  target_journal: "",
  citation_style: "APA 7",
  model_profile: "balanced",
  default_text_model: null,
  default_research_depth: "full",
  default_output_format: "markdown",
  network_access: "ask",
  remote_perception: false,
  privacy_mode: "controlled-materials",
};

export function PreferencesPage() {
  const queryClient = useQueryClient(); const query = useQuery({queryKey: ["preferences"], queryFn: ({signal}) => client.preferences(signal)}); const [draft, setDraft] = useState<Preferences | null>(null); const [error, setError] = useState<unknown>(null); const [saved, setSaved] = useState(false); const [pending, setPending] = useState(false);
  useEffect(() => {if (query.data) setDraft(query.data.preferences);}, [query.data]);
  const usingFallback = Boolean(query.error) && !query.data;
  const formDraft = draft || (usingFallback ? localDefaults : null);
  if (!formDraft) return <div className="page-container">{query.isLoading ? <Loading label="正在读取研究偏好…" /> : <ErrorNotice error={query.error} retry={() => void query.refetch()} />}</div>;
  const update = <K extends keyof Preferences>(key: K, value: Preferences[K]) => {setSaved(false); setDraft({...formDraft, [key]: value});};
  const save = async () => {setPending(true); setError(null); try {const result = await client.savePreferences(formDraft); setDraft(result.preferences); setSaved(true); await queryClient.invalidateQueries({queryKey: ["preferences"]});} catch (error) {setError(error);} finally {setPending(false);}};
  const conflict = error instanceof ApiError && error.status === 409;
  return <div className="preferences-page page-container"><PageHeading title="研究偏好" description="这些设置只影响之后创建的运行和任务；已经开始的任务使用自己的冻结清单。" action={<Button variant="primary" pending={pending} onClick={() => void save()}><Save size={16} />保存设置</Button>} />{usingFallback && <><ErrorNotice error={query.error} retry={() => void query.refetch()} /><Notice tone="warning">服务端暂时不可用，当前显示本地默认草稿。保存时仍会由服务端检查版本和权限。</Notice></>}<ErrorNotice error={error} /><div className="preferences-grid"><section className="panel preference-section"><p className="eyebrow">RESEARCH DEFAULTS</p><h2>重复的选择，保存一次。</h2><Field label="界面语言"><select value={formDraft.language} onChange={event => update("language", event.target.value as Preferences["language"])}><option value="zh-CN">简体中文</option><option value="en">English</option></select></Field><Field label="默认研究深度"><select value={formDraft.default_research_depth} onChange={event => update("default_research_depth", event.target.value as Preferences["default_research_depth"])}><option value="light">轻度研究</option><option value="full">完整研究</option></select></Field><Field label="默认输出格式"><select value={formDraft.default_output_format} onChange={event => update("default_output_format", event.target.value as Preferences["default_output_format"])}><option value="markdown">Markdown</option><option value="docx">DOCX</option><option value="pdf">PDF</option></select></Field><Field label="目标期刊"><input value={formDraft.target_journal} onChange={event => update("target_journal", event.target.value)} placeholder="可选" /></Field><Field label="引用风格"><input value={formDraft.citation_style} onChange={event => update("citation_style", event.target.value)} /></Field></section><section className="panel preference-section"><p className="eyebrow">MODEL &amp; OUTPUT</p><h2>让模型选择有依据。</h2><Field label="模型档位"><select value={formDraft.model_profile} onChange={event => update("model_profile", event.target.value as Preferences["model_profile"])}><option value="fast">快速</option><option value="balanced">平衡</option><option value="quality">质量优先</option></select></Field><Field label="默认文本模型" hint="图像示意图仍使用服务端 academic_figure 角色。"><select value={formDraft.default_text_model || ""} onChange={event => update("default_text_model", event.target.value || null)}><option value="">由模型档位决定</option><option value="qwen3.6-flash">qwen3.6-flash</option><option value="qwen3.7-plus">qwen3.7-plus</option><option value="qwen3.8-flash">qwen3.8-flash</option><option value="qwen3.8-max">qwen3.8-max</option></select></Field><Field label="默认学科"><input value={formDraft.disciplines.join(", ")} onChange={event => update("disciplines", event.target.value.split(",").map(item => item.trim()).filter(Boolean))} placeholder="用逗号分隔" /></Field><Notice tone="info">当前偏好版本 v{formDraft.version}。保存时服务端会检查并发版本。</Notice></section><section className="panel preference-section"><p className="eyebrow">PRIVACY &amp; NETWORK</p><h2>决定哪些内容可以离开工作区。</h2><Field label="网络访问"><select value={formDraft.network_access} onChange={event => update("network_access", event.target.value as Preferences["network_access"])}><option value="never">从不</option><option value="ask">每次询问</option><option value="allowed">允许</option></select></Field><Field label="隐私模式"><select value={formDraft.privacy_mode} onChange={event => update("privacy_mode", event.target.value as Preferences["privacy_mode"])}><option value="controlled-materials">只发送受控材料</option><option value="local-only">仅本地处理</option></select></Field><label className="toggle-field"><input type="checkbox" checked={formDraft.remote_perception} onChange={event => update("remote_perception", event.target.checked)} /><span><strong>允许远程视觉分析</strong><small>每个任务仍需要单独授权；关闭后不会静默切换。</small></span></label><div className="privacy-callout"><ShieldCheck size={18} /><p>标记为 do_not_send 的材料不会进入远程文本或图像调用。</p></div>{conflict && <Notice tone="warning">服务端版本已变化。请重新读取后将本地草稿逐项合并。</Notice>}{saved && <Notice tone="success">设置已保存，将用于之后创建的运行和任务。</Notice>}</section></div></div>;
}
