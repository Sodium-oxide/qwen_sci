import { z } from "zod";

export const moduleIds = ["full-research", "light-research", "figure", "polish", "translate", "preferences"] as const;
export type ModuleId = typeof moduleIds[number];
export type FeatureKind = "figure" | "polish" | "translation";
export const jobStatuses = ["QUEUED", "RUNNING", "WAITING_FOR_REVIEW", "SUCCEEDED", "FAILED", "CANCEL_REQUESTED", "CANCELLED", "EXPIRED"] as const;
export const jobSchema = z.object({
  job_id: z.string(), kind: z.enum(["science", "figure", "polish", "translation"]),
  status: z.enum(jobStatuses), progress: z.number().nullable(), current_step: z.string().nullable(),
  attempt: z.number(), revision: z.number(), max_attempts: z.number(),
  created_at: z.string(), updated_at: z.string(), available_actions: z.array(z.string()),
  output_artifact_ids: z.array(z.string()), model_name: z.string().nullable(),
  provider_name: z.string().nullable(), prompt_id: z.string().nullable(), prompt_version: z.string().nullable(),
  prompt_hash: z.string().nullable(), input_manifest_sha256: z.string(), request_hash: z.string(),
  project_id: z.string().nullable(), run_id: z.string().nullable(),
  error_code: z.string().nullable(), error_message: z.string().nullable(), retryable: z.boolean(),
}).passthrough();
export type Job = z.infer<typeof jobSchema>;

export const reviewSchema = z.object({
  job_id: z.string(), attempt: z.number(), revision: z.number(), review_version: z.number(),
  decision: z.enum(["accept", "reject"]).nullable(),
  segments: z.record(z.string(), z.enum(["accepted", "rejected"])),
  pages: z.record(z.string(), z.enum(["accepted", "rejected"])),
});
export type Review = z.infer<typeof reviewSchema>;

export const artifactSchema = z.object({
  artifact_id: z.string(), job_id: z.string(), attempt: z.number(), revision: z.number(),
  role: z.string(), label: z.string(), media_type: z.string(), size_bytes: z.number(),
  sha256: z.string(), validator_status: z.string().nullable(), created_at: z.string(),
  provenance: z.record(z.string(), z.unknown()),
}).passthrough();
export type JobArtifact = z.infer<typeof artifactSchema>;

export const fileSchema = z.object({
  file_id: z.string(), original_name: z.string(), mime_type: z.string(), detected_type: z.string(),
  size_bytes: z.number(), sha256: z.string(), source: z.enum(["upload", "run_material", "generated"]),
  sensitivity: z.enum(["public", "controlled", "sensitive"]), content_url: z.string(),
  project_id: z.string().nullable(), run_id: z.string().nullable(), job_id: z.string().nullable(),
  material_scope: z.string().nullable(), created_at: z.string(), source_artifact_id: z.string().nullable(),
}).passthrough();
export type SharedFile = z.infer<typeof fileSchema>;

export const productModuleSchema = z.object({
  id: z.enum(moduleIds), title: z.string(), summary: z.string(),
  status: z.enum(["available", "partial", "planned"]), enabled: z.boolean(), implemented: z.boolean(),
  workspaceRoute: z.string(), previewRoute: z.string(), evidence: z.array(z.string()), steps: z.array(z.string()),
  data_source: z.enum(["static_registry", "representative"]), is_live: z.literal(false),
  last_verified_at: z.string().nullable(),
}).passthrough();
export type ProductModule = z.infer<typeof productModuleSchema>;
export const previewSchema = productModuleSchema.extend({
  description: z.string().optional(),
  representative: z.object({
    project_id: z.string(), title: z.string(), summary: z.string(),
    cover_url: z.string().nullable().optional(),
    files: z.array(z.object({file_id: z.string(), label: z.string(), kind: z.string(), url: z.string(), media_type: z.string(), size_bytes: z.number()})),
  }).optional(),
});
export type ProductPreview = z.infer<typeof previewSchema>;

const availabilitySchema = z.object({
  status: z.string(), reason: z.string().nullable().optional(), configured: z.boolean().optional(),
  verified: z.boolean().optional(), model: z.string().optional(), role: z.string().optional(),
}).passthrough();
export const capabilitiesSchema = z.object({
  text_model_choices: z.array(z.string()), text_models: z.record(z.string(), availabilitySchema),
  figure: z.object({enabled: z.boolean(), python: availabilitySchema, r: availabilitySchema, image_generation: availabilitySchema,
    chart_types: z.array(z.string()), planning_modes: z.array(z.string()), style_fields: z.array(z.string()),
    reference_image_editing: availabilitySchema, panels: z.string()}).passthrough(),
  polish: z.object({enabled: z.boolean(), input_formats: z.array(z.string()), docx_equations: z.string()}).passthrough(),
  translation: z.object({enabled: z.boolean(), modes: z.record(z.string(), availabilitySchema), pdf_parser: availabilitySchema,
    pdf_text: availabilitySchema, ocr: availabilitySchema, layout_reconstruction: z.boolean()}).passthrough(),
  export: z.object({markdown: availabilitySchema, json: availabilitySchema, docx: availabilitySchema, pdf: availabilitySchema, fidelity: z.string()}).passthrough(),
  preferences: z.object({status: z.string(), scope: z.string(), multiuser: z.boolean()}).passthrough(),
}).passthrough();
export type Capabilities = z.infer<typeof capabilitiesSchema>;

export const preferencesSchema = z.object({
  version: z.number().int().min(1), language: z.enum(["zh-CN", "en"]), disciplines: z.array(z.string()).max(20),
  target_journal: z.string().max(128), citation_style: z.string().max(128),
  model_profile: z.enum(["fast", "balanced", "quality"]), default_text_model: z.string().nullable(),
  default_research_depth: z.enum(["light", "full"]), default_output_format: z.enum(["markdown", "docx", "pdf"]),
  network_access: z.enum(["never", "ask", "allowed"]), remote_perception: z.boolean(),
  privacy_mode: z.enum(["controlled-materials", "local-only"]),
});
export type Preferences = z.infer<typeof preferencesSchema>;
export const preferencesEnvelopeSchema = z.object({scope: z.literal("workspace"), auth_required: z.boolean(), preferences: preferencesSchema});

export const segmentSchema = z.object({
  segment_id: z.string(), original: z.string(), revised: z.string(), rationale: z.string(),
  risk: z.enum(["low", "medium", "high"]), preserved_entities: z.array(z.string()), unresolved_items: z.array(z.string()),
});
export const polishSchema = z.object({segments: z.array(segmentSchema), global_notes: z.array(z.string())}).passthrough();
export type PolishResult = z.infer<typeof polishSchema>;

const blockSchema = z.object({block_id: z.string(), text: z.string(), kind: z.string().optional()}).passthrough();
export const pageSchema = z.object({
  page_number: z.number(), source_blocks: z.array(blockSchema), translated_blocks: z.array(blockSchema),
  parser_backend: z.string(), ocr_used: z.boolean(), review_status: z.string(),
  review_version: z.number(), unresolved_items: z.array(z.string()),
  parser_diagnostics: z.array(z.unknown()).optional(),
}).passthrough();
export type TranslationPage = z.infer<typeof pageSchema>;
export const pageListSchema = z.object({job_id: z.string(), review_version: z.number(), pages: z.array(z.object({
  page_number: z.number(), block_count: z.number(), parser_backend: z.string(), ocr_used: z.boolean(),
  review_status: z.string(), unresolved_count: z.number(), parser_diagnostics: z.array(z.unknown()).optional(),
}))});
export type PageList = z.infer<typeof pageListSchema>;

export interface FeatureAction {
  type: string;
  notes?: string;
  segment_ids?: string[];
  page_numbers?: number[];
  expected_attempt?: number;
  expected_review_version?: number;
  figure_style?: FigureStyle;
}
export interface FigureStyle {
  x_label?: string; y_label?: string; title?: string; width_mm?: number; height_mm?: number;
  palette?: "colorblind" | "blue" | "neutral";
}
export const featurePath = (kind: FeatureKind) => `/api/${kind}/jobs`;
export const featureRoute = (kind: FeatureKind) => `/app/${kind === "translation" ? "translate" : kind}`;
