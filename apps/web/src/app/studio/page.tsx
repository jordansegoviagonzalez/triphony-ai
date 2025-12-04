"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Scene, Asset } from "@/lib/types";
import { artifactUrl, createScene, getScene, regenerate, sceneEventsUrl } from "@/lib/api";
import { EditorModal } from "@/components/EditorModal";

function useQueryParam(name: string) {
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setValue(params.get(name));
  }, [name]);
  return value;
}

function pick(assets: Asset[], type: Asset["asset_type"]) {
  return assets.find(a => a.asset_type === type);
}

export default function StudioPage() {
  const existingId = useQueryParam("scene");
  const [prompt, setPrompt] = useState("");
  const [scene, setScene] = useState<Scene | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");

  const [editNarrativeOpen, setEditNarrativeOpen] = useState(false);
  const [editSoundOpen, setEditSoundOpen] = useState(false);

  const esRef = useRef<EventSource | null>(null);

  async function load(sceneId: string) {
    const s = await getScene(sceneId);
    setScene(s);
    setPrompt(s.prompt);
    return s;
  }

  useEffect(() => {
    if (!existingId) return;
    load(existingId).catch(() => null);
  }, [existingId]);

  useEffect(() => () => esRef.current?.close(), []);

  const narrative = useMemo(() => (scene ? pick(scene.assets, "narrative") : undefined), [scene]);
  const visual = useMemo(() => (scene ? pick(scene.assets, "visual") : undefined), [scene]);
  const soundtrack = useMemo(() => (scene ? pick(scene.assets, "soundtrack") : undefined), [scene]);

  async function onGenerate() {
    const p = prompt.trim();
    if (p.length < 3) return;

    setBusy(true);
    setStatus("Generating…");
    try {
      const out = await createScene(p);
      const s = await load(out.scene_id);

      window.history.replaceState({}, "", `/studio?scene=${encodeURIComponent(out.scene_id)}`);

      esRef.current?.close();
      esRef.current = new EventSource(sceneEventsUrl(out.scene_id));
      esRef.current.addEventListener("scene.update", (ev) => {
        try {
          const next = JSON.parse((ev as MessageEvent).data) as Scene;
          setScene(next);
        } catch {}
      });
      esRef.current.addEventListener("scene.completed", async () => {
        const final = await load(out.scene_id);
        setStatus(final.status === "done" ? "Done." : "Completed.");
        esRef.current?.close();
      });

    } finally {
      setBusy(false);
    }
  }

  async function onRegenerateClip() {
    if (!scene) return;
    setBusy(true);
    setStatus("Regenerating clip…");
    try {
      // This button is the “producer” action: refresh all assets together.
      await Promise.all([
        regenerate(scene.scene_id, "narrative"),
        regenerate(scene.scene_id, "visual"),
        regenerate(scene.scene_id, "soundtrack")
      ]);
      await load(scene.scene_id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="shell">
      <div className="studioHeader">
        <div style={{ textAlign: "center" }}>
          <div className="logoRow">
          <img
             src="/branding/Triphony_solo 1.png"
              alt="Triphony"
              style={{ width: 400, height: 180, display: "block" }} // ↑ bump size here
           />
        </div>
          <div className="subtitle">The AI Art Studio</div>
        </div>
      </div>

      <div className="cardFrame">
        <div className="studioGrid">
          {/* Soundtrack */}
          <div className="panel">
            <div className="panelTitle cyan">Soundtrack</div>
            <div className="panelBody">
              {soundtrack?.artifact_path ? (
                <audio controls src={artifactUrl(soundtrack.artifact_path)} style={{ width: "100%" }} />
              ) : (
                <div className="placeholder">Waiting for audio…</div>
              )}
            </div>

            <button className="btn" disabled={!scene || busy} onClick={() => setEditSoundOpen(true)}>
              Edit Soundtrack
            </button>
          </div>

          {/* Visual */}
          <div className="panel">
            <div className="panelTitle pink">Visual</div>
            <div className="panelBody">
              {visual?.artifact_path ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="visualImg" src={artifactUrl(visual.artifact_path)} alt="visual concept frame" />
              ) : (
                <div className="placeholder">Waiting for visual…</div>
              )}
            </div>

            <button className="btn btnPrimary" disabled={!scene || busy} onClick={onRegenerateClip}>
              Regenerate Cinematic Clip
            </button>
          </div>

          {/* Narrative */}
          <div className="panel">
            <div className="panelTitle cyan">Narrative</div>
            <div className="panelBody" style={{ placeItems: "start" }}>
              <pre className="narrativeText">{narrative?.content_text ?? "Waiting for narrative…"}</pre>
            </div>

            <button className="btn" disabled={!scene || busy} onClick={() => setEditNarrativeOpen(true)}>
              Edit Narrative
            </button>
          </div>
        </div>

        <div className="promptBar">
          <input
            className="promptInput"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe your scene..."
          />
          <button className="btn btnPrimary" onClick={onGenerate} disabled={busy || prompt.trim().length < 3}>
            {busy ? "Working…" : "Generate Scene"}
          </button>
        </div>

        <div style={{ marginTop: 10, color: "rgba(255,255,255,.62)", fontSize: 12 }}>
          {status ? status : "NOTE: Postgres and Redis are configured with Docker for the full pipeline."}
        </div>
      </div>

      <EditorModal
        title="Edit Narrative"
        open={editNarrativeOpen}
        initialValue={narrative?.content_text || ""}
        onClose={() => setEditNarrativeOpen(false)}
        onSave={async (val) => {
          // UI-only edit for now (pipeline still stays authoritative).
          // In production you’d add a writeback endpoint.
          setEditNarrativeOpen(false);
          if (!scene) return;
          const next = { ...scene };
          const a = next.assets.find(x => x.asset_type === "narrative");
          if (a) a.content_text = val;
          setScene(next);
        }}
      />

      <EditorModal
        title="Edit Soundtrack (notes)"
        open={editSoundOpen}
        initialValue={"Lo-fi noir, slow pulse, rainy alley vibe"}
        onClose={() => setEditSoundOpen(false)}
        onSave={async () => {
          setEditSoundOpen(false);
          // Notes can be wired into real provider prompts later.
        }}
      />
    </section>
  );
}
