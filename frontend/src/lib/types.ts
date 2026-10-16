export type FieldType =
  | "text_short" | "text_long" | "number" | "currency" | "date" | "cpf" | "cnpj" | "cep" | "oab"
  | "email" | "phone" | "select" | "yes_no" | "checkbox";

export type FieldOption = { id?: string; label: string; value: string };

export type FieldOut = {
  id: string;
  name: string;
  label: string;
  type: FieldType;
  description: string | null;
  required: boolean;
  default_value: unknown;
  example: string | null;
  mask: string | null;
  group_name: string | null;
  position: number;
  include_in_batch: boolean;
  config: Record<string, unknown>;
  options: FieldOption[];
  occurrences: number;
  missing_in_document: boolean;
};

export type Me = {
  user: { id: string; name: string; email: string };
  workspace: { id: string; name: string; slug: string; role: "owner" | "member" };
  csrf_token: string | null;
  limits?: { max_generators: number; max_batch_rows: number; max_upload_mb: number; max_docs_per_month: number };
  features?: { pdf_import: boolean; external_ai: boolean };
};

export type GeneratorOut = {
  id: string;
  name: string;
  description: string | null;
  status: "active" | "archived";
  is_pinned: boolean;
  filename_pattern: string;
  fields_count: number;
  documents_generated: number;
  has_template: boolean;
  analysis_status: "pending" | "running" | "done" | "failed" | "skipped" | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type VersionOut = {
  id: string;
  version_number: number;
  revision: number;
  analysis_status: string;
  analysis_error: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
  author?: string | null;
  fields_count?: number;
  source_format?: "docx" | "pdf";
};

/** POST /batch/identify — tabela colada → modelo provável e como cada coluna vira campo. */
export type IdentifyMatch = { column: number; header: string; field: string; label: string; confidence: number; source: "nome" | "parecido" | "conteudo" | "semantico" };
export type IdentifyCandidate = {
  generator_id: string;
  name: string;
  score: number;
  exact: boolean;
  batch_fields: number;
  mapping: IdentifyMatch[];
  missing_required: string[];
  unmatched_columns: string[];
};
export type IdentifyResult = { status: "exact" | "probable" | "weak" | "none"; semantic: boolean; header_looks_like_data: boolean; columns: string[]; candidates: IdentifyCandidate[] };

// Documento do editor (ProseMirror JSON)
export type DocNode = {
  type: string;
  attrs?: Record<string, unknown>;
  content?: DocNode[];
  marks?: { type: string }[];
  text?: string;
};

export type EditorPayload = {
  generator: GeneratorOut;
  version: VersionOut;
  doc: DocNode;
  fields: FieldOut[];
  warnings: string[];
  stats: Record<string, number>;
};

export type FormPayload = {
  generator: GeneratorOut;
  version: VersionOut;
  fields: FieldOut[];
  doc: DocNode;
  pdf_available: boolean;
};

export type SuggestionGroup = {
  id: string;
  text: string;
  suggested_name: string;
  suggested_label: string;
  suggested_type: FieldType;
  confidence: number;
  source: "rule" | "ai" | "local";
  reason: string | null;
  count: number;
  occurrences: { id: string; block_key: string; location: string; start: number; end: number; context_before: string; context_after: string }[];
};

export type SuggestionsPayload = {
  items: SuggestionGroup[];
  analysis: {
    status: string;
    error: string | null;
    provider: string | null;
    model: string | null;
    provider_label: string | null;
    reused: boolean;
  };
};

export type JobFile = { id: string; kind: "docx" | "pdf" | "zip" | "report"; filename: string; size_bytes: number; expires_at: string; expired: boolean; item_id: string | null };

export type JobOut = {
  id: string;
  kind: "single" | "batch";
  status: "queued" | "processing" | "succeeded" | "partial" | "failed" | "cancelled";
  output_format: "docx" | "pdf" | "both";
  generator_id: string;
  generator_name: string;
  version_number: number | null;
  total_items: number;
  succeeded_items: number;
  failed_items: number;
  skipped_items: number;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  bytes_total: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_by: string | null;
  source_job_id: string | null;
  kit_run_id: string | null;
  kit_name: string | null;
  can_repeat: boolean;
  files_expire_at: string | null;
  files?: JobFile[];
};

export type JobItem = {
  id: string;
  row_index: number;
  status: "pending" | "processing" | "succeeded" | "failed" | "skipped";
  filename: string | null;
  error_code: string | null;
  error_message: string | null;
  attempts: number;
  files: JobFile[];
};

export type Paged<T> = { items: T[]; total: number; page: number; page_size: number };

export const TERMINAL_STATUSES = ["succeeded", "partial", "failed", "cancelled"];

// ------------------------------------------------------------------ Kit de documentos

export type KitOut = {
  id: string;
  name: string;
  description: string | null;
  status: "active" | "archived";
  is_pinned: boolean;
  filename_pattern: string;
  items_count: number;
  fields_count: number;
  documents_generated: number;
  has_documents: boolean;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type KitFieldOut = {
  id: string;
  name: string;
  label: string;
  type: FieldType;
  description: string | null;
  required: boolean;
  default_value: unknown;
  example: string | null;
  mask: string | null;
  position: number;
  config: Record<string, unknown>;
  options: FieldOption[];
};

export type KitItemFieldSummary = { name: string; label: string; type: FieldType; required: boolean };

export type KitItemOut = {
  id: string;
  generator_id: string;
  generator_name: string;
  position: number;
  usable: boolean;
  reason: string | null;
  fields: KitItemFieldSummary[];
  field_mapping: Record<string, string>;
  extra_field_names: string[];
};

export type KitFormPayload = {
  kit: KitOut;
  fields: KitFieldOut[];
  members: KitItemOut[];
  pdf_available: boolean;
  warnings: string[];
};

export type KitRunMember = { generator_id: string; job: JobOut };

export type KitRunOut = {
  id: string;
  kit_id: string;
  kit_name: string;
  status: JobOut["status"];
  output_format: "docx" | "pdf" | "both";
  total_members: number;
  succeeded_items: number;
  failed_items: number;
  created_at: string;
  created_by: string | null;
  members: KitRunMember[];
  files?: JobFile[];
};
