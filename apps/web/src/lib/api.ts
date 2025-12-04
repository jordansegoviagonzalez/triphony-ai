import type { Scene, AssetKind } from "@/lib/types";
import { upsertLibraryItem } from "@/lib/libraryStore";

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/+$/, "");

export function artifactUrl(path: string) {
  const u = new URL(`${API_BASE}/artifacts`);
  u.searchParams.set("path", path);
  return u.toString();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });

  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as T;
}

export async function createScene(prompt: string): Promise<{ scene_id: string }> {
  const out = await request<{ scene_id: string }>(`/scenes`, {
    method: "POST",
    body: JSON.stringify({ prompt })
  });

  upsertLibraryItem({ id: out.scene_id, prompt, createdAt: new Date().toISOString() });
  return out;
}

export async function getScene(sceneId: string): Promise<Scene> {
  return request<Scene>(`/scenes/${encodeURIComponent(sceneId)}`);
}

export async function listScenes(): Promise<Scene[]> {
  return request<Scene[]>(`/scenes`);
}

export async function regenerate(sceneId: string, assetType: AssetKind): Promise<void> {
  await request<{ ok: true }>(`/scenes/${encodeURIComponent(sceneId)}/regenerate`, {
    method: "POST",
    body: JSON.stringify({ asset_type: assetType })
  });
}

export function sceneEventsUrl(sceneId: string) {
  return `${API_BASE}/scenes/${encodeURIComponent(sceneId)}/events`;
}
