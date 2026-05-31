"use client";

import { useState } from "react";
import { Sparkles, RefreshCw } from "lucide-react";
import { AIInsightsTable } from "@/components/AIInsightsTable";
import { fetchAIInsightsSummary } from "@/lib/api";
import { useQueryClient, useQuery } from "@tanstack/react-query";

const TYPE_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "concall", label: "Concall" },
  { value: "investor_presentation", label: "Investor Presentation" },
  { value: "monthly_business_update", label: "Monthly Business Update" },
];

const STATUS_OPTIONS = [
  { value: "", label: "All Status" },
  { value: "completed", label: "Completed" },
  { value: "pending", label: "Queued" },
  { value: "processing", label: "Extracting" },
  { value: "failed", label: "Failed" },
];

export default function AIInsightsPage() {
  const [perPage, setPerPage] = useState(30);
  const [insightType, setInsightType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();

  const filters = {
    insight_type: insightType || undefined,
    status: status || undefined,
    symbol: search || undefined,
    per_page: perPage,
  };

  // Summary counts — single endpoint
  const { data: summary } = useQuery({
    queryKey: ["ai-insights-summary"],
    queryFn: fetchAIInsightsSummary,
    staleTime: 15_000,
  });

  const counts = {
    total: summary?.total || 0,
    completed: summary?.completed || 0,
    pending: summary?.in_progress || 0,
    failed: summary?.failed || 0,
  };

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["ai-insights-list"] });
    queryClient.invalidateQueries({ queryKey: ["ai-insights-summary"] });
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="w-5 h-5 text-violet-500" />
          <h1 className="text-lg font-bold text-gray-800">AI Insights</h1>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full font-medium">
            {counts.total} total
          </span>
        </div>
        <button
          onClick={handleRefresh}
          className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Summary Counts */}
      <div className="grid grid-cols-4 gap-3">
        <SummaryCard label="Total Extracted" value={counts.completed} color="text-green-600" bg="bg-green-50" />
        <SummaryCard label="In Queue" value={counts.pending} color="text-amber-600" bg="bg-amber-50" />
        <SummaryCard label="Failed" value={counts.failed} color="text-red-600" bg="bg-red-50" />
        <SummaryCard label="Total" value={counts.total} color="text-gray-700" bg="bg-gray-50" />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={insightType}
          onChange={(e) => setInsightType(e.target.value)}
          className="text-xs border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
        >
          {TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="text-xs border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Search symbol..."
          value={search}
          onChange={(e) => setSearch(e.target.value.toUpperCase())}
          className="text-xs border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none w-36"
        />

        <select
          value={perPage}
          onChange={(e) => setPerPage(Number(e.target.value))}
          className="text-xs border border-gray-300 rounded-lg px-3 py-2 bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
        >
          <option value={20}>20 per page</option>
          <option value={30}>30 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
        </select>
      </div>

      {/* Table */}
      <AIInsightsTable filters={filters} perPage={perPage} />
    </div>
  );
}

function SummaryCard({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className={`rounded-xl border border-gray-200 p-3 ${bg}`}>
      <div className={`text-xl font-bold ${color}`}>{value.toLocaleString()}</div>
      <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wider mt-0.5">{label}</div>
    </div>
  );
}
