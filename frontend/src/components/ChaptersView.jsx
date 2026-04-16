const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function ChaptersView({ audiobook, onStartOver }) {
  const {
    title,
    author,
    page_count,
    summary,
    key_points = [],
    chapters = [],
    audio = [],
  } = audiobook;

  // Map audio by index for quick lookup
  const audioByIndex = new Map(audio.map((a) => [a.index, a]));

  return (
    <div className="audiobook-view">
      <div className="book-metadata">
        <h1 className="book-title">{title || 'Your audiobook'}</h1>
        {author && <p className="book-author">by {author}</p>}
        {page_count && <p className="book-pages">{page_count} pages</p>}
      </div>

      {summary && (
        <section className="summary-block">
          <h2>Summary</h2>
          <p className="summary-body">{summary}</p>
        </section>
      )}

      {key_points.length > 0 && (
        <section className="key-points">
          <h3>Key points</h3>
          <ul>
            {key_points.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </section>
      )}

      <section className="chapters-section">
        <h2>Chapters</h2>
        <p className="section-hint">
          {chapters.length} {chapters.length === 1 ? 'chapter' : 'chapters'} · stream or download each track.
        </p>
        {chapters.map((ch, idx) => {
          const num = ch.chapter_number || idx + 1;
          const track = audioByIndex.get(num);
          const url = track ? `${API_BASE}${track.url}` : null;
          return (
            <article key={num} className="chapter-card">
              <div className="chapter-header">
                <span className="chapter-number">CH {String(num).padStart(2, '0')}</span>
                <h3 className="chapter-title">{ch.title || `Chapter ${num}`}</h3>
              </div>
              {ch.summary && <p className="chapter-summary">{ch.summary}</p>}
              {url ? (
                <div className="chapter-audio">
                  <audio controls preload="none" src={url} />
                  <a className="download-link" href={url} download>
                    download
                  </a>
                </div>
              ) : (
                <div className="chapter-audio-missing">
                  Audio not generated for this chapter.
                </div>
              )}
            </article>
          );
        })}
      </section>

      <div className="action-buttons">
        <button className="secondary-button" onClick={onStartOver}>
          Process another book
        </button>
      </div>
    </div>
  );
}
