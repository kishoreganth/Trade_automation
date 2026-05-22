import { useQuery } from "@tanstack/react-query";
import { fetchConcallInsightByMessage } from "@/lib/api";

/**
 * Fetch concall insight for a message.
 * Pass `poll: true` when user has expanded the card or triggered extraction.
 */
export function useConcallInsight(messageId: number | null, poll = false) {
  return useQuery({
    queryKey: ["concall-insight", messageId],
    queryFn: () => fetchConcallInsightByMessage(messageId!),
    enabled: !!messageId,
    staleTime: poll ? 10_000 : 120_000,
    retry: 1,
    refetchInterval: poll
      ? (query) => {
          const status = query.state.data?.extraction_status;
          if (status === "pending" || status === "processing") return 5000;
          return false;
        }
      : false,
  });
}
