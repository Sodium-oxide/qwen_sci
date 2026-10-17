import { useState } from "react";
import { Check, FileOutput, RotateCcw, Undo2 } from "lucide-react";
import { client } from "../../shared/api";
import type { FeatureAction, Job, Review } from "../../shared/contracts";
import { ApiError } from "../../shared/api/http";
import { Button, ErrorNotice, Notice } from "../../shared/ui";

type Kind = "figure" | "polish" | "translation";
export function ReviewToolbar({kind, job, review, selected, onUpdated}: {kind: Kind; job: Job; review: Review; selected: string[]; onUpdated: (job: Job) => void}) {
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const action = async (type: string) => {setPending(true); setError(null); const payload: FeatureAction = {type, notes, expected_attempt: review.attempt, expected_review_version: review.review_version}; if (kind === "polish") payload.segment_ids = selected; else if (kind === "translation") payload.page_numbers = selected.map(Number); try {onUpdated(await client.action(kind, job.job_id, payload)); setNotes("");} catch (error) {setError(error);} finally {setPending(false);}};
  const suffix = kind === "polish" ? "segments" : "pages";
  return <div className="review-toolbar"><div className="review-selection"><strong>{selected.length}</strong> 个{kind === "polish" ? "段落" : "页面"}已选</div><label className="review-notes"><span>反馈或导出备注</span><textarea value={notes} onChange={event => setNotes(event.target.value)} placeholder={selected.length ? "重新生成时必须填写具体修改意见" : "整体退回或导出时可选"} rows={2} /></label><div className="review-actions">{job.available_actions.includes(`accept_${suffix}`) && <Button variant="primary" pending={pending} disabled={!selected.length} onClick={() => void action(`accept_${suffix}`)}><Check size={15} />采纳选中</Button>}{job.available_actions.includes(`reject_${suffix}`) && <Button pending={pending} disabled={!selected.length} onClick={() => void action(`reject_${suffix}`)}><Undo2 size={15} />保留原文</Button>}{job.available_actions.includes(`regenerate_${suffix}`) && <Button pending={pending} disabled={!selected.length || !notes.trim()} onClick={() => void action(`regenerate_${suffix}`)}><RotateCcw size={15} />按意见重生成</Button>}{job.available_actions.includes("accept") && <Button variant="primary" pending={pending} onClick={() => void action("accept")}><Check size={15} />接受全部并完成</Button>}{job.available_actions.includes("reject") && <Button variant="danger" pending={pending} disabled={!notes.trim()} onClick={() => void action("reject")}><Undo2 size={15} />整体退回</Button>}{job.status === "SUCCEEDED" && <ExportMenu kind={kind} job={job} version={review.review_version} />}</div><ErrorNotice error={error} focus={error instanceof ApiError && error.status === 409} /><Notice tone="info"><FileOutput size={15} />“保留原文”会在最终导出时使用来源文本；“重生成”只影响选中的内容。</Notice></div>;
}

function ExportMenu({kind, job, version}: {kind: "polish" | "translation" | "figure"; job: Job; version: number}) {
  const [pending, setPending] = useState("");
  const formats = kind === "figure" ? [] : ["markdown", "json", "docx", "pdf"];
  if (!formats.length) return null;
  return <label className="export-select"><span>导出</span><select value={pending} onChange={event => {const format = event.target.value; setPending(format); if (format) void client.export(kind as "polish" | "translation", job.job_id, format, version).finally(() => setPending(""));}}><option value="">选择格式</option>{formats.map(format => <option key={format} value={format}>{format.toUpperCase()}</option>)}</select></label>;
}
