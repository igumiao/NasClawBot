export type ResourceCandidate = {
  id: string;
  title: string;
  media_type: string;
  year: number | null;
  seeders: number;
  resolution: string | null;
  size: string;
  size_bytes: number | null;
  source: string;
};

export type ChatResponse = {
  session_id: string;
  status: string;
  message: string;
  results: ResourceCandidate[];
  tool_calls: Array<Record<string, unknown>>;
  error: string | null;
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
