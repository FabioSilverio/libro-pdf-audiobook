import { useEffect, useState, useRef } from 'react';
import { getLibrary, getProgress, removeBook, upsertBook, computeBookProgress, exportLibrary, importLibrary } from '../services/library';
import { resummarizeAudiobook } from '../services/api';

export default function Library({ onOpen, onNew }) {
  const [books, setBooks] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState('');
  const importRef = useRef(null);

  const refresh = () => setBooks(getLibrary());
  useEffect(() => { refresh(); }, []);

  const handleDelete = (e, taskId) => {
    e.stopPropagation();
    if (confirm('Remove this book from your library?')) {
      removeBook(taskId);
      refresh();
    }
  };

  const handleRefreshAll = async () => {
    const all = getLibrary();
    if (all.length === 0) return;
    if (!confirm(
      `Re-generate AI summaries for ${all.length} book(s)? ` +
      `This may take a minute per book.`
    )) return;
    setRefreshing(true);
    let ok = 0, fail = 0;
    for (let i = 0; i < all.length; i++) {
      const b = all[i];
      setRefreshMsg(`Refreshing ${i + 1}/${all.length}: ${b.title || b.task_id}`);
      try {
        const fresh = await resummarizeAudiobook(b.task_id, 'medium');
        // Preserve library-saved fields (saved_at), update the AI bits.
        upsertBook({ ...b, ...fresh });
        ok++;
      } catch (err) {
        console.warn('resummarize failed for', b.task_id, err);
        fail++;
      }
    }
    setRefreshing(false);
    setRefreshMsg(
      `Done. ${ok} refreshed${fail ? `, ${fail} failed (source text missing — re-upload those)` : ''}.`
    );
    refresh();
    setTimeout(() => setRefreshMsg(''), 6000);
  };

  const handleExport = () => {
    const blob = exportLibrary();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `libro-library-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const count = importLibrary(reader.result);
        setRefreshMsg(`Imported ${count} book(s) successfully.`);
        refresh();
        setTimeout(() => setRefreshMsg(''), 5000);
      } catch (err) {
        setRefreshMsg(`Import failed: ${err.message}`);
        setTimeout(() => setRefreshMsg(''), 5000);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  if (books.length === 0) {
    return (
      <div className="library-empty">
        <h2>Your library is empty</h2>
        <p>Books you process are saved here locally so you can pick up where you left off.</p>
        <button className="upload-button" onClick={onNew}>Process your first book</button>
        <div className="library-import-hint">
          <button className="text-button" onClick={() => importRef.current?.click()}>
            Import from file
          </button>
          <input ref={importRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
        </div>
      </div>
    );
  }

  return (
    <div className="library">
      <div className="library-header">
        <h2>Your library</h2>
        <div className="library-header-actions">
          <button
            className="secondary-button"
            onClick={handleRefreshAll}
            disabled={refreshing}
            title="Regenerate summaries and key points for every book"
          >
            {refreshing ? 'Refreshing…' : '↻ Refresh summaries'}
          </button>
          <button className="secondary-button" onClick={handleExport} title="Export library as JSON">
            ↓ Export
          </button>
          <button className="secondary-button" onClick={() => importRef.current?.click()} title="Import library from JSON">
            ↑ Import
          </button>
          <input ref={importRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
          <button className="secondary-button" onClick={onNew}>+ New book</button>
        </div>
      </div>
      {refreshMsg && (
        <div className="library-refresh-status">{refreshMsg}</div>
      )}
      <div className="library-grid">
        {books.map((b) => {
          const prog = getProgress(b.task_id);
          const pct = Math.round(computeBookProgress(b, prog) * 100);
          const when = new Date(b.saved_at || b.created_at || Date.now()).toLocaleDateString();
          return (
            <article
              key={b.task_id}
              className="library-card"
              onClick={() => onOpen(b.task_id)}
            >
              <div className="library-card-head">
                <h3>{b.title || 'Untitled book'}</h3>
                <button
                  className="library-delete"
                  onClick={(e) => handleDelete(e, b.task_id)}
                  aria-label="Remove"
                  title="Remove from library"
                >✕</button>
              </div>
              {b.author && <p className="library-author">{b.author}</p>}
              <div className="library-meta">
                <span>{b.chapters?.length || 0} chapters</span>
                <span>·</span>
                <span>{when}</span>
              </div>
              <div className="library-progress">
                <div className="library-progress-bar">
                  <div className="library-progress-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="library-progress-text">{pct}%</span>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
