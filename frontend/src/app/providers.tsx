"use client";

import { useEffect } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";
import toast, { Toaster, useToasterStore } from "react-hot-toast";
import { useWebSocket } from "@/hooks/useWebSocket";
import { ConfirmProvider } from "@/components/ConfirmDialog";

const MAX_TOASTS = 3;

function ToastLimiter() {
  const { toasts } = useToasterStore();
  useEffect(() => {
    toasts.filter((t) => t.visible).slice(MAX_TOASTS).forEach((t) => toast.dismiss(t.id));
  }, [toasts]);
  return null;
}

function WebSocketProvider({ children }: { children: React.ReactNode }) {
  useWebSocket();
  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfirmProvider>
        <WebSocketProvider>
          {children}
        </WebSocketProvider>
      </ConfirmProvider>
      <ToastLimiter />
      <Toaster
        position="top-right"
        containerStyle={{ top: 12 }}
        toastOptions={{
          style: { background: "#2a2a3e", color: "#f3f4f6", border: "1px solid #363650" },
          duration: 2000,
        }}
        gutter={8}
      />
    </QueryClientProvider>
  );
}
