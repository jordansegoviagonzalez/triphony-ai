import type { Scene, AssetKind } from "@/lib/types";

export const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/+$/, "");

export function artifactUrl(assetId: number) {
  return `${API_BASE}/artifacts/${assetId}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const csrf = typeof document === "undefined"
    ? undefined
    : document.cookie.split("; ").find((item) => item.startsWith("triphony_csrf="))?.split("=")[1];
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(csrf && !["GET", "HEAD", "OPTIONS"].includes(method) ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
      ...(init?.headers || {})
    },
    cache: "no-store"
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      message = body.detail || message;
    } catch {
      // Keep the stable status-based message for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function createScene(prompt: string): Promise<{ scene_id: string }> {
  const out = await request<{ scene_id: string }>(`/scenes`, {
    method: "POST",
    body: JSON.stringify({ prompt })
  });

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
