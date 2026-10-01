// 히스토리는 기기에만 저장한다(서버 비저장 원칙, PRD F-HIST-01).
const DB_NAME = "talksoft";
const STORE = "history";
const DB_VERSION = 1;
export const HISTORY_LIMIT = 500;

export type HistoryKind = "tone_transform" | "reply_interpret";

export interface HistoryItem {
  id: string;
  kind: HistoryKind;
  createdAt: string;
  /** 같은 밀리초에 저장돼도 순서가 정해지도록 하는 단조 증가 값 */
  seq: number;
  context?: string;
  draft?: string;
  persona?: string;
  targetLang?: string;
  result: unknown;
  pinned: boolean;
}

let lastSeq = 0;
function nextSeq(): number {
  lastSeq = Math.max(lastSeq + 1, Date.now() * 1000);
  return lastSeq;
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function open(): Promise<IDBDatabase> {
  const req = indexedDB.open(DB_NAME, DB_VERSION);
  req.onupgradeneeded = () => {
    const store = req.result.createObjectStore(STORE, { keyPath: "id" });
    store.createIndex("createdAt", "createdAt");
  };
  return request(req);
}

export async function listHistory(): Promise<HistoryItem[]> {
  const db = await open();
  try {
    const items = await request(db.transaction(STORE).objectStore(STORE).getAll());
    return (items as HistoryItem[]).sort((a, b) => b.seq - a.seq);
  } finally {
    db.close();
  }
}

export async function addHistory(
  item: Omit<HistoryItem, "id" | "createdAt" | "seq" | "pinned">,
): Promise<HistoryItem> {
  const full: HistoryItem = {
    ...item,
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    seq: nextSeq(),
    pinned: false,
  };
  const db = await open();
  try {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    store.put(full);
    // 한도를 넘으면 고정하지 않은 오래된 항목부터 지운다.
    const all = (await request(store.getAll())) as HistoryItem[];
    const excess = all.length - HISTORY_LIMIT;
    if (excess > 0) {
      all
        .filter((h) => !h.pinned)
        .sort((a, b) => a.seq - b.seq)
        .slice(0, excess)
        .forEach((h) => store.delete(h.id));
    }
    await done(tx);
    return full;
  } finally {
    db.close();
  }
}

export async function setPinned(id: string, pinned: boolean): Promise<void> {
  const db = await open();
  try {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const item = (await request(store.get(id))) as HistoryItem | undefined;
    if (item) store.put({ ...item, pinned });
    await done(tx);
  } finally {
    db.close();
  }
}

export async function deleteHistory(id: string): Promise<void> {
  const db = await open();
  try {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    await done(tx);
  } finally {
    db.close();
  }
}

export async function clearHistory(): Promise<void> {
  const db = await open();
  try {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).clear();
    await done(tx);
  } finally {
    db.close();
  }
}
