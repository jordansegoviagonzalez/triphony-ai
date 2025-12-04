"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { deleteLibraryItem, listLibrary, type LibraryItem } from "@/lib/libraryStore";

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([]);

  function refresh() {
    setItems(listLibrary());
  }

  useEffect(() => refresh(), []);

  return (
    <section className="shell">
      <div className="rowBetween">
        <div>
          <h1 className="h1">Library</h1>
          <p className="p">Saved scenes you’ve generated.</p>
        </div>
        <Link className="btn btnPrimary" href="/studio">New Scene</Link>
      </div>

      {items.length === 0 ? (
        <p className="p">No scenes yet. Create one in Studio.</p>
      ) : (
        <div className="list">
          {items.map((x) => (
            <div key={x.id} className="listRow">
              <div>
                <div className="listTitle">{x.prompt}</div>
                <div className="listMeta">{new Date(x.createdAt).toLocaleString()}</div>
              </div>

              <div className="row">
                <Link className="btn" href={`/studio?scene=${encodeURIComponent(x.id)}`}>Open</Link>
                <button
                  className="btn btnDanger"
                  onClick={() => {
                    deleteLibraryItem(x.id);
                    refresh();
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
