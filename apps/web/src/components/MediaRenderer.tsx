"use client";

import type { Asset } from "@/lib/types";
import { artifactUrl } from "@/lib/api";

export function MediaRenderer({ asset }: { asset: Asset | undefined }) {
  if (!asset) return <div className="placeholder">Waiting for asset…</div>;
  if (asset.status === "pending" || asset.status === "running") {
    return <div className="placeholder">{asset.status === "pending" ? "Queued…" : "Processing…"}</div>;
  }
  if (asset.status === "failed") {
    return <div className="errorBanner">Generation failed: {asset.error || "Unknown error"}</div>;
  }

  if (asset.asset_type === "narrative") {
    return <pre className="narrativeText">{asset.content_text || "No narrative was returned."}</pre>;
  }

  if (!asset.artifact_url) {
    return <div className="placeholder">Completed without a deliverable.</div>;
  }

  const source = artifactUrl(asset.id);
  if (asset.mime_type?.startsWith("image/")) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="visualImg" src={source} alt="Mock visual asset" />;
  }
  if (asset.mime_type?.startsWith("video/") || (asset.asset_type === "visual" && !asset.mime_type)) {
    return <video className="visualVideo" controls preload="metadata" src={source} />;
  }
  if (asset.mime_type?.startsWith("audio/") || asset.asset_type === "soundtrack") {
    return <audio controls src={source} style={{ width: "100%" }} />;
  }
  return <div className="placeholder">Unsupported media type.</div>;
}
