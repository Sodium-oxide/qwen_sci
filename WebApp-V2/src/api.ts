import type { ActionPayload, CreateRunPayload, Discipline, MaterialDraft, ResearchRun, RunEvent, RunLogChunk, RunLogSource, RepresentativeProject } from "./types";

const API_BASE = "/api";

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? String(body.detail) : String(body);
    throw new Error(detail || "服务端未能完成该操作。");
  }
  return body as T;
}

export const api = {
  health: () => requestJson<{ status: string; runs_detected: number }>("/health"),
  disciplines: () => requestJson<{ disciplines: Discipline[] }>("/disciplines"),
  resolveDisciplines: (topic: string) => requestJson<{ suggested_catalog_ids?: string[]; reason?: string; primary?: { label?: string } }>("/disciplines/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  }),
  runs: (query = "") => requestJson<ResearchRun[]>(`/runs?query=${encodeURIComponent(query)}`),
  run: (runId: string) => requestJson<ResearchRun>(`/runs/${encodeURIComponent(runId)}`),
  createRun: (payload: CreateRunPayload) => requestJson<ResearchRun>("/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
  action: (runId: string, payload: ActionPayload) => requestJson<ResearchRun>(`/runs/${encodeURIComponent(runId)}/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
  logs: (runId: string) => requestJson<RunLogSource[]>(`/runs/${encodeURIComponent(runId)}/logs`),
  logChunk: (runId: string, logId: string, offset = 0) => requestJson<RunLogChunk>(
    `/runs/${encodeURIComponent(runId)}/logs/${encodeURIComponent(logId)}?offset=${offset}`,
  ),
  representative: () => requestJson<RepresentativeProject[]>("/representative"),
  async uploadMaterials(runId: string, drafts: MaterialDraft[]): Promise<ResearchRun> {
    if (!drafts.length) return this.run(runId);
    const form = new FormData();
    drafts.forEach((draft) => form.append("files", draft.file));
    form.append("metadata", JSON.stringify(drafts.map((draft) => ({
      label: draft.file.name,
      scope: draft.scope,
      contains_sensitive_data: draft.contains_sensitive_data,
    }))));
    const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/materials`, { method: "POST", body: form });
    const body: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body === "object" && body && "detail" in body ? String(body.detail) : "材料上传失败。");
    }
    return (body as { run: ResearchRun }).run;
  },
  removeMaterial: (runId: string, materialId: string) => requestJson<ResearchRun>(`/runs/${encodeURIComponent(runId)}/materials/${encodeURIComponent(materialId)}`, {
    method: "DELETE",
  }),
  materialUrl: (runId: string, materialId: string) => `${API_BASE}/runs/${encodeURIComponent(runId)}/materials/${encodeURIComponent(materialId)}`,
  artifactUrl: (runId: string, artifactId: string) => `${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
  artifactText: async (runId: string, artifactId: string) => {
    const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`);
    if (!response.ok) throw new Error("无法读取已登记的产物。");
    return response.text();
  },
};

export function parseRunEvent(message: MessageEvent<string>): RunEvent | null {
  try {
    return JSON.parse(message.data) as RunEvent;
  } catch {
    return null;
  }
}
