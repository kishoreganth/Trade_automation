import { useQuery } from "@tanstack/react-query";
import { fetchAnnouncementInsightByMessage } from "@/lib/api";

/**
 * Fetch announcement insight for a message.
 * Pass `poll: true` when user has expanded the card or triggered extraction.
 */
export function useAnnouncementInsight(messageId: number | null, poll = false) {
  return useQuery({
    queryKey: ["announcement-insight", messageId],
    queryFn: () => fetchAnnouncementInsightByMessage(messageId!),
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
