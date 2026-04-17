/**
 * Progress Tracker Component - Shows real-time processing progress
 * with animated step indicator, elapsed timer, and reassuring tips.
 */
import { useState, useEffect, useRef } from 'react';
import { useTaskProgress } from '../hooks/useTaskProgress';

const STAGES = [
  { key: 'extracting', icon: '📖', label: 'Extracting text', desc: 'Reading pages and extracting content' },
  { key: 'summarizing', icon: '🤖', label: 'AI Summary', desc: 'Generating chapter summaries with AI' },
  { key: 'generating_audio', icon: '🔊', label: 'Audiobook', desc: 'Converting text to speech (MP3)' },
];

const TIPS = [
  'Large books may take several minutes — everything is happening server-side.',
  'EPUBs are faster because they don\'t need OCR.',
  'You can close this tab and come back — your task is saved.',
  'Scanned PDFs take longer because each page needs OCR.',
  'Summaries are generated per chapter with AI key-points.',
  'Audio is generated chapter by chapter so you can listen as soon as the first is ready.',
  'Your library is saved locally in this browser.',
];

function useElapsed(running) {
  const [seconds, setSeconds] = useState(0);
  const ref = useRef(null);
  useEffect(() => {
    if (running) {
      ref.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } else {
      clearInterval(ref.current);
    }
    return () => clearInterval(ref.current);
  }, [running]);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`;
}

export default function ProgressTracker({ taskId, onComplete, onCancel }) {
  const {
    status,
    progress,
    stage,
    message,
    isConnected,
    error,
    cancelTask,
  } = useTaskProgress(taskId);

  const isProcessing = !['completed', 'failed', 'cancelled'].includes(status);
  const elapsed = useElapsed(isProcessing);

  // Rotating tips
  const [tipIdx, setTipIdx] = useState(0);
  useEffect(() => {
    if (!isProcessing) return;
    const id = setInterval(() => setTipIdx((i) => (i + 1) % TIPS.length), 8000);
    return () => clearInterval(id);
  }, [isProcessing]);

  // Handle completion
  useEffect(() => {
    if (status === 'completed' && onComplete) {
      const t = setTimeout(onComplete, 1000);
      return () => clearTimeout(t);
    }
  }, [status, onComplete]);

  // Which stage index are we on?
  const currentIdx = STAGES.findIndex((s) => s.key === stage);

  const handleCancel = async () => {
    if (window.confirm('Are you sure you want to cancel this task?')) {
      await cancelTask();
      if (onCancel) onCancel();
    }
  };

  return (
    <div className="progress-tracker">
      <h2>Processing Your Book</h2>

      <div className="connection-status">
        {isConnected ? (
          <span className="connected">● Live updates</span>
        ) : (
          <span className="polling">◌ Polling for updates</span>
        )}
        {isProcessing && <span className="elapsed-time">{elapsed}</span>}
      </div>

      {/* === Step-by-step pipeline === */}
      {isProcessing && (
        <div className="pipeline">
          {STAGES.map((s, i) => {
            const done = currentIdx > i || status === 'completed';
            const active = currentIdx === i;
            return (
              <div key={s.key} className="pipeline-step-wrap">
                {i > 0 && <div className={`pipeline-connector ${done ? 'done' : ''}`} />}
                <div className={`pipeline-step ${done ? 'done' : ''} ${active ? 'active' : ''}`}>
                  <div className="pipeline-icon">
                    {done ? '✓' : active ? s.icon : <span className="pipeline-num">{i + 1}</span>}
                  </div>
                  <div className="pipeline-label">{s.label}</div>
                  {active && <div className="pipeline-desc">{s.desc}</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Completed / Failed header icons */}
      {status === 'completed' && <div className="stage-icon">✅</div>}
      {status === 'failed' && <div className="stage-icon">❌</div>}
      {status === 'cancelled' && <div className="stage-icon">⏹️</div>}

      {/* Progress Bar */}
      <div className="progress-container">
        <div className="progress-bar-wrapper">
          <div className="progress-bar">
            <div
              className={`progress-fill ${isProcessing ? 'animated' : ''}`}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="progress-percentage">{progress}%</div>
        </div>
      </div>

      {/* Status Message */}
      {message && <div className="status-message">{message}</div>}

      {/* Rotating tip */}
      {isProcessing && (
        <div className="progress-tip" key={tipIdx}>
          💡 {TIPS[tipIdx]}
        </div>
      )}

      {/* Error Display */}
      {error && <div className="error-message">{error}</div>}

      {/* Cancel Button */}
      {isProcessing && (
        <button className="cancel-button" onClick={handleCancel}>
          Cancel Processing
        </button>
      )}

      {/* Retry hint */}
      {(status === 'failed' || status === 'cancelled') && (
        <div className="retry-hint">
          <p>You can upload another file to try again</p>
        </div>
      )}
    </div>
  );
}
