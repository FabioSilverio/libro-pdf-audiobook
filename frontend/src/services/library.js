/**
 * Library persistence — localStorage-based.
 * Stores the list of processed audiobooks and per-book progress (audio
 * playback position per chapter, summary/key-points read flags, last-opened).
 */

const LIBRARY_KEY = 'libro.library.v1';
const PROGRESS_KEY = (taskId) => `libro.progress.v1.${taskId}`;

// ---------- Library list ----------
export function getLibrary() {
  try {
    const raw = localStorage.getItem(LIBRARY_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function saveLibrary(list) {
  try {
    localStorage.setItem(LIBRARY_KEY, JSON.stringify(list));
  } catch (e) {
    console.warn('Library save failed (quota?):', e);
  }
}

/**
 * Add or replace a book in the library.
 * `book` must include: task_id, title, author, created_at, chapters, audio, summary, key_points.
 */
export function upsertBook(book) {
  if (!book?.task_id) return;
  const list = getLibrary();
  const existing = list.findIndex((b) => b.task_id === book.task_id);
  const entry = {
    ...book,
    saved_at: new Date().toISOString(),
  };
  if (existing >= 0) list[existing] = entry;
  else list.unshift(entry);
  // Cap to 50 most recent so we don't balloon localStorage.
  saveLibrary(list.slice(0, 50));
}

export function getBook(taskId) {
  return getLibrary().find((b) => b.task_id === taskId) || null;
}

export function removeBook(taskId) {
  saveLibrary(getLibrary().filter((b) => b.task_id !== taskId));
  try {
    localStorage.removeItem(PROGRESS_KEY(taskId));
  } catch {
    // Ignore storage cleanup failures.
  }
}

// ---------- Per-book progress ----------
export function getProgress(taskId) {
  try {
    const raw = localStorage.getItem(PROGRESS_KEY(taskId));
    if (!raw) return defaultProgress();
    const p = JSON.parse(raw);
    return { ...defaultProgress(), ...p };
  } catch {
    return defaultProgress();
  }
}

function defaultProgress() {
  return {
    summaryRead: false,
    keyPointsRead: false,
    chaptersRead: {},   // { [chapterNumber]: true }
    audio: {},          // { [chapterNumber]: { time: seconds, duration, done } }
    lastOpened: null,
  };
}

export function saveProgress(taskId, patch) {
  const current = getProgress(taskId);
  const merged = { ...current, ...patch };
  try {
    localStorage.setItem(PROGRESS_KEY(taskId), JSON.stringify(merged));
  } catch (e) {
    console.warn('Progress save failed:', e);
  }
  return merged;
}

export function updateChapterAudio(taskId, chapterNumber, data) {
  const current = getProgress(taskId);
  const audio = { ...current.audio, [chapterNumber]: { ...(current.audio[chapterNumber] || {}), ...data } };
  return saveProgress(taskId, { audio });
}

export function markChapterRead(taskId, chapterNumber, read = true) {
  const current = getProgress(taskId);
  const chaptersRead = { ...current.chaptersRead, [chapterNumber]: read };
  return saveProgress(taskId, { chaptersRead });
}

export function markLastOpened(taskId) {
  return saveProgress(taskId, { lastOpened: new Date().toISOString() });
}

// ---------- Export / Import ----------

/**
 * Export entire library + per-book progress as a JSON blob.
 * Returns a Blob suitable for download.
 */
export function exportLibrary() {
  const books = getLibrary();
  const progress = {};
  for (const b of books) {
    progress[b.task_id] = getProgress(b.task_id);
  }
  const payload = { version: 1, exported_at: new Date().toISOString(), books, progress };
  return new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
}

/**
 * Import library from a JSON blob (merges with existing).
 * Returns the number of books imported.
 */
export function importLibrary(jsonStr) {
  const data = JSON.parse(jsonStr);
  if (!data?.books || !Array.isArray(data.books)) {
    throw new Error('Invalid library file');
  }
  let count = 0;
  for (const book of data.books) {
    if (book?.task_id) {
      upsertBook(book);
      count++;
    }
  }
  // Restore per-book progress if present
  if (data.progress && typeof data.progress === 'object') {
    for (const [taskId, prog] of Object.entries(data.progress)) {
      if (prog && typeof prog === 'object') {
        saveProgress(taskId, prog);
      }
    }
  }
  return count;
}

/**
 * Compute a 0-1 progress score for a book based on audio played + chapters read.
 */
export function computeBookProgress(book, progress) {
  if (!book?.chapters?.length) return 0;
  const total = book.chapters.length;
  let score = 0;
  for (const ch of book.chapters) {
    const n = ch.chapter_number || ch.number;
    const readW = progress.chaptersRead?.[n] ? 0.5 : 0;
    const a = progress.audio?.[n];
    let audioW = 0;
    if (a?.done) audioW = 0.5;
    else if (a?.duration && a?.time) audioW = 0.5 * Math.min(1, a.time / a.duration);
    score += readW + audioW;
  }
  return Math.min(1, score / total);
}
