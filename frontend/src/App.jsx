import { useState } from 'react';
import UploadForm from './components/UploadForm';
import ProgressTracker from './components/ProgressTracker';
import ChaptersView from './components/ChaptersView';
import { getAudiobookMetadata } from './services/api';
import './App.css';

export default function App() {
  const [view, setView] = useState('upload'); // upload | processing | audiobook
  const [taskId, setTaskId] = useState(null);
  const [audiobook, setAudiobook] = useState(null);
  const [error, setError] = useState(null);

  const handleUploadSuccess = (result) => {
    setTaskId(result.task_id);
    setView('processing');
    setError(null);
  };

  const handleProcessingComplete = async () => {
    try {
      const data = await getAudiobookMetadata(taskId);
      setAudiobook(data);
      setView('audiobook');
    } catch (err) {
      setError('Failed to load audiobook data');
    }
  };

  const handleStartOver = () => {
    setView('upload');
    setTaskId(null);
    setAudiobook(null);
    setError(null);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-mark">L</span>
            <span>Libro</span>
          </div>
          <div className="header-nav">PDF → Audiobook, with care.</div>
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
                summarise each one, and generate a neural audiobook — all free, no keys.
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
                  <p>pdfplumber pulls clean text from every page, even messy books.</p>
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
          <ChaptersView audiobook={audiobook} onStartOver={handleStartOver} />
        )}
      </main>

      <footer className="app-footer">
        Built with FastAPI · React · edge-tts · sumy — no API keys required.
      </footer>
    </div>
  );
}
