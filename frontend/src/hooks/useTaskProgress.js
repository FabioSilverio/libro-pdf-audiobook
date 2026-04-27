/**
 * Custom hook for tracking task progress via WebSocket with polling fallback.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { getTaskStatus } from '../services/api';

const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';
const FINISHED_STATUSES = ['completed', 'failed', 'cancelled'];

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
  const statusRef = useRef(null);

  const applyTaskStatus = useCallback((taskStatus) => {
    statusRef.current = taskStatus.status;
    setStatus(taskStatus.status);
    setProgress(taskStatus.progress);
    setStage(taskStatus.stage || '');
    setMessage(taskStatus.message || '');
  }, []);

  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (!taskId || pollingIntervalRef.current) return;

    const poll = async () => {
      try {
        const taskStatus = await getTaskStatus(taskId);
        applyTaskStatus(taskStatus);

        if (FINISHED_STATUSES.includes(taskStatus.status)) {
          stopPolling();
        }
      } catch (err) {
        const code = err?.response?.status || err?.status;
        if (code === 404) {
          statusRef.current = 'failed';
          setStatus('failed');
          setMessage(
            'The server lost track of this task (it probably restarted). ' +
            'Please upload the file again to resume.'
          );
          setError('Task not found on server.');
          stopPolling();
          return;
        }
        console.error('Polling error:', err);
        setError(err.message || 'Failed to fetch task status');
      }
    };

    poll();
    pollingIntervalRef.current = setInterval(poll, 2000);
  }, [applyTaskStatus, stopPolling, taskId]);

  const disconnectWebSocket = useCallback(() => {
    if (wsRef.current) {
      clearInterval(wsRef.current.pingInterval);
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connectWebSocket = useCallback(() => {
    if (!taskId || wsRef.current) return;

    try {
      const ws = new WebSocket(`${WS_BASE_URL}/ws/${taskId}`);

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);

        ws.pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          } else {
            clearInterval(ws.pingInterval);
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        const raw = event.data;
        if (typeof raw !== 'string' || !raw.startsWith('{')) return;

        try {
          const data = JSON.parse(raw);
          if (data.type === 'progress' || data.type === 'status') {
            applyTaskStatus(data.data);
          }
        } catch {
          console.warn('Ignoring non-JSON WS message:', raw);
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        setIsConnected(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
        clearInterval(ws.pingInterval);
        wsRef.current = null;

        if (!FINISHED_STATUSES.includes(statusRef.current)) {
          startPolling();
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to connect WebSocket:', err);
      setError('Failed to connect to real-time updates');
      startPolling();
    }
  }, [applyTaskStatus, startPolling, taskId]);

  useEffect(() => {
    if (!taskId) return undefined;
    const retryTimer = retryTimeoutRef.current;

    getTaskStatus(taskId)
      .then((taskStatus) => {
        applyTaskStatus(taskStatus);
        if (!FINISHED_STATUSES.includes(taskStatus.status)) {
          connectWebSocket();
        }
      })
      .catch((err) => {
        console.error('Failed to fetch initial status:', err);
        setError(err.message || 'Failed to fetch task status');
      });

    return () => {
      disconnectWebSocket();
      stopPolling();
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [applyTaskStatus, connectWebSocket, disconnectWebSocket, stopPolling, taskId]);

  const cancelTask = useCallback(async () => {
    try {
      const response = await fetch(`${WS_BASE_URL.replace('ws', 'http')}/api/v1/tasks/${taskId}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        statusRef.current = 'cancelled';
        setStatus('cancelled');
        setMessage('Task cancelled by user');
        disconnectWebSocket();
        stopPolling();
      }
    } catch (err) {
      console.error('Failed to cancel task:', err);
      setError('Failed to cancel task');
    }
  }, [disconnectWebSocket, stopPolling, taskId]);

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
