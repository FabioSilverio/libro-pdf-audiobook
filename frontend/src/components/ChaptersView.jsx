import { useEffect, useMemo, useRef, useState } from 'react';
import { getChapterText } from '../services/api';
import {
  getProgress,
  saveProgress,
  updateChapterAudio,
  markChapterRead,
  markLastOpened,
  computeBookProgress,
} from '../services/library';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function paragraphsFromText(text) {
  return text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((part) => part.replace(/\n/g, ' ').trim())
    .filter(Boolean);
}

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

  const audioRef = useRef(null);
  const lastSavedTimeRef = useRef(0);
  const [progress, setProgress] = useState(() => getProgress(task_id));
  const [activeChapter, setActiveChapter] = useState(() => {
    const saved = getProgress(task_id);
    const firstUnfinished = chapters.find((ch, idx) => {
      const n = ch.chapter_number || idx + 1;
      return !saved.audio?.[n]?.done;
    });
    return firstUnfinished?.chapter_number || chapters[0]?.chapter_number || 1;
  });
  const [chapterText, setChapterText] = useState('');
  const [textState, setTextState] = useState('idle');
  const [textError, setTextError] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  /** True from Play click until the browser has enough of the (server-generated) file to start playback. */
  const [isAudioPreparing, setIsAudioPreparing] = useState(false);
  const [playback, setPlayback] = useState(() => {
    const saved = getProgress(task_id);
    const first = saved.audio?.[activeChapter] || {};
    return { time: first.time || 0, duration: first.duration || 0 };
  });

  const audioByIndex = useMemo(() => new Map(audio.map((a) => [a.index, a])), [audio]);
  const activeIndex = Math.max(0, chapters.findIndex((ch, idx) => (ch.chapter_number || idx + 1) === activeChapter));
  const active = chapters[activeIndex] || chapters[0];
  const activeNumber = active?.chapter_number || activeIndex + 1 || 1;
  const activeAudio = audioByIndex.get(activeNumber);
  const audioUrl = activeAudio ? `${API_BASE}${activeAudio.url}` : null;
  const savedAudio = progress.audio?.[activeNumber] || {};
  const overallPct = Math.round(computeBookProgress(audiobook, progress) * 100);
  const chapterPct = savedAudio.duration
    ? Math.min(100, Math.round((savedAudio.time / savedAudio.duration) * 100))
    : 0;

  useEffect(() => {
    markLastOpened(task_id);
  }, [task_id]);

  useEffect(() => {
    let cancelled = false;

    getChapterText(task_id, activeNumber)
      .then((data) => {
        if (cancelled) return;
        setChapterText(data.text || '');
        setTextState('ready');
      })
      .catch((err) => {
        if (cancelled) return;
        setTextError(err.message || 'Could not load this chapter text.');
        setTextState('error');
      });

    return () => {
      cancelled = true;
    };
  }, [task_id, activeNumber]);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    lastSavedTimeRef.current = savedAudio.time || 0;

    const restore = () => {
      if (savedAudio.time && savedAudio.time < (el.duration || Infinity) - 2) {
        el.currentTime = savedAudio.time;
      }
    };

    if (el.readyState >= 1) restore();
    else el.addEventListener('loadedmetadata', restore, { once: true });
  }, [activeNumber, audioUrl, savedAudio.time]);

  const selectChapter = (number) => {
    const nextSaved = progress.audio?.[number] || {};
    setIsPlaying(false);
    setIsAudioPreparing(false);
    setPlayback({ time: nextSaved.time || 0, duration: nextSaved.duration || 0 });
    setTextState('loading');
    setTextError('');
    setChapterText('');
    setActiveChapter(number);
  };

  const toggleRead = (number) => {
    setProgress(markChapterRead(task_id, number, !progress.chaptersRead?.[number]));
  };

  const toggleSummaryRead = () => {
    setProgress(saveProgress(task_id, { summaryRead: !progress.summaryRead }));
  };

  const toggleKeyPointsRead = () => {
    setProgress(saveProgress(task_id, { keyPointsRead: !progress.keyPointsRead }));
  };

  const saveAudioProgress = (data) => {
    setProgress(updateChapterAudio(task_id, activeNumber, data));
  };

  const togglePlayback = async () => {
    const el = audioRef.current;
    if (!el || !audioUrl) return;

    // Cancel while the server is still generating / the stream is opening.
    if (isAudioPreparing) {
      el.pause();
      setIsAudioPreparing(false);
      setIsPlaying(false);
      return;
    }

    if (el.paused) {
      setIsAudioPreparing(true);
      try {
        await el.play();
      } catch {
        setIsAudioPreparing(false);
        setIsPlaying(false);
      }
    } else {
      el.pause();
      setIsAudioPreparing(false);
      setIsPlaying(false);
    }
  };

  const handleSeek = (e) => {
    const el = audioRef.current;
    const next = Number(e.target.value);
    if (!el || Number.isNaN(next)) return;
    el.currentTime = next;
    setPlayback((current) => ({ ...current, time: next }));
    saveAudioProgress({ time: next, duration: el.duration || playback.duration || 0 });
  };

  const handleTimeUpdate = (e) => {
    const el = e.currentTarget;
    const now = el.currentTime;
    if (now > 0.15) setIsAudioPreparing(false);
    setPlayback({ time: now, duration: el.duration || 0 });
    if (Math.abs(now - lastSavedTimeRef.current) >= 3) {
      lastSavedTimeRef.current = now;
      saveAudioProgress({ time: now, duration: el.duration || 0 });
    }
  };

  const handleEnded = (e) => {
    setIsPlaying(false);
    setIsAudioPreparing(false);
    saveAudioProgress({
      time: e.currentTarget.duration || 0,
      duration: e.currentTarget.duration || 0,
      done: true,
    });
    setProgress(markChapterRead(task_id, activeNumber, true));

    const next = chapters[activeIndex + 1];
    if (next) {
      const nextNumber = next.chapter_number || activeIndex + 2;
      setTextState('loading');
      setTextError('');
      setChapterText('');
      const nextSaved = progress.audio?.[nextNumber] || {};
      setPlayback({ time: nextSaved.time || 0, duration: nextSaved.duration || 0 });
      setActiveChapter(nextNumber);
      window.setTimeout(() => {
        const a = audioRef.current;
        if (!a) return;
        setIsAudioPreparing(true);
        a.play()
          .catch(() => {
            setIsAudioPreparing(false);
            setIsPlaying(false);
          });
      }, 350);
    }
  };

  const chapterParagraphs = useMemo(() => paragraphsFromText(chapterText), [chapterText]);
  const duration = playback.duration || savedAudio.duration || 0;
  const currentTime = playback.time || savedAudio.time || 0;
  const formatTime = (seconds) => {
    if (!Number.isFinite(seconds) || seconds <= 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${mins}:${secs}`;
  };

  return (
    <div className="audiobook-view reader-shell">
      {onBackToLibrary && (
        <button className="back-link" onClick={onBackToLibrary}>Back to library</button>
      )}

      <section className="reader-hero">
        <div>
          <p className="reader-kicker">Continuous audiobook</p>
          <h1 className="book-title">{title || 'Your audiobook'}</h1>
          <div className="book-subtitle">
            {author && <span>by {author}</span>}
            {page_count && <span>{page_count} pages</span>}
            <span>{chapters.length} chapters</span>
          </div>
        </div>
        <div className="book-overall-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${overallPct}%` }} />
          </div>
          <span className="book-overall-text">{overallPct}% complete</span>
        </div>
      </section>

      <section className="continuous-player" aria-label="Audiobook player">
        <div className="now-playing">
          <span className="chapter-number">CH {String(activeNumber).padStart(2, '0')}</span>
          <div>
            <h2>{active?.title || `Chapter ${activeNumber}`}</h2>
            <p>
              {savedAudio.done
                ? 'Finished'
                : isAudioPreparing
                  ? 'Generating audio (first time can be slow) — hang tight…'
                  : chapterPct
                    ? `${chapterPct}% listened`
                    : isPlaying
                      ? 'Playing'
                      : 'Ready to listen'}
            </p>
          </div>
        </div>
        {audioUrl ? (
          <div className={`custom-player ${isAudioPreparing ? 'is-preparing' : ''}`}>
            <button
              className="player-toggle"
              type="button"
              onClick={togglePlayback}
              aria-busy={isAudioPreparing}
              title={
                isAudioPreparing
                  ? 'Click to stop waiting'
                  : undefined
              }
            >
              {isAudioPreparing ? 'Preparing…' : isPlaying ? 'Pause' : 'Play'}
            </button>
            <span className="player-time">
              {isAudioPreparing ? '—' : formatTime(currentTime)}
            </span>
            <input
              className="player-seek"
              type="range"
              min="0"
              max={Math.max(duration, 1)}
              step="0.1"
              value={Math.min(currentTime, Math.max(duration, 1))}
              onChange={handleSeek}
              disabled={isAudioPreparing}
              aria-label="Seek audio"
            />
            <span className="player-time">
              {isAudioPreparing || !Number.isFinite(duration) || duration <= 0 ? '—' : formatTime(duration)}
            </span>
            <audio
              ref={audioRef}
              preload="none"
              src={audioUrl}
              onPlaying={() => {
                setIsAudioPreparing(false);
                setIsPlaying(true);
              }}
              onPause={() => {
                setIsPlaying(false);
                if (!audioRef.current || !Number.isFinite(audioRef.current.currentTime) || audioRef.current.currentTime < 0.01) {
                  setIsAudioPreparing(false);
                }
              }}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={(e) => {
                const nextDuration = e.currentTarget.duration || 0;
                if (Number.isFinite(nextDuration) && nextDuration > 0) {
                  setIsAudioPreparing(false);
                }
                setPlayback((current) => ({ ...current, duration: nextDuration }));
                saveAudioProgress({ duration: nextDuration });
              }}
              onCanPlay={() => setIsAudioPreparing(false)}
              onError={() => {
                setIsAudioPreparing(false);
                setIsPlaying(false);
              }}
              onEnded={handleEnded}
            />
          </div>
        ) : (
          <p className="chapter-audio-missing">Audio is not available for this chapter.</p>
        )}
      </section>

      <div className="reader-layout">
        <aside className="chapters-rail" aria-label="Chapters">
          <h2>Chapters</h2>
          <div className="chapter-list">
            {chapters.map((ch, idx) => {
              const number = ch.chapter_number || idx + 1;
              const isActive = number === activeNumber;
              const isRead = !!progress.chaptersRead?.[number] || !!progress.audio?.[number]?.done;
              return (
                <button
                  key={number}
                  className={`chapter-row ${isActive ? 'is-active' : ''} ${isRead ? 'is-read' : ''}`}
                  onClick={() => selectChapter(number)}
                >
                  <span>{String(number).padStart(2, '0')}</span>
                  <strong>{ch.title || `Chapter ${number}`}</strong>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="book-reader">
          <div className="reader-actions">
            <label className="read-toggle">
              <input
                type="checkbox"
                checked={!!progress.chaptersRead?.[activeNumber]}
                onChange={() => toggleRead(activeNumber)}
              />
              <span>Read</span>
            </label>
          </div>

          {active?.summary && (
            <section className="chapter-note">
              <h2>Chapter summary</h2>
              <p>{active.summary}</p>
            </section>
          )}

          {active?.key_points?.length > 0 && (
            <section className="chapter-note compact">
              <h2>Key points</h2>
              <ul>
                {active.key_points.map((point, i) => <li key={i}>{point}</li>)}
              </ul>
            </section>
          )}

          <article className="chapter-page">
            <h2>{active?.title || `Chapter ${activeNumber}`}</h2>
            {textState === 'loading' && <p className="reader-muted">Loading chapter text...</p>}
            {textState === 'error' && <p className="reader-error">{textError}</p>}
            {textState === 'ready' && chapterParagraphs.length === 0 && (
              <p className="reader-muted">No full text was saved for this chapter.</p>
            )}
            {textState === 'ready' && chapterParagraphs.map((paragraph, i) => (
              <p key={i}>{paragraph}</p>
            ))}
          </article>
        </main>
      </div>

      {(summary || key_points.length > 0) && (
        <section className="book-notes">
          {summary && (
            <div className={`summary-block ${progress.summaryRead ? 'is-read' : ''}`}>
              <div className="block-head">
                <h2>Book summary</h2>
                <label className="read-toggle">
                  <input type="checkbox" checked={!!progress.summaryRead} onChange={toggleSummaryRead} />
                  <span>Read</span>
                </label>
              </div>
              <p className="summary-body">{summary}</p>
            </div>
          )}

          {key_points.length > 0 && (
            <div className={`key-points ${progress.keyPointsRead ? 'is-read' : ''}`}>
              <div className="block-head">
                <h3>Book key points</h3>
                <label className="read-toggle">
                  <input type="checkbox" checked={!!progress.keyPointsRead} onChange={toggleKeyPointsRead} />
                  <span>Read</span>
                </label>
              </div>
              <ul>
                {key_points.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
        </section>
      )}

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
