"use client";

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Trash2, RotateCw, Info } from "lucide-react";

type Variant = "danger" | "warning" | "info";

interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: Variant;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const fn = useContext(ConfirmContext);
  if (!fn) throw new Error("useConfirm must be used within ConfirmProvider");
  return fn;
}

const VARIANT_CONFIG: Record<Variant, { icon: typeof AlertTriangle; iconBg: string; iconColor: string; btnColor: string }> = {
  danger: {
    icon: Trash2,
    iconBg: "bg-red-100",
    iconColor: "text-red-600",
    btnColor: "bg-red-600 hover:bg-red-700 focus:ring-red-500",
  },
  warning: {
    icon: RotateCw,
    iconBg: "bg-amber-100",
    iconColor: "text-amber-600",
    btnColor: "bg-amber-500 hover:bg-amber-600 focus:ring-amber-400",
  },
  info: {
    icon: Info,
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
    btnColor: "bg-blue-600 hover:bg-blue-700 focus:ring-blue-500",
  },
};

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ConfirmOptions>({
    title: "",
    message: "",
  });

  const resolveRef = useRef<((val: boolean) => void) | null>(null);

  const confirm: ConfirmFn = useCallback((opts) => {
    setOptions(opts);
    setOpen(true);
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
    });
  }, []);

  const handleConfirm = () => {
    setOpen(false);
    resolveRef.current?.(true);
    resolveRef.current = null;
  };

  const handleCancel = () => {
    setOpen(false);
    resolveRef.current?.(false);
    resolveRef.current = null;
  };

  const variant = options.variant || "info";
  const config = VARIANT_CONFIG[variant];
  const Icon = config.icon;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {open && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px] animate-in fade-in duration-150"
            onClick={handleCancel}
          />
          {/* Dialog */}
          <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-[380px] mx-4 animate-in zoom-in-95 fade-in duration-200">
            <div className="p-6">
              {/* Icon */}
              <div className={`w-11 h-11 rounded-full ${config.iconBg} flex items-center justify-center mb-4`}>
                <Icon className={`w-5 h-5 ${config.iconColor}`} />
              </div>
              {/* Title */}
              <h3 className="text-base font-semibold text-gray-900 mb-1">
                {options.title}
              </h3>
              {/* Message */}
              <p className="text-sm text-gray-500 leading-relaxed">
                {options.message}
              </p>
            </div>
            {/* Actions */}
            <div className="flex items-center justify-end gap-2.5 px-6 pb-5">
              <button
                onClick={handleCancel}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-200 transition-colors"
              >
                {options.cancelLabel || "Cancel"}
              </button>
              <button
                onClick={handleConfirm}
                autoFocus
                className={`px-4 py-2 text-sm font-medium text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-offset-1 transition-colors ${config.btnColor}`}
              >
                {options.confirmLabel || "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
