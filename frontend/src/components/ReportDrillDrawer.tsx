"use client";

import { useEffect, useCallback } from "react";
import { X } from "lucide-react";
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
      <div className="relative ml-auto w-full max-w-2xl bg-white shadow-2xl flex flex-col animate-slide-in-right">
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
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 bg-gray-50">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{params.title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {total} stock{total !== 1 ? "s" : ""} found
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-gray-200 text-gray-500 hover:text-gray-700 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-10 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : results.length === 0 ? (
          <div className="p-10 text-center text-gray-400">No stocks found</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white border-b border-gray-200">
              <tr className="text-xs text-gray-500 uppercase">
                <th className="px-4 py-3 text-left">#</th>
                <th className="px-4 py-3 text-left">Company</th>
                <th className="px-4 py-3 text-left">Sector</th>
                <th className="px-4 py-3 text-right">PE</th>
                <th className="px-4 py-3 text-right">CMP</th>
                <th className="px-4 py-3 text-left">Valuation</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row: Record<string, unknown>, idx: number) => (
                <tr
                  key={row.stock_symbol as string}
                  className="border-b border-gray-100 hover:bg-primary/5 transition-colors"
                >
                  <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">{idx + 1}</td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-900 truncate max-w-[200px]">
                      {(row.company_name as string) || (row.stock_symbol as string)}
                    </div>
                    <div className="text-[11px] text-gray-400">{row.stock_symbol as string}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full truncate max-w-[120px] inline-block">
                      {(row.sector as string) || "—"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono font-medium">
                    {row.pe ? fmtNumber(row.pe as number) : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-gray-600">
                    {row.cmp ? `₹${fmtNumber(row.cmp as number)}` : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <ValuationBadge value={(row.valuation as string) || ""} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > 100 && (
        <div className="px-5 py-3 border-t border-gray-200 bg-gray-50 text-xs text-gray-500 text-center">
          Showing first 100 of {total} results
        </div>
      )}
    </>
  );
}

function ValuationBadge({ value }: { value: string }) {
  const v = value.toUpperCase();
  let classes = "text-xs px-2 py-0.5 rounded-full font-medium ";
  if (v.includes("CHEAP") || v.includes("UNDER")) {
    classes += "bg-green-100 text-green-700";
  } else if (v.includes("EXPENSIVE") || v.includes("OVER")) {
    classes += "bg-red-100 text-red-700";
  } else if (v.includes("FAIR")) {
    classes += "bg-amber-100 text-amber-700";
  } else {
    classes += "bg-gray-100 text-gray-600";
  }
  return <span className={classes}>{value || "—"}</span>;
}
