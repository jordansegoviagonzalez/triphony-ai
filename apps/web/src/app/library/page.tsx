"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listScenes } from "@/lib/api";
import type { Scene } from "@/lib/types";

export default function LibraryPage() {
  const [items, setItems] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void listScenes()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load library."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="shell">
      <div className="rowBetween">
        <div>
          <h1 className="h1">Library</h1>
          <p className="p">Saved scenes you’ve generated.</p>
        </div>
        <Link className="btn btnPrimary" href="/studio">New Scene</Link>
      </div>

      {loading ? (
        <p className="p">Loading library…</p>
      ) : error ? (
        <div className="errorBanner">{error}</div>
      ) : items.length === 0 ? (
        <p className="p">No scenes yet. Create one in Studio.</p>
      ) : (
        <div className="list">
          {items.map((x) => (
            <div key={x.scene_id} className="listRow">
              <div>
                <div className="listTitle">{x.prompt}</div>
                <div className="listMeta">{new Date(x.created_at).toLocaleString()} · {x.status}</div>
              </div>

              <div className="row">
                <Link className="btn" href={`/studio?scene=${encodeURIComponent(x.scene_id)}`}>Open</Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
