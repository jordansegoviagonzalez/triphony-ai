export type AssetKind = "narrative" | "visual" | "soundtrack";
export type AssetStatus = "pending" | "running" | "succeeded" | "failed";
export type SceneStatus = "queued" | "running" | "done" | "failed";
export type WorkflowState =
  | "queued" | "planning" | "generating" | "technical_qa" | "agent_qa"
  | "regenerating" | "assembling" | "final_qa" | "completed" | "failed" | "cancelled";

export type Asset = {
  id: number;
  asset_type: AssetKind;
  version: number;
  status: AssetStatus;
  content_text?: string | null;
  artifact_url?: string | null;
  mime_type?: string | null;
  error?: string | null;
};

export type Scene = {
  scene_id: string;
  prompt: string;
  status: SceneStatus;
  created_at: string;
  assets: Asset[];
  workflow_state: WorkflowState;
  final_render?: {
    id: string;
    version: number;
    status: "pending" | "succeeded" | "failed";
    artifact_url?: string | null;
    mime_type: string;
    duration_ms?: number | null;
  } | null;
};
