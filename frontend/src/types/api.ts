export type ResourceCandidate = {
  id: string;
  title: string;
  media_type: string;
  year: number | null;
  seeders: number;
  leechers: number;
  discount: string | null;
  imdb: string | null;
  douban: string | null;
  resolution: string | null;
  size: string;
  size_bytes: number | null;
  source: string;
  small_description: string | null;
  subtitle_flags: string[];
  labels_new: string[];
};

export type AgentToolCall = {
  tool: string;
  tool_call_id: string;
  arguments: Record<string, unknown>;
  status: string;
  stats: Record<string, unknown>;
  truncated: boolean;
  observation_stats: Record<string, unknown>;
  gate_result: "allow" | "deny" | "ask_user" | null;
  gate_reason: string | null;
  approval_id: string | null;
  results?: ResourceCandidate[];
  assistant_text?: string;
  reasoning_content?: string | null;
};

export type ApprovalRisk = {
  level: "readonly" | "side_effect" | "destructive";
  summary: string;
};

export type PendingApproval = {
  approval_id: string;
  session_id: string;
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "failed" | "expired";
  reason: string;
  created_at: string;
  expires_at: string;
  decided_at: string | null;
  decision: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  expired_at: string | null;
  authorization?: {
    eligible?: boolean;
    reason?: string;
    policy_id?: string;
    grant_scope_preview?: Record<string, unknown>;
    item_count?: number;
  } | null;
  risk: ApprovalRisk;
};

export type ContextUsage = {
  context_window: number;
  prompt_tokens: number;
  completion_tokens?: number;
  total_tokens?: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  usage_pct?: number;
  cache_hit_rate?: number | null;
};

export type SessionUsage = {
  context_window: number;
  model_calls: number;
  total_tokens: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cache_hit_tokens: number;
  total_cache_miss_tokens: number;
  cache_hit_rate?: number | null;
};

export type ChatResponse = {
  session_id: string;
  status: string;
  message: string;
  results: ResourceCandidate[];
  tool_calls: AgentToolCall[];
  pending_approvals: PendingApproval[];
  error: string | null;
  context_usage: ContextUsage | null;
  session_usage: SessionUsage | null;
};

export type AgentApprovalResponse = {
  session_id: string;
  approval_id: string;
  status: string;
  message: string;
  receipt: Record<string, unknown> | null;
  pending_approvals?: PendingApproval[];
  error: string | null;
  context_usage?: ContextUsage | null;
  session_usage?: SessionUsage | null;
};

export type AgentSessionMessage = {
  role: "user" | "assistant" | "system" | "tool" | "summary";
  content: string;
  timestamp: string | null;
  metadata: Record<string, unknown> | null;
};

export type AgentSessionArchive = {
  id: string;
  created_at: string;
  reason: string;
  messages: AgentSessionMessage[];
  source_message_count?: number;
};

export type AgentSessionDetailResponse = {
  session_id: string;
  created_at: string;
  saved_at: string;
  messages: AgentSessionMessage[];
  archives: AgentSessionArchive[];
  metadata: Record<string, unknown>;
};

export type AgentSessionSummary = {
  session_id: string;
  created_at: string;
  saved_at: string;
  message_count: number;
  archive_count: number;
  metadata: Record<string, unknown>;
};

export type AgentSessionListResponse = {
  sessions: AgentSessionSummary[];
};

export type SessionUpdateRequest = {
  title?: string | null;
};

export type DownloadResponse = {
  status: string;
  receipt: Record<string, unknown> | null;
  error: string | null;
  watch_task_id?: string | null;
};

export type TorrentSummary = {
  hash: string;
  name: string;
  category: string;
  tags: string[];
  state: string;
  progress: number;
  download_speed: number;
  upload_speed: number;
  eta: number;
  save_path: string;
  size: number;
  total_size: number;
};

export type TorrentDetail = TorrentSummary & {
  comment: string;
  total_uploaded: number;
  share_ratio: number;
  creation_date: number;
};

export type TorrentListResponse = {
  items: TorrentSummary[];
};

export type TorrentAction = "pause" | "resume" | "recheck" | "reannounce" | "delete";

export type TorrentActionResponse = {
  ok: boolean;
  status: string;
  qb_hash: string | null;
};

export type HealthResponse = {
  status: string;
};

export type ServiceHealthStatus = "ok" | "unavailable" | "unconfigured" | "error";

export type ServiceHealth = {
  service: string;
  status: ServiceHealthStatus;
  latency_ms: number;
  message: string;
};

export type HealthServicesResponse = {
  status: string;
  services: ServiceHealth[];
};

export type DownloadAuthorizationPolicy = {
  enabled: boolean;
  save_path_prefixes: string[];
  max_items_per_batch: number;
  max_total_items_per_session: number;
  paused_required: boolean;
};

export type TMDBNetworkSettings = {
  enabled: boolean;
  proxy_url: string;
};

export type OrganizationAuthorizationPolicy = {
  background_organization_allowed: boolean;
  allowed_source_path_prefixes: string[];
  destination_root: string;
  allow_delete: boolean;
  allow_overwrite: boolean;
};

export type FreeToppedTorrent = {
  id: string;
  name: string;
  size_bytes: number;
  size_display: string;
  seeders: number;
  leechers: number;
  discount: string | null;
  topping_level: number;
  free_until: string | null;
  category: string;
  imdb: string | null;
  douban: string | null;
};

export type FreeToppedResponse = {
  level2: FreeToppedTorrent[];
  level1: FreeToppedTorrent[];
  total_count: number;
};

// ── Runtime Task types (Task 10/11) ─────────────────────────────

export type TaskSummary = {
  task_id: string;
  kind: string;
  status: string;
  source_session_id: string | null;
  parent_task_id: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type WorkerRunSummary = {
  run_id: string;
  attempt: number;
  status: string;
  started_at: string;
  completed_at: string | null;
};

export type TaskDetail = TaskSummary & {
  child_task_ids: string[];
  max_attempts: number;
  latest_run: WorkerRunSummary | null;
};

export type TaskListResponse = {
  tasks: TaskSummary[];
  total_count: number;
};

export type TaskDetailResponse = {
  task: TaskDetail;
};

export type TaskCancelResponse = {
  task_id: string;
  status: string;
  previous_status: string;
};

export type TaskEventSummary = {
  event_id: string;
  task_id: string;
  source_session_id: string | null;
  kind: string;
  severity: string;
  title: string;
  summary: string;
  created_at: string;
  acknowledged_at: string | null;
};

export type TaskEventListResponse = {
  events: TaskEventSummary[];
  total_count: number;
};

export type TaskEventAcknowledgeResponse = {
  event_id: string;
  status: string;
};
