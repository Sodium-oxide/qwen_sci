import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertCircle, ArrowRight, Check, Copy, Loader2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import type { Connection } from "../events/stream";

export function Button({variant = "secondary", pending = false, children, className = "", ...props}: ButtonHTMLAttributes<HTMLButtonElement> & {variant?: "primary" | "secondary" | "ghost" | "danger"; pending?: boolean}) {
  return <button type="button" {...props} disabled={props.disabled || pending} aria-busy={pending || undefined} className={`button ${variant} ${className}`}>{pending && <Loader2 size={16} className="spin" aria-hidden="true" />}{children}</button>;
}
export function ActionLink({to, children, primary = false}: {to: string; children: ReactNode; primary?: boolean}) {
  return <Link className={`button ${primary ? "primary" : "secondary"}`} to={to}>{children}<ArrowRight size={16} aria-hidden="true" /></Link>;
}
export function PageHeading({title, description, action}: {title: string; description?: string; action?: ReactNode}) {
  return <header className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</header>;
}
export function Field({label, hint, error, children, className = ""}: {label: string; hint?: string; error?: string; children: ReactNode; className?: string}) {
  return <label className={`field ${className}`}><span className="field-label">{label}</span>{children}{hint && <small className="field-hint">{hint}</small>}{error && <small className="field-error">{error}</small>}</label>;
}
export function ErrorNotice({error, retry, focus = false}: {error: unknown; retry?: () => void; focus?: boolean}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {if (focus && error) ref.current?.focus();}, [error, focus]);
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <div ref={ref} className="notice error-notice" role="alert" tabIndex={-1}><AlertCircle size={19} aria-hidden="true" /><div><strong>{error instanceof ApiError && error.status === 409 ? "状态已更新，请核对最新结果" : "操作未完成"}</strong><p>{message}</p>{error instanceof ApiError && error.code === "MODEL_CALL_OUTCOME_UNKNOWN" && <p>请核对服务商的调用记录后再处理，避免重复生成。</p>}{error instanceof ApiError && error.requestId && <CopyText value={error.requestId} label="复制请求编号" />}{retry && <Button onClick={retry}>重新读取</Button>}</div></div>;
}
export function Notice({children, tone = "info"}: {children: ReactNode; tone?: "info" | "success" | "warning"}) {
  return <div className={`notice ${tone}`} role="status">{children}</div>;
}
export function Loading({label = "正在读取…"}: {label?: string}) {return <div className="loading" role="status"><Loader2 size={20} className="spin" aria-hidden="true" />{label}</div>;}
export function Empty({title, children, action}: {title: string; children?: ReactNode; action?: ReactNode}) {
  return <div className="empty-state"><h2>{title}</h2>{children && <p>{children}</p>}{action}</div>;
}
export const statusLabels: Record<string, string> = {QUEUED: "排队中", RUNNING: "正在处理", WAITING_FOR_REVIEW: "等待复核", SUCCEEDED: "已完成", FAILED: "处理失败", CANCEL_REQUESTED: "已请求取消", CANCELLED: "已取消", EXPIRED: "已过期", COMPLETED: "已完成", PENDING: "待开始", READY: "已就绪", PAUSED: "已暂停", DRAFT: "草稿", accepted: "已采纳", rejected: "保留原文", pending: "待复核", PASS: "检查通过", WARN: "存在提醒", NOT_AUDITABLE: "暂无法审计"};
export function StatusBadge({status}: {status: string}) {return <span className={`status-badge status-${status.toLowerCase()}`}><span className="status-dot" aria-hidden="true" />{statusLabels[status] || status}</span>;}
export function ConnectionBadge({connection}: {connection: Connection}) {
  const labels: Record<Connection, string> = {connecting: "正在连接事件流", connected: "事件流已连接", reconnecting: "正在重连", polling: "事件流中断 · 定期同步", closed: "按需同步"};
  return <span className={`connection connection-${connection}`}><span aria-hidden="true" />{labels[connection]}</span>;
}
export function Modal({open, onOpenChange, title, description, children, drawer = false}: {open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; children: ReactNode; drawer?: boolean}) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className={`dialog-content ${drawer ? "drawer-content" : ""}`}><div className="dialog-heading"><Dialog.Title>{title}</Dialog.Title><Dialog.Close className="icon-button" aria-label="关闭"><X size={20} /></Dialog.Close></div><Dialog.Description className="dialog-description">{description}</Dialog.Description>{children}</Dialog.Content></Dialog.Portal></Dialog.Root>;
}
export function Tabs({items, value, onChange, children, label = "内容视图"}: {items: {id: string; label: string}[]; value: string; onChange: (value: string) => void; children?: ReactNode; label?: string}) {
  const id = useId();
  return <><div className="tabs" role="tablist" aria-label={label}>{items.map((item, index) => <button key={item.id} id={`${id}-tab-${item.id}`} role="tab" type="button" aria-selected={item.id === value} aria-controls={`${id}-panel`} tabIndex={item.id === value ? 0 : -1} onClick={() => onChange(item.id)} onKeyDown={event => {
    const next = event.key === "ArrowRight" ? (index + 1) % items.length : event.key === "ArrowLeft" ? (index + items.length - 1) % items.length : event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault(); onChange(items[next].id);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus();
  }}>{item.label}</button>)}</div><div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${value}`} tabIndex={0}>{children}</div></>;
}
export function CopyText({value, label = "复制"}: {value: string; label?: string}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {if (!copied) return; const timer = setTimeout(() => setCopied(false), 2000); return () => clearTimeout(timer);}, [copied]);
  return <Button variant="ghost" onClick={() => {void navigator.clipboard.writeText(value).then(() => setCopied(true)).catch(() => setCopied(false));}}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "已复制" : label}</Button>;
}
export function formatDate(value: string) {return new Intl.DateTimeFormat("zh-CN", {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}).format(new Date(value));}
export function formatBytes(value: number) {return value < 1024 * 1024 ? `${Math.ceil(value / 1024)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`;}
