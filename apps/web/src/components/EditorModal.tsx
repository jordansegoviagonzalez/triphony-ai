"use client";

import { useEffect, useState } from "react";

export function EditorModal(props: {
  title: string;
  initialValue: string;
  open: boolean;
  onClose: () => void;
  onSave: (value: string) => void;
}) {
  const { title, initialValue, open, onClose, onSave } = props;
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    if (open) setValue(initialValue);
  }, [open, initialValue]);

  if (!open) return null;

  return (
    <div className="modalBackdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modalHeader">
          <div className="modalTitle">{title}</div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>

        <textarea
          className="modalTextarea"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Type your edits here…"
        />

        <div className="modalActions">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btnPrimary" onClick={() => onSave(value)}>Save</button>
        </div>
      </div>
    </div>
  );
}
