export type ConfirmationCandidate = {
  id: string;
  title: string;
  seeders: number;
  resolution: string | null;
  size: string | null;
};

export type ConfirmationPayload = {
  summary: string;
  recommended_result_id: string | null;
  results: ConfirmationCandidate[];
  selected_result_id: string | null;
  qb_category: string | null;
  execution_result: Record<string, unknown> | null;
  receipt: Record<string, unknown> | null;
};

export type ChatResponse = {
  session_id: string;
  status: string;
  confirmation_payload: ConfirmationPayload | null;
  receipt: Record<string, unknown> | null;
  error: string | null;
};

export type ConfirmResponse = ChatResponse & {
  messages: string[];
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
