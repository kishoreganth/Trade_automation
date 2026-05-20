"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPEAnalysis, fetchPEFilters, fetchReportSummary, fetchReportDetail } from "@/lib/api";

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

interface ReportFilters {
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}

export function useReportSummary(filters?: ReportFilters) {
  return useQuery({
    queryKey: ["report-summary", filters],
    queryFn: () => fetchReportSummary(filters),
    staleTime: 30_000,
  });
}

interface ReportDetailParams {
  filter_type: string;
  filter_value: string;
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
  page?: number;
  per_page?: number;
}

export function useReportDetail(params: ReportDetailParams | null) {
  return useQuery({
    queryKey: ["report-detail", params],
    queryFn: () => fetchReportDetail(params!),
    enabled: !!params,
    staleTime: 15_000,
  });
}
