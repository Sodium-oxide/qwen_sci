export type QuantitativeMode = "off" | "optional" | "required";
export type ScienceStage = "survey" | "idea" | "exp_design" | "author";

export type RunActionType =
  | "start_workflow"
  | "resume_science"
  | "cancel_science"
  | "resume_quantitative"
  | "prepare_quantitative_blueprint"
  | "discover_parameters"
  | "fetch_open_access_fulltext"
  | "register_parameter_material"
  | "extract_parameters"
  | "propose_parameters"
  | "approve_parameters"
  | "materialize_plan"
  | "execute_plan"
  | "qualify_result"
  | "propose_refinement"
  | "accept_refinement"
  | "finalize_quantitative_idea"
  | "publish_quantitative_models"
  | "build_quantitative_author_handoff"
  | "continue_author";

export interface Discipline {
  id: string;
  label: string;
  domain: string;
  template_family: string;
  allowed: boolean;
}

export interface MaterialRecord {
  material_id: string;
  original_name: string;
  stored_name?: string;
  file_size_bytes: number;
  sha256?: string;
  scope: "survey_evidence" | "parameter_source" | "context_only" | "do_not_send";
  modality?: string | null;
  contains_sensitive_data: boolean;
  metadata?: Record<string, string>;
}

export interface Artifact {
  artifact_id: string;
  label: string;
  stage: string;
  media_type: string;
  previewable: boolean;
  size_bytes: number;
}

export interface RunEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface RunLogSource {
  log_id: string;
  label: string;
  stage: string;
  attempt?: number | null;
  format: "jsonl" | "text";
  size_bytes: number;
}

export interface RunLogChunk {
  log_id: string;
  format: "jsonl" | "text";
  offset: number;
  next_offset: number;
  has_more: boolean;
  content: string;
}

export interface RepresentativeFile {
  file_id: string;
  label: string;
  kind: "image" | "pdf" | "log";
  media_type: string;
  size_bytes: number;
  url: string;
}

export interface RepresentativeProject {
  project_id: string;
  title: string;
  discipline: string;
  summary: string;
  cover_url?: string | null;
  files: RepresentativeFile[];
  pdf_count: number;
  image_count: number;
  log_count: number;
}

export interface StageState {
  status?: string;
  attempt?: number;
  failure?: { message?: string };
}

export interface QuantitativeState {
  status?: string;
  ideas?: Record<string, QuantitativeIdea>;
  active?: { idea_id: "Q1" | "Q2"; version: number; status?: string } | null;
  available_parameter_materials?: Array<{ material_id: string; title?: string; original_name?: string }>;
  documents?: Array<{ document_id: string; title?: string; source?: string }>;
  candidates?: Array<ParameterCandidate>;
  parameter_requests?: Array<ParameterRequest>;
  proposal?: { proposal_identity?: string };
  allowed_actions?: RunActionType[];
}

export interface QuantitativeIdea {
  title?: string;
  status?: string;
  current_version?: number;
  versions?: Record<string, QuantitativeVersion>;
}

export interface QuantitativeVersion {
  plan_identity?: string;
  execution_ids?: string[];
  unqualified_execution_ids?: string[];
}

export interface ParameterCandidate {
  parameter_id: string;
  candidate_id: string;
  normalized_value?: number;
  normalized_unit?: string;
  source?: { title?: string; document_id?: string };
}

export interface ParameterRequest {
  parameter_id: string;
  mathir_symbol?: string;
  meaning?: string;
  unit?: string;
  evidence_requirement?: string;
}

export interface ResearchRun {
  run_id: string;
  topic: string;
  created_at: string;
  last_updated_at: string;
  status: string;
  execution_mode: string;
  discipline_ids: string[];
  quantitative_mode: QuantitativeMode;
  language: string;
  remote_perception_authorized: boolean;
  stages: Record<string, StageState>;
  materials: MaterialRecord[];
  allowed_actions: RunActionType[];
  next_step: string;
  cancellation?: { requested_at?: string; requested_stage?: ScienceStage; acknowledged_at?: string } | null;
  event_url: string;
  artifacts: Artifact[];
  quantitative?: QuantitativeState | null;
}

export interface CreateRunPayload {
  topic: string;
  discipline_ids: string[];
  run_id?: string;
  language: "zh-CN" | "en";
  minimum_pages: number;
  quantitative_mode: QuantitativeMode;
  allow_remote_perception: boolean;
}

export interface MaterialDraft {
  file: File;
  scope: MaterialRecord["scope"];
  contains_sensitive_data: boolean;
}

export type ActionPayload = { type: RunActionType } & Record<string, unknown>;
