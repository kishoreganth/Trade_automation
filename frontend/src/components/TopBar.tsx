"use client";

import { useWebSocket } from "@/hooks/useWebSocket";
import { cn } from "@/lib/utils";
import { Settings, Maximize2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/lib/api";

interface HealthPayload {
  status?: string;
  postgres?: string;
  redis?: string;
  websocket?: { local_connections?: number; total_connections?: number; unique_ips?: number };
}

export function TopBar() {
  const { status, lastUpdate } = useWebSocket();

  const { data: health, isError: healthError } = useQuery<HealthPayload>({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: false,
  });

  const wsStatusColor =
    status === "connected"
      ? "bg-accent-green"
      : status === "reconnecting"
      ? "bg-accent-amber"
      : "bg-accent-amber";

  const wsStatusText =
    status === "connected"
      ? "Connected"
      : status === "reconnecting"
      ? "Reconnecting\u2026"
      : "Disconnected";

  const lastUpdateTime = lastUpdate
    ? new Date(lastUpdate).toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      })
    : "--:--:--";

  let backendColor = "bg-accent-amber";
  let backendText = "Checking\u2026";
  if (healthError || !health) {
    backendColor = "bg-red-500";
    backendText = "Backend offline";
  } else if (health.status === "ok") {
    backendColor = "bg-accent-green";
    backendText = "Backend ok";
  } else {
    backendColor = "bg-accent-amber";
    backendText = `Backend degraded (pg=${health.postgres}, redis=${health.redis})`;
  }

  return (
    <header className="h-12 bg-navy-800 border-b border-navy-600 flex items-center justify-between px-4">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-primary/20 flex items-center justify-center">
          <svg className="w-4 h-4 text-primary" fill="currentColor" viewBox="0 0 20 20">
            <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zm6-4a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zm6-3a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
          </svg>
        </div>
        <span className="text-sm font-bold text-white">StockHIFI</span>
        <span className="text-gray-500 text-sm">|</span>
        <span className="text-sm text-gray-400">Trading Dashboard</span>
      </div>

      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-2" title={backendText}>
          <span className={cn("w-2 h-2 rounded-full", backendColor)} />
          <span className="text-gray-400 text-xs">{backendText}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("w-2 h-2 rounded-full animate-pulse", wsStatusColor)} />
          <span className="text-gray-400 text-xs">{wsStatusText}</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-500">Last update: {lastUpdateTime}</span>
        <button className="text-gray-500 hover:text-gray-300 transition-colors">
          <Settings className="w-4 h-4" />
        </button>
        <button className="text-gray-500 hover:text-gray-300 transition-colors">
          <Maximize2 className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
