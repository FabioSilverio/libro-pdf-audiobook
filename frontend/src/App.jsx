import { useEffect, useState } from 'react';
import UploadForm from './components/UploadForm';
import ProgressTracker from './components/ProgressTracker';
import ChaptersView from './components/ChaptersView';
import Library from './components/Library';
import { getAudiobookMetadata } from './services/api';
import { getBook, getLibrary, upsertBook } from './services/library';
import './App.css';

const ACTIVE_TASK_KEY = 'libro.activeTask.v1';

// Views: upload | processing | audiobook | library
export default function App() {
  // Boot state: check URL ?task=..., then an unfinished task in localStorage.
  const boot = (() => {
    try {
      const urlTask = new URLSearchParams(window.location.search).get('task');
      if (urlTask) return { view: 'processing', taskId: urlTask };
      const stored = localStorage.getItem(ACTIVE_TASK_KEY);
      if (stored) return { view: 'processing', taskId: stored };
    } catch {
      // Ignore malformed URL/localStorage data and use the default boot view.
    }
    return {
      view: getLibrary().length > 0 ? 'library' : 'upload',
      taskId: null,
    };
  })();

  const [view, setView] = useState(boot.view);
  const [taskId, setTaskId] = useState(boot.taskId);
  const [audiobook, setAudiobook] = useState(null);
  const [error, setError] = useState(null);
  const [libraryCount, setLibraryCount] = useState(getLibrary().length);

  // Persist the active taskId so a refresh / closed tab can resume.
  useEffect(() => {
    try {
      if (taskId && view === 'processing') {
        localStorage.setItem(ACTIVE_TASK_KEY, taskId);
      } else {
        localStorage.removeItem(ACTIVE_TASK_KEY);
      }
    } catch {
      // localStorage can be unavailable in private or restricted browser modes.
    }
  }, [taskId, view]);

  const handleUploadSuccess = (result) => {
    setTaskId(result.task_id);
    setView('processing');
    setError(null);
  };

  const handleProcessingComplete = async () => {
    try {
      const data = await getAudiobookMetadata(taskId);
      upsertBook(data);
      setLibraryCount(getLibrary().length);
      setAudiobook(data);
      setView('audiobook');
    } catch {
      setError('Failed to load audiobook data');
    }
  };

  const handleStartOver = () => {
    setView('upload');
    setTaskId(null);
    setAudiobook(null);
    setError(null);
  };

  const openBook = async (id) => {
    // Try cache first for instant load, then refresh from server
    const cached = getBook(id);
    if (cached) {
      setAudiobook(cached);
      setTaskId(id);
      setView('audiobook');
    }
    try {
      const fresh = await getAudiobookMetadata(id);
      upsertBook(fresh);
      setLibraryCount(getLibrary().length);
      setAudiobook(fresh);
      setTaskId(id);
      if (!cached) setView('audiobook');
    } catch {
      if (!cached) setError('Could not load this book from the server. It may have expired.');
    }
  };

  const goLibrary = () => {
    setAudiobook(null);
    setTaskId(null);
    setError(null);
    setLibraryCount(getLibrary().length);
    setView('library');
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <button
            className="brand"
            onClick={() => setView(libraryCount > 0 ? 'library' : 'upload')}
            style={{ cursor: 'pointer' }}
          >
            <span className="brand-mark">L</span>
            <span>Libro</span>
          </button>
          <nav className="header-nav-buttons">
            {view !== 'library' && libraryCount > 0 && (
              <button className="nav-link" onClick={goLibrary}>
                Library <span className="badge">{libraryCount}</span>
              </button>
            )}
            {view !== 'upload' && (
              <button className="nav-link" onClick={handleStartOver}>+ New</button>
            )}
          </nav>
        </div>
      </header>

      <main className="app-main">
        {error && (
          <div className="global-error">
            <span>{error}</span>
            <button onClick={() => setError(null)}>dismiss</button>
          </div>
        )}

        {view === 'upload' && (
          <>
            <section className="hero">
              <h1>Turn any book into a <em>listenable</em> story.</h1>
              <p className="tagline">
                Upload a PDF up to 400&nbsp;MB. We'll extract its chapters,
                summarise each one, generate a neural audiobook, and remember
                where you left off.
              </p>
            </section>

            <UploadForm
              onUploadSuccess={handleUploadSuccess}
              onUploadError={(err) => setError(err.message || 'Upload failed')}
            />

            <section className="features-section">
              <h2>How it reads to you</h2>
              <div className="features-grid">
                <div className="feature-card">
                  <div className="feature-icon">📖</div>
                  <h3>Extract</h3>
                  <p>pdfplumber pulls clean text; scanned PDFs fall back to Tesseract OCR.</p>
                </div>
                <div className="feature-card">
                  <div className="feature-icon">✨</div>
                  <h3>Summarise</h3>
                  <p>Per-chapter summaries with an offline multilingual engine.</p>
                </div>
                <div className="feature-card">
                  <div className="feature-icon">🎧</div>
                  <h3>Listen</h3>
                  <p>Edge Neural TTS renders MP3s you can stream or download.</p>
                </div>
              </div>
            </section>
          </>
        )}

        {view === 'processing' && taskId && (
          <ProgressTracker
            taskId={taskId}
            onComplete={handleProcessingComplete}
            onCancel={handleStartOver}
          />
        )}

        {view === 'audiobook' && audiobook && (
          <ChaptersView
            audiobook={audiobook}
            onStartOver={handleStartOver}
            onBackToLibrary={libraryCount > 0 ? goLibrary : null}
          />
        )}

        {view === 'library' && (
          <Library onOpen={openBook} onNew={handleStartOver} />
        )}
      </main>

      <footer className="app-footer">
        Built with FastAPI · React · edge-tts · sumy — progress saved locally in your browser.
      </footer>
    </div>
  );
}
