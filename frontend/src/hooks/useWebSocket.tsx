"use client";

import { useEffect, useRef, useCallback, useState, createContext, useContext, type ReactNode } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

interface WSEvent {
  type: string;
  [key: string]: unknown;
}

type WSEventListener = (event: WSEvent) => void;

interface WSContextValue {
  status: ConnectionStatus;
  lastUpdate: string | null;
  subscribe: (eventType: string, listener: WSEventListener) => () => void;
}

const WebSocketContext = createContext<WSContextValue>({
  status: "disconnected",
  lastUpdate: null,
  subscribe: () => () => {},
});

const WS_PING_MS = 15_000;
const RECONNECT_MS = 3_000;
const INVALIDATE_DEBOUNCE_MS = 1500;

function useWebSocketConnection() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pendingKeysRef = useRef<Set<string>>(new Set());
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listenersRef = useRef<Map<string, Set<WSEventListener>>>(new Map());
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);

  const subscribe = useCallback((eventType: string, listener: WSEventListener) => {
    if (!listenersRef.current.has(eventType)) {
      listenersRef.current.set(eventType, new Set());
    }
    listenersRef.current.get(eventType)!.add(listener);
    return () => {
      listenersRef.current.get(eventType)?.delete(listener);
    };
  }, []);

  const flushInvalidations = useCallback(() => {
    flushTimerRef.current = null;
    const keys = Array.from(pendingKeysRef.current);
    pendingKeysRef.current.clear();
    keys.forEach((k) => {
      queryClient.invalidateQueries({ queryKey: [k] as QueryKey, refetchType: "active" });
    });
  }, [queryClient]);

  const queueInvalidate = useCallback(
    (...keys: string[]) => {
      keys.forEach((k) => pendingKeysRef.current.add(k));
      if (flushTimerRef.current === null) {
        flushTimerRef.current = setTimeout(flushInvalidations, INVALIDATE_DEBOUNCE_MS);
      }
    },
    [flushInvalidations]
  );

  const handleEvent = useCallback(
    (event: WSEvent) => {
      // Dispatch to subscribers
      const listeners = listenersRef.current.get(event.type);
      if (listeners) {
        listeners.forEach((fn) => { try { fn(event); } catch {} });
      }

      switch (event.type) {
        case "new_message":
          queueInvalidate("messages", "stats");
          break;
        case "quarterly_results":
        case "extraction_status_update":
          queueInvalidate("pe-analysis", "pe-filters", "report-summary");
          break;
        case "job_completed":
        case "job_failed":
        case "job_progress":
          queueInvalidate("jobs");
          break;
        case "scheduled_task":
          queueInvalidate("scheduled-task");
          break;
        case "ai_analysis_complete":
          queueInvalidate("pe-analysis");
          break;
        case "concall_insight_ready":
          queueInvalidate("concall-insight", "ai-insights-list");
          break;
        case "announcement_insight_ready":
          queueInvalidate("announcement-insight", "ai-insights-list");
          break;
      }
    },
    [queueInvalidate]
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const backendHost = process.env.NEXT_PUBLIC_WS_URL || window.location.host;
    const ws = new WebSocket(`${protocol}//${backendHost}/ws`);

    ws.onopen = () => {
      setStatus("connected");
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, WS_PING_MS);
    };

    ws.onmessage = (e) => {
      if (e.data === "pong") return;
      try {
        const event: WSEvent = JSON.parse(e.data);
        if (event.type === "connected") return;
        setLastUpdate(new Date().toISOString());
        handleEvent(event);
      } catch {}
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (pingRef.current) {
        clearInterval(pingRef.current);
        pingRef.current = null;
      }
      setStatus("reconnecting");
      setTimeout(connect, RECONNECT_MS);
    };

    ws.onerror = () => {};

    wsRef.current = ws;
  }, [handleEvent]);

  useEffect(() => {
    connect();
    return () => {
      if (pingRef.current) clearInterval(pingRef.current);
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return { status, lastUpdate, subscribe };
}

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const value = useWebSocketConnection();
  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>;
}

export function useWebSocketStatus() {
  return useContext(WebSocketContext);
}

export function useWSEvent(eventType: string, listener: WSEventListener) {
  const { subscribe } = useContext(WebSocketContext);
  useEffect(() => subscribe(eventType, listener), [eventType, listener, subscribe]);
}
