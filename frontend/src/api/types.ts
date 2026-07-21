export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export interface DataTypeItem {
  data_type: string;
  domain: string;
  label: string;
  is_activated: boolean;
  browse_enabled?: boolean;
  min_points: number;
  chart_type?: string | null;
  table_name?: string | null;
  filters?: CatalogFilterMeta[];
  row_count?: number | null;
}

export interface CatalogFilterMeta {
  key: string;
  label: string;
  filter_type: string;
}

export interface CatalogColumnMeta {
  key: string;
  label: string;
  type: string;
}

export interface BrowseDomainCount {
  domain: string;
  label: string;
  count: number;
}

export interface BrowseTypeSummary {
  total: number;
  domains: BrowseDomainCount[];
}

export interface DataTypeListResponse {
  items: DataTypeItem[];
  domains: DomainItem[];
  summary?: BrowseTypeSummary | null;
}

export interface DataBrowseResponse {
  items: Array<Record<string, unknown>>;
  total: number;
  page: number;
  size: number;
  data_type: string;
  label: string;
  domain: string;
  table_name?: string | null;
  columns: CatalogColumnMeta[];
  filters: CatalogFilterMeta[];
}

export interface DomainItem {
  key: string;
  label: string;
}

export interface SyncTask {
  id: number;
  name?: string | null;
  source_id?: number | null;
  data_type: string;
  data_type_label: string;
  schedule_cron?: string | null;
  status: string;
  upstream_task_id?: number | null;
  next_run_at?: string | null;
  tia_api_name?: string | null;
  proposal_id?: number | null;
  source_name?: string | null;
  collect_params?: Record<string, string | number | boolean> | null;
  created_at: string;
  updated_at: string;
}

export interface CollectConfig {
  task_id: number;
  data_type: string;
  api_name?: string | null;
  collect_mode?: string | null;
  collect_pattern?: string | null;
  default_params: Record<string, unknown>;
  task_overrides: Record<string, unknown>;
  effective_params: Record<string, unknown>;
  runtime_keys: string[];
  editable_keys: string[];
  param_hints: Record<string, string>;
}

export interface WorkflowRun {
  id: number;
  workflow_id: number;
  workflow_name: string;
  status: string;
  trigger_type: string;
  job_id?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

export interface NodeRun {
  id: number;
  workflow_run_id: number;
  node_id: string;
  node_type: string;
  label?: string | null;
  status: string;
  message?: string | null;
  result_json?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface WorkflowCollectProfile {
  data_type: string;
  api_name: string;
  batch_mode: string;
  collect_mode: string;
  max_codes_stored?: number | null;
  max_codes_effective: number;
  max_api_calls_per_run: number;
  rotation_enabled: boolean;
  rotation_codes_per_run?: number | null;
  recent_periods?: number | null;
  publish_lag_days?: number | null;
  notes: string[];
}

export interface PlatformJob {
  id: number;
  job_type: string;
  status: string;
  progress: number;
  message?: string | null;
  error?: string | null;
  result?: Record<string, unknown> | null;
}

export interface DataSourceQuota {
  account_points: number;
  max_calls_per_minute: number;
  tier_max_calls_per_minute: number;
  account_points_from_source: boolean;
  max_calls_from_override: boolean;
  env_account_points: number;
}

export interface DataSource {
  id: number;
  name: string;
  provider: string;
  config: {
    token?: string;
    account_points?: number;
    max_calls_per_minute?: number;
  };
  quota?: DataSourceQuota | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface QualityRule {
  id: number;
  name: string;
  rule_type: string;
  threshold?: number | null;
  target_data_type: string;
  is_enabled: boolean;
  created_at: string;
}

export interface QualityReport {
  id: number;
  data_type: string;
  stock_code?: string | null;
  status: string;
  detail_json?: Record<string, unknown> | null;
  created_at: string;
}

export interface PlatformSettings {
  sync_start_date: string;
  sync_type_overrides: Record<string, string>;
  env_sync_start_date: string;
  watch_alert_webhook_url: string | null;
  watch_alert_webhook_secret_masked: string | null;
  watch_alert_webhook_secret_configured: boolean;
  watch_alert_webhook_signature_version: string;
  watch_alert_webhook_active_source: "db" | "env" | "none";
  env_watch_alert_webhook_configured: boolean;
}

export interface UserInfo {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
}

export interface CatalogColumn {
  key: string;
  label: string;
  type: string;
}

export interface DataStandardField {
  api_field: string;
  standard_key?: string | null;
  standard_label?: string | null;
  standard_type?: string | null;
  inferred_type: string;
  status: "matched" | "missing_in_standard" | "extra_in_standard" | "type_mismatch";
  is_unique_key: boolean;
}

export interface DataStandardIndexItem {
  name: string;
  columns: string[];
  unique: boolean;
  purpose: string;
}

export interface NamingCompliance {
  score: number;
  issues: string[];
}

export interface DataStandardSummaryItem {
  api_name: string;
  data_type: string;
  label: string;
  domain: string;
  provider_id?: string;
  table_name?: string;
  doc_id?: number | null;
  doc_url?: string | null;
  is_activated: boolean;
  proposal_id: number;
  proposal_status: string;
  proposal_reason?: string | null;
  probe_status: "configured" | "template" | "unconfigured" | string;
  probe_category?: string | null;
  category?: string | null;
  field_source: string;
  schema_stage: string;
  drift_status?: string;
  last_probe_at?: string | null;
  naming_compliance?: NamingCompliance | null;
  unique_keys: string[];
  indexes?: DataStandardIndexItem[];
  unique_constraint?: { name: string; columns: string[] } | null;
  api_field_count: number;
  standard_field_count: number;
  matched_count: number;
  missing_count: number;
  extra_count: number;
  type_mismatch_count: number;
  coverage_pct: number;
  ddl_ready: boolean;
  ddl_errors: string[];
}

export interface DataStandardDetail extends DataStandardSummaryItem {
  fields: DataStandardField[];
  extra_fields: DataStandardField[];
  field_mappings: Record<string, string>;
}

export interface DataStandardListSummary {
  total: number;
  full_match_count: number;
  partial_match_count: number;
  gap_count: number;
  ddl_ready_count: number;
  schema_ready_count: number;
  activated_count: number;
  proposal_total: number;
  pending_count: number;
  applied_count: number;
  configured_count: number;
  template_count: number;
  unconfigured_count: number;
  drift_count?: number;
}

export interface DriftDetail {
  api_name: string;
  data_type: string;
  drift_status: string;
  last_probe_at?: string | null;
  doc_drift: { has_drift: boolean; missing: string[]; extra: string[] };
  live_drift: { has_drift: boolean; missing: string[]; extra: string[] };
  ddl_drift?: {
    has_drift: boolean;
    table_exists: boolean;
    missing: string[];
    extra: string[];
  } | null;
}

export interface QualitySuggestion {
  rule_type: string;
  target_data_type: string;
  column: string;
  reason: string;
  config_json?: Record<string, unknown>;
}

export interface QualitySuggestionsResponse {
  api_name: string;
  data_type: string;
  suggestions: QualitySuggestion[];
}

export interface DataStandardExportResponse {
  api_name: string;
  data_type: string;
  label: string;
  format: string;
  json_schema?: Record<string, unknown> | null;
  openapi?: Record<string, unknown> | null;
}

export interface DataStandardListResponse {
  items: DataStandardSummaryItem[];
  total: number;
  page: number;
  size: number;
  summary: DataStandardListSummary;
}

export interface SchemaMappingChange {
  api_field: string;
  before?: string | null;
  after?: string | null;
}

export interface SchemaRegistryHint {
  api_name: string;
  registry_registered: boolean;
  heuristic_unique_keys: string[];
  registered_unique_keys?: string[] | null;
  suggested_unique_keys: string[];
  registry_snippet: string;
  registry_file: string;
}

export interface SchemaPlan {
  api_name: string;
  data_type: string;
  table_name: string;
  columns_before: string[];
  columns_after: string[];
  columns_added: string[];
  columns_dropped: string[];
  mapping_changes: SchemaMappingChange[];
  collect_mode_before?: string | null;
  collect_mode_after?: string | null;
  unique_keys_before: string[];
  unique_keys_registry: string[];
  unique_keys_changed: boolean;
  columns_drift: boolean;
  keys_drift: boolean;
  registry_registered: boolean;
  registry_hint: SchemaRegistryHint;
  row_count: number;
  ddl_errors: string[];
  warnings: string[];
  available_modes: string[];
  needs_confirm_risk: boolean;
  has_drift: boolean;
}

export interface SchemaApplyResult {
  api_name: string;
  data_type: string;
  table_name: string;
  modes_applied: string[];
  columns_before: string[];
  columns_after: string[];
  unique_keys_before: string[];
  unique_keys_after: string[];
  collect_mode?: string | null;
  columns_added: string[];
  columns_dropped: string[];
  unique_index_created: boolean;
  browse_indexes_created: string[];
  unique_constraint?: { name: string; columns: string[] } | null;
  sync_task_updated: boolean;
  schedule_cron?: string | null;
  message: string;
}
