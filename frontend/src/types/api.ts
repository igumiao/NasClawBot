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

export type ChatResponse = {
  session_id: string;
  status: string;
  message: string;
  results: ResourceCandidate[];
  tool_calls: AgentToolCall[];
  pending_approvals: PendingApproval[];
  error: string | null;
};

export type AgentApprovalResponse = {
  session_id: string;
  approval_id: string;
  status: string;
  message: string;
  receipt: Record<string, unknown> | null;
  pending_approvals?: PendingApproval[];
  error: string | null;
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
  categories: string[];
  save_path_prefixes: string[];
  max_items_per_batch: number;
  max_total_items_per_session: number;
  paused_required: boolean;
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
