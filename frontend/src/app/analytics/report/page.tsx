"use client";

import { useReportSummary } from "@/hooks/usePEAnalysis";
import { fmtNumber } from "@/lib/utils";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts";

const PIE_COLORS = ["#10b981", "#ef4444", "#f59e0b", "#6366f1", "#8b5cf6"];

export default function AnalyticsReportPage() {
  const { data, isLoading } = useReportSummary();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card h-32 animate-pulse bg-surface-lighter/50" />
        ))}
      </div>
    );
  }

  if (!data) return <div className="text-gray-500">No data available</div>;

  const { summary, pe_distribution, valuation_counts, sector_summary, top_cheapest, top_expensive } = data;

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white">Analytics Report</h2>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <SummaryCard label="Total Reviewed" value={summary?.total || 0} />
        <SummaryCard label="Avg PE" value={fmtNumber(summary?.avg_pe || 0)} />
        <SummaryCard label="Median PE" value={fmtNumber(summary?.median_pe || 0)} />
        <SummaryCard label="Cheap" value={valuation_counts?.CHEAP || 0} color="text-accent-green" />
        <SummaryCard label="Expensive" value={valuation_counts?.EXPENSIVE || 0} color="text-accent-red" />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* PE Distribution Bar Chart */}
        <div className="card">
          <h3 className="text-sm font-medium text-gray-400 mb-3">PE Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pe_distribution || []}>
              <XAxis dataKey="range" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: "#1e1e2e", border: "1px solid #363650", borderRadius: 8 }}
                labelStyle={{ color: "#f3f4f6" }}
              />
              <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Valuation Pie Chart */}
        <div className="card">
          <h3 className="text-sm font-medium text-gray-400 mb-3">Valuation Split</h3>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={Object.entries(valuation_counts || {}).map(([name, value]) => ({ name, value }))}
                cx="50%"
                cy="50%"
                outerRadius={80}
                dataKey="value"
                label={({ name, value }) => `${name}: ${value}`}
              >
                {Object.keys(valuation_counts || {}).map((_, idx) => (
                  <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Sector Table */}
      <div className="card">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Sector Summary</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-lighter text-left text-xs text-gray-500 uppercase">
                <th className="px-3 py-2">Sector</th>
                <th className="px-3 py-2 text-right">Count</th>
                <th className="px-3 py-2 text-right">Avg PE</th>
                <th className="px-3 py-2 text-right">Cheap</th>
                <th className="px-3 py-2 text-right">Expensive</th>
              </tr>
            </thead>
            <tbody>
              {(sector_summary || []).map((s: Record<string, unknown>) => (
                <tr key={s.sector as string} className="border-b border-surface-lighter/50">
                  <td className="px-3 py-2 text-white">{s.sector as string}</td>
                  <td className="px-3 py-2 text-right text-gray-400">{s.count as number}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtNumber(s.avg_pe as number)}</td>
                  <td className="px-3 py-2 text-right text-accent-green">{s.cheap as number}</td>
                  <td className="px-3 py-2 text-right text-accent-red">{s.expensive as number}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top 10 Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Top10Table title="Top 10 Cheapest" data={top_cheapest || []} color="text-accent-green" />
        <Top10Table title="Top 10 Expensive" data={top_expensive || []} color="text-accent-red" />
      </div>
    </div>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="card text-center">
      <div className={`text-2xl font-bold ${color || "text-white"}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

function Top10Table({ title, data, color }: { title: string; data: Record<string, unknown>[]; color: string }) {
  return (
    <div className="card">
      <h3 className="text-sm font-medium text-gray-400 mb-3">{title}</h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-lighter text-xs text-gray-500">
            <th className="px-2 py-1 text-left">Symbol</th>
            <th className="px-2 py-1 text-right">PE</th>
            <th className="px-2 py-1 text-right">CMP</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.stock_symbol as string} className="border-b border-surface-lighter/30">
              <td className={`px-2 py-1.5 font-medium ${color}`}>{row.stock_symbol as string}</td>
              <td className="px-2 py-1.5 text-right font-mono">{fmtNumber(row.pe as number)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-gray-400">
                ₹{fmtNumber(row.cmp as number)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
