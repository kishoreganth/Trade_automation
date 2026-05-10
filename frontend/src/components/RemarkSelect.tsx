"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Plus, X, Loader2, Search } from "lucide-react";
import toast from "react-hot-toast";
import {
  fetchValuationOptions,
  createCustomValuation,
  deleteCustomValuation,
} from "@/lib/api";
import { useConfirm } from "./ConfirmDialog";
import {
  FALLBACK_VALUATION_OPTIONS,
  valuationLabel,
  type ValuationOption,
} from "@/lib/valuationOptions";

interface RemarkSelectProps {
  value: string;
  onChange: (value: string) => void;
}

// Layout sizing — keep dropdown bounded so Add/Cancel of the inline-add panel
// always stay visible inside the parent drawer.
const ROW_PX = 36;            // ~px height of one option row (px-3 py-2 + 14px text)
const VISIBLE_ROWS = 6;       // show ~6 options before list starts to scroll
const LIST_MAX_PX = ROW_PX * VISIBLE_ROWS;
const MENU_MAX_PX = 440;      // total menu cap (search + list + footer)
const MENU_MIN_BELOW_PX = 260; // if less than this below trigger, flip up

/**
 * Searchable dropdown with custom-add + per-row delete.
 *
 * Visual structure (top → bottom, all sticky except the list):
 *   1. Search input               (fixed)
 *   2. "—" clear-selection row    (fixed)
 *   3. Scrollable options list    (capped at VISIBLE_ROWS rows; scrolls if more)
 *   4. Footer:
 *        a. "+ Add custom..." button   OR
 *        b. inline { input, Add, Cancel } panel — always fully visible
 *
 * Backend: /api/pe_analysis/valuation_options (GET / POST / DELETE).
 * Built-ins (defined in backend/app/constants.py) cannot be deleted; only
 * `is_custom: true` rows show the red ✕ on hover.
 */
export function RemarkSelect({ value, onChange }: RemarkSelectProps) {
  const confirmDialog = useConfirm();
  const queryClient = useQueryClient();
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const customInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [busyValue, setBusyValue] = useState<string | null>(null);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});

  const { data } = useQuery({
    queryKey: ["valuation-options"],
    queryFn: fetchValuationOptions,
    staleTime: 60 * 60_000,
    retry: false,
  });
  const options: ValuationOption[] = (data?.options as ValuationOption[]) || FALLBACK_VALUATION_OPTIONS;

  const filteredOptions = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.value.toLowerCase().includes(q) ||
        o.label.toLowerCase().includes(q),
    );
  }, [options, search]);

  // Compute menu coordinates from the trigger button's bounding rect. We use
  // position: fixed so the menu escapes any ancestor `overflow-y: auto` (e.g.
  // the EditDrawer scroll area) — that was clipping the dropdown footer.
  const positionMenu = useCallback(() => {
    const btn = triggerRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const vh = window.innerHeight;
    const spaceBelow = vh - rect.bottom - 8;
    const spaceAbove = rect.top - 8;
    const placeAbove = spaceBelow < MENU_MIN_BELOW_PX && spaceAbove > spaceBelow;

    if (placeAbove) {
      setMenuStyle({
        position: "fixed",
        bottom: vh - rect.top + 4,
        left: rect.left,
        width: rect.width,
        maxHeight: `min(${MENU_MAX_PX}px, ${Math.max(spaceAbove, 220)}px)`,
      });
    } else {
      setMenuStyle({
        position: "fixed",
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        maxHeight: `min(${MENU_MAX_PX}px, ${Math.max(spaceBelow, 220)}px)`,
      });
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    positionMenu();
    // capture-phase so we catch scrolls in nested containers (e.g. drawer body)
    window.addEventListener("scroll", positionMenu, true);
    window.addEventListener("resize", positionMenu);
    return () => {
      window.removeEventListener("scroll", positionMenu, true);
      window.removeEventListener("resize", positionMenu);
    };
  }, [open, positionMenu, adding]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      const inTrigger = wrapRef.current?.contains(target);
      const inMenu = menuRef.current?.contains(target);
      if (!inTrigger && !inMenu) {
        setOpen(false);
        setAdding(false);
        setDraft("");
        setSearch("");
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  useEffect(() => {
    if (open && !adding) searchInputRef.current?.focus();
  }, [open, adding]);

  useEffect(() => {
    if (adding) customInputRef.current?.focus();
  }, [adding]);

  const handlePick = (v: string) => {
    onChange(v);
    setOpen(false);
    setAdding(false);
    setDraft("");
    setSearch("");
  };

  const handleAdd = async () => {
    const raw = draft.trim();
    if (!raw) return;
    setBusyValue("__add__");
    try {
      const created = await createCustomValuation(raw, raw);
      await queryClient.invalidateQueries({ queryKey: ["valuation-options"] });
      toast.success(`Added "${created.label}"`);
      onChange(created.value);
      setAdding(false);
      setDraft("");
      setOpen(false);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Could not add custom remark");
    } finally {
      setBusyValue(null);
    }
  };

  const handleDelete = async (opt: ValuationOption) => {
    if (!opt.is_custom) return;
    const ok = await confirmDialog({
      title: "Delete custom remark",
      message: `Remove "${opt.label}" from your valuation options? Rows already tagged with it won't be affected.`,
      confirmLabel: "Delete",
      cancelLabel: "Keep",
      variant: "danger",
    });
    if (!ok) return;
    setBusyValue(opt.value);
    try {
      const res = await deleteCustomValuation(opt.value);
      await queryClient.invalidateQueries({ queryKey: ["valuation-options"] });
      if (res?.rows_still_using > 0) {
        toast.success(
          `Deleted — ${res.rows_still_using} row(s) still tagged with "${opt.value}". Edit them to clear.`,
          { duration: 4500 },
        );
      } else {
        toast.success(`Deleted "${opt.label}"`);
      }
      if (value === opt.value) onChange("");
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Could not delete");
    } finally {
      setBusyValue(null);
    }
  };

  const currentLabel = value ? valuationLabel(value, options).toUpperCase() : "—";

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="w-full text-left text-sm border border-gray-300 rounded-md px-3 py-2 bg-white flex items-center justify-between hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-primary/30"
      >
        <span className={value ? "text-gray-900" : "text-gray-400"}>{currentLabel}</span>
        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          ref={menuRef}
          className="z-50 bg-white border border-gray-200 rounded-md shadow-xl flex flex-col overflow-hidden"
          style={menuStyle}
        >
          {/* 1. Search (fixed top) */}
          <div className="px-2 py-2 border-b border-gray-100 bg-white flex-shrink-0">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    if (search) setSearch("");
                    else setOpen(false);
                  }
                }}
                placeholder="Search remarks..."
                className="w-full pl-7 pr-7 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-600"
                  title="Clear search"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* 2. Clear-selection row (fixed) */}
          {!search && (
            <button
              type="button"
              onClick={() => handlePick("")}
              className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-gray-50 border-b border-gray-100 flex-shrink-0"
            >
              —
            </button>
          )}

          {/* 3. Scrollable list — capped at VISIBLE_ROWS */}
          <div
            className="overflow-y-auto min-h-0 flex-1"
            style={{ maxHeight: `${LIST_MAX_PX}px` }}
          >
            {filteredOptions.length === 0 ? (
              <div className="px-3 py-4 text-sm text-gray-400 text-center">
                No remarks match &quot;{search}&quot;
              </div>
            ) : (
              filteredOptions.map((opt) => {
                const isActive = opt.value === value;
                const isBusy = busyValue === opt.value;
                return (
                  <div
                    key={opt.value}
                    className={`group flex items-center justify-between px-3 py-2 text-sm cursor-pointer transition-colors ${
                      isActive ? "bg-primary/10 text-primary font-medium" : "hover:bg-gray-50 text-gray-800"
                    }`}
                    onClick={() => handlePick(opt.value)}
                    style={{ minHeight: `${ROW_PX}px` }}
                  >
                    <span className="truncate flex items-center gap-2">
                      {opt.label.toUpperCase()}
                      {opt.is_custom && (
                        <span className="text-[9px] uppercase tracking-wider text-gray-400 font-medium bg-gray-100 px-1.5 py-0.5 rounded">
                          custom
                        </span>
                      )}
                    </span>
                    {opt.is_custom && (
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(opt);
                        }}
                        className="ml-2 hidden group-hover:flex items-center justify-center w-5 h-5 rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                        title={`Delete "${opt.label}"`}
                      >
                        {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* 4. Sticky footer — Add-custom button OR inline add panel.
                 ALWAYS visible: even when adding, this never gets pushed below
                 the dropdown's max-height because the list above scrolls. */}
          <div className="border-t border-gray-100 bg-gray-50 flex-shrink-0">
            {!adding ? (
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="w-full flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/5"
              >
                <Plus className="w-3.5 h-3.5" /> Add custom...
              </button>
            ) : (
              <div className="px-3 py-2.5 space-y-2">
                <input
                  ref={customInputRef}
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAdd();
                    } else if (e.key === "Escape") {
                      setAdding(false);
                      setDraft("");
                    }
                  }}
                  placeholder="e.g. UNDERVALUED"
                  className="w-full text-sm border border-gray-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary/30"
                  maxLength={50}
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleAdd}
                    disabled={!draft.trim() || busyValue === "__add__"}
                    className="flex-1 inline-flex items-center justify-center gap-1 px-3 py-1.5 rounded bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {busyValue === "__add__" ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Adding...
                      </>
                    ) : (
                      <>
                        <Plus className="w-3.5 h-3.5" /> Add
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAdding(false);
                      setDraft("");
                    }}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-gray-200 hover:bg-gray-300 text-gray-700 text-sm font-medium"
                  >
                    <X className="w-3.5 h-3.5" /> Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
