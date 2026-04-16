import { useEffect, useRef, useState } from 'react';
import {
  getProgress,
  saveProgress,
  updateChapterAudio,
  markChapterRead,
  markLastOpened,
  computeBookProgress,
} from '../services/library';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function ChaptersView({ audiobook, onStartOver, onBackToLibrary }) {
  const {
    task_id,
    title,
    author,
    page_count,
    summary,
    key_points = [],
    chapters = [],
    audio = [],
  } = audiobook;

  const [progress, setProgress] = useState(() => getProgress(task_id));

  useEffect(() => {
    markLastOpened(task_id);
  }, [task_id]);

  const overallPct = Math.round(computeBookProgress(audiobook, progress) * 100);

  const audioByIndex = new Map(audio.map((a) => [a.index, a]));

  const toggleRead = (ch) => {
    const n = ch.chapter_number;
    setProgress(markChapterRead(task_id, n, !progress.chaptersRead?.[n]));
  };

  const toggleSummaryRead = () => {
    setProgress(saveProgress(task_id, { summaryRead: !progress.summaryRead }));
  };

  const toggleKeyPointsRead = () => {
    setProgress(saveProgress(task_id, { keyPointsRead: !progress.keyPointsRead }));
  };

  return (
    <div className="audiobook-view">
      {onBackToLibrary && (
        <button className="back-link" onClick={onBackToLibrary}>← Library</button>
      )}

      <div className="book-metadata">
        <h1 className="book-title">{title || 'Your audiobook'}</h1>
        {author && <p className="book-author">by {author}</p>}
        {page_count && <p className="book-pages">{page_count} pages</p>}
        <div className="book-overall-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${overallPct}%` }} />
          </div>
          <span className="book-overall-text">{overallPct}% complete</span>
        </div>
      </div>

      {summary && (
        <section className={`summary-block ${progress.summaryRead ? 'is-read' : ''}`}>
          <div className="block-head">
            <h2>Summary</h2>
            <label className="read-toggle">
              <input type="checkbox" checked={!!progress.summaryRead} onChange={toggleSummaryRead} />
              <span>Read</span>
            </label>
          </div>
          <p className="summary-body">{summary}</p>
        </section>
      )}

      {key_points.length > 0 && (
        <section className={`key-points ${progress.keyPointsRead ? 'is-read' : ''}`}>
          <div className="block-head">
            <h3>Key points</h3>
            <label className="read-toggle">
              <input type="checkbox" checked={!!progress.keyPointsRead} onChange={toggleKeyPointsRead} />
              <span>Read</span>
            </label>
          </div>
          <ul>
            {key_points.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </section>
      )}

      <section className="chapters-section">
        <h2>Chapters</h2>
        <p className="section-hint">
          {chapters.length} {chapters.length === 1 ? 'chapter' : 'chapters'} · progress saved automatically.
        </p>
        {chapters.map((ch, idx) => {
          const num = ch.chapter_number || idx + 1;
          const track = audioByIndex.get(num);
          const url = track ? `${API_BASE}${track.url}` : null;
          const isRead = !!progress.chaptersRead?.[num];
          const saved = progress.audio?.[num] || {};
          return (
            <ChapterCard
              key={num}
              chapter={ch}
              number={num}
              audioUrl={url}
              isRead={isRead}
              savedAudio={saved}
              taskId={task_id}
              onToggleRead={() => toggleRead(ch)}
              onAudioProgress={(data) => {
                setProgress(updateChapterAudio(task_id, num, data));
              }}
            />
          );
        })}
      </section>

      <div className="action-buttons">
        {onBackToLibrary && (
          <button className="secondary-button" onClick={onBackToLibrary}>
            Back to library
          </button>
        )}
        <button className="secondary-button" onClick={onStartOver}>
          Process another book
        </button>
      </div>
    </div>
  );
}

function ChapterCard({
  chapter, number, audioUrl, isRead, savedAudio, onToggleRead, onAudioProgress,
}) {
  const audioRef = useRef(null);
  const lastSavedTimeRef = useRef(0);
  const [restored, setRestored] = useState(false);

  // Restore playback position once metadata is loaded
  useEffect(() => {
    const el = audioRef.current;
    if (!el || restored) return;
    const restore = () => {
      if (savedAudio.time && savedAudio.time < (el.duration || Infinity) - 2) {
        el.currentTime = savedAudio.time;
      }
      setRestored(true);
    };
    if (el.readyState >= 1) restore();
    else el.addEventListener('loadedmetadata', restore, { once: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  const handleTimeUpdate = (e) => {
    const el = e.currentTarget;
    const now = el.currentTime;
    if (Math.abs(now - lastSavedTimeRef.current) >= 3) {
      lastSavedTimeRef.current = now;
      onAudioProgress({ time: now, duration: el.duration || 0 });
    }
  };

  const handleEnded = (e) => {
    onAudioProgress({
      time: e.currentTarget.duration || 0,
      duration: e.currentTarget.duration || 0,
      done: true,
    });
  };

  const pct = savedAudio.duration
    ? Math.min(100, Math.round((savedAudio.time / savedAudio.duration) * 100))
    : 0;

  return (
    <article className={`chapter-card ${isRead ? 'is-read' : ''}`}>
      <div className="chapter-header">
        <span className="chapter-number">CH {String(number).padStart(2, '0')}</span>
        <h3 className="chapter-title">{chapter.title || `Chapter ${number}`}</h3>
        <label className="read-toggle">
          <input type="checkbox" checked={isRead} onChange={onToggleRead} />
          <span>Read</span>
        </label>
      </div>
      {chapter.summary && <p className="chapter-summary">{chapter.summary}</p>}
      {audioUrl ? (
        <div className="chapter-audio">
          <audio
            ref={audioRef}
            controls
            preload="metadata"
            src={audioUrl}
            onTimeUpdate={handleTimeUpdate}
            onEnded={handleEnded}
          />
          {savedAudio.duration > 0 && (
            <span className="chapter-listen-pct" title="Audio progress">
              {savedAudio.done ? '✓' : `${pct}%`}
            </span>
          )}
          <a className="download-link" href={audioUrl} download>download</a>
        </div>
      ) : (
        <div className="chapter-audio-missing">
          Audio not generated for this chapter.
        </div>
      )}
    </article>
  );
}
