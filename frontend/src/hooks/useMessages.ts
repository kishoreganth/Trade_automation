"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchMessages, fetchMessageStats } from "@/lib/api";

interface MessageFilters {
  exchange?: string;
  sector?: string;
  search?: string;
  [key: string]: string | undefined;
}

export function useMessages(page = 1, perPage = 50, option = "all", filters: MessageFilters = {}) {
  const { exchange, sector, search } = filters;
  return useQuery({
    queryKey: ["messages", page, perPage, option, exchange, sector, search],
    queryFn: () => fetchMessages(page, perPage, option, { exchange, sector, search }),
    staleTime: 10_000,
  });
}

export function useMessageStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: fetchMessageStats,
    staleTime: 10_000,
  });
}
