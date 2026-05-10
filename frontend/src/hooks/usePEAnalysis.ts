"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPEAnalysis, fetchPEFilters, fetchReportSummary } from "@/lib/api";

interface PEFilters {
  page?: number;
  per_page?: number;
  valuation_filter?: string;
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
}

export function usePEAnalysis(filters: PEFilters) {
  return useQuery({
    queryKey: ["pe-analysis", filters],
    queryFn: () => fetchPEAnalysis(filters),
    staleTime: 15_000,
  });
}

export function usePEFilters() {
  return useQuery({
    queryKey: ["pe-filters"],
    queryFn: fetchPEFilters,
    staleTime: 60_000,
  });
}

export function useReportSummary() {
  return useQuery({
    queryKey: ["report-summary"],
    queryFn: fetchReportSummary,
    staleTime: 30_000,
  });
}
