"use client";

import { MessageFeed } from "@/components/MessageFeed";
import { FilterPanel } from "@/components/FilterPanel";
import { useMessageStats } from "@/hooks/useMessages";
import { MessageSquare, Hash, Clock, Calendar } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, useCallback, useEffect } from "react";

function DashboardContent() {
  const searchParams = useSearchParams();
  const filter = searchParams.get("filter") || "all";
  const { data: stats } = useMessageStats();
  const [feedFilters, setFeedFilters] = useState<Record<string, string>>({});

  useEffect(() => {
    setFeedFilters({});
  }, [filter]);

  const handleFilterChange = useCallback((key: string, value: string) => {
    setFeedFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          icon={<MessageSquare className="w-5 h-5 text-primary" />}
          value={stats?.total?.toLocaleString() || "0"}
          label="TOTAL MESSAGES"
          color="border-l-primary"
        />
        <StatCard
          icon={<Calendar className="w-5 h-5 text-accent-green" />}
          value={stats?.today_count?.toLocaleString() || "0"}
          label="TODAY'S MESSAGES"
          color="border-l-accent-green"
        />
        <StatCard
          icon={<Hash className="w-5 h-5 text-accent-blue" />}
          value={stats?.unique_symbols?.toLocaleString() || "0"}
          label="UNIQUE SYMBOLS"
          color="border-l-accent-blue"
        />
        <StatCard
          icon={<Clock className="w-5 h-5 text-accent-purple" />}
          value={
            stats?.last_message_time
              ? new Date(stats.last_message_time).toLocaleTimeString("en-US", {
                  hour: "numeric",
                  minute: "2-digit",
                  second: "2-digit",
                  hour12: true,
                })
              : "--:--"
          }
          label="LAST MESSAGE"
          color="border-l-accent-purple"
        />
      </div>

      <FilterPanel key={filter} filters={feedFilters} onChange={handleFilterChange} />

      <MessageFeed option={filter} filters={feedFilters} />
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="animate-pulse h-96 bg-gray-100 rounded-xl" />}>
      <DashboardContent />
    </Suspense>
  );
}

function StatCard({ icon, value, label, color }: { icon: React.ReactNode; value: string; label: string; color: string }) {
  return (
    <div className={`stat-card border-l-4 ${color}`}>
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center">{icon}</div>
      <div>
        <p className="text-2xl font-bold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      </div>
    </div>
  );
}
