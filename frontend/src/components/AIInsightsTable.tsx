"use client";

import { useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Sparkles,
  ExternalLink,
} from "lucide-react";
import { useAIInsightsList, type AIInsightsFilters } from "@/hooks/useAIInsightsList";
import { cn } from "@/lib/utils";

interface AIInsightsTableProps {
  filters: AIInsightsFilters;
  perPage: number;
}

const statusConfig: Record<string, { bg: string; text: string; label: string; pulse?: boolean }> = {
  pending: { bg: "bg-amber-100", text: "text-amber-700", label: "QUEUED", pulse: true },
  queued: { bg: "bg-amber-100", text: "text-amber-700", label: "QUEUED", pulse: true },
  processing: { bg: "bg-blue-100", text: "text-blue-700", label: "EXTRACTING", pulse: true },
  completed: { bg: "bg-green-100", text: "text-green-700", label: "SUCCESS" },
  failed: { bg: "bg-red-100", text: "text-red-700", label: "FAILED" },
};

const outlookConfig: Record<string, { bg: string; text: string; label: string }> = {
  bullish: { bg: "bg-emerald-100", text: "text-emerald-700", label: "BULLISH" },
  positive: { bg: "bg-emerald-100", text: "text-emerald-700", label: "POSITIVE" },
  neutral: { bg: "bg-amber-100", text: "text-amber-700", label: "NEUTRAL" },
  mixed: { bg: "bg-amber-100", text: "text-amber-700", label: "MIXED" },
  cautious: { bg: "bg-red-100", text: "text-red-700", label: "CAUTIOUS" },
  negative: { bg: "bg-red-100", text: "text-red-700", label: "NEGATIVE" },
};

const typeLabels: Record<string, string> = {
  concall: "Concall",
  investor_presentation: "Investor Pres",
  monthly_business_update: "Monthly Update",
};

function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const c = statusConfig[status];
  if (!c) return null;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded", c.bg, c.text)}>
      {c.pulse && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {c.label}
    </span>
  );
}

function OutlookBadge({ outlook }: { outlook: string | null | undefined }) {
  if (!outlook) return null;
  const c = outlookConfig[outlook];
  if (!c) return null;
  return (
    <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", c.bg, c.text)}>
      {c.label}
    </span>
  );
}

export function AIInsightsTable({ filters, perPage }: AIInsightsTableProps) {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useAIInsightsList({ ...filters, page, per_page: perPage });

  const insights = data?.insights || [];
  const total = data?.total || 0;
  const totalPages = data?.total_pages || 1;

  if (isLoading && !data) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="space-y-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="animate-pulse flex gap-4">
              <div className="h-4 bg-gray-200 rounded w-16" />
              <div className="h-4 bg-gray-200 rounded w-20" />
              <div className="h-4 bg-gray-200 rounded w-24" />
              <div className="h-4 bg-gray-200 rounded flex-1" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (isError && !data) {
    return (
      <div className="bg-white rounded-xl border border-red-200 p-6 text-sm text-red-700">
        Failed to load insights. Please try refreshing.
      </div>
    );
  }

  if (!insights.length) {
    return (
      <div className="text-center text-gray-400 py-12 bg-white rounded-xl border border-gray-200">
        No AI insights found for the selected filters.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
      <Pagination page={page} totalPages={totalPages} total={total} perPage={perPage} onPageChange={setPage} position="top" />

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-[11px] text-gray-600 uppercase font-bold bg-gray-50">
              <th className="text-left px-3 py-2.5 font-semibold">Status</th>
              <th className="text-left px-3 py-2.5 font-semibold">Symbol</th>
              <th className="text-left px-3 py-2.5 font-semibold">Company</th>
              <th className="text-left px-3 py-2.5 font-semibold">Type</th>
              <th className="text-left px-3 py-2.5 font-semibold">Quarter</th>
              <th className="text-left px-3 py-2.5 font-semibold">Outlook</th>
              <th className="text-left px-3 py-2.5 font-semibold">Summary</th>
              <th className="text-left px-3 py-2.5 font-semibold">Exchange</th>
              <th className="text-left px-3 py-2.5 font-semibold">Date</th>
              <th className="text-left px-3 py-2.5 font-semibold">PDF</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {insights.map((row: Record<string, unknown>) => (
              <InsightRow key={`${row.insight_type}-${row.id}`} row={row} />
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} perPage={perPage} onPageChange={setPage} position="bottom" />
    </div>
  );
}

function InsightRow({ row }: { row: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        className="hover:bg-gray-50 transition-colors cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-3 py-2.5">
          <StatusBadge status={row.extraction_status as string} />
        </td>
        <td className="px-3 py-2.5 text-primary font-semibold text-xs">
          {(row.stock_symbol as string) || "\u2014"}
        </td>
        <td className="px-3 py-2.5 text-gray-700 text-xs max-w-[160px] truncate">
          {(row.company_name as string) || "\u2014"}
        </td>
        <td className="px-3 py-2.5">
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
            {typeLabels[(row.insight_type as string)] || (row.insight_type as string)}
          </span>
        </td>
        <td className="px-3 py-2.5 text-xs text-gray-600 whitespace-nowrap">
          {row.quarter !== "TBD" ? `${row.quarter} ${row.financial_year}` : "\u2014"}
        </td>
        <td className="px-3 py-2.5">
          <OutlookBadge outlook={row.management_outlook as string} />
        </td>
        <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[300px] truncate">
          {(row.executive_summary as string) || (row.investment_thesis as string) || "\u2014"}
        </td>
        <td className="px-3 py-2.5">
          <span className={(row.exchange as string) === "BSE" ? "badge-bse" : "badge-nse"}>
            {(row.exchange as string) || "BSE"}
          </span>
        </td>
        <td className="px-3 py-2.5 text-[10px] text-gray-500 whitespace-nowrap">
          {row.updated_at
            ? new Date(row.updated_at as string).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
            : "\u2014"}
        </td>
        <td className="px-3 py-2.5">
          {row.source_pdf_url ? (
            <a
              href={row.source_pdf_url as string}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary text-xs hover:underline flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-3 h-3" />
            </a>
          ) : (
            <span className="text-gray-300 text-xs">{"\u2014"}</span>
          )}
        </td>
      </tr>
      {expanded && row.extraction_status === "completed" && (
        <tr>
          <td colSpan={10} className="px-4 py-3 bg-gray-50/50">
            <div className="space-y-2">
              {row.executive_summary ? (
                <div>
                  <span className="text-[10px] font-semibold text-gray-500 uppercase">Executive Summary</span>
                  <p className="text-sm text-gray-700 mt-0.5">{String(row.executive_summary)}</p>
                </div>
              ) : null}
              {row.investment_thesis ? (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-indigo-50/50 border border-indigo-100">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <span className="text-[10px] font-semibold text-indigo-600 uppercase">Investment Thesis</span>
                    <p className="text-sm text-gray-700 mt-0.5">{String(row.investment_thesis)}</p>
                  </div>
                </div>
              ) : null}
              {row.management_outlook ? (
                <div className="text-xs text-gray-600">
                  <span className="font-medium">Outlook:</span> {String(row.management_outlook)}
                </div>
              ) : null}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Pagination({
  page,
  totalPages,
  total,
  perPage,
  onPageChange,
  position,
}: {
  page: number;
  totalPages: number;
  total: number;
  perPage: number;
  onPageChange: (p: number) => void;
  position: "top" | "bottom";
}) {
  const start = (page - 1) * perPage + 1;
  const end = Math.min(page * perPage, total);

  return (
    <div className={cn(
      "flex items-center justify-between px-4 py-1.5 text-[10px] text-gray-500 bg-gray-50",
      position === "top" ? "border-b" : "border-t",
      "border-gray-200"
    )}>
      <span>
        Showing <span className="font-semibold text-gray-700">{start}</span>–<span className="font-semibold text-gray-700">{end}</span> of{" "}
        <span className="font-semibold text-gray-700">{total.toLocaleString()}</span>
      </span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPageChange(1)} disabled={page <= 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronsLeft className="w-4 h-4" />
        </button>
        <button onClick={() => onPageChange(page - 1)} disabled={page <= 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="px-2 font-medium text-gray-700">
          Page {page} of {totalPages}
        </span>
        <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronRight className="w-4 h-4" />
        </button>
        <button onClick={() => onPageChange(totalPages)} disabled={page >= totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30">
          <ChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
