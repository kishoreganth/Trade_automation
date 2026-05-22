import { useQuery } from "@tanstack/react-query";
import { fetchAllInsights } from "@/lib/api";

export interface AIInsightsFilters {
  page?: number;
  per_page?: number;
  insight_type?: string;
  symbol?: string;
  quarter?: string;
  financial_year?: string;
  status?: string;
}

export function useAIInsightsList(filters: AIInsightsFilters) {
  return useQuery({
    queryKey: ["ai-insights-list", filters],
    queryFn: () => fetchAllInsights(filters),
    staleTime: 15_000,
    refetchInterval: (query) => {
      const insights = query.state.data?.insights;
      if (insights?.some((i: { extraction_status: string }) =>
        i.extraction_status === "pending" || i.extraction_status === "processing"
      )) {
        return 8000;
      }
      return false;
    },
  });
}
