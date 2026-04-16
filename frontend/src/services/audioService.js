/**
 * Audio service using Browser Speech Synthesis API
 */

class AudioService {
  constructor() {
    this.synth = window.speechSynthesis;
    this.utterance = null;
    this.isPlaying = false;
    this.isPaused = false;
    this.currentTime = 0;
    this.duration = 0;
    this.playbackRate = 1.0;
    this.volume = 1.0;
    this.selectedVoice = null;
    this.textChunks = [];
    this.currentChunkIndex = 0;
    this.onProgressCallback = null;
    this.onEndCallback = null;
    this.onErrorCallback = null;
  }

  /**
   * Initialize and load available voices
   * @returns {Promise<Array>} Available voices
   */
  async initialize() {
    return new Promise((resolve) => {
      const loadVoices = () => {
        const voices = this.synth.getVoices();
        if (voices.length > 0) {
          resolve(voices);
        }
      };

      // Try to get voices immediately
      loadVoices();

      // Fallback: wait for voiceschanged event
      this.synth.onvoiceschanged = loadVoices;

      // Timeout after 2 seconds
      setTimeout(() => resolve(this.synth.getVoices()), 2000);
    });
  }

  /**
   * Get available voices
   * @returns {Array} Available voices
   */
  getVoices() {
    return this.synth.getVoices();
  }

  /**
   * Set selected voice
   * @param {SpeechSynthesisVoice} voice - Voice to use
   */
  setVoice(voice) {
    this.selectedVoice = voice;
  }

  /**
   * Prepare text for playback by chunking it
   * @param {string} text - Full text to speak
   * @param {number} chunkSize - Words per chunk (default 250)
   */
  prepareText(text, chunkSize = 250) {
    // Split text into words
    const words = text.split(/\s+/);
    this.textChunks = [];

    // Create chunks of approximately chunkSize words
    for (let i = 0; i < words.length; i += chunkSize) {
      const chunk = words.slice(i, i + chunkSize).join(' ');
      this.textChunks.push(chunk);
    }

    // Estimate duration (rough calculation: ~150 words per minute)
    const totalWords = words.length;
    this.duration = (totalWords / 150) * 60 / this.playbackRate;

    this.currentChunkIndex = 0;
    this.currentTime = 0;
  }

  /**
   * Start or resume playback
   */
  play() {
    if (this.isPaused) {
      this.synth.resume();
      this.isPaused = false;
      this.isPlaying = true;
      return;
    }

    if (this.isPlaying) {
      return; // Already playing
    }

    this.isPlaying = true;
    this._playCurrentChunk();
  }

  /**
   * Play current chunk
   * @private
   */
  _playCurrentChunk() {
    if (this.currentChunkIndex >= this.textChunks.length) {
      this._onEnd();
      return;
    }

    const chunk = this.textChunks[this.currentChunkIndex];
    this.utterance = new SpeechSynthesisUtterance(chunk);

    // Configure utterance
    if (this.selectedVoice) {
      this.utterance.voice = this.selectedVoice;
    }
    this.utterance.rate = this.playbackRate;
    this.utterance.volume = this.volume;

    // Event handlers
    this.utterance.onstart = () => {
      console.log(`Playing chunk ${this.currentChunkIndex + 1}/${this.textChunks.length}`);
    };

    this.utterance.onend = () => {
      this.currentChunkIndex++;
      this.currentTime = (this.currentChunkIndex / this.textChunks.length) * this.duration;

      // Call progress callback
      if (this.onProgressCallback) {
        this.onProgressCallback({
          currentTime: this.currentTime,
          duration: this.duration,
          progress: (this.currentChunkIndex / this.textChunks.length) * 100,
        });
      }

      // Play next chunk
      if (this.isPlaying && !this.isPaused) {
        this._playCurrentChunk();
      }
    };

    this.utterance.onerror = (event) => {
      console.error('Speech synthesis error:', event);
      if (this.onErrorCallback) {
        this.onErrorCallback(event);
      }
      this.stop();
    };

    // Speak
    this.synth.speak(this.utterance);
  }

  /**
   * Pause playback
   */
  pause() {
    if (this.isPlaying && !this.isPaused) {
      this.synth.pause();
      this.isPaused = true;
    }
  }

  /**
   * Stop playback
   */
  stop() {
    this.synth.cancel();
    this.isPlaying = false;
    this.isPaused = false;
    this.currentChunkIndex = 0;
    this.currentTime = 0;
  }

  /**
   * Seek to a specific time
   * @param {number} time - Time in seconds
   */
  seek(time) {
    const wasPlaying = this.isPlaying;

    // Stop current playback
    this.stop();

    // Calculate chunk index from time
    const progress = time / this.duration;
    this.currentChunkIndex = Math.floor(progress * this.textChunks.length);
    this.currentTime = time;

    // Resume if was playing
    if (wasPlaying) {
      this.play();
    }
  }

  /**
   * Set playback rate
   * @param {number} rate - Playback rate (0.5 to 2.0)
   */
  setPlaybackRate(rate) {
    this.playbackRate = Math.max(0.5, Math.min(2.0, rate));

    // Recalculate duration
    if (this.textChunks.length > 0) {
      const totalWords = this.textChunks.reduce((sum, chunk) => sum + chunk.split(/\s+/).length, 0);
      this.duration = (totalWords / 150) * 60 / this.playbackRate;
    }

    // If currently playing, restart with new rate
    if (this.isPlaying) {
      const currentTime = this.currentTime;
      this.stop();
      this.seek(currentTime);
      this.play();
    }
  }

  /**
   * Set volume
   * @param {number} volume - Volume (0.0 to 1.0)
   */
  setVolume(volume) {
    this.volume = Math.max(0.0, Math.min(1.0, volume));
  }

  /**
   * Skip to next chunk
   */
  skipForward(seconds = 30) {
    const newTime = Math.min(this.currentTime + seconds, this.duration);
    this.seek(newTime);
  }

  /**
   * Skip to previous chunk
   */
  skipBackward(seconds = 30) {
    const newTime = Math.max(this.currentTime - seconds, 0);
    this.seek(newTime);
  }

  /**
   * Handle playback end
   * @private
   */
  _onEnd() {
    this.isPlaying = false;
    this.isPaused = false;
    this.currentChunkIndex = 0;
    this.currentTime = 0;

    if (this.onEndCallback) {
      this.onEndCallback();
    }
  }

  /**
   * Set progress callback
   * @param {Function} callback - Progress callback function
   */
  onProgress(callback) {
    this.onProgressCallback = callback;
  }

  /**
   * Set end callback
   * @param {Function} callback - End callback function
   */
  onEnd(callback) {
    this.onEndCallback = callback;
  }

  /**
   * Set error callback
   * @param {Function} callback - Error callback function
   */
  onError(callback) {
    this.onErrorCallback = callback;
  }

  /**
   * Get current playback state
   * @returns {Object} Playback state
   */
  getState() {
    return {
      isPlaying: this.isPlaying,
      isPaused: this.isPaused,
      currentTime: this.currentTime,
      duration: this.duration,
      playbackRate: this.playbackRate,
      volume: this.volume,
      progress: this.textChunks.length > 0
        ? (this.currentChunkIndex / this.textChunks.length) * 100
        : 0,
    };
  }

  /**
   * Clean up resources
   */
  destroy() {
    this.stop();
    this.onProgressCallback = null;
    this.onEndCallback = null;
    this.onErrorCallback = null;
  }
}

// Export singleton instance
const audioService = new AudioService();
export default audioService;
