"use client";

import { useState, useEffect } from "react";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Factory,
  Target,
  Shield,
  Zap,
  BarChart3,
  Loader2,
  Cpu,
  CheckCircle2,
  Clock,
  XCircle,
  Globe,
  PieChart,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { useAnnouncementInsight } from "@/hooks/useInsights";
import { triggerAnnouncementExtraction } from "@/lib/api";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

interface AIInsightCardProps {
  messageId: number;
  symbol: string;
  fileUrl?: string;
  companyName?: string;
  exchange?: string;
  announcementType: "investor_presentation" | "monthly_business_update";
}

const outlookConfig: Record<string, { bg: string; text: string; border: string; label: string }> = {
  bullish: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", label: "BULLISH" },
  positive: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", label: "POSITIVE" },
  neutral: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", label: "NEUTRAL" },
  mixed: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", label: "MIXED" },
  cautious: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200", label: "CAUTIOUS" },
  negative: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200", label: "NEGATIVE" },
};

const typeLabel: Record<string, string> = {
  investor_presentation: "Investor Presentation",
  monthly_business_update: "Monthly Business Update",
};

function ConfidenceDots({ level }: { level: number }) {
  return (
    <div className="flex items-center gap-0.5" title={`Confidence: ${level}/5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            i <= level ? "bg-emerald-500" : "bg-gray-200"
          )}
        />
      ))}
    </div>
  );
}

export function AIInsightCard({ messageId, symbol, fileUrl, companyName, exchange, announcementType }: AIInsightCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [polling, setPolling] = useState(false);
  const { data, isLoading, isError, refetch } = useAnnouncementInsight(messageId, true);

  useEffect(() => {
    if (polling && data?.found && data?.extraction_status === "completed") {
      setPolling(false);
    }
  }, [polling, data]);

  const handleExtract = async () => {
    if (!fileUrl || !symbol) return;
    setExtracting(true);
    try {
      await triggerAnnouncementExtraction({
        symbol: symbol.toUpperCase(),
        pdf_url: fileUrl,
        announcement_type: announcementType,
        exchange: exchange || "BSE",
        company_name: companyName || "",
        message_id: messageId,
      });
      toast.success(`Extraction queued for ${symbol}`);
      setPolling(true);
      if (expanded) {
        setTimeout(() => refetch(), 3000);
      }
    } catch {
      toast.error("Failed to trigger extraction");
    } finally {
      setExtracting(false);
    }
  };

  const status = data?.extraction_status;

  if (!expanded) {
    return (
      <div className="flex items-center gap-2 mt-1.5">
        <button
          onClick={() => setExpanded(true)}
          className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-md bg-violet-50 text-violet-600 hover:bg-violet-100 transition-colors border border-violet-100"
        >
          <Sparkles className="w-3.5 h-3.5" />
          View Insights
          <ChevronDown className="w-3 h-3" />
        </button>
        {fileUrl && (
          <button
            onClick={handleExtract}
            disabled={extracting || polling}
            className={cn(
              "inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-md transition-colors border disabled:opacity-60",
              extracting || polling
                ? "bg-amber-50 text-amber-600 border-amber-200"
                : "bg-gray-50 text-gray-600 hover:bg-gray-100 border-gray-200"
            )}
            title={`Extract AI insights from this ${typeLabel[announcementType]} PDF`}
          >
            {extracting || polling ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Cpu className="w-3.5 h-3.5" />
            )}
            {extracting ? "Queuing..." : polling ? "Extracting..." : "Extract AI"}
          </button>
        )}
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="mt-3 p-4 rounded-lg bg-gray-50 border border-gray-200">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin text-violet-500" />
          Loading insights for <span className="font-semibold text-gray-700">{symbol}</span>...
        </div>
      </div>
    );
  }

  const isInProgress = status === "pending" || status === "processing";
  if (isError || !data?.found || isInProgress) {
    return (
      <div className="mt-3 p-4 rounded-lg bg-gray-50 border border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {status === "processing" || status === "pending" || polling ? (
              <>
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                  <span className="text-sm font-medium text-blue-700">
                    {status === "pending" ? "Queued for extraction..." : "Extracting insights..."}
                  </span>
                </div>
                <span className="text-xs text-gray-400">Usually takes 15-30 seconds</span>
                {fileUrl && (
                  <button
                    onClick={handleExtract}
                    disabled={extracting}
                    className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors border border-gray-200 ml-2"
                  >
                    <Cpu className="w-3.5 h-3.5" />
                    Re-trigger
                  </button>
                )}
              </>
            ) : status === "failed" ? (
              <>
                <div className="flex items-center gap-2">
                  <XCircle className="w-4 h-4 text-red-500" />
                  <span className="text-sm font-medium text-red-700">Extraction failed</span>
                </div>
                {fileUrl && (
                  <button
                    onClick={handleExtract}
                    disabled={extracting}
                    className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors border border-gray-200"
                  >
                    <Cpu className="w-3.5 h-3.5" />
                    Retry
                  </button>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-gray-400" />
                  <span className="text-sm text-gray-600">No insights yet</span>
                </div>
                {fileUrl && (
                  <button
                    onClick={handleExtract}
                    disabled={extracting || polling}
                    className={cn(
                      "inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md transition-colors border",
                      extracting || polling
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-violet-50 text-violet-700 hover:bg-violet-100 border-violet-200"
                    )}
                  >
                    {extracting || polling ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Cpu className="w-3.5 h-3.5" />
                    )}
                    {extracting ? "Queuing..." : polling ? "Extracting..." : "Extract Now"}
                  </button>
                )}
              </>
            )}
          </div>
          <button
            onClick={() => setExpanded(false)}
            className="p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ChevronUp className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  const insight = data;
  const outlook = outlookConfig[insight.management_outlook] || outlookConfig.neutral;

  return (
    <div className="mt-3 rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-violet-50 to-fuchsia-50 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-4 h-4 text-violet-500" />
            <span className="text-sm font-semibold text-gray-800">AI Insights</span>
            <span className="text-xs text-gray-500">
              {insight.quarter} {insight.financial_year}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-600 font-medium">
              {typeLabel[announcementType]}
            </span>
          </div>
          {insight.management_outlook && (
            <span className={cn(
              "text-[11px] px-2 py-0.5 rounded-full font-semibold border",
              outlook.bg, outlook.text, outlook.border
            )}>
              {outlook.label}
            </span>
          )}
          {insight.management_confidence && (
            <ConfidenceDots level={insight.management_confidence} />
          )}
          <div className="flex items-center gap-1 text-xs text-emerald-600">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Extracted</span>
          </div>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="p-1 rounded hover:bg-white/80 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <ChevronUp className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Executive Summary */}
        {insight.executive_summary && (
          <p className="text-sm text-gray-700 leading-relaxed">
            {insight.executive_summary}
          </p>
        )}

        {/* Investment Thesis */}
        {insight.investment_thesis && (
          <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-violet-50/50 border border-violet-100">
            <Target className="w-4 h-4 text-violet-500 mt-0.5 flex-shrink-0" />
            <div>
              <span className="text-[10px] font-semibold text-violet-600 uppercase tracking-wider">Investment Thesis</span>
              <p className="text-sm text-gray-700 mt-0.5">{insight.investment_thesis}</p>
            </div>
          </div>
        )}

        {/* Bull/Bear Case */}
        {(insight.bull_case || insight.bear_case) && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {insight.bull_case && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-emerald-50/50 border border-emerald-100">
                <ArrowUpRight className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                <div>
                  <span className="text-[10px] font-semibold text-emerald-600 uppercase tracking-wider">Bull Case</span>
                  <p className="text-xs text-gray-700 mt-0.5">{insight.bull_case}</p>
                </div>
              </div>
            )}
            {insight.bear_case && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-50/50 border border-red-100">
                <ArrowDownRight className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
                <div>
                  <span className="text-[10px] font-semibold text-red-600 uppercase tracking-wider">Bear Case</span>
                  <p className="text-xs text-gray-700 mt-0.5">{insight.bear_case}</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Key Financial Metrics Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {insight.revenue != null && (
            <MetricCard
              label="Revenue"
              value={`₹${insight.revenue} ${insight.revenue_unit || "Cr"}`}
              icon={BarChart3}
              color="text-indigo-500"
            />
          )}
          {insight.ebitda_margin_pct != null && (
            <MetricCard label="EBITDA Margin" value={`${insight.ebitda_margin_pct}%`} icon={BarChart3} color="text-indigo-500" />
          )}
          {insight.pat_margin_pct != null && (
            <MetricCard label="PAT Margin" value={`${insight.pat_margin_pct}%`} icon={BarChart3} color="text-blue-500" />
          )}
          {insight.roce_pct != null && (
            <MetricCard label="ROCE" value={`${insight.roce_pct}%`} icon={TrendingUp} color="text-emerald-500" />
          )}
          {insight.roe_pct != null && (
            <MetricCard label="ROE" value={`${insight.roe_pct}%`} icon={TrendingUp} color="text-teal-500" />
          )}
          {insight.debt_to_equity != null && (
            <MetricCard label="D/E Ratio" value={`${insight.debt_to_equity}x`} icon={BarChart3} color="text-orange-500" />
          )}
          {insight.yoy_revenue_growth_pct != null && (
            <MetricCard label="YoY Growth" value={`${insight.yoy_revenue_growth_pct}%`} icon={TrendingUp} color="text-green-500" />
          )}
          {insight.capacity_utilization_pct != null && (
            <MetricCard label="Capacity Util" value={`${insight.capacity_utilization_pct}%`} icon={Factory} color="text-purple-500" />
          )}
          {insight.order_book_value != null && (
            <MetricCard label="Order Book" value={`₹${insight.order_book_value} Cr`} icon={Target} color="text-cyan-500" />
          )}
          {insight.free_cash_flow != null && (
            <MetricCard label="Free Cash Flow" value={`₹${insight.free_cash_flow} Cr`} icon={BarChart3} color="text-green-600" />
          )}
          {(insight.revenue_guidance_low || insight.revenue_guidance_high) && (
            <MetricCard
              label="Revenue Guidance"
              value={insight.revenue_guidance_low && insight.revenue_guidance_high
                ? `₹${insight.revenue_guidance_low}-${insight.revenue_guidance_high} Cr`
                : `₹${insight.revenue_guidance_low || insight.revenue_guidance_high} Cr`}
              icon={Target}
              color="text-emerald-500"
            />
          )}
          {insight.export_share_pct != null && (
            <MetricCard label="Export Share" value={`${insight.export_share_pct}%`} icon={Globe} color="text-sky-500" />
          )}
          {insight.next_quarter_outlook && (
            <MetricCard
              label="Next Quarter"
              value={insight.next_quarter_outlook.charAt(0).toUpperCase() + insight.next_quarter_outlook.slice(1)}
              icon={insight.next_quarter_outlook === "positive" ? TrendingUp : insight.next_quarter_outlook === "negative" ? TrendingDown : Minus}
              color={insight.next_quarter_outlook === "positive" ? "text-emerald-500" : insight.next_quarter_outlook === "negative" ? "text-red-500" : "text-amber-500"}
            />
          )}
        </div>

        {/* Segment Revenue Breakdown */}
        {insight.segment_revenue && insight.segment_revenue.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <PieChart className="w-3.5 h-3.5" /> Segment Breakdown
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {insight.segment_revenue.map((seg: { name: string; revenue?: number; margin_pct?: number }, i: number) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-50 border border-gray-100">
                  <span className="text-xs font-medium text-gray-700 truncate">{seg.name}</span>
                  <div className="flex items-center gap-2 text-xs">
                    {seg.revenue != null && <span className="font-semibold text-gray-800">₹{seg.revenue} Cr</span>}
                    {seg.margin_pct != null && (
                      <span className="text-emerald-600 font-medium">{seg.margin_pct}%</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Geography Split */}
        {insight.geography_split && insight.geography_split.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5" /> Geography Split
            </h4>
            <div className="flex flex-wrap gap-2">
              {insight.geography_split.map((geo: { region: string; pct: number }, i: number) => (
                <div key={i} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-sky-50 border border-sky-100">
                  <span className="text-xs text-gray-700 font-medium">{geo.region}</span>
                  <span className="text-xs text-sky-600 font-semibold">{geo.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Key Takeaways */}
        {insight.key_takeaways && insight.key_takeaways.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Key Takeaways</h4>
            <ul className="space-y-1.5">
              {insight.key_takeaways.map((t: string, i: number) => (
                <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center text-[10px] font-bold flex-shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Next Quarter Prediction */}
        {insight.next_quarter_prediction && (
          <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-amber-50/50 border border-amber-100">
            <Target className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
            <div>
              <span className="text-[10px] font-semibold text-amber-600 uppercase tracking-wider">Next Quarter Watch</span>
              <p className="text-sm text-gray-700 mt-0.5">{insight.next_quarter_prediction}</p>
            </div>
          </div>
        )}

        {/* Growth Drivers & Risks */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {insight.growth_drivers && insight.growth_drivers.length > 0 && (
            <div className="p-3 rounded-lg bg-emerald-50/50 border border-emerald-100">
              <h4 className="text-xs font-semibold text-emerald-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5" /> Growth Drivers
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {insight.growth_drivers.map((d: string, i: number) => (
                  <span key={i} className="text-xs px-2 py-1 rounded-md bg-white text-emerald-700 border border-emerald-200 font-medium">
                    {d}
                  </span>
                ))}
              </div>
            </div>
          )}
          {insight.key_risks && insight.key_risks.length > 0 && (
            <div className="p-3 rounded-lg bg-red-50/50 border border-red-100">
              <h4 className="text-xs font-semibold text-red-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5" /> Key Risks
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {insight.key_risks.map((r: string, i: number) => (
                  <span key={i} className="text-xs px-2 py-1 rounded-md bg-white text-red-700 border border-red-200 font-medium">
                    {r}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Management Priorities */}
        {insight.management_priorities && insight.management_priorities.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-2">Management Priorities</h4>
            <div className="flex flex-wrap gap-1.5">
              {insight.management_priorities.map((p: string, i: number) => (
                <span key={i} className="text-xs px-2 py-1 rounded-md bg-blue-50 text-blue-700 border border-blue-200 font-medium">
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon: Icon,
  color = "text-indigo-500",
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  color?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-gray-50 border border-gray-100">
      <Icon className={cn("w-4 h-4 flex-shrink-0", color)} />
      <div className="min-w-0">
        <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wide truncate">{label}</div>
        <div className="text-sm font-semibold text-gray-800 truncate">{value}</div>
      </div>
    </div>
  );
}
