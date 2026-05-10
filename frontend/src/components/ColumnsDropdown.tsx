"use client";

import { useState, useRef, useEffect } from "react";
import { Settings2, Search } from "lucide-react";

interface Column {
  key: string;
  label: string;
}

interface ColumnsDropdownProps {
  columns: Column[];
  visible: string[];
  onChange: (cols: string[]) => void;
}

export function ColumnsDropdown({ columns, visible, onChange }: ColumnsDropdownProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = columns.filter((c) => c.label.toLowerCase().includes(search.toLowerCase()));

  const toggle = (key: string) => {
    onChange(visible.includes(key) ? visible.filter((k) => k !== key) : [...visible, key]);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`text-xs px-3 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors ${open ? "bg-primary text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}
      >
        <Settings2 className="w-3 h-3" /> Columns
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-56 bg-gray-900 rounded-xl shadow-2xl border border-gray-700 z-50 overflow-hidden">
          <div className="p-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
              <input
                type="text"
                placeholder="Search columns..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-gray-800 text-gray-200 text-xs rounded-lg pl-7 pr-2 py-1.5 border border-gray-700 outline-none focus:border-primary placeholder-gray-500"
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto px-2 pb-2 space-y-0.5">
            {filtered.map((col) => (
              <label key={col.key} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-800 cursor-pointer text-xs text-gray-200">
                <input
                  type="checkbox"
                  checked={visible.includes(col.key)}
                  onChange={() => toggle(col.key)}
                  className="rounded border-gray-600 bg-gray-700 text-primary focus:ring-primary w-3.5 h-3.5"
                />
                {col.label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
