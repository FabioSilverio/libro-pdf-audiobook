/**
 * Progress Tracker Component - Shows real-time processing progress
 */
import { useTaskProgress } from '../hooks/useTaskProgress';

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

  // Handle completion
  if (status === 'completed') {
    setTimeout(() => {
      if (onComplete) onComplete();
    }, 1000);
  }

  // Get stage icon
  const getStageIcon = () => {
    switch (stage) {
      case 'extracting':
        return '📖';
      case 'summarizing':
        return '🤖';
      case 'generating_audio':
        return '🔊';
      case 'completed':
        return '✅';
      case 'failed':
        return '❌';
      case 'cancelled':
        return '⏹️';
      default:
        return '⏳';
    }
  };

  // Get stage text
  const getStageText = () => {
    switch (stage) {
      case 'queued':
        return 'Queued for processing';
      case 'extracting':
        return 'Extracting text from PDF';
      case 'summarizing':
        return 'Generating AI summary';
      case 'generating_audio':
        return 'Converting to speech';
      case 'completed':
        return 'Processing complete!';
      case 'failed':
        return 'Processing failed';
      case 'cancelled':
        return 'Cancelled by user';
      default:
        return 'Processing...';
    }
  };

  // Handle cancel
  const handleCancel = async () => {
    if (window.confirm('Are you sure you want to cancel this task?')) {
      await cancelTask();
      if (onCancel) onCancel();
    }
  };

  const isProcessing = !['completed', 'failed', 'cancelled'].includes(status);

  return (
    <div className="progress-tracker">
      <h2>Processing Your Book</h2>

      {/* Connection Status */}
      <div className="connection-status">
        {isConnected ? (
          <span className="connected">● Live Updates</span>
        ) : (
          <span className="polling">◌ Polling for updates</span>
        )}
      </div>

      {/* Stage Icon */}
      <div className="stage-icon">{getStageIcon()}</div>

      {/* Stage Text */}
      <div className="stage-text">{getStageText()}</div>

      {/* Progress Bar */}
      <div className="progress-container">
        <div className="progress-bar-wrapper">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${progress}%`,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div className="progress-percentage">{progress}%</div>
        </div>
      </div>

      {/* Status Message */}
      {message && <div className="status-message">{message}</div>}

      {/* Error Display */}
      {error && <div className="error-message">⚠️ {error}</div>}

      {/* Processing Stages Indicator */}
      {isProcessing && (
        <div className="stages-indicator">
          <div className={`stage-dot ${['extracting', 'summarizing', 'generating_audio', 'completed'].includes(stage) || progress >= 30 ? 'active' : ''}`}>
            <span>1</span>
          </div>
          <div className="stage-line" />
          <div className={`stage-dot ${['summarizing', 'generating_audio', 'completed'].includes(stage) || progress >= 60 ? 'active' : ''}`}>
            <span>2</span>
          </div>
          <div className="stage-line" />
          <div className={`stage-dot ${['generating_audio', 'completed'].includes(stage) || progress >= 90 ? 'active' : ''}`}>
            <span>3</span>
          </div>
        </div>
      )}

      {/* Cancel Button */}
      {isProcessing && (
        <button className="cancel-button" onClick={handleCancel}>
          Cancel Processing
        </button>
      )}

      {/* Retry Button for Failed Tasks */}
      {(status === 'failed' || status === 'cancelled') && (
        <div className="retry-hint">
          <p>You can upload another PDF to try again</p>
        </div>
      )}
    </div>
  );
}
