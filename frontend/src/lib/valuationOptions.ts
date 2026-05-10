/**
 * Valuation option fallback list — mirrors `backend/app/constants.py`.
 *
 * Used as the initial value while React Query is fetching the canonical list
 * from `/api/pe_analysis/valuation_options`. The runtime list ALWAYS wins,
 * so adding/removing options on the backend automatically updates the UI
 * without a frontend redeploy.
 */

export type ValuationTone = "bullish" | "neutral" | "bearish" | "ignored";

export interface ValuationOption {
  value: string;
  label: string;
  tone: ValuationTone;
  is_custom?: boolean;
  id?: number;
}

export const FALLBACK_VALUATION_OPTIONS: ValuationOption[] = [
  { value: "CHEAP",         label: "Cheap",         tone: "bullish" },
  { value: "UNDER_VALUED",  label: "Under Valued",  tone: "bullish" },
  { value: "INLINE",        label: "Inline",        tone: "neutral" },
  { value: "FAIRLY_VALUED", label: "Fairly Valued", tone: "neutral" },
  { value: "EXPENSIVE",     label: "Expensive",     tone: "bearish" },
  { value: "IGNORE",        label: "Ignore",        tone: "ignored" },
];

// Tailwind classes per option, for badges.
export const VALUATION_BADGE_COLORS: Record<string, string> = {
  CHEAP:         "bg-green-100 text-green-800 font-semibold",
  UNDER_VALUED:  "bg-emerald-100 text-emerald-800 font-semibold",
  INLINE:        "bg-blue-100 text-blue-800 font-semibold",
  FAIRLY_VALUED: "bg-amber-100 text-amber-800 font-semibold",
  EXPENSIVE:     "bg-red-100 text-red-800 font-semibold",
  IGNORE:        "bg-gray-200 text-gray-700 font-semibold",

  // Backward-compat for legacy stored values
  FAIR:          "bg-amber-100 text-amber-800 font-semibold",
  "FAIRLY VALUED": "bg-amber-100 text-amber-800 font-semibold",
  "UNDER VALUED":  "bg-emerald-100 text-emerald-800 font-semibold",
  UNDERVALUED:   "bg-emerald-100 text-emerald-800 font-semibold",
  OVERVALUED:    "bg-red-100 text-red-800 font-semibold",
  "OVER VALUED": "bg-red-100 text-red-800 font-semibold",
};

/** Convert a stored value to its display label, falling back to the value itself. */
export function valuationLabel(value: string | null | undefined, options: ValuationOption[]): string {
  if (!value) return "";
  const match = options.find((o) => o.value === value);
  if (match) return match.label;
  // Convert UNDER_VALUED -> Under Valued for legacy/unknown values
  return value.replace(/_/g, " ").replace(/\w\S*/g, (t) => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase());
}
