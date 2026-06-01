"use client";

import { usePEAnalysis, usePEFilters } from "@/hooks/usePEAnalysis";
import { fmtCurrency, fmtNumber } from "@/lib/utils";
import { useState, useEffect, useRef, useCallback } from "react";
import { deletePEAnalysis, updatePEAnalysis, retriggerPEExtraction, fetchValuationOptions, bulkIgnorePE } from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Trash2, Pencil, X, ExternalLink, AlertTriangle, RefreshCw, RotateCw } from "lucide-react";
import {
  FALLBACK_VALUATION_OPTIONS,
  VALUATION_BADGE_COLORS,
  valuationLabel,
  type ValuationOption,
} from "@/lib/valuationOptions";
import { RemarkSelect } from "./RemarkSelect";
import { SectorSelect } from "./SectorSelect";
import { useConfirm } from "./ConfirmDialog";

function useValuationOptions(): ValuationOption[] {
  const { data } = useQuery({
    queryKey: ["valuation-options"],
    queryFn: fetchValuationOptions,
    staleTime: 60 * 60_000,
    retry: false,
  });
  return (data?.options as ValuationOption[]) || FALLBACK_VALUATION_OPTIONS;
}

interface PETableProps {
  valuationFilter: "pending" | "reviewed";
  filters?: Record<string, string>;
  perPage?: number;
  visibleColumns?: string[];
  onTotalChange?: (total: number) => void;
}

function SegmentBadge({ segment }: { segment?: string | null }) {
  if (!segment) return <span className="text-gray-400">—</span>;
  const labels: Record<string, string> = {
    NSE_EQ: "NSE EQ", NSE_SME: "NSE SME",
    BSE_EQ: "BSE EQ", BSE_SME: "BSE SME",
  };
  const isSME = segment.includes("SME");
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap ${
      isSME ? "bg-amber-100 text-amber-700" : "bg-blue-50 text-blue-600"
    }`}>
      {labels[segment] || segment}
    </span>
  );
}

function cleanStr(val: unknown): string | null {
  if (val == null) return null;
  if (typeof val === "string") {
    const cleaned = val
      .replace(/[\x00-\x1F\x7F\u2014\u2013\u00a0]/g, "")
      .replace(/\\u[0-9a-fA-F]{4}/g, "")
      .trim();
    if (!cleaned || cleaned === "—" || cleaned === "-") return null;
    return cleaned;
  }
  return String(val);
}

function cleanNum(val: unknown): number | null {
  if (val == null) return null;
  if (typeof val === "number") return isNaN(val) ? null : val;
  if (typeof val === "string") {
    const stripped = val
      .replace(/[\x00-\x1F\x7F\u2014\u2013\u00a0]/g, "")
      .replace(/\\u[0-9a-fA-F]{4}/g, "")
      .replace(/[^\d.\-]/g, "")
      .trim();
    if (!stripped) return null;
    const num = parseFloat(stripped);
    return isNaN(num) ? null : num;
  }
  return null;
}

export function PETable({ valuationFilter, filters = {}, perPage = 50, visibleColumns, onTotalChange }: PETableProps) {
  const show = (col: string) => !visibleColumns || visibleColumns.includes(col);
  const [page, setPage] = useState(1);
  const [drawerRow, setDrawerRow] = useState<Record<string, unknown> | null>(null);
  const [retriggering, setRetriggering] = useState<Set<number>>(new Set());
  const queryClient = useQueryClient();

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const lastClickedIdx = useRef<number | null>(null);
  const shiftHeld = useRef(false);
  const isPending = valuationFilter === "pending";

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.key === "Shift") shiftHeld.current = true; };
    const up = (e: KeyboardEvent) => { if (e.key === "Shift") shiftHeld.current = false; };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, []);

  const filtersKey = JSON.stringify(filters) + valuationFilter + perPage;
  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [filtersKey]);
  useEffect(() => { setSelectedIds(new Set()); }, [page]);

  const confirm = useConfirm();
  const params = { page, per_page: perPage, valuation_filter: valuationFilter, ...filters };
  const { data, isLoading, isError, error, refetch, isFetching } = usePEAnalysis(params);

  useEffect(() => {
    if (data?.total != null && onTotalChange) onTotalChange(data.total);
  }, [data?.total, onTotalChange]);

  const toggleOne = useCallback((id: number, idx: number, isShift: boolean, allIds: number[]) => {
    const lastIdx = lastClickedIdx.current;
    lastClickedIdx.current = idx;

    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (isShift && lastIdx !== null) {
        const start = Math.min(lastIdx, idx);
        const end = Math.max(lastIdx, idx);
        for (let i = start; i <= end; i++) {
          if (allIds[i] != null) next.add(allIds[i]);
        }
      } else {
        if (next.has(id)) next.delete(id); else next.add(id);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback((allIds: number[]) => {
    setSelectedIds((prev) => {
      const allOn = allIds.length > 0 && allIds.every((id) => prev.has(id));
      return allOn ? new Set<number>() : new Set(allIds);
    });
  }, []);

  const handleDelete = async (symbol: string) => {
    const ok = await confirm({
      title: "Delete stock data",
      message: `This will permanently delete all PE analysis data for ${symbol}. This action cannot be undone.`,
      confirmLabel: "Delete",
      cancelLabel: "Keep",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await deletePEAnalysis(symbol);
      queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
      toast.success(`${symbol} deleted`);
    } catch {
      toast.error("Failed to delete");
    }
  };

  const handleRetrigger = async (
    symbol: string,
    rowId: number,
    extractionStatus: string,
    hasPdf: boolean,
  ) => {
    if (!hasPdf) {
      toast.error(`${symbol}: no source PDF on this row — cannot re-extract`);
      return;
    }
    if (extractionStatus === "completed") {
      const ok = await confirm({
        title: "Re-extract completed stock",
        message: `${symbol} is already extracted successfully. Re-extracting will call OpenAI again and overwrite existing data.`,
        confirmLabel: "Re-extract",
        cancelLabel: "Cancel",
        variant: "warning",
      });
      if (!ok) return;
    }
    setRetriggering((prev) => {
      const next = new Set(prev);
      next.add(rowId);
      return next;
    });
    try {
      await retriggerPEExtraction(symbol, rowId);
      toast.success(`${symbol}: queued for re-extraction`);
      queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || `Failed to retrigger ${symbol}`);
    } finally {
      setRetriggering((prev) => {
        const next = new Set(prev);
        next.delete(rowId);
        return next;
      });
    }
  };

  const handleIgnore = async (symbol: string, rowId: number) => {
    try {
      await updatePEAnalysis(symbol, { valuation: "ignore" }, rowId);
      queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
      setSelectedIds((prev) => { const next = new Set(prev); next.delete(rowId); return next; });
      toast.success(`${symbol} marked as IGNORE`);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || `Failed to ignore ${symbol}`);
    }
  };

  if (isLoading && !data) return <TableSkeleton />;

  if (isError && !data) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    return (
      <div className="bg-white rounded-xl border border-red-200 p-6 flex items-start gap-3 m-4">
        <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-sm font-semibold text-red-700">
            Could not load PE analysis{status ? ` (HTTP ${status})` : ""}
          </div>
          <div className="text-xs text-gray-600 mt-1">
            {status === 429
              ? "Backend rate-limit hit. Will retry automatically; click Retry to retry now."
              : "Backend may be restarting or unreachable."}
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

  const rows = data?.results || [];
  const totalPages = data?.total_pages || 1;
  const totalCount = data?.total || 0;

  const failedRows = rows.filter(
    (r: Record<string, unknown>) =>
      (r.extraction_status === "failed" || r.extraction_status === "pending") && r.source_pdf_url,
  );

  const handleRetryAllFailed = async () => {
    if (failedRows.length === 0) return;
    const confirmed = await confirm({
      title: "Retry failed extractions",
      message: `Re-queue ${failedRows.length} failed/pending row${failedRows.length === 1 ? "" : "s"} on this page for extraction? This will call OpenAI for each row.`,
      confirmLabel: `Retry ${failedRows.length} row${failedRows.length === 1 ? "" : "s"}`,
      cancelLabel: "Cancel",
      variant: "warning",
    });
    if (!confirmed) return;
    let ok = 0;
    let bad = 0;
    for (const r of failedRows) {
      const symbol = r.stock_symbol as string;
      const rowId = Number(r.id);
      try {
        await retriggerPEExtraction(symbol, rowId);
        ok += 1;
      } catch {
        bad += 1;
      }
    }
    queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
    if (bad === 0) toast.success(`Queued ${ok} row(s) for re-extraction`);
    else toast.error(`Queued ${ok}, failed ${bad}`);
  };

  // ── Bulk selection (PE Pending only) ──
  const allIds = rows.map((r: Record<string, unknown>) => r.id as number);
  const allSelected = isPending && allIds.length > 0 && allIds.every((id: number) => selectedIds.has(id));

  const handleBulkIgnore = async () => {
    if (selectedIds.size === 0) return;
    const n = selectedIds.size;
    const confirmed = await confirm({
      title: "Skip selected stocks",
      message: `Mark ${n} stock${n === 1 ? "" : "s"} as IGNORE? They will move to PE Reviewed.`,
      confirmLabel: `Skip ${n} stock${n === 1 ? "" : "s"}`,
      cancelLabel: "Cancel",
      variant: "warning",
    });
    if (!confirmed) return;
    setBulkProcessing(true);
    try {
      const result = await bulkIgnorePE(Array.from(selectedIds));
      queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
      setSelectedIds(new Set());
      if (result.skipped > 0) {
        toast.success(`Skipped ${result.updated} stock${result.updated === 1 ? "" : "s"} (${result.skipped} already reviewed)`);
      } else {
        toast.success(`Skipped ${result.updated} stock${result.updated === 1 ? "" : "s"}`);
      }
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Bulk skip failed");
    } finally {
      setBulkProcessing(false);
    }
  };

  const dateColW = "w-[90px] min-w-[90px] max-w-[90px]";
  const stockColW = "w-[160px] min-w-[160px] max-w-[160px]";
  const stickyDate = isPending ? "sticky left-[40px] z-10" : "sticky left-0 z-10";
  const stickyStock = isPending
    ? "sticky left-[130px] z-10 border-r-2 border-r-slate-400"
    : "sticky left-[90px] z-10 border-r-2 border-r-slate-400";

  return (
    <div className="flex flex-col h-full">
      {failedRows.length > 0 && (
        <div className="px-3 py-2 bg-amber-50 border-y border-amber-200 flex items-center justify-between text-xs">
          <span className="text-amber-800">
            <strong>{failedRows.length}</strong> failed / pending row{failedRows.length === 1 ? "" : "s"} on this page can be re-extracted.
          </span>
          <button
            onClick={handleRetryAllFailed}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-500 hover:bg-amber-600 text-white font-medium transition-colors"
          >
            <RotateCw className="w-3 h-3" /> Retry all failed
          </button>
        </div>
      )}

      {isPending && selectedIds.size > 0 && (
        <div className="px-3 py-2 bg-blue-50 border-y border-blue-200 flex items-center gap-3 text-xs">
          <span className="font-semibold text-blue-800">{selectedIds.size} selected</span>
          <button
            onClick={handleBulkIgnore}
            disabled={bulkProcessing}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-slate-600 hover:bg-slate-700 text-white font-medium transition-colors disabled:opacity-50"
          >
            {bulkProcessing && <RotateCw className="w-3 h-3 animate-spin" />}
            Skip {selectedIds.size} Selected
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            disabled={bulkProcessing}
            className="text-blue-600 hover:text-blue-800 hover:underline font-medium disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      )}

      <PEPagination page={page} totalPages={totalPages} total={totalCount} perPage={perPage} onPageChange={setPage} position="top" />

      <div className="flex-1 min-h-0 overflow-auto relative">
        <table className="w-max min-w-full text-xs border-collapse">
          <thead className="sticky top-0 z-20">
            <tr className="border-b border-gray-200 text-[11px] text-gray-600 uppercase font-bold">
              {isPending && (
                <th className="w-[40px] min-w-[40px] max-w-[40px] px-2 py-2 bg-gray-50 sticky left-0 z-10 text-center">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleAll(allIds)}
                    disabled={bulkProcessing || allIds.length === 0}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-primary accent-primary cursor-pointer"
                  />
                </th>
              )}
              {show("date") && <th className={`text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50 ${dateColW} ${stickyDate}`}>Date</th>}
              {show("stock") && <th className={`text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50 ${stockColW} ${stickyStock}`}>Stock</th>}
              {show("exch") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Exch</th>}
              {show("segment") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Segment</th>}
              {show("quarter") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Quarter</th>}
              {show("year") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Year</th>}
              {show("qtr_eps") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-amber-100 text-amber-800">Qtr EPS</th>}
              {show("eps_qoq") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">EPS Q/Q</th>}
              {show("eps_yoy") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">EPS Y/Y</th>}
              {show("cum_eps") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Cum. EPS</th>}
              {show("cum_prev_fy") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Cum. Prev FY</th>}
              {show("prev_fy_eps") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Prev FY EPS</th>}
              {show("fy_eps_est") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-green-100 text-green-800">FY EPS (Est.)</th>}
              {show("manual_eps") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Manual EPS</th>}
              {show("cmp") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">CMP (₹)</th>}
              {show("pe") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-purple-100 text-purple-800">PE</th>}
              {show("signal") && <th className="text-center px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Signal</th>}
              {show("target") && <th className="text-right px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Target (₹)</th>}
              {show("sector") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Sector</th>}
              {show("remark") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Remark</th>}
              {show("comments") && <th className="text-left px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Comments</th>}
              {show("file") && <th className="text-center px-3 py-2 font-medium whitespace-nowrap bg-gray-50">File</th>}
              {show("actions") && <th className="text-center px-3 py-2 font-medium whitespace-nowrap bg-gray-50">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row: Record<string, unknown>, rowIdx: number) => {
              const pe = cleanNum(row.pe);
              const cmp = cleanNum(row.cmp);
              const target = cleanNum(row.target_price);
              const manualEps = cleanNum(row.manual_fy_eps);
              const qtrEps = cleanNum(row.qtr_eps);
              const epsQoq = cleanNum(row.eps_qoq);
              const epsYoy = cleanNum(row.eps_yoy);
              const cumEps = cleanNum(row.cum_eps);
              const cumPrevFy = cleanNum(row.cum_prev_fy);
              const prevFyEps = cleanNum(row.prev_fy_eps);
              const fyEpsEst = cleanNum(row.fy_eps_estimated);
              const epsQoqLabel = (row.eps_qoq_label as string) || "";
              const epsYoyLabel = (row.eps_yoy_label as string) || "";
              const cumEpsLabel = (row.cum_eps_label as string) || "";
              const cumPrevFyLabel = (row.cum_prev_fy_label as string) || "";
              const prevFyEpsLabel = (row.prev_fy_eps_label as string) || "";
              const fyEpsEstLabel = (row.fy_eps_est_label as string) || "";
              const signal = cleanStr(row.recommendation);
              const valuation = cleanStr(row.valuation);
              const comments = cleanStr(row.comments);
              const sector = cleanStr(row.sector);
              const pdfUrl = cleanStr(row.source_pdf_url);

              const annDate = cleanStr(row.announcement_date);
              const dateObj = annDate ? new Date(annDate) : null;
              const fmtDate = dateObj ? dateObj.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
              const fmtTime = dateObj ? dateObj.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }) : "";

              const rowId = row.id as number;

              return (
                <tr key={rowId} className={`hover:bg-gray-50/80 transition-colors group ${isPending && selectedIds.has(rowId) ? "bg-blue-50/60" : ""}`}>
                  {isPending && (
                    <td
                      className="w-[40px] min-w-[40px] max-w-[40px] px-2 py-2 bg-white group-hover:bg-gray-50 sticky left-0 z-10 text-center cursor-pointer select-none"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleOne(rowId, rowIdx, e.shiftKey, allIds);
                      }}
                    >
                      <div className={`w-3.5 h-3.5 rounded border-2 mx-auto flex items-center justify-center transition-colors ${
                        selectedIds.has(rowId)
                          ? "bg-primary border-primary"
                          : "border-gray-300 hover:border-gray-400"
                      }`}>
                        {selectedIds.has(rowId) && (
                          <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none">
                            <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        )}
                      </div>
                    </td>
                  )}
                  {show("date") && <td className={`px-3 py-2 text-gray-500 whitespace-nowrap bg-white group-hover:bg-gray-50 ${dateColW} ${stickyDate}`}>
                    <div className="text-[11px]">{fmtDate}</div>
                    {fmtTime && <div className="text-[9px] text-gray-400">{fmtTime}</div>}
                  </td>}
                  {show("stock") && <td className={`px-3 py-2 bg-white group-hover:bg-gray-50 ${stockColW} ${stickyStock}`}>
                    <div className="font-medium text-gray-900 text-xs truncate">{cleanStr(row.company_name) || cleanStr(row.stock_symbol) || "—"}</div>
                    <div className="text-[10px] text-gray-400">{cleanStr(row.stock_symbol) || ""}</div>
                    <StatusBadge status={row.extraction_status as string} error={cleanStr(row.extraction_error)} />
                  </td>}
                  {show("exch") && <td className="px-3 py-2"><span className={row.exchange === "BSE" ? "badge-bse" : "badge-nse"}>{cleanStr(row.exchange) || "BSE"}</span></td>}
                  {show("segment") && <td className="px-3 py-2"><SegmentBadge segment={row.market_segment as string} /></td>}
                  {show("quarter") && <td className="px-3 py-2 text-gray-600">{cleanStr(row.quarter) || "—"}</td>}
                  {show("year") && <td className="px-3 py-2 text-gray-600">{cleanStr(row.financial_year) || "—"}</td>}
                  {show("qtr_eps") && <td className="px-3 py-2 text-right font-mono bg-amber-50"><ColorNum value={qtrEps} /></td>}
                  {show("eps_qoq") && <td className="px-3 py-2 text-right font-mono"><LabeledVal value={epsQoq} label={epsQoqLabel} /></td>}
                  {show("eps_yoy") && <td className="px-3 py-2 text-right font-mono"><LabeledVal value={epsYoy} label={epsYoyLabel} /></td>}
                  {show("cum_eps") && <td className="px-3 py-2 text-right font-mono"><LabeledVal value={cumEps} label={cumEpsLabel} /></td>}
                  {show("cum_prev_fy") && <td className="px-3 py-2 text-right font-mono text-gray-500"><LabeledVal value={cumPrevFy} label={cumPrevFyLabel} /></td>}
                  {show("prev_fy_eps") && <td className="px-3 py-2 text-right font-mono text-gray-500"><LabeledVal value={prevFyEps} label={prevFyEpsLabel} /></td>}
                  {show("fy_eps_est") && <td className="px-3 py-2 text-right font-mono font-bold bg-green-50"><LabeledVal value={fyEpsEst} label={fyEpsEstLabel} colored={false} /></td>}
                  {show("manual_eps") && <td className="px-3 py-2 text-right font-mono">{manualEps != null ? fmtNumber(manualEps) : "—"}</td>}
                  {show("cmp") && <td className="px-3 py-2 text-right font-mono text-gray-900 font-medium">{cmp != null ? `₹${fmtCurrency(cmp)}` : "—"}</td>}
                  {show("pe") && <td className="px-3 py-2 text-right font-mono font-bold bg-purple-50 text-purple-700">{pe != null ? fmtNumber(pe) : "—"}</td>}
                  {show("signal") && <td className="px-3 py-2 text-center"><SignalBadge signal={signal} /></td>}
                  {show("target") && <td className="px-3 py-2 text-right font-mono">{target != null ? `₹${fmtCurrency(target)}` : "—"}</td>}
                  {show("sector") && <td className="px-3 py-2 text-gray-500 text-[10px] max-w-[100px] truncate">{sector || "—"}</td>}
                  {show("remark") && <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-2">
                      <ValuationBadge value={valuation} pending={valuationFilter === "pending"} />
                      {valuationFilter === "pending" && !valuation && (
                        <button
                          onClick={() => handleIgnore(row.stock_symbol as string, rowId)}
                          className="text-[11px] px-2.5 py-0.5 rounded-full border-2 border-slate-400 text-slate-700 hover:border-slate-600 hover:text-slate-900 hover:bg-slate-100 font-bold tracking-wide transition-all"
                          title="Mark as ignored — moves to PE Reviewed"
                        >
                          SKIP
                        </button>
                      )}
                    </div>
                  </td>}
                  {show("comments") && <td className="px-3 py-2 max-w-[120px]"><span className="text-gray-500 text-[10px] truncate block">{comments || "—"}</span></td>}
                  {show("file") && <td className="px-3 py-2 text-center" onClick={(e) => e.stopPropagation()}>
                    {pdfUrl ? (
                      <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5 text-[10px]">
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : <span className="text-gray-300">—</span>}
                  </td>}
                  {show("actions") && <td className="px-3 py-2 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1">
                      {(() => {
                        const status = String(row.extraction_status || "");
                        const hasPdf = Boolean(row.source_pdf_url);
                        const isRetrying = retriggering.has(rowId);
                        const isFailedOrPending = status === "failed" || status === "pending";
                        const tooltip = !hasPdf
                          ? "No source PDF on this row"
                          : status === "completed"
                          ? "Re-extract (will re-run OpenAI)"
                          : status === "pending"
                          ? "Re-queue extraction"
                          : "Retry extraction";
                        return (
                          <button
                            onClick={() => handleRetrigger(row.stock_symbol as string, rowId, status, hasPdf)}
                            disabled={isRetrying || !hasPdf}
                            className={`p-1 rounded transition-colors ${
                              !hasPdf
                                ? "text-gray-200 cursor-not-allowed"
                                : isFailedOrPending
                                ? "text-amber-500 hover:bg-amber-50 hover:text-amber-700"
                                : "text-gray-400 hover:bg-emerald-50 hover:text-emerald-600"
                            }`}
                            title={tooltip}
                          >
                            <RotateCw className={`w-3.5 h-3.5 ${isRetrying ? "animate-spin" : ""}`} />
                          </button>
                        );
                      })()}
                      <button onClick={() => setDrawerRow(row)} className="p-1 rounded hover:bg-blue-50 text-gray-400 hover:text-blue-600" title="Edit"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => handleDelete(row.stock_symbol as string)} className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <PEPagination page={page} totalPages={totalPages} total={totalCount} perPage={perPage} onPageChange={setPage} position="bottom" />

      {drawerRow && (
        <EditDrawer
          row={drawerRow}
          onClose={() => setDrawerRow(null)}
          onSaved={() => { queryClient.invalidateQueries({ queryKey: ["pe-analysis"] }); setDrawerRow(null); }}
        />
      )}
    </div>
  );
}

function ColorNum({ value }: { value: number | null }) {
  if (value == null) return <span className="text-gray-300">{"—"}</span>;
  const color = value > 0 ? "text-green-600" : value < 0 ? "text-red-600" : "text-gray-700";
  return <span className={color}>{fmtNumber(value)}</span>;
}

function LabeledVal({ value, label, colored = true }: { value: number | null; label?: string; colored?: boolean }) {
  if (value == null) return <span className="text-gray-300">{"—"}</span>;
  const color = colored ? (value > 0 ? "text-green-600" : value < 0 ? "text-red-600" : "text-gray-700") : "";
  return (
    <div className="leading-tight">
      <span className={color}>{fmtNumber(value)}</span>
      {label && <div className="text-[9px] text-gray-400">{label}</div>}
    </div>
  );
}

function SignalBadge({ signal }: { signal: string | null }) {
  if (!signal) return <span className="text-gray-300">{"—"}</span>;
  const colors: Record<string, string> = { BUY: "bg-green-600 text-white", SELL: "bg-red-600 text-white", HOLD: "bg-amber-500 text-white" };
  return <span className={`text-[11px] px-2.5 py-0.5 rounded font-bold tracking-wide ${colors[signal] || "bg-gray-300 text-gray-700"}`}>{signal}</span>;
}

function ValuationBadge({ value, pending }: { value: string | null; pending?: boolean }) {
  if (!value && pending) return <span className="text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-amber-100 text-amber-800">PENDING</span>;
  if (!value) return <span className="text-gray-300">{"—"}</span>;
  const cls = VALUATION_BADGE_COLORS[value] || "bg-gray-100 text-gray-700 font-semibold";
  const label = valuationLabel(value, FALLBACK_VALUATION_OPTIONS);
  return <span className={`text-[11px] px-2.5 py-0.5 rounded-full whitespace-nowrap ${cls}`}>{label.toUpperCase()}</span>;
}

function simplifyError(raw: string): string {
  const lower = raw.toLowerCase();
  if (lower.includes("non-results-pdf") || lower.includes("no financial periods"))
    return "No financial data found";
  if (lower.includes("no images extracted") || lower.includes("pdf download") || lower.includes("getaddrinfo failed"))
    return "PDF download failed";
  if (lower.includes("too many clients") || lower.includes("connection"))
    return "DB connection error (retrying)";
  if (lower.includes("ai extraction returned empty"))
    return "AI could not extract data";
  if (lower.includes("timeout") || lower.includes("timed out"))
    return "Request timed out";
  if (lower.includes("rate limit") || lower.includes("429"))
    return "Rate limited (retrying)";
  if (raw.length > 50) return raw.slice(0, 47) + "...";
  return raw;
}

function StatusBadge({ status, error }: { status: string | null | undefined; error?: string | null }) {
  if (!status) return null;
  const colors: Record<string, string> = {
    pending:    "bg-amber-100 text-amber-700",
    queued:     "bg-amber-100 text-amber-700",
    processing: "bg-blue-100 text-blue-700",
    extracting: "bg-blue-100 text-blue-700",
    completed:  "bg-green-100 text-green-700",
    failed:     "bg-red-100 text-red-700",
    error:      "bg-red-100 text-red-700",
  };
  const labels: Record<string, string> = {
    pending:    "QUEUED",
    queued:     "QUEUED",
    processing: "EXTRACTING",
    extracting: "EXTRACTING",
    completed:  "SUCCESS",
    failed:     "FAILED",
    error:      "FAILED",
  };
  const inFlight = status === "pending" || status === "queued" ||
                   status === "processing" || status === "extracting";
  const isFailed = status === "failed" || status === "error";

  const shortError = error ? simplifyError(error) : null;

  return (
    <div className="inline-flex flex-col items-start gap-0.5 mt-0.5">
      <span
        className={`text-[9px] px-1.5 py-0.5 rounded inline-flex items-center gap-1 font-medium ${
          colors[status] || "bg-gray-100 text-gray-500"
        }`}
        title={error || undefined}
      >
        {inFlight && (
          <span
            className={`w-1.5 h-1.5 rounded-full animate-pulse ${
              status === "processing" || status === "extracting" ? "bg-blue-500" : "bg-amber-500"
            }`}
          />
        )}
        {labels[status] || status.toUpperCase()}
      </span>
      {isFailed && shortError && (
        <span className="text-[8px] text-red-500/80 leading-tight max-w-[140px] truncate" title={error || undefined}>
          {shortError}
        </span>
      )}
    </div>
  );
}

function PEPagination({
  page, totalPages, total, perPage, onPageChange, position,
}: {
  page: number; totalPages: number; total: number; perPage: number; onPageChange: (p: number) => void; position: "top" | "bottom";
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
        <span className="font-semibold text-gray-700">{total.toLocaleString()}</span> stocks
      </span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPageChange(1)} disabled={page <= 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed" title="First"><ChevronsLeft className="w-4 h-4" /></button>
        <button onClick={() => onPageChange(page - 1)} disabled={page <= 1} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed" title="Prev"><ChevronLeft className="w-4 h-4" /></button>
        <span className="px-2 font-medium text-gray-700 flex items-center gap-1">
          Page
          <input type="number" min={1} max={totalPages} defaultValue={page} key={page} onKeyDown={handlePageInput}
            onBlur={(e) => { const val = Math.min(Math.max(1, Number(e.target.value)), totalPages); if (!isNaN(val) && val !== page) onPageChange(val); }}
            className="w-9 text-center border border-gray-300 rounded px-1 py-0.5 text-[10px] font-semibold" />
          of {totalPages}
        </span>
        <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed" title="Next"><ChevronRight className="w-4 h-4" /></button>
        <button onClick={() => onPageChange(totalPages)} disabled={page >= totalPages} className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed" title="Last"><ChevronsRight className="w-4 h-4" /></button>
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="p-4 space-y-2">
      {Array.from({ length: 10 }).map((_, i) => (<div key={i} className="h-12 bg-gray-100 rounded animate-pulse" />))}
    </div>
  );
}

function EditDrawer({ row, onClose, onSaved }: { row: Record<string, unknown>; onClose: () => void; onSaved: () => void }) {
  const { data: filterOptions } = usePEFilters();
  const sectorOptions: string[] = filterOptions?.sectors || [];
  const [saving, setSaving] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const symbol = (row.stock_symbol as string) || "";
  const companyName = (row.company_name as string) || symbol;
  const qtrEps = row.qtr_eps != null ? Number(row.qtr_eps) : null;

  const initialForm = {
    cmp: row.cmp != null ? String(row.cmp) : "",
    fy_eps_est: row.fy_eps_estimated != null ? String(row.fy_eps_estimated) : "",
    manual_fy_eps: row.manual_fy_eps != null ? String(row.manual_fy_eps) : "",
    formula_q1: "",
    formula_q2: "",
    formula_q3: "",
    formula_q4: "",
    pe: row.pe != null ? String(row.pe) : "",
    sector: (row.sector as string) || "",
    sub_sector: (row.sub_sector as string) || "",
    recommendation: (row.recommendation as string) || "",
    target_price: row.target_price != null ? String(row.target_price) : "",
    valuation: (row.valuation as string) || "",
    comments: (row.comments as string) || "",
  };

  const [form, setForm] = useState(initialForm);
  const [originalForm, setOriginalForm] = useState(initialForm);

  useEffect(() => {
    try {
      const f = row.manual_fy_eps_formula ? JSON.parse(row.manual_fy_eps_formula as string) : {};
      const formulas = { formula_q1: f.q1_expr || "", formula_q2: f.q2_expr || "", formula_q3: f.q3_expr || "", formula_q4: f.q4_expr || "" };
      setForm((prev) => ({ ...prev, ...formulas }));
      setOriginalForm((prev) => ({ ...prev, ...formulas }));
    } catch { /* ignore */ }
  }, [row.manual_fy_eps_formula]);

  const isDirty = JSON.stringify(form) !== JSON.stringify(originalForm);

  const [showConfirm, setShowConfirm] = useState(false);
  const [showMoveToPending, setShowMoveToPending] = useState(false);
  const [moveToPendingSaving, setMoveToPendingSaving] = useState(false);

  const confirmClose = () => {
    if (isDirty) {
      setShowConfirm(true);
    } else {
      onClose();
    }
  };

  const handleRemarkChange = (v: string) => {
    if (!v && originalForm.valuation) {
      setShowMoveToPending(true);
    } else {
      set("valuation", v);
    }
  };

  const confirmMoveToPending = async () => {
    setMoveToPendingSaving(true);
    try {
      const rowId = row.id != null ? Number(row.id) : undefined;
      await updatePEAnalysis(symbol, { valuation: "" }, rowId);
      toast.success(`${symbol} moved to PE Pending`);
      setShowMoveToPending(false);
      onSaved();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to update");
    } finally {
      setMoveToPendingSaving(false);
    }
  };

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") confirmClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  });

  const set = (key: string, val: string) => setForm((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      if (form.cmp) payload.cmp = parseFloat(form.cmp);
      if (form.manual_fy_eps) payload.manual_fy_eps = parseFloat(form.manual_fy_eps);
      if (form.pe) payload.pe = parseFloat(form.pe);
      if (form.recommendation) {
        payload.recommendation = form.recommendation;
      } else if (originalForm.recommendation && !form.recommendation) {
        payload.recommendation = "";
      }
      if (form.target_price) payload.target_price = parseFloat(form.target_price);
      if (form.valuation) {
        payload.valuation = form.valuation;
      } else if (originalForm.valuation && !form.valuation) {
        payload.valuation = "";
      }
      if (form.comments) payload.comments = form.comments;
      if (form.sector) payload.sector = form.sector;
      if (form.sub_sector) payload.sub_sector = form.sub_sector;
      const hasFormula = form.formula_q1 || form.formula_q2 || form.formula_q3 || form.formula_q4;
      if (hasFormula) {
        payload.manual_fy_eps_formula = JSON.stringify({ q1_expr: form.formula_q1, q2_expr: form.formula_q2, q3_expr: form.formula_q3, q4_expr: form.formula_q4 });
      }
      const rowId = row.id != null ? Number(row.id) : undefined;
      await updatePEAnalysis(symbol, payload, rowId);
      toast.success(`${symbol} updated`);
      onSaved();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to update");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" />
      <div ref={panelRef} className="fixed top-0 right-0 h-full w-[380px] bg-white shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Pencil className="w-4 h-4 text-gray-400" />
            <h2 className="font-semibold text-gray-900 text-sm">{companyName}</h2>
          </div>
          <button onClick={confirmClose} className="p-1 rounded hover:bg-gray-100"><X className="w-5 h-5 text-gray-500" /></button>
        </div>

        {/* Info badge */}
        <div className="mx-5 mt-4 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs">
          <span className="font-semibold text-amber-800">{symbol}</span>
          <span className="text-amber-600"> — {row.quarter as string} {row.financial_year as string}</span>
          <div className="text-amber-600 text-[10px] mt-0.5">{row.exchange as string} • Qtr EPS: {qtrEps != null ? qtrEps : "—"}</div>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <DrawerField label="CMP (₹)">
            <input type="number" step="0.01" value={form.cmp} onChange={(e) => set("cmp", e.target.value)} className="drawer-input" placeholder="—" />
          </DrawerField>

          <DrawerField label="FY EPS (Est.) auto-calculated">
            <input type="text" value={form.fy_eps_est} readOnly className="drawer-input bg-gray-50 text-gray-500 cursor-not-allowed" />
          </DrawerField>

          <div className="border-t border-green-200 pt-3">
            <DrawerField label="Manual FY EPS (Estimated)" labelColor="text-amber-600">
              <input type="number" step="0.01" value={form.manual_fy_eps} onChange={(e) => set("manual_fy_eps", e.target.value)} className="drawer-input" placeholder="Override auto EPS" />
            </DrawerField>
          </div>

          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Formula Per Quarter</label>
            <p className="text-[9px] text-gray-400 mb-2">(used to derive manual EPS)</p>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-[10px] text-gray-500 font-medium">Q1</label><input type="text" value={form.formula_q1} onChange={(e) => set("formula_q1", e.target.value)} className="drawer-input text-xs" placeholder="e.g. Q1*4" /></div>
              <div><label className="text-[10px] text-gray-500 font-medium">Q2</label><input type="text" value={form.formula_q2} onChange={(e) => set("formula_q2", e.target.value)} className="drawer-input text-xs" placeholder="e.g. (Q1+Q2)*2" /></div>
              <div><label className="text-[10px] text-gray-500 font-medium">Q3</label><input type="text" value={form.formula_q3} onChange={(e) => set("formula_q3", e.target.value)} className="drawer-input text-xs" placeholder="e.g. (Q1+Q2+Q3)*4" /></div>
              <div><label className="text-[10px] text-gray-500 font-medium">Q4</label><input type="text" value={form.formula_q4} onChange={(e) => set("formula_q4", e.target.value)} className="drawer-input text-xs" placeholder="e.g. FY" /></div>
            </div>
          </div>

          <DrawerField label="PE Value">
            <input type="number" step="0.01" value={form.pe} onChange={(e) => set("pe", e.target.value)} className="drawer-input" placeholder="—" />
          </DrawerField>

          <DrawerField label="Sector">
            <SectorSelect value={form.sector} onChange={(v) => set("sector", v)} options={sectorOptions} />
          </DrawerField>

          <DrawerField label="Sub-Sector">
            <input type="text" value={form.sub_sector} onChange={(e) => set("sub_sector", e.target.value)} className="drawer-input" placeholder="e.g. NBFC, Insurance" />
          </DrawerField>

          <DrawerField label="Signal">
            <select value={form.recommendation} onChange={(e) => set("recommendation", e.target.value)} className="drawer-input">
              <option value="">—</option>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
              <option value="HOLD">HOLD</option>
            </select>
          </DrawerField>

          <DrawerField label="Target Price (₹)">
            <input type="number" step="0.01" value={form.target_price} onChange={(e) => set("target_price", e.target.value)} className="drawer-input" placeholder="—" />
          </DrawerField>

          <DrawerField label="Remark">
            <RemarkSelect value={form.valuation} onChange={handleRemarkChange} />
          </DrawerField>

          <DrawerField label="Comments">
            <textarea value={form.comments} onChange={(e) => set("comments", e.target.value)} className="drawer-input min-h-[80px] resize-y" placeholder="Add a comment..." />
          </DrawerField>
        </div>

        {/* Footer — Save only visible when dirty */}
        <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-200 bg-gray-50">
          {isDirty && (
            <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-1.5">
              ✓ Save
            </button>
          )}
          <button onClick={confirmClose} className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 flex items-center gap-1.5">
            ✕ Cancel
          </button>
        </div>

        {/* Inline discard confirm */}
        {showConfirm && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/30 rounded-lg">
            <div className="bg-white rounded-xl shadow-lg border border-gray-200 mx-6 p-5 max-w-[300px] w-full">
              <p className="text-sm font-medium text-gray-900 mb-1">Discard changes?</p>
              <p className="text-xs text-gray-500 mb-4">Unsaved changes will be lost.</p>
              <div className="flex items-center justify-end gap-2">
                <button onClick={() => setShowConfirm(false)} className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200">
                  Keep Editing
                </button>
                <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-white bg-red-500 rounded-lg hover:bg-red-600">
                  Discard
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Move to PE Pending confirm */}
        {showMoveToPending && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/20 backdrop-blur-[2px] rounded-lg">
            <div className="bg-white rounded-2xl shadow-2xl border border-gray-100 mx-6 p-6 max-w-[320px] w-full animate-in zoom-in-95 duration-150">
              <div className="flex items-center gap-2.5 mb-3">
                <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                </div>
                <p className="text-sm font-semibold text-gray-900">Move to PE Pending?</p>
              </div>
              <p className="text-xs text-gray-500 mb-5 leading-relaxed">
                Clearing the remark will move <span className="font-semibold text-gray-700">{symbol}</span> back to the PE Pending list.
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={() => setShowMoveToPending(false)}
                  disabled={moveToPendingSaving}
                  className="px-3.5 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmMoveToPending}
                  disabled={moveToPendingSaving}
                  className="px-3.5 py-1.5 text-xs font-medium text-white bg-amber-500 rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                >
                  {moveToPendingSaving ? "Moving..." : "Move to Pending"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function DrawerField({ label, labelColor, children }: { label: string; labelColor?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className={`text-[10px] font-semibold uppercase tracking-wide ${labelColor || "text-gray-500"}`}>{label}</label>
      {children}
    </div>
  );
}
