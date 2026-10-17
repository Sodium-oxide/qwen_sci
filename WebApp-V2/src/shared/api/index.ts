import { z } from "zod";
import {
  artifactSchema, capabilitiesSchema, featurePath, fileSchema, jobSchema, pageListSchema, pageSchema,
  polishSchema, preferencesEnvelopeSchema, previewSchema, productModuleSchema, reviewSchema,
  type FeatureAction, type FeatureKind, type Preferences,
} from "../contracts";
import { checkedResponse, download, jsonBody, request, safeId } from "./http";

export interface JobFilters {kind?: string; status?: string; project_id?: string; run_id?: string; limit?: number; offset?: number}
export const queryString = (filters: object) => {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {if (value !== undefined && value !== "") query.set(key, String(value));});
  return query.toString();
};
export const client = {
  health: (signal?: AbortSignal) => request("/api/health", {signal}, z.object({status: z.string(), runs_detected: z.number()})),
  capabilities: (signal?: AbortSignal) => request("/api/capabilities", {signal}, capabilitiesSchema),
  modules: (signal?: AbortSignal) => request("/api/product/modules", {signal}, z.array(productModuleSchema)),
  preview: (moduleId: string, signal?: AbortSignal) => request(`/api/product/preview/${safeId(moduleId)}`, {signal}, previewSchema),
  preferences: (signal?: AbortSignal) => request("/api/preferences", {signal}, preferencesEnvelopeSchema),
  preferenceFields: (signal?: AbortSignal) => request("/api/preferences/schema", {signal}, z.object({scope: z.string(), fields: z.record(z.string(), z.array(z.string()))})),
  savePreferences: (value: Preferences) => request("/api/preferences", jsonBody("PUT", value), preferencesEnvelopeSchema),
  jobs: (filters: JobFilters = {}, signal?: AbortSignal) => request(`/api/jobs?${queryString(filters)}`, {signal}, z.array(jobSchema)),
  job: (jobId: string, signal?: AbortSignal) => request(`/api/jobs/${safeId(jobId)}`, {signal}, jobSchema),
  review: (jobId: string, signal?: AbortSignal) => request(`/api/jobs/${safeId(jobId)}/review`, {signal}, reviewSchema),
  action: (kind: FeatureKind, jobId: string, action: FeatureAction) => request(`${featurePath(kind)}/${safeId(jobId)}/actions`, jsonBody("POST", action), jobSchema),
  create: (kind: FeatureKind, input: unknown) => request(featurePath(kind), jsonBody("POST", input), jobSchema),
  artifacts: (jobId: string, signal?: AbortSignal) => request(`/api/jobs/${safeId(jobId)}/artifacts`, {signal}, z.array(artifactSchema)),
  artifactUrl: (jobId: string, artifactId: string) => `/api/jobs/${safeId(jobId)}/artifacts/${safeId(artifactId)}`,
  artifactText: async (jobId: string, artifactId: string, signal?: AbortSignal) => (await checkedResponse(client.artifactUrl(jobId, artifactId), {signal})).text(),
  reuse: (jobId: string, artifactId: string) => request(`/api/jobs/${safeId(jobId)}/artifacts/${safeId(artifactId)}/files`, jsonBody("POST", {}), fileSchema),
  files: (projectId = "", signal?: AbortSignal) => request(`/api/files?${queryString({project_id: projectId})}`, {signal}, z.array(fileSchema)),
  file: (fileId: string, signal?: AbortSignal) => request(`/api/files/${safeId(fileId)}`, {signal}, fileSchema),
  upload: (file: File, projectId = "", sensitivity = "controlled") => {
    const form = new FormData();
    form.append("file", file);
    form.append("sensitivity", sensitivity);
    if (projectId) form.append("project_id", projectId);
    return request("/api/files", {method: "POST", body: form}, fileSchema);
  },
  removeFile: (fileId: string) => request<void>(`/api/files/${safeId(fileId)}`, {method: "DELETE"}),
  revisions: (jobId: string, signal?: AbortSignal) => request(`/api/polish/jobs/${safeId(jobId)}/revisions`, {signal}, polishSchema),
  pages: (jobId: string, signal?: AbortSignal) => request(`/api/translation/jobs/${safeId(jobId)}/pages`, {signal}, pageListSchema),
  page: (jobId: string, page: number, signal?: AbortSignal) => request(`/api/translation/jobs/${safeId(jobId)}/pages/${page}`, {signal}, pageSchema),
  export: (kind: "polish" | "translation", jobId: string, format: string, version: number) => download(`${featurePath(kind)}/${safeId(jobId)}/export`, {format, expected_review_version: version}),
};
