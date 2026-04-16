import { useState, useCallback, useEffect } from 'react';
import { uploadPDF, getVoices } from '../services/api';

const MAX_SIZE = 400 * 1024 * 1024; // 400 MB

export default function UploadForm({ onUploadSuccess, onUploadError }) {
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState('');
  const [voices, setVoices] = useState([]);

  const [options, setOptions] = useState({
    summarize: true,
    summary_length: 'medium',
    voice: '',
    generate_audio: true,
    language: 'auto',
  });

  useEffect(() => {
    getVoices()
      .then((data) => {
        const list = data.voices || [];
        setVoices(list);
        if (list.length && !options.voice) {
          setOptions((o) => ({ ...o, voice: list[0].id }));
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const validateFile = (f) => {
    setError('');
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are accepted');
      return false;
    }
    if (f.size > MAX_SIZE) {
      setError(`File too large. Max is ${MAX_SIZE / (1024 * 1024)} MB`);
      return false;
    }
    if (f.size < 1024) {
      setError('File is too small or corrupted');
      return false;
    }
    return true;
  };

  const handleDrag = useCallback((e, state) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(state);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f && validateFile(f)) setFile(f);
  }, []);

  const handleFileInput = (e) => {
    const f = e.target.files?.[0];
    if (f && validateFile(f)) setFile(f);
  };

  const handleUpload = async () => {
    if (!file) return;
    setIsUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      const result = await uploadPDF(file, options, (pct) => setUploadProgress(pct));
      setUploadProgress(100);
      setTimeout(() => onUploadSuccess(result), 400);
    } catch (err) {
      setError(err.message || 'Upload failed');
      onUploadError?.(err);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadProgress(0), 800);
    }
  };

  const handleReset = () => {
    setFile(null);
    setError('');
    setUploadProgress(0);
  };

  return (
    <div className="upload-form">
      <h2>Upload a PDF</h2>
      <p className="subtitle">Up to 400 MB. We'll do the rest.</p>

      <div
        className={`drop-zone ${isDragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
        onDragEnter={(e) => handleDrag(e, true)}
        onDragLeave={(e) => handleDrag(e, false)}
        onDragOver={(e) => handleDrag(e, true)}
        onDrop={handleDrop}
        onClick={() => !file && document.getElementById('file-input').click()}
      >
        {file ? (
          <div className="file-info">
            <div className="file-icon">📄</div>
            <div className="file-details">
              <div className="file-name">{file.name}</div>
              <div className="file-size">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
            </div>
            {!isUploading && (
              <button
                className="remove-file-btn"
                onClick={(e) => { e.stopPropagation(); handleReset(); }}
                aria-label="Remove file"
              >
                ✕
              </button>
            )}
          </div>
        ) : (
          <div className="drop-message">
            <div className="drop-icon">⇪</div>
            <p>Drop your PDF here</p>
            <p className="drop-subtext">or click to browse</p>
            <p className="file-limits">Max 400 MB · PDF only</p>
          </div>
        )}
        <input
          id="file-input"
          type="file"
          accept=".pdf,application/pdf"
          onChange={handleFileInput}
          style={{ display: 'none' }}
          disabled={isUploading}
        />
      </div>

      {error && <div className="error-message">{error}</div>}

      {isUploading && (
        <div className="upload-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
          <div className="progress-text">Uploading… {uploadProgress}%</div>
        </div>
      )}

      {file && !isUploading && (
        <div className="options-panel">
          <h3>Processing options</h3>
          <div className="options-grid">
            <label className="option-item checkbox">
              <input
                type="checkbox"
                checked={options.summarize}
                onChange={(e) => setOptions({ ...options, summarize: e.target.checked })}
              />
              <span>Generate AI summary (per chapter)</span>
            </label>

            <label className="option-item checkbox">
              <input
                type="checkbox"
                checked={options.generate_audio}
                onChange={(e) => setOptions({ ...options, generate_audio: e.target.checked })}
              />
              <span>Generate audiobook (MP3 per chapter)</span>
            </label>

            <div className="option-item">
              <label>Summary length</label>
              <select
                value={options.summary_length}
                onChange={(e) => setOptions({ ...options, summary_length: e.target.value })}
              >
                <option value="short">Short</option>
                <option value="medium">Medium</option>
                <option value="long">Long</option>
              </select>
            </div>

            <div className="option-item">
              <label>Language</label>
              <select
                value={options.language}
                onChange={(e) => setOptions({ ...options, language: e.target.value })}
              >
                <option value="auto">Auto-detect</option>
                <option value="portuguese">Portuguese</option>
                <option value="english">English</option>
                <option value="spanish">Spanish</option>
              </select>
            </div>

            <div className="option-item" style={{ gridColumn: '1 / -1' }}>
              <label>Voice</label>
              <select
                value={options.voice}
                onChange={(e) => setOptions({ ...options, voice: e.target.value })}
              >
                {voices.length === 0 && <option value="">Default</option>}
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.locale} — {v.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      <button
        className="upload-button"
        onClick={handleUpload}
        disabled={!file || isUploading}
      >
        {isUploading ? 'Uploading…' : 'Upload & Generate Audiobook'}
      </button>
    </div>
  );
}
