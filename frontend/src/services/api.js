/**
 * API service for backend communication
 */
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Create axios instance with default config
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for logging (development)
api.interceptors.request.use(
  (config) => {
    console.log(`API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const errorMessage = error.response?.data?.error || error.message || 'Unknown error occurred';
    console.error('API Error:', errorMessage);
    return Promise.reject({
      message: errorMessage,
      code: error.response?.data?.code,
      status: error.response?.status,
    });
  }
);

/**
 * Upload a PDF file for processing
 * @param {File} file - PDF file to upload
 * @param {Object} options - Processing options
 * @returns {Promise<Object>} Task information
 */
export const uploadPDF = async (file, options = {}, onProgress) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('summarize', options.summarize !== false);
  formData.append('summary_length', options.summary_length || 'medium');
  formData.append('voice', options.voice || 'pt-BR-AntonioNeural');
  formData.append('generate_audio', options.generate_audio !== false);
  formData.append('language', options.language || 'auto');

  const response = await api.post('/api/v1/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
    timeout: 0,
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded * 100) / evt.total));
      }
    },
  });

  return response.data;
};

export const getVoices = async () => {
  const response = await api.get('/api/v1/audiobooks/voices');
  return response.data;
};

/**
 * Get task status
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Task status
 */
export const getTaskStatus = async (taskId) => {
  const response = await api.get(`/api/v1/tasks/${taskId}`);
  return response.data;
};

/**
 * Cancel a task
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Cancellation result
 */
export const cancelTask = async (taskId) => {
  const response = await api.delete(`/api/v1/tasks/${taskId}`);
  return response.data;
};

/**
 * List all tasks
 * @returns {Promise<Object>} List of tasks
 */
export const listTasks = async () => {
  const response = await api.get('/api/v1/tasks');
  return response.data;
};

/**
 * Get audiobook metadata
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Audiobook metadata
 */
export const getAudiobookMetadata = async (taskId) => {
  const response = await api.get(`/api/v1/audiobooks/${taskId}`);
  return response.data;
};

/**
 * Get extracted text for TTS
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Extracted text
 */
export const getExtractedText = async (taskId) => {
  const response = await api.get(`/api/v1/audiobooks/${taskId}/text`);
  return response.data;
};

/**
 * Get summary
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Summary data
 */
export const getSummary = async (taskId) => {
  const response = await api.get(`/api/v1/audiobooks/${taskId}/summary`);
  return response.data;
};

/**
 * Regenerate summaries for an existing audiobook using the latest summarizer.
 * @param {string} taskId
 * @param {string} length - "short" | "medium" | "long"
 */
export const resummarizeAudiobook = async (taskId, length = 'medium') => {
  const response = await api.post(
    `/api/v1/audiobooks/${taskId}/resummarize`,
    null,
    { params: { length }, timeout: 0 }
  );
  return response.data;
};

/**
 * Delete an audiobook
 * @param {string} taskId - Task identifier
 * @returns {Promise<Object>} Deletion result
 */
export const deleteAudiobook = async (taskId) => {
  const response = await api.delete(`/api/v1/audiobooks/${taskId}`);
  return response.data;
};

/**
 * List all audiobooks
 * @returns {Promise<Object>} List of audiobooks
 */
export const listAudiobooks = async () => {
  const response = await api.get('/api/v1/audiobooks');
  return response.data;
};

/**
 * Validate file before upload
 * @param {string} filename - File name
 * @param {number} size - File size in bytes
 * @returns {Promise<Object>} Validation result
 */
export const validateUpload = async (filename, size) => {
  const response = await api.get('/api/v1/upload/validate', {
    params: { filename, size },
  });
  return response.data;
};

export default api;
