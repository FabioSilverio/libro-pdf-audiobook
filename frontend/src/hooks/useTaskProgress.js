/**
 * Custom hook for tracking task progress via WebSocket with polling fallback
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { getTaskStatus } from '../services/api';

const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

export function useTaskProgress(taskId) {
  const [status, setStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [message, setMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);

  const wsRef = useRef(null);
  const pollingIntervalRef = useRef(null);
  const retryTimeoutRef = useRef(null);

  // Connect to WebSocket
  const connectWebSocket = useCallback(() => {
    if (!taskId || wsRef.current) return;

    try {
      const ws = new WebSocket(`${WS_BASE_URL}/ws/${taskId}`);

      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        setError(null);

        // Send ping to keep connection alive
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          } else {
            clearInterval(pingInterval);
          }
        }, 30000);

        ws.pingInterval = pingInterval;
      };

      ws.onmessage = (event) => {
        // Server replies plain text "pong" to our "ping"; ignore non-JSON frames.
        const raw = event.data;
        if (typeof raw !== 'string' || !raw.startsWith('{')) return;
        try {
          const data = JSON.parse(raw);
          if (data.type === 'progress' || data.type === 'status') {
            const taskData = data.data;
            setStatus(taskData.status);
            setProgress(taskData.progress);
            setStage(taskData.stage || '');
            setMessage(taskData.message || '');
          }
        } catch (err) {
          console.warn('Ignoring non-JSON WS message:', raw);
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        setIsConnected(false);
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);
        clearTimeout(wsRef.current?.pingInterval);
        wsRef.current = null;

        // Fallback to polling if not completed
        if (status !== 'completed' && status !== 'failed' && status !== 'cancelled') {
          console.log('Starting polling fallback');
          startPolling();
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to connect WebSocket:', err);
      setError('Failed to connect to real-time updates');
      startPolling();
    }
  }, [taskId, status]);

  // Start polling fallback
  const startPolling = useCallback(() => {
    if (pollingIntervalRef.current) return;

    const poll = async () => {
      try {
        const taskStatus = await getTaskStatus(taskId);
        setStatus(taskStatus.status);
        setProgress(taskStatus.progress);
        setStage(taskStatus.stage || '');
        setMessage(taskStatus.message || '');

        // Stop polling when complete
        if (['completed', 'failed', 'cancelled'].includes(taskStatus.status)) {
          stopPolling();
        }
      } catch (err) {
        // 404 on polling almost always means the server forgot the task
        // (most commonly a redeploy / container restart wiped in-memory
        // state). Give up immediately with a clear message — otherwise
        // the UI would hammer the endpoint forever.
        const code = err?.response?.status;
        if (code === 404) {
          console.warn('Task not found on server (404). Likely server restart.');
          setStatus('failed');
          setMessage(
            'The server lost track of this task (it probably restarted). ' +
            'Please upload the PDF again to resume.'
          );
          setError('Task not found on server.');
          stopPolling();
          return;
        }
        console.error('Polling error:', err);
        setError(err.message || 'Failed to fetch task status');
      }
    };

    // Poll immediately
    poll();

    // Then every 2 seconds
    pollingIntervalRef.current = setInterval(poll, 2000);
  }, [taskId]);

  // Stop polling
  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  }, []);

  // Disconnect WebSocket
  const disconnectWebSocket = useCallback(() => {
    if (wsRef.current) {
      clearTimeout(wsRef.current.pingInterval);
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // Initialize connection
  useEffect(() => {
    if (!taskId) return;

    // Fetch initial status
    getTaskStatus(taskId)
      .then((taskStatus) => {
        setStatus(taskStatus.status);
        setProgress(taskStatus.progress);
        setStage(taskStatus.stage || '');
        setMessage(taskStatus.message || '');

        // If already complete, don't connect
        if (!['completed', 'failed', 'cancelled'].includes(taskStatus.status)) {
          connectWebSocket();
        }
      })
      .catch((err) => {
        console.error('Failed to fetch initial status:', err);
        setError(err.message || 'Failed to fetch task status');
      });

    // Cleanup on unmount
    return () => {
      disconnectWebSocket();
      stopPolling();
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, [taskId, connectWebSocket, disconnectWebSocket, stopPolling]);

  // Cancel task
  const cancelTask = useCallback(async () => {
    try {
      const response = await fetch(`${WS_BASE_URL.replace('ws', 'http')}/api/v1/tasks/${taskId}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        setStatus('cancelled');
        setMessage('Task cancelled by user');
        disconnectWebSocket();
        stopPolling();
      }
    } catch (err) {
      console.error('Failed to cancel task:', err);
      setError('Failed to cancel task');
    }
  }, [taskId, disconnectWebSocket, stopPolling]);

  return {
    status,
    progress,
    stage,
    message,
    isConnected,
    error,
    cancelTask,
  };
}

export default useTaskProgress;
