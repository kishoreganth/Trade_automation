"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useReportSummary } from "@/hooks/usePEAnalysis";
import { ReportFilterBar } from "@/components/ReportFilterBar";
import { ReportDrillDrawer } from "@/components/ReportDrillDrawer";
import { fmtNumber } from "@/lib/utils";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  TrendingDown, TrendingUp, BarChart3, Target, Hash,
  ArrowUpDown, ChevronUp, ChevronDown,
} from "lucide-react";

interface DrillParams {
  filter_type: string;
  filter_value: string;
  title: string;
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}

interface ReportFilters {
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}

export default function AnalyticsReportPage() {
  const [filters, setFilters] = useState<ReportFilters>({});
  const [drillParams, setDrillParams] = useState<DrillParams | null>(null);
  const { data, isLoading } = useReportSummary(filters);
  const router = useRouter();

  const openDrill = (filter_type: string, filter_value: string, title: string) => {
    setDrillParams({ filter_type, filter_value, title, ...filters });
  };

  const openFullPage = (filter_type: string, filter_value: string, title: string) => {
    const params = new URLSearchParams({ type: filter_type, value: filter_value, title });
    if (filters.year) params.set("year", filters.year);
    if (filters.quarter) params.set("quarter", filters.quarter);
    if (filters.exchange) params.set("exchange", filters.exchange);
    if (filters.sector) params.set("sector", filters.sector);
    router.push(`/analytics/report/detail?${params.toString()}`);
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="h-10 bg-white rounded-xl animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-24 bg-white rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-64 bg-white rounded-xl animate-pulse" />
          <div className="h-64 bg-white rounded-xl animate-pulse" />
        </div>
      </div>
    );
  }

  if (!data) return <div className="text-gray-500 p-8 text-center">No data available</div>;

  const { summary, pe_distribution, valuation_counts, signal_counts, sector_summary, top_cheapest, top_expensive } = data;
  const total = summary?.total || 0;
  const cheapCount = valuation_counts?.CHEAP || 0;
  const expensiveCount = valuation_counts?.EXPENSIVE || 0;
  const cheapPct = total > 0 ? ((cheapCount / total) * 100).toFixed(1) : "0";
  const expensivePct = total > 0 ? ((expensiveCount / total) * 100).toFixed(1) : "0";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Analytics Report</h2>
          <p className="text-xs text-gray-500 mt-0.5">PE reviewed stocks — aggregated insights</p>
        </div>
      </div>

      <ReportFilterBar filters={filters} onChange={setFilters} />

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <SummaryCard
          icon={<Hash className="w-4 h-4" />}
          label="Total Reviewed"
          value={total}
          subtitle="stocks analyzed"
          onClick={() => router.push("/analytics/pe-reviewed")}
        />
        <SummaryCard
          icon={<BarChart3 className="w-4 h-4" />}
          label="Avg PE"
          value={fmtNumber(summary?.avg_pe || 0)}
          subtitle="price to earnings"
          color="text-primary"
        />
        <SummaryCard
          icon={<Target className="w-4 h-4" />}
          label="Median PE"
          value={fmtNumber(summary?.median_pe || 0)}
          subtitle="mid-point value"
          color="text-purple-600"
        />
        <SummaryCard
          icon={<TrendingDown className="w-4 h-4" />}
          label="Cheap"
          value={cheapCount}
          subtitle={`${cheapPct}% of total`}
          color="text-emerald-600"
          bgAccent="bg-emerald-50 border-emerald-200"
          onClick={() => openFullPage("valuation", "CHEAP", "Cheap Stocks")}
        />
        <SummaryCard
          icon={<TrendingUp className="w-4 h-4" />}
          label="Expensive"
          value={expensiveCount}
          subtitle={`${expensivePct}% of total`}
          color="text-red-600"
          bgAccent="bg-red-50 border-red-200"
          onClick={() => openFullPage("valuation", "EXPENSIVE", "Expensive Stocks")}
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PEDistributionChart data={pe_distribution || []} onBarClick={(range) => openDrill("pe_range", range, `PE Range: ${range}`)} />
        <ValuationBarChart data={valuation_counts || {}} onBarClick={(val) => openFullPage("valuation", val, `${val} Stocks`)} />
      </div>

      {/* Signal Distribution */}
      {signal_counts && Object.keys(signal_counts).length > 0 && (
        <SignalSection data={signal_counts} onSignalClick={(sig) => openFullPage("signal", sig, `Signal: ${sig}`)} />
      )}

      {/* Sector Table */}
      <SectorSummaryTable data={sector_summary || []} onRowClick={(sec) => openDrill("sector", sec, `Sector: ${sec}`)} />

      {/* Top 10 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Top10Table title="Top 10 Cheapest" data={top_cheapest || []} variant="cheap" />
        <Top10Table title="Top 10 Most Expensive" data={top_expensive || []} variant="expensive" />
      </div>

      <ReportDrillDrawer params={drillParams} onClose={() => setDrillParams(null)} />
    </div>
  );
}

/* ─── Summary Card ─── */

function SummaryCard({
  icon, label, value, subtitle, color, bgAccent, onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  subtitle: string;
  color?: string;
  bgAccent?: string;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border p-4 transition-all duration-200 ${
        onClick ? "cursor-pointer hover:shadow-md hover:-translate-y-0.5 active:scale-[0.98]" : ""
      } ${bgAccent || "bg-white border-gray-200"}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className={`p-1.5 rounded-lg bg-gray-100 ${color || "text-gray-600"}`}>{icon}</div>
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${color || "text-gray-900"}`}>{value}</div>
      <div className="text-[11px] text-gray-400 mt-1">{subtitle}</div>
    </div>
  );
}

/* ─── PE Distribution Bar Chart ─── */

function PEDistributionChart({ data, onBarClick }: { data: { range: string; count: number }[]; onBarClick: (range: string) => void }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">PE Distribution</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} onClick={(e) => { if (e?.activeLabel) onBarClick(e.activeLabel); }}>
          <XAxis dataKey="range" tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 10, boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}
            labelStyle={{ color: "#111827", fontWeight: 600 }}
            cursor={{ fill: "rgba(99,102,241,0.08)" }}
          />
          <Bar dataKey="count" fill="#6366f1" radius={[6, 6, 0, 0]} cursor="pointer" />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[11px] text-gray-400 mt-2 text-center">Click a bar to view stocks in that PE range</p>
    </div>
  );
}

/* ─── Valuation Bar Chart ─── */

const VALUATION_COLORS: Record<string, string> = {
  CHEAP: "#10b981",
  UNDER_VALUED: "#34d399",
  FAIR: "#f59e0b",
  EXPENSIVE: "#ef4444",
  OVER_VALUED: "#dc2626",
  IGNORE: "#9ca3af",
  UNKNOWN: "#d1d5db",
};

function ValuationBarChart({ data, onBarClick }: { data: Record<string, number>; onBarClick: (val: string) => void }) {
  const chartData = Object.entries(data)
    .map(([name, value]) => ({ name, value, fill: VALUATION_COLORS[name] || "#6366f1" }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">Valuation Split</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={chartData} layout="vertical" onClick={(e) => { if (e?.activeLabel) onBarClick(e.activeLabel); }}>
          <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} width={90} />
          <Tooltip
            contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 10, boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}
            labelStyle={{ color: "#111827", fontWeight: 600 }}
            cursor={{ fill: "rgba(99,102,241,0.05)" }}
          />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} cursor="pointer">
            {chartData.map((entry, idx) => (
              <Cell key={idx} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[11px] text-gray-400 mt-1 text-center">Click a bar to drill down</p>
    </div>
  );
}

/* ─── Sector Summary Table ─── */

type SortKey = "sector" | "count" | "avg_pe" | "cheap" | "expensive";
type SortDir = "asc" | "desc";

function SectorSummaryTable({ data, onRowClick }: { data: Record<string, unknown>[]; onRowClick: (sector: string) => void }) {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  const sorted = useMemo(() => {
    return [...data].sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      if (typeof av === "string") return sortDir === "asc" ? (av as string).localeCompare(bv as string) : (bv as string).localeCompare(av as string);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [data, sortKey, sortDir]);

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-700">Sector Summary</h3>
        <p className="text-[11px] text-gray-400 mt-0.5">Click a row to view all stocks in that sector</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/50">
              <SortHeader label="Sector" sortKey="sector" current={sortKey} dir={sortDir} onSort={toggleSort} align="left" />
              <SortHeader label="Count" sortKey="count" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
              <SortHeader label="Avg PE" sortKey="avg_pe" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
              <SortHeader label="Cheap" sortKey="cheap" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
              <SortHeader label="Expensive" sortKey="expensive" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
              <th className="px-4 py-2.5 text-xs text-gray-500 text-right">Ratio</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, idx) => {
              const count = s.count as number;
              const cheap = s.cheap as number;
              const expensive = s.expensive as number;
              const cheapRatio = count > 0 ? (cheap / count) * 100 : 0;
              return (
                <tr
                  key={s.sector as string}
                  onClick={() => onRowClick(s.sector as string)}
                  className={`border-b border-gray-50 cursor-pointer hover:bg-primary/5 transition-colors ${idx % 2 === 0 ? "" : "bg-gray-50/30"}`}
                >
                  <td className="px-4 py-2.5 font-medium text-gray-900">{s.sector as string}</td>
                  <td className="px-4 py-2.5 text-right text-gray-600 font-mono">{count}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmtNumber(s.avg_pe as number)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-emerald-600">{cheap}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-red-600">{expensive}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-emerald-500 rounded-full"
                          style={{ width: `${cheapRatio}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-gray-400 w-8 text-right">{cheapRatio.toFixed(0)}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SortHeader({ label, sortKey, current, dir, onSort, align }: {
  label: string; sortKey: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void; align: "left" | "right";
}) {
  const isActive = current === sortKey;
  return (
    <th
      className={`px-4 py-2.5 text-xs text-gray-500 font-medium cursor-pointer select-none hover:text-gray-700 transition-colors ${align === "right" ? "text-right" : "text-left"}`}
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

/* ─── Top 10 Table ─── */

function Top10Table({ title, data, variant }: { title: string; data: Record<string, unknown>[]; variant: "cheap" | "expensive" }) {
  const accentColor = variant === "cheap" ? "text-emerald-600" : "text-red-600";
  const badgeBg = variant === "cheap" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700";

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${badgeBg}`}>
          {variant === "cheap" ? "Low PE" : "High PE"}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/50">
            <th className="px-4 py-2 text-left text-xs text-gray-500 w-8">#</th>
            <th className="px-4 py-2 text-left text-xs text-gray-500">Company</th>
            <th className="px-4 py-2 text-left text-xs text-gray-500">Sector</th>
            <th className="px-4 py-2 text-right text-xs text-gray-500">PE</th>
            <th className="px-4 py-2 text-right text-xs text-gray-500">CMP</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => (
            <tr key={row.stock_symbol as string} className="border-b border-gray-50 hover:bg-gray-50/80 transition-colors">
              <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">{idx + 1}</td>
              <td className="px-4 py-2.5">
                <div className={`font-medium truncate max-w-[180px] ${accentColor}`}>
                  {(row.company_name as string) || (row.stock_symbol as string)}
                </div>
                <div className="text-[11px] text-gray-400">{row.stock_symbol as string}</div>
              </td>
              <td className="px-4 py-2.5">
                <span className="text-[11px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                  {(row.sector as string) || "—"}
                </span>
              </td>
              <td className="px-4 py-2.5 text-right font-mono font-semibold">
                {fmtNumber(row.pe as number)}
              </td>
              <td className="px-4 py-2.5 text-right font-mono text-gray-500">
                ₹{fmtNumber(row.cmp as number)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Signal Section ─── */

const SIGNAL_COLORS: Record<string, { bg: string; text: string; bar: string }> = {
  BUY: { bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-700", bar: "#10b981" },
  HOLD: { bg: "bg-amber-50 border-amber-200", text: "text-amber-700", bar: "#f59e0b" },
  SELL: { bg: "bg-red-50 border-red-200", text: "text-red-700", bar: "#ef4444" },
  WATCH: { bg: "bg-blue-50 border-blue-200", text: "text-blue-700", bar: "#3b82f6" },
};

function SignalSection({ data, onSignalClick }: { data: Record<string, number>; onSignalClick: (sig: string) => void }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const totalSignals = entries.reduce((sum, [, v]) => sum + v, 0);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">Signal Distribution</h3>
          <p className="text-[11px] text-gray-400 mt-0.5">{totalSignals} stocks with signals assigned</p>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {entries.map(([signal, count]) => {
          const colors = SIGNAL_COLORS[signal.toUpperCase()] || { bg: "bg-gray-50 border-gray-200", text: "text-gray-700", bar: "#6b7280" };
          const pct = totalSignals > 0 ? ((count / totalSignals) * 100).toFixed(0) : "0";
          return (
            <div
              key={signal}
              onClick={() => onSignalClick(signal)}
              className={`rounded-xl border p-4 cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all active:scale-[0.98] ${colors.bg}`}
            >
              <div className={`text-xl font-bold ${colors.text}`}>{count}</div>
              <div className="text-xs font-semibold text-gray-700 mt-1">{signal}</div>
              <div className="flex items-center gap-2 mt-2">
                <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: colors.bar }} />
                </div>
                <span className="text-[10px] text-gray-500">{pct}%</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
