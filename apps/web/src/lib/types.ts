export type AssetKind = "narrative" | "visual" | "soundtrack";
export type AssetStatus = "pending" | "running" | "succeeded" | "failed";
export type SceneStatus = "queued" | "running" | "done" | "failed";

export type Asset = {
  id: number;
  asset_type: AssetKind;
  version: number;
  status: AssetStatus;
  content_text?: string | null;
  artifact_path?: string | null;
  error?: string | null;
};

export type Scene = {
  scene_id: string;
  prompt: string;
  status: SceneStatus;
  created_at: string;
  assets: Asset[];
};
