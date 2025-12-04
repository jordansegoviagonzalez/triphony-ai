export type LibraryItem = {
  id: string;
  prompt: string;
  createdAt: string;
};

const KEY = "ai_art_studio_library_v1";

function read(): LibraryItem[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(KEY) || "[]") as LibraryItem[];
  } catch {
    return [];
  }
}

function write(items: LibraryItem[]) {
  window.localStorage.setItem(KEY, JSON.stringify(items));
}

export function listLibrary(): LibraryItem[] {
  return read().sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function upsertLibraryItem(item: LibraryItem) {
  const items = read();
  const idx = items.findIndex(x => x.id === item.id);
  if (idx >= 0) items[idx] = item;
  else items.push(item);
  write(items);
}

export function deleteLibraryItem(id: string) {
  write(read().filter(x => x.id !== id));
}
