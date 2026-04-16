import { useEffect, useState } from 'react';
import { getLibrary, getProgress, removeBook, computeBookProgress } from '../services/library';

export default function Library({ onOpen, onNew }) {
  const [books, setBooks] = useState([]);

  const refresh = () => setBooks(getLibrary());
  useEffect(() => { refresh(); }, []);

  const handleDelete = (e, taskId) => {
    e.stopPropagation();
    if (confirm('Remove this book from your library?')) {
      removeBook(taskId);
      refresh();
    }
  };

  if (books.length === 0) {
    return (
      <div className="library-empty">
        <h2>Your library is empty</h2>
        <p>Books you process are saved here locally so you can pick up where you left off.</p>
        <button className="upload-button" onClick={onNew}>Process your first book</button>
      </div>
    );
  }

  return (
    <div className="library">
      <div className="library-header">
        <h2>Your library</h2>
        <button className="secondary-button" onClick={onNew}>+ New book</button>
      </div>
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
