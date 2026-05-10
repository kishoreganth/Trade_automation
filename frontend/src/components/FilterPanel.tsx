"use client";

import { useState } from "react";
import { Search, RefreshCw } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSectors } from "@/lib/api";

interface FilterPanelProps {
  filters?: Record<string, string>;
  onChange?: (key: string, value: string) => void;
  showSearch?: boolean;
}

export function FilterPanel({ filters = {}, onChange, showSearch = true }: FilterPanelProps) {
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();
  const { data: sectorsData } = useQuery({
    queryKey: ["sectors"],
    queryFn: fetchSectors,
    staleTime: 300_000,
  });

  const sectors: string[] = sectorsData?.sectors || [];

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["messages"] });
    queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  return (
    <div className="flex flex-wrap items-center gap-3 bg-white rounded-xl border border-gray-200 p-3 shadow-sm">
      {showSearch && (
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search symbol, company, sector..."
            className="input pl-8 w-52 text-xs"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              onChange?.("search", e.target.value);
            }}
          />
        </div>
      )}

      <div className="flex items-center gap-1 text-xs text-gray-500">
        <span>EXCHANGE</span>
        <select
          className="input text-xs py-1 px-2"
          value={filters.exchange || ""}
          onChange={(e) => onChange?.("exchange", e.target.value)}
        >
          <option value="">All</option>
          <option value="BSE">BSE</option>
          <option value="NSE">NSE</option>
        </select>
      </div>

      <div className="flex items-center gap-1 text-xs text-gray-500">
        <span>SECTOR</span>
        <select
          className="input text-xs py-1 px-2"
          value={filters.sector || ""}
          onChange={(e) => onChange?.("sector", e.target.value)}
        >
          <option value="">All Sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-1 text-xs text-gray-500">
        <span>SHOW</span>
        <select
          className="input text-xs py-1 px-2"
          value={filters.limit || "50"}
          onChange={(e) => onChange?.("limit", e.target.value)}
        >
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100">100</option>
          <option value="200">200</option>
        </select>
      </div>

      <button
        onClick={handleRefresh}
        className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5 ml-auto"
      >
        <RefreshCw className="w-3.5 h-3.5" />
        Refresh
      </button>
    </div>
  );
}
