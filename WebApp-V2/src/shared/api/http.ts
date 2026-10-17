import type { z } from "zod";

export class ApiError extends Error {
  constructor(message: string, public status = 0, public code = "NETWORK_ERROR", public requestId = "", public retryable = false, public details: unknown = null) {
    super(message);
    this.name = "ApiError";
  }
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

export async function checkedResponse(path: string, options: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, {credentials: "same-origin", ...options});
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接服务。请检查连接后重试；已提交的任务会继续保存在服务端。");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const outer = record(body);
    const envelope = record(outer.error);
    const message = typeof envelope.message === "string" ? envelope.message : typeof outer.detail === "string" ? outer.detail : `请求失败（${response.status}）。`;
    throw new ApiError(message, response.status, typeof envelope.code === "string" ? envelope.code : "REQUEST_FAILED",
      typeof envelope.request_id === "string" ? envelope.request_id : response.headers.get("x-request-id") || "",
      envelope.retryable === true, envelope.details ?? outer.detail ?? null);
  }
  return response;
}

export async function request<T>(path: string, options: RequestInit = {}, schema?: z.ZodType<T>): Promise<T> {
  const response = await checkedResponse(path, options);
  if (response.status === 204) return undefined as T;
  const value: unknown = await response.json();
  if (!schema) return value as T;
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new ApiError("服务返回的数据格式与页面不一致。请刷新页面；问题持续时提供请求编号。", 502, "INVALID_RESPONSE", response.headers.get("x-request-id") || "", false, parsed.error.issues);
  return parsed.data;
}

export const jsonBody = (method: "POST" | "PUT", body: unknown): RequestInit => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
export const safeId = (value: string) => encodeURIComponent(value);
export const safeContentUrl = (value: string): string | undefined => /^\/api\/(?:files|jobs|runs|representative)\//.test(value) && !value.includes("\\") && !value.includes("..") ? value : undefined;

export async function download(path: string, body: unknown) {
  const response = await checkedResponse(path, jsonBody("POST", body));
  const blob = await response.blob();
  const filename = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] || "qwensci-export";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[\\/]/g, "_");
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return response.headers.get("x-artifact-id");
}
