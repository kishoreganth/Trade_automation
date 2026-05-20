"use client";

import { useState, useMemo, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useReportDetail, usePEFilters } from "@/hooks/usePEAnalysis";
import { fmtNumber } from "@/lib/utils";
import {
  ArrowLeft, Search, X, Download, ArrowUpDown, ChevronUp, ChevronDown,
  FileText, ExternalLink, Columns3,
} from "lucide-react";

const ALL_COLUMNS = [
  { key: "rank", label: "#", default: true },
  { key: "company", label: "Company", default: true },
  { key: "sector", label: "Sector", default: true },
  { key: "pe", label: "PE", default: true },
  { key: "cmp", label: "CMP", default: true },
  { key: "target", label: "Target", default: true },
  { key: "signal", label: "Signal", default: true },
  { key: "valuation", label: "Remark", default: true },
  { key: "comments", label: "Comments", default: true },
  { key: "file", label: "File", default: true },
  { key: "quarter", label: "Quarter", default: false },
  { key: "exchange", label: "Exchange", default: false },
];

type SortKey = "company" | "pe" | "cmp" | "target" | "sector" | "valuation" | "signal";
type SortDir = "asc" | "desc";

export default function ReportDetailPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const filterType = searchParams.get("type") || "valuation";
  const filterValue = searchParams.get("value") || "";
  const title = searchParams.get("title") || "Stocks";
  const year = searchParams.get("year") || undefined;
  const quarter = searchParams.get("quarter") || undefined;
  const exchange = searchParams.get("exchange") || undefined;
  const sector = searchParams.get("sector") || undefined;

  const [search, setSearch] = useState("");
  const [remarkFilter, setRemarkFilter] = useState("");
  const [signalFilter, setSignalFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("pe");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [visibleCols, setVisibleCols] = useState<string[]>(
    ALL_COLUMNS.filter((c) => c.default).map((c) => c.key)
  );
  const [showColMenu, setShowColMenu] = useState(false);

  const { data: filterOptions } = usePEFilters();
  const { data, isLoading } = useReportDetail({
    filter_type: filterType,
    filter_value: filterValue,
    year,
    quarter,
    exchange,
    sector,
    page: 1,
    per_page: 500,
  });

  const results = data?.results || [];
  const total = data?.total || 0;

  const remarkOptions = useMemo(() => {
    const set = new Set<string>();
    results.forEach((r: Record<string, unknown>) => { if (r.valuation) set.add(r.valuation as string); });
    return Array.from(set).sort();
  }, [results]);

  const signalOptions = useMemo(() => {
    const set = new Set<string>();
    results.forEach((r: Record<string, unknown>) => { if (r.recommendation) set.add(r.recommendation as string); });
    return Array.from(set).sort();
  }, [results]);

  const filtered = useMemo(() => {
    let items = [...results];
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((r: Record<string, unknown>) =>
        ((r.company_name as string) || "").toLowerCase().includes(q) ||
        ((r.stock_symbol as string) || "").toLowerCase().includes(q)
      );
    }
    if (remarkFilter) {
      items = items.filter((r: Record<string, unknown>) => r.valuation === remarkFilter);
    }
    if (signalFilter) {
      items = items.filter((r: Record<string, unknown>) => r.recommendation === signalFilter);
    }
    return items;
  }, [results, search, remarkFilter, signalFilter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a: Record<string, unknown>, b: Record<string, unknown>) => {
      let av: unknown, bv: unknown;
      switch (sortKey) {
        case "company": av = a.company_name || a.stock_symbol; bv = b.company_name || b.stock_symbol; break;
        case "pe": av = a.pe || 99999; bv = b.pe || 99999; break;
        case "cmp": av = a.cmp || 0; bv = b.cmp || 0; break;
        case "target": av = a.target_price || 0; bv = b.target_price || 0; break;
        case "sector": av = a.sector || ""; bv = b.sector || ""; break;
        case "valuation": av = a.valuation || ""; bv = b.valuation || ""; break;
        case "signal": av = a.recommendation || ""; bv = b.recommendation || ""; break;
        default: av = a.pe || 99999; bv = b.pe || 99999;
      }
      if (typeof av === "string") return sortDir === "asc" ? (av as string).localeCompare(bv as string) : (bv as string).localeCompare(av as string);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  };

  const handleExport = () => {
    if (!sorted.length) return;
    const headers = ["Symbol", "Company", "Sector", "PE", "CMP", "Target", "Signal", "Remark", "Comments"];
    const csv = [
      headers.join(","),
      ...sorted.map((r: Record<string, unknown>) => [
        r.stock_symbol, r.company_name, r.sector, r.pe, r.cmp,
        r.target_price, r.recommendation, r.valuation, r.comments,
      ].map((v) => v != null ? `"${String(v).replace(/"/g, '""')}"` : "").join(","))
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report_${filterValue || "all"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggleCol = (key: string) => {
    setVisibleCols((prev) =>
      prev.includes(key) ? prev.filter((c) => c !== key) : [...prev, key]
    );
  };

  const hasCol = (key: string) => visibleCols.includes(key);

  return (
    <div className="h-full flex flex-col space-y-2">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.push("/analytics/report")}
          className="p-1.5 rounded-lg hover:bg-gray-200 text-gray-500 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h2 className="text-sm font-bold text-gray-900">{title}</h2>
          <p className="text-[11px] text-gray-500">{filtered.length} of {total} stocks</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-2 bg-white rounded-lg border border-gray-200 px-3 py-2 shadow-sm">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search company or symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input text-xs py-1.5 pl-8 pr-3 w-48"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        <select
          value={remarkFilter}
          onChange={(e) => setRemarkFilter(e.target.value)}
          className="text-xs py-1.5 px-2.5 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 font-medium focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="">All Remarks</option>
          {remarkOptions.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>

        <select
          value={signalFilter}
          onChange={(e) => setSignalFilter(e.target.value)}
          className="text-xs py-1.5 px-2.5 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 font-medium focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="">All Signals</option>
          {signalOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {(search || remarkFilter || signalFilter) && (
          <button
            onClick={() => { setSearch(""); setRemarkFilter(""); setSignalFilter(""); }}
            className="text-xs text-red-500 border border-red-200 rounded-lg px-2 py-1 hover:bg-red-50 flex items-center gap-0.5"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handleExport}
            className="text-xs bg-green-100 text-green-700 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium hover:bg-green-200"
          >
            <Download className="w-3 h-3" /> Export
          </button>

          {/* Column Toggle */}
          <div className="relative">
            <button
              onClick={() => setShowColMenu(!showColMenu)}
              className="text-xs bg-gray-100 text-gray-700 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium hover:bg-gray-200"
            >
              <Columns3 className="w-3 h-3" /> Columns
            </button>
            {showColMenu && (
              <div className="absolute top-full right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 w-44 py-1">
                {ALL_COLUMNS.map((col) => (
                  <label key={col.key} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-xs text-gray-700">
                    <input
                      type="checkbox"
                      checked={visibleCols.includes(col.key)}
                      onChange={() => toggleCol(col.key)}
                      className="w-3 h-3 rounded border-gray-300 accent-primary"
                    />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
        <div className="overflow-auto h-full">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 10 }).map((_, i) => (
                <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />
              ))}
            </div>
          ) : sorted.length === 0 ? (
            <div className="p-10 text-center text-gray-400">No stocks found</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 z-10">
                <tr>
                  {hasCol("rank") && <th className="px-3 py-2 text-left text-xs text-gray-500 w-8">#</th>}
                  {hasCol("company") && <SortTh label="Company" sortKey="company" current={sortKey} dir={sortDir} onSort={toggleSort} />}
                  {hasCol("sector") && <SortTh label="Sector" sortKey="sector" current={sortKey} dir={sortDir} onSort={toggleSort} />}
                  {hasCol("pe") && <SortTh label="PE" sortKey="pe" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />}
                  {hasCol("cmp") && <SortTh label="CMP" sortKey="cmp" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />}
                  {hasCol("target") && <SortTh label="Target" sortKey="target" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />}
                  {hasCol("signal") && <SortTh label="Signal" sortKey="signal" current={sortKey} dir={sortDir} onSort={toggleSort} />}
                  {hasCol("valuation") && <SortTh label="Remark" sortKey="valuation" current={sortKey} dir={sortDir} onSort={toggleSort} />}
                  {hasCol("comments") && <th className="px-3 py-2 text-left text-xs text-gray-500">Comments</th>}
                  {hasCol("file") && <th className="px-3 py-2 text-left text-xs text-gray-500 w-12">File</th>}
                  {hasCol("quarter") && <th className="px-3 py-2 text-left text-xs text-gray-500">Qtr</th>}
                  {hasCol("exchange") && <th className="px-3 py-2 text-left text-xs text-gray-500">Exch</th>}
                </tr>
              </thead>
              <tbody>
                {sorted.map((row: Record<string, unknown>, idx: number) => (
                  <tr key={row.stock_symbol as string} className={`border-b border-gray-50 hover:bg-primary/5 transition-colors ${idx % 2 === 0 ? "" : "bg-gray-50/30"}`}>
                    {hasCol("rank") && <td className="px-3 py-2 text-gray-400 font-mono text-xs">{idx + 1}</td>}
                    {hasCol("company") && (
                      <td className="px-3 py-2">
                        <div className="font-medium text-gray-900 truncate max-w-[200px]">
                          {(row.company_name as string) || (row.stock_symbol as string)}
                        </div>
                        <div className="text-[10px] text-gray-400">{row.stock_symbol as string}</div>
                      </td>
                    )}
                    {hasCol("sector") && (
                      <td className="px-3 py-2">
                        <span className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full truncate max-w-[100px] inline-block">
                          {(row.sector as string) || "—"}
                        </span>
                      </td>
                    )}
                    {hasCol("pe") && (
                      <td className="px-3 py-2 text-right font-mono font-semibold">
                        {row.pe ? fmtNumber(row.pe as number) : "—"}
                      </td>
                    )}
                    {hasCol("cmp") && (
                      <td className="px-3 py-2 text-right font-mono text-gray-600">
                        {row.cmp ? `₹${fmtNumber(row.cmp as number)}` : "—"}
                      </td>
                    )}
                    {hasCol("target") && (
                      <td className="px-3 py-2 text-right font-mono text-gray-600">
                        {row.target_price ? `₹${fmtNumber(row.target_price as number)}` : "—"}
                      </td>
                    )}
                    {hasCol("signal") && (
                      <td className="px-3 py-2">
                        {row.recommendation ? (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium">
                            {row.recommendation as string}
                          </span>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                    )}
                    {hasCol("valuation") && (
                      <td className="px-3 py-2">
                        <RemarkBadge value={(row.valuation as string) || ""} />
                      </td>
                    )}
                    {hasCol("comments") && (
                      <td className="px-3 py-2 max-w-[200px]">
                        <span className="text-xs text-gray-500 truncate block">{(row.comments as string) || "—"}</span>
                      </td>
                    )}
                    {hasCol("file") && (
                      <td className="px-3 py-2">
                        {row.source_pdf_url ? (
                          <a
                            href={row.source_pdf_url as string}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-0.5 text-primary hover:text-primary-dark"
                          >
                            <FileText className="w-3.5 h-3.5" />
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                    )}
                    {hasCol("quarter") && (
                      <td className="px-3 py-2 text-xs text-gray-500">{row.quarter as string} {row.financial_year as string}</td>
                    )}
                    {hasCol("exchange") && (
                      <td className="px-3 py-2 text-xs text-gray-500">{(row.exchange as string) || "—"}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function SortTh({ label, sortKey, current, dir, onSort, align }: {
  label: string; sortKey: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void; align?: "left" | "right";
}) {
  const isActive = current === sortKey;
  return (
    <th
      className={`px-3 py-2 text-xs text-gray-500 font-medium cursor-pointer select-none hover:text-gray-700 ${align === "right" ? "text-right" : "text-left"}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {isActive ? (
          dir === "asc" ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
        ) : (
          <ArrowUpDown className="w-3 h-3 opacity-40" />
        )}
      </span>
    </th>
  );
}

function RemarkBadge({ value }: { value: string }) {
  const v = value.toUpperCase();
  let classes = "text-[11px] px-2 py-0.5 rounded-full font-medium ";
  if (v.includes("CHEAP") || v.includes("UNDER")) {
    classes += "bg-green-100 text-green-700";
  } else if (v.includes("EXPENSIVE") || v.includes("OVER")) {
    classes += "bg-red-100 text-red-700";
  } else if (v.includes("FAIR") || v.includes("INLINE")) {
    classes += "bg-amber-100 text-amber-700";
  } else if (v.includes("IGNORE")) {
    classes += "bg-gray-200 text-gray-600";
  } else {
    classes += "bg-gray-100 text-gray-600";
  }
  return <span className={classes}>{value || "—"}</span>;
}
