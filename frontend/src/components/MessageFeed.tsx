"use client";

import { useState, useEffect } from "react";
import { useMessages } from "@/hooks/useMessages";
import { useConcallInsight } from "@/hooks/useConcallInsights";
import { useAnnouncementInsight } from "@/hooks/useInsights";
import { ExternalLink, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertTriangle, RefreshCw, Sparkles } from "lucide-react";
import { ConcallInsightCard } from "./ConcallInsightCard";
import { AIInsightCard } from "./AIInsightCard";

interface MessageFeedProps {
  option?: string;
  filters?: Record<string, string>;
}

export function MessageFeed({ option = "all", filters = {} }: MessageFeedProps) {
  const [page, setPage] = useState(1);
  const perPage = Number(filters.limit) || 50;

  useEffect(() => {
    setPage(1);
  }, [option, filters.exchange, filters.sector, filters.search, perPage]);

  const { limit: _, ...apiFilters } = filters;
  const { data, isLoading, isError, error, refetch, isFetching } = useMessages(page, perPage, option, apiFilters);

  const messages = data?.messages || [];
  const total = data?.total || 0;
  const totalPages = data?.total_pages || 1;

  if (isLoading && !data) return <TableSkeleton />;

  if (isError && !data) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    return (
      <div className="bg-white rounded-xl border border-red-200 p-6 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-sm font-semibold text-red-700">
            Could not load messages{status ? ` (HTTP ${status})` : ""}
          </div>
          <div className="text-xs text-gray-600 mt-1">
            {status === 429
              ? "Backend rate-limit hit. Will retry automatically; click Retry to retry now."
              : "Backend may be restarting or unreachable. Retrying will not refresh data until backend responds."}
          </div>
          <button
            onClick={() => refetch()}
            className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
          >
            <RefreshCw className={`w-3 h-3 ${isFetching ? "animate-spin" : ""}`} /> Retry now
          </button>
        </div>
      </div>
    );
  }

  if (!messages.length) {
    return (
      <div className="text-center text-gray-400 py-12 bg-white rounded-xl border border-gray-200">
        No announcements found
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
              <th className="text-left px-4 py-2.5 font-semibold">Time</th>
              <th className="text-left px-4 py-2.5 font-semibold">Exchange</th>
              <th className="text-left px-4 py-2.5 font-semibold">Symbol</th>
              <th className="text-left px-4 py-2.5 font-semibold">Company</th>
              <th className="text-left px-4 py-2.5 font-semibold">Sector</th>
              <th className="text-left px-4 py-2.5 font-semibold">Description</th>
              <th className="text-left px-4 py-2.5 font-semibold">File</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {messages.map((msg: Record<string, string>) => {
              const isConcall = option === "concall" || option === "result_concall" || msg.option === "concall" || msg.option === "result_concall";
              const isAnnouncement = option === "investor_presentation" || option === "monthly_business_update"
                || msg.option === "investor_presentation" || msg.option === "monthly_business_update";
              const announcementType = (msg.option === "investor_presentation" || option === "investor_presentation")
                ? "investor_presentation" as const
                : "monthly_business_update" as const;
              return (
                <MessageRow key={msg.id} msg={msg} isConcall={isConcall} isAnnouncement={isAnnouncement} announcementType={announcementType} />
              );
            })}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} perPage={perPage} onPageChange={setPage} position="bottom" />
    </div>
  );
}

function ExtractionStatusBadge({ status }: { status: string | undefined | null }) {
  if (!status) return null;
  const config: Record<string, { bg: string; text: string; label: string; pulse?: boolean }> = {
    pending: { bg: "bg-amber-100", text: "text-amber-700", label: "QUEUED", pulse: true },
    queued: { bg: "bg-amber-100", text: "text-amber-700", label: "QUEUED", pulse: true },
    processing: { bg: "bg-blue-100", text: "text-blue-700", label: "EXTRACTING", pulse: true },
    completed: { bg: "bg-green-100", text: "text-green-700", label: "SUCCESS" },
    failed: { bg: "bg-red-100", text: "text-red-700", label: "FAILED" },
  };
  const c = config[status];
  if (!c) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded ${c.bg} ${c.text}`}>
      {c.pulse && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {c.label}
    </span>
  );
}

function MessageRow({ msg, isConcall, isAnnouncement, announcementType }: {
  msg: Record<string, string>;
  isConcall: boolean;
  isAnnouncement: boolean;
  announcementType: "investor_presentation" | "monthly_business_update";
}) {
  const [showInsight, setShowInsight] = useState(false);
  const hasAI = (isConcall || isAnnouncement) && msg.id;

  const msgId = hasAI ? Number(msg.id) : null;
  const concallQuery = useConcallInsight(isConcall && showInsight ? msgId : null, showInsight);
  const announcementQuery = useAnnouncementInsight(isAnnouncement && showInsight ? msgId : null, showInsight);
  const insightStatus = isConcall
    ? concallQuery.data?.extraction_status
    : isAnnouncement
    ? announcementQuery.data?.extraction_status
    : undefined;

  return (
    <>
      <tr className="hover:bg-gray-50 transition-colors">
        <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
          {msg.timestamp
            ? new Date(msg.timestamp).toLocaleString("en-US", {
                month: "numeric",
                day: "numeric",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
                hour12: true,
              })
            : ""}
        </td>
        <td className="px-4 py-2.5">
          <span className={msg.exchange === "BSE" ? "badge-bse" : "badge-nse"}>
            {msg.exchange || "NSE"}
          </span>
        </td>
        <td className="px-4 py-2.5 text-primary font-semibold">{msg.symbol || "\u2014"}</td>
        <td className="px-4 py-2.5 text-gray-700 max-w-[200px] truncate">{msg.company_name || "\u2014"}</td>
        <td className="px-4 py-2.5 text-gray-500 text-xs">{msg.sector || "\u2014"}</td>
        <td className="px-4 py-2.5 text-gray-600 text-xs max-w-[400px] truncate">
          {msg.description || msg.message || "\u2014"}
        </td>
        <td className="px-4 py-2.5">
          <div className="flex items-center gap-2">
            {msg.file_url ? (
              <a href={msg.file_url} target="_blank" rel="noopener noreferrer" className="text-primary text-xs hover:underline flex items-center gap-1">
                View File <ExternalLink className="w-3 h-3" />
              </a>
            ) : (
              <span className="text-gray-300 text-xs">{"\u2014"}</span>
            )}
            {hasAI && (
              <>
                <ExtractionStatusBadge status={insightStatus} />
                <button
                  onClick={() => setShowInsight(!showInsight)}
                  className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md transition-colors border ${
                    showInsight
                      ? isAnnouncement ? "bg-violet-100 text-violet-700 border-violet-200" : "bg-indigo-100 text-indigo-700 border-indigo-200"
                      : isAnnouncement ? "bg-violet-50 text-violet-600 hover:bg-violet-100 border-violet-100" : "bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border-indigo-100"
                  }`}
                >
                  <Sparkles className="w-3 h-3" />
                  AI
                </button>
              </>
            )}
          </div>
        </td>
      </tr>
      {isConcall && showInsight && msg.id && (
        <tr>
          <td colSpan={7} className="px-4 py-0 bg-gray-50/50">
            <ConcallInsightCard
              messageId={Number(msg.id)}
              symbol={msg.symbol || ""}
              fileUrl={msg.file_url}
              companyName={msg.company_name}
              exchange={msg.exchange}
            />
          </td>
        </tr>
      )}
      {isAnnouncement && showInsight && msg.id && (
        <tr>
          <td colSpan={7} className="px-4 py-0 bg-gray-50/50">
            <AIInsightCard
              messageId={Number(msg.id)}
              symbol={msg.symbol || ""}
              fileUrl={msg.file_url}
              companyName={msg.company_name}
              exchange={msg.exchange}
              announcementType={announcementType}
            />
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

  const handlePageInput = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      const val = Math.min(Math.max(1, Number((e.target as HTMLInputElement).value)), totalPages);
      if (!isNaN(val)) onPageChange(val);
    }
  };

  return (
    <div className={`flex items-center justify-between px-4 py-1.5 text-[10px] text-gray-500 bg-gray-50 ${position === "top" ? "border-b" : "border-t"} border-gray-200`}>
      <span>
        Showing <span className="font-semibold text-gray-700">{start}</span>–<span className="font-semibold text-gray-700">{end}</span> of{" "}
        <span className="font-semibold text-gray-700">{total.toLocaleString()}</span>
      </span>

      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(1)}
          disabled={page <= 1}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          title="First page"
        >
          <ChevronsLeft className="w-4 h-4" />
        </button>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Previous page"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>

        <span className="px-2 font-medium text-gray-700 flex items-center gap-1">
          Page
          <input
            type="number"
            min={1}
            max={totalPages}
            defaultValue={page}
            key={page}
            onKeyDown={handlePageInput}
            onBlur={(e) => {
              const val = Math.min(Math.max(1, Number(e.target.value)), totalPages);
              if (!isNaN(val) && val !== page) onPageChange(val);
            }}
            className="w-9 text-center border border-gray-300 rounded px-1 py-0.5 text-[10px] font-semibold"
          />
          of {totalPages}
        </span>

        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Next page"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={() => onPageChange(totalPages)}
          disabled={page >= totalPages}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
          title="Last page"
        >
          <ChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="animate-pulse flex gap-4">
          <div className="h-4 bg-gray-200 rounded w-24" />
          <div className="h-4 bg-gray-200 rounded w-12" />
          <div className="h-4 bg-gray-200 rounded w-16" />
          <div className="h-4 bg-gray-200 rounded flex-1" />
        </div>
      ))}
    </div>
  );
}
