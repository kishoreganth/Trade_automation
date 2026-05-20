"use client";

import { useEffect, useCallback } from "react";
import { X, FileText, ExternalLink, MessageSquare } from "lucide-react";
import { useReportDetail } from "@/hooks/usePEAnalysis";
import { fmtNumber } from "@/lib/utils";

interface DrillParams {
  filter_type: string;
  filter_value: string;
  title: string;
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}

interface ReportDrillDrawerProps {
  params: DrillParams | null;
  onClose: () => void;
}

export function ReportDrillDrawer({ params, onClose }: ReportDrillDrawerProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!params) return;
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [params, handleKeyDown]);

  if (!params) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-3xl bg-gray-50 shadow-2xl flex flex-col animate-slide-in-right">
        <DrawerContent params={params} onClose={onClose} />
      </div>
    </div>
  );
}

function DrawerContent({ params, onClose }: { params: DrillParams; onClose: () => void }) {
  const { data, isLoading } = useReportDetail({
    filter_type: params.filter_type,
    filter_value: params.filter_value,
    year: params.year,
    quarter: params.quarter,
    exchange: params.exchange,
    sector: params.sector,
    page: 1,
    per_page: 100,
  });

  const results = data?.results || [];
  const total = data?.total || 0;

  return (
    <>
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-white sticky top-0 z-10">
        <div>
          <h3 className="text-base font-bold text-gray-900">{params.title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {total} stock{total !== 1 ? "s" : ""} found
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-28 bg-white rounded-xl animate-pulse" />
            ))}
          </div>
        ) : results.length === 0 ? (
          <div className="p-10 text-center text-gray-400">No stocks found</div>
        ) : (
          <div className="space-y-3">
            {results.map((row: Record<string, unknown>, idx: number) => (
              <StockCard key={row.stock_symbol as string} row={row} rank={idx + 1} />
            ))}
          </div>
        )}
      </div>

      {total > 100 && (
        <div className="px-6 py-3 border-t border-gray-200 bg-white text-xs text-gray-500 text-center">
          Showing first 100 of {total} results
        </div>
      )}
    </>
  );
}

function StockCard({ row, rank }: { row: Record<string, unknown>; rank: number }) {
  const pe = row.pe as number | null;
  const cmp = row.cmp as number | null;
  const valuation = (row.valuation as string) || "";
  const recommendation = (row.recommendation as string) || "";
  const comments = (row.comments as string) || "";
  const pdfUrl = (row.source_pdf_url as string) || "";
  const targetPrice = row.target_price as number | null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-md transition-shadow">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-xs font-mono text-gray-400 w-5 text-right flex-shrink-0">{rank}</span>
          <div className="min-w-0">
            <div className="font-semibold text-gray-900 truncate">
              {(row.company_name as string) || (row.stock_symbol as string)}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[11px] text-gray-400 font-mono">{row.stock_symbol as string}</span>
              <span className="text-[11px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                {(row.sector as string) || "—"}
              </span>
              <span className="text-[11px] text-gray-400">{row.quarter as string} {row.financial_year as string}</span>
            </div>
          </div>
        </div>
        <ValuationBadge value={valuation} />
      </div>

      {/* Metrics row */}
      <div className="flex items-center gap-4 mt-3 pl-8">
        <MetricPill label="PE" value={pe ? fmtNumber(pe) : "—"} />
        <MetricPill label="CMP" value={cmp ? `₹${fmtNumber(cmp)}` : "—"} />
        {targetPrice && <MetricPill label="Target" value={`₹${fmtNumber(targetPrice)}`} />}
        {recommendation && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium">
            {recommendation}
          </span>
        )}
      </div>

      {/* Comments & File row */}
      {(comments || pdfUrl) && (
        <div className="flex items-start gap-3 mt-3 pl-8">
          {comments && (
            <div className="flex items-start gap-1.5 flex-1 min-w-0">
              <MessageSquare className="w-3 h-3 text-gray-400 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-gray-500 line-clamp-2">{comments}</p>
            </div>
          )}
          {pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-primary hover:text-primary-dark font-medium flex-shrink-0"
            >
              <FileText className="w-3 h-3" />
              PDF
              <ExternalLink className="w-2.5 h-2.5" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-gray-400 uppercase">{label}</span>
      <span className="text-xs font-mono font-semibold text-gray-800">{value}</span>
    </div>
  );
}

function ValuationBadge({ value }: { value: string }) {
  const v = value.toUpperCase();
  let classes = "text-xs px-2.5 py-1 rounded-lg font-medium ";
  if (v.includes("CHEAP") || v.includes("UNDER")) {
    classes += "bg-emerald-50 text-emerald-700 border border-emerald-200";
  } else if (v.includes("EXPENSIVE") || v.includes("OVER")) {
    classes += "bg-red-50 text-red-700 border border-red-200";
  } else if (v.includes("FAIR")) {
    classes += "bg-amber-50 text-amber-700 border border-amber-200";
  } else {
    classes += "bg-gray-50 text-gray-600 border border-gray-200";
  }
  return <span className={classes}>{value || "—"}</span>;
}
