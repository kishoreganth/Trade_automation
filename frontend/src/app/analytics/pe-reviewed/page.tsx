"use client";

import { useState, useEffect, useRef } from "react";
import { PETable } from "@/components/PETable";
import { ColumnsDropdown } from "@/components/ColumnsDropdown";
import { FormulasModal } from "@/components/FormulasModal";
import { usePEFilters, usePEAnalysis } from "@/hooks/usePEAnalysis";
import { CheckCircle2, RefreshCw, Download, Search, X, ChevronDown, Filter } from "lucide-react";
import { DateRangePicker } from "@/components/DateRangePicker";
import { triggerJob, exportPEAnalysisCSV, fetchValuationOptions } from "@/lib/api";
import toast from "react-hot-toast";
import { useQueryClient, useQuery } from "@tanstack/react-query";

const ALL_COLUMNS = [
  { key: "date", label: "Date" },
  { key: "stock", label: "Stock" },
  { key: "exch", label: "Exchange" },
  { key: "quarter", label: "Quarter" },
  { key: "year", label: "Year" },
  { key: "qtr_eps", label: "Qtr EPS" },
  { key: "eps_qoq", label: "EPS Q/Q" },
  { key: "eps_yoy", label: "EPS Y/Y" },
  { key: "cum_eps", label: "Cum. EPS" },
  { key: "cum_prev_fy", label: "Cum. Prev FY" },
  { key: "prev_fy_eps", label: "Prev FY EPS" },
  { key: "fy_eps_est", label: "FY EPS (Est.)" },
  { key: "manual_eps", label: "Manual EPS" },
  { key: "cmp", label: "CMP" },
  { key: "pe", label: "PE" },
  { key: "signal", label: "Signal" },
  { key: "target", label: "Target" },
  { key: "sector", label: "Sector" },
  { key: "remark", label: "Remark" },
  { key: "comments", label: "Comments" },
  { key: "file", label: "File" },
  { key: "actions", label: "Actions" },
];

function getDefaultFilters() {
  const now = new Date();
  const m = now.getMonth() + 1;
  let quarter: string, fy: number;
  if (m >= 4 && m <= 6) { quarter = "Q4"; fy = now.getFullYear(); }
  else if (m >= 7 && m <= 9) { quarter = "Q1"; fy = now.getFullYear() + 1; }
  else if (m >= 10 && m <= 12) { quarter = "Q2"; fy = now.getFullYear() + 1; }
  else { quarter = "Q3"; fy = now.getFullYear(); }
  return { year: String(fy), quarter, exchange: "BSE" };
}

export default function PEReviewedPage() {
  const [filters, setFilters] = useState<Record<string, string>>(getDefaultFilters);
  const [search, setSearch] = useState("");
  const [sectors, setSectors] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [perPage, setPerPage] = useState(50);
  const [showFormulas, setShowFormulas] = useState(false);
  const [visibleCols, setVisibleCols] = useState<string[]>(ALL_COLUMNS.map((c) => c.key));
  const [remarkFilter, setRemarkFilter] = useState("");
  const [signalFilter, setSignalFilter] = useState("");
  const { data: filterOptions } = usePEFilters();
  const { data: valuationOptions } = useQuery({ queryKey: ["valuation-options"], queryFn: fetchValuationOptions, staleTime: 60_000 });
  const queryClient = useQueryClient();

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const clearFilters = () => setFilters({});
  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  const clearSecondRow = () => { setSearch(""); setSectors([]); setDateFrom(""); setDateTo(""); setRemarkFilter(""); setSignalFilter(""); };
  const secondRowActive = !!(search || sectors.length || dateFrom || dateTo || remarkFilter || signalFilter);

  const allFilters: Record<string, string> = { ...filters };
  if (search) allFilters.search = search;
  if (sectors.length) allFilters.sector = sectors.join(",");
  if (dateFrom) allFilters.date_from = dateFrom;
  if (dateTo) allFilters.date_to = dateTo;
  if (remarkFilter) allFilters.valuation = remarkFilter;
  if (signalFilter) allFilters.signal = signalFilter;

  const { data: peData } = usePEAnalysis({ page: 1, per_page: perPage, valuation_filter: "reviewed", ...allFilters });
  const totalStocks = peData?.total || 0;

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
    toast.success("Refreshed");
  };

  const handleFetchCMP = async () => {
    try {
      await triggerJob("fetch_quotes");
      toast.success("CMP fetch started");
    } catch {
      toast.error("Failed to start CMP fetch");
    }
  };

  const handleExport = async () => {
    try {
      const data = await exportPEAnalysisCSV({ ...allFilters, valuation_filter: "reviewed" });
      const rows = data.results || [];
      if (!rows.length) { toast.error("No data to export"); return; }
      const headers = ["stock_symbol", "company_name", "quarter", "financial_year", "exchange", "eps_diluted_standalone", "eps_diluted_consolidated", "fy_eps_diluted_standalone", "fy_eps_diluted_consolidated", "manual_fy_eps", "cmp", "pe", "recommendation", "target_price", "valuation", "comments"];
      const headerLabels = ["Symbol", "Company", "Quarter", "Year", "Exchange", "Qtr EPS (S)", "Qtr EPS (C)", "FY EPS (S)", "FY EPS (C)", "Manual EPS", "CMP", "PE", "Signal", "Target", "Valuation", "Comments"];
      const csv = [headerLabels.join(","), ...rows.map((r: Record<string, unknown>) => headers.map((h) => {
        const v = r[h];
        if (v == null) return "";
        return `"${String(v).replace(/"/g, '""')}"`;
      }).join(","))].join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pe_reviewed_${filters.year || "all"}_${filters.quarter || "all"}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${rows.length} rows`);
    } catch (err) {
      console.error(err);
      toast.error("Export failed");
    }
  };

  return (
    <div className="space-y-2 h-full flex flex-col">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="w-4 h-4 text-green-600" />
        <h2 className="text-sm font-semibold text-gray-900">PE Reviewed — Q4 FY26 Results</h2>
      </div>

      {/* Row 1: SHOW, Year, Quarter, Exchange */}
      <div className="flex flex-wrap items-center gap-2 bg-white rounded-lg border border-gray-200 px-3 py-2 shadow-sm">
        <div className="flex items-center gap-1 text-xs text-gray-500">
          <span>SHOW</span>
          <select className="input text-xs py-1 px-2" value={perPage} onChange={(e) => setPerPage(Number(e.target.value))}>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>

        <FilterBadge label="Year" value={filters.year} options={filterOptions?.years || ["2026", "2025"]} onChange={(v) => handleFilterChange("year", v)} formatLabel={(v) => `FY${v.slice(-2)}`} />
        <FilterBadge label="Quarter" value={filters.quarter} options={filterOptions?.quarters || ["Q1", "Q2", "Q3", "Q4"]} onChange={(v) => handleFilterChange("quarter", v)} />
        <FilterBadge label="Exchange" value={filters.exchange} options={filterOptions?.exchanges || ["BSE", "NSE"]} onChange={(v) => handleFilterChange("exchange", v)} />

        {activeFilterCount > 0 && (
          <button onClick={clearFilters} className="text-xs text-red-500 border border-red-200 rounded-md px-2 py-0.5 hover:bg-red-50 hover:border-red-300 active:scale-95 transition-all flex items-center gap-0.5"><X className="w-3 h-3" /> Clear</button>
        )}

        {totalStocks > 0 && <span className="text-xs text-gray-600 font-semibold bg-gray-100 px-2 py-0.5 rounded-md">{totalStocks} stocks</span>}
      </div>

      {/* Row 2: Refresh, Fetch CMP, Search, Sector, Date Range | Export, Formulas, Columns */}
      <div className="flex flex-wrap items-center gap-2 bg-white rounded-lg border border-gray-200 px-3 py-2 shadow-sm">
        <button onClick={handleRefresh} className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1">
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
        <button onClick={handleFetchCMP} className="bg-green-100 text-green-700 text-xs py-1.5 px-3 rounded-lg font-medium hover:bg-green-200 flex items-center gap-1">
          ₹ Fetch CMP
        </button>

        <div className="w-px h-5 bg-gray-200 mx-1" />

        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Filter by symbol or se..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input text-xs py-1.5 pl-8 pr-3 w-40"
          />
        </div>

        <MultiSectorSelect options={filterOptions?.sectors || []} selected={sectors} onChange={setSectors} />

        <DateRangePicker from={dateFrom} to={dateTo} onChange={(f, t) => { setDateFrom(f); setDateTo(t); }} />

        <select
          value={remarkFilter}
          onChange={(e) => setRemarkFilter(e.target.value)}
          className="text-xs py-1.5 px-2 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 font-medium focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="">All Remarks</option>
          {(valuationOptions || []).map((opt: { value: string; label: string }) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <select
          value={signalFilter}
          onChange={(e) => setSignalFilter(e.target.value)}
          className="text-xs py-1.5 px-2 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 font-medium focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="">All Signals</option>
          <option value="BUY">BUY</option>
          <option value="HOLD">HOLD</option>
          <option value="SELL">SELL</option>
          <option value="WATCH">WATCH</option>
        </select>

        {secondRowActive && (
          <button onClick={clearSecondRow} className="text-xs text-red-500 border border-red-200 rounded-md px-2 py-0.5 hover:bg-red-50 hover:border-red-300 active:scale-95 transition-all flex items-center gap-0.5"><X className="w-3 h-3" /> Clear</button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button onClick={handleExport} className="text-xs bg-green-100 text-green-700 px-2.5 py-1 rounded-lg flex items-center gap-1 font-medium hover:bg-green-200">
            <Download className="w-3 h-3" /> Export
          </button>
          <button onClick={() => setShowFormulas(true)} className="text-xs bg-primary/10 text-primary px-2.5 py-1 rounded-lg font-medium hover:bg-primary/20">
            Σ Formulas
          </button>
          <ColumnsDropdown columns={ALL_COLUMNS} visible={visibleCols} onChange={setVisibleCols} />
        </div>
      </div>

      <FormulasModal open={showFormulas} onClose={() => setShowFormulas(false)} />

      <div className="flex-1 min-h-0 bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
        <PETable valuationFilter="reviewed" filters={allFilters} perPage={perPage} visibleColumns={visibleCols} />
      </div>
    </div>
  );
}

function FilterBadge({ label, value, options, onChange, formatLabel }: { label: string; value?: string; options: string[]; onChange: (v: string) => void; formatLabel?: (v: string) => string }) {
  return (
    <select
      className="bg-primary/10 text-primary text-xs py-1 px-2 rounded-lg border border-primary/20 outline-none font-medium"
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">All {label}</option>
      {options.map((o) => (<option key={o} value={o}>{formatLabel ? formatLabel(o) : o}</option>))}
    </select>
  );
}

function MultiSectorSelect({ options, selected, onChange }: { options: string[]; selected: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const toggle = (s: string) => {
    onChange(selected.includes(s) ? selected.filter((x) => x !== s) : [...selected, s]);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="input text-xs py-1.5 px-2 min-w-[100px] flex items-center gap-1 text-left"
      >
        <span className="truncate max-w-[120px]">{selected.length ? `${selected.length} sector${selected.length > 1 ? "s" : ""}` : "All Sectors"}</span>
        <ChevronDown className="w-3 h-3 text-gray-400 ml-auto flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 w-56 max-h-60 overflow-y-auto py-1">
          {selected.length > 0 && (
            <button onClick={() => onChange([])} className="w-full text-left px-3 py-1.5 text-[10px] text-red-500 hover:bg-red-50 font-medium">Clear all</button>
          )}
          {options.map((s) => (
            <label key={s} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-xs text-gray-700">
              <input type="checkbox" checked={selected.includes(s)} onChange={() => toggle(s)} className="w-3 h-3 rounded border-gray-300 text-primary accent-primary" />
              <span className="truncate">{s}</span>
            </label>
          ))}
          {!options.length && <p className="px-3 py-2 text-[10px] text-gray-400">No sectors available</p>}
        </div>
      )}
    </div>
  );
}
