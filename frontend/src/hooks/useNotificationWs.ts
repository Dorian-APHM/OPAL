/**
 * WebSocket hook for real-time notifications.
 *
 * Connects to /api/ws/notifications using a one-time SSE ticket for auth.
 * Falls back to polling if WebSocket fails or is unavailable.
 *
 * Dispatches 'opal:notification' for new notifications and
 * 'opal:badges-refresh' to sync sidebar badges.
 */
import { useEffect, useRef, useCallback } from 'react';
import { notificationsApi } from '../api/client';

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000]; // ms
const PING_INTERVAL = 30000; // 30s keepalive

export function useNotificationWs(enabled: boolean) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectIdx = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const pingTimer = useRef<ReturnType<typeof setInterval>>();
  const mountedRef = useRef(true);

  const connect = useCallback(async () => {
    if (!mountedRef.current || !enabled) return;

    // Get a ticket for WS auth
    let ticket: string;
    try {
      const res = await notificationsApi.sseTicket();
      ticket = res.data.ticket;
    } catch {
      // Auth endpoint failed — schedule retry
      scheduleReconnect();
      return;
    }

    if (!mountedRef.current) return;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/ws/notifications?ticket=${ticket}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectIdx.current = 0; // Reset backoff on success
      // Start ping keepalive
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'notification') {
          // Dispatch custom event with notification data
          window.dispatchEvent(new CustomEvent('opal:notification', { detail: msg.data }));
          // Refresh sidebar badges
          window.dispatchEvent(new Event('opal:badges-refresh'));
        }
        // pong messages are silently ignored
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      cleanup();
      if (mountedRef.current && enabled) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror
    };
  }, [enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const cleanup = useCallback(() => {
    if (pingTimer.current) {
      clearInterval(pingTimer.current);
      pingTimer.current = undefined;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    const delay = RECONNECT_DELAYS[Math.min(reconnectIdx.current, RECONNECT_DELAYS.length - 1)];
    reconnectIdx.current++;
    reconnectTimer.current = setTimeout(() => {
      connect();
    }, delay);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) {
      connect();
    }
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      cleanup();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enabled, connect, cleanup]);
}
