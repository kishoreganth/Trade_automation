"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X, Check } from "lucide-react";

interface SectorSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}

const ROW_PX = 36;
const VISIBLE_ROWS = 7;
const LIST_MAX_PX = ROW_PX * VISIBLE_ROWS;
const MENU_MAX_PX = 380;
const MENU_MIN_BELOW_PX = 240;

export function SectorSelect({ value, onChange, options }: SectorSelectProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter((s) => s.toLowerCase().includes(q));
  }, [options, search]);

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
        maxHeight: `min(${MENU_MAX_PX}px, ${Math.max(spaceAbove, 200)}px)`,
      });
    } else {
      setMenuStyle({
        position: "fixed",
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        maxHeight: `min(${MENU_MAX_PX}px, ${Math.max(spaceBelow, 200)}px)`,
      });
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    positionMenu();
    window.addEventListener("scroll", positionMenu, true);
    window.addEventListener("resize", positionMenu);
    return () => {
      window.removeEventListener("scroll", positionMenu, true);
      window.removeEventListener("resize", positionMenu);
    };
  }, [open, positionMenu]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!wrapRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  useEffect(() => {
    if (open) searchInputRef.current?.focus();
  }, [open]);

  const handlePick = (v: string) => {
    onChange(v);
    setOpen(false);
    setSearch("");
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="w-full text-left text-sm border border-gray-300 rounded-md px-3 py-2 bg-white flex items-center justify-between hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-primary/30"
      >
        <span className={value ? "text-gray-900" : "text-gray-400"}>{value || "—"}</span>
        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          ref={menuRef}
          className="z-50 bg-white border border-gray-200 rounded-md shadow-xl flex flex-col overflow-hidden"
          style={menuStyle}
        >
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
                placeholder="Search sectors..."
                className="w-full pl-7 pr-7 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-600"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {!search && (
            <button
              type="button"
              onClick={() => handlePick("")}
              className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-gray-50 border-b border-gray-100 flex-shrink-0"
            >
              —
            </button>
          )}

          <div
            className="overflow-y-auto min-h-0 flex-1"
            style={{ maxHeight: `${LIST_MAX_PX}px` }}
          >
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-sm text-gray-400 text-center">
                No sectors match &quot;{search}&quot;
              </div>
            ) : (
              filtered.map((sector) => {
                const isActive = sector === value;
                return (
                  <div
                    key={sector}
                    className={`flex items-center justify-between px-3 py-2 text-sm cursor-pointer transition-colors ${
                      isActive ? "bg-primary/10 text-primary font-medium" : "hover:bg-gray-50 text-gray-800"
                    }`}
                    onClick={() => handlePick(sector)}
                    style={{ minHeight: `${ROW_PX}px` }}
                  >
                    <span className="truncate">{sector}</span>
                    {isActive && <Check className="w-4 h-4 text-primary flex-shrink-0" />}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
