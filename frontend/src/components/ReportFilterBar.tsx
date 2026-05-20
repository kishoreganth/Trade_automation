"use client";

import { RotateCcw } from "lucide-react";
import { usePEFilters } from "@/hooks/usePEAnalysis";

interface ReportFilters {
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}

interface ReportFilterBarProps {
  filters: ReportFilters;
  onChange: (filters: ReportFilters) => void;
}

export function ReportFilterBar({ filters, onChange }: ReportFilterBarProps) {
  const { data: filterOptions } = usePEFilters();

  const handleChange = (key: keyof ReportFilters, value: string) => {
    onChange({ ...filters, [key]: value || undefined });
  };

  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <div className="flex flex-wrap items-center gap-2 bg-white rounded-xl border border-gray-200 px-4 py-2.5 shadow-sm">
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide mr-1">Filters</span>

      <FilterSelect
        value={filters.year || ""}
        options={filterOptions?.years || ["2026", "2025"]}
        onChange={(v) => handleChange("year", v)}
        placeholder="All Years"
        formatLabel={(v) => `FY${v.slice(-2)}`}
      />
      <FilterSelect
        value={filters.quarter || ""}
        options={filterOptions?.quarters || ["Q1", "Q2", "Q3", "Q4"]}
        onChange={(v) => handleChange("quarter", v)}
        placeholder="All Quarters"
      />
      <FilterSelect
        value={filters.exchange || ""}
        options={filterOptions?.exchanges || ["BSE", "NSE"]}
        onChange={(v) => handleChange("exchange", v)}
        placeholder="All Exchanges"
      />
      <FilterSelect
        value={filters.sector || ""}
        options={filterOptions?.sectors || []}
        onChange={(v) => handleChange("sector", v)}
        placeholder="All Sectors"
      />

      {hasFilters && (
        <button
          onClick={() => onChange({})}
          className="ml-1 flex items-center gap-1 text-xs text-red-500 border border-red-200 rounded-lg px-2.5 py-1.5 hover:bg-red-50 hover:border-red-300 transition-all active:scale-95"
        >
          <RotateCcw className="w-3 h-3" />
          Reset
        </button>
      )}
    </div>
  );
}

function FilterSelect({
  value,
  options,
  onChange,
  placeholder,
  formatLabel,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder: string;
  formatLabel?: (v: string) => string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="text-xs py-1.5 px-2.5 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 font-medium focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary hover:border-gray-300 transition-colors cursor-pointer"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {formatLabel ? formatLabel(o) : o}
        </option>
      ))}
    </select>
  );
}
