import { useEffect, useState } from "react";
import { Ban, RefreshCw, RotateCcw } from "lucide-react";
import { client } from "../../shared/api";
import type { Job } from "../../shared/contracts";
import { ApiError } from "../../shared/api/http";
import { Button, ConnectionBadge, ErrorNotice, StatusBadge } from "../../shared/ui";
import type { Connection } from "../../shared/events/stream";

export function JobStatusCard({job, connection, onUpdated}: {job: Job; connection: Connection; onUpdated: (job: Job) => void}) {
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const act = async (type: "cancel" | "retry") => {setPending(true); setError(null); try {onUpdated(await client.action(job.kind === "translation" ? "translation" : job.kind as "figure" | "polish", job.job_id, {type}));} catch (error) {setError(error);} finally {setPending(false);}};
  return <section className="job-status panel"><div className="job-status-head"><div><span className="eyebrow">{job.kind.toUpperCase()} / ATTEMPT {job.attempt}</span><h2><StatusBadge status={job.status} /></h2></div><ConnectionBadge connection={connection} /></div>{job.current_step && <p className="job-step">当前步骤：{job.current_step}</p>}{job.progress !== null && <div className="progress-track" aria-label={`进度 ${job.progress}%`}><span style={{width: `${job.progress}%`}} /></div>}<div className="job-facts"><span>内容版本 v{job.revision}</span><span>输入 {job.input_manifest_sha256.slice(0, 12)}…</span>{job.model_name && <span>模型 {job.model_name}</span>}</div>{job.status === "FAILED" && <div className="job-failure"><strong>{job.error_code || "任务失败"}</strong><p>{job.error_message || "服务端没有提供更多说明。"}</p>{job.retryable && job.available_actions.includes("retry") && <Button pending={pending} onClick={() => void act("retry")}><RotateCcw size={15} />重新尝试</Button>}{job.error_code === "MODEL_CALL_OUTCOME_UNKNOWN" && <p>服务商调用结果未知。请核对 provider 记录，避免直接重复生成。</p>}</div>}{job.status === "CANCEL_REQUESTED" && <p className="field-hint">取消会在安全检查点生效，任务仍然保留历史记录。</p>}{job.available_actions.includes("cancel") && <Button variant="danger" pending={pending} onClick={() => void act("cancel")}><Ban size={15} />请求取消</Button>}<ErrorNotice error={error} /></section>;
}

export function FeatureArtifacts({job, onReuse}: {job: Job; onReuse?: (artifactId: string) => void}) {
  const [artifacts, setArtifacts] = useState<Array<Record<string, unknown>>>([]);
  useEffect(() => {let active = true; setArtifacts([]); void client.artifacts(job.job_id).then(value => {if (active) setArtifacts(value as Array<Record<string, unknown>>);}).catch(() => undefined); return () => {active = false;};}, [job.job_id, job.attempt]);
  return <section className="panel artifact-strip"><div className="panel-title"><h2>本次产物</h2><span>{artifacts.length} 个已登记</span></div>{artifacts.length ? <div className="artifact-chips">{artifacts.map(item => <a key={String(item.artifact_id)} href={client.artifactUrl(job.job_id, String(item.artifact_id))} target="_blank" rel="noreferrer"><strong>{String(item.label)}</strong><small>{String(item.role)} · attempt {String(item.attempt)}</small></a>)}</div> : <p className="field-hint">结果完成或进入复核后，产物会显示在这里。</p>}{job.status === "SUCCEEDED" && onReuse && artifacts.map(item => <Button variant="ghost" key={`reuse-${String(item.artifact_id)}`} onClick={() => onReuse(String(item.artifact_id))}>将已接受产物登记到共享文件</Button>)}</section>;
}
