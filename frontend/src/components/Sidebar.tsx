"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import {
  MessageSquare,
  Clock,
  CheckCircle2,
  BarChartBig,
  Cpu,
  IndianRupee,
  FileText,
  Presentation,
  Phone,
  TrendingUp,
  Banknote,
  Users,
  ChevronLeft,
  ChevronRight,
  LogOut,
  User,
  Settings,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMessageStats } from "@/hooks/useMessages";

const feedItems = [
  { label: "All Messages", href: "/", icon: MessageSquare, id: "all" },
  { label: "Quarterly Result", href: "/?filter=quarterly_result", icon: FileText, id: "quarterly_result" },
  { label: "Investor Presentation", href: "/?filter=investor_presentation", icon: Presentation, id: "investor_presentation" },
  { label: "Concall", href: "/?filter=concall", icon: Phone, id: "concall" },
  { label: "Monthly Business Update", href: "/?filter=monthly_business_update", icon: TrendingUp, id: "monthly_business_update" },
  { label: "Fund Raising", href: "/?filter=fund_raising", icon: Banknote, id: "fund_raising" },
  { label: "Result + Concall", href: "/?filter=result_concall", icon: Users, id: "result_concall" },
  { label: "Outcome of Board Mee...", href: "/?filter=board_meeting", icon: FileText, id: "board_meeting" },
];

const analyticsItems = [
  { label: "PE Pending", href: "/analytics/pe-pending", icon: Clock },
  { label: "PE Reviewed", href: "/analytics/pe-reviewed", icon: CheckCircle2 },
  { label: "AI Insights", href: "/analytics/ai-insights", icon: Sparkles },
  { label: "Analytics Report", href: "/analytics/report", icon: BarChartBig },
];

export function Sidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data: stats } = useMessageStats();
  const currentFilter = searchParams.get("filter") || "";
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!profileOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [profileOpen]);

  const w = collapsed ? "w-[60px]" : "w-56";

  return (
    <aside className={cn("relative bg-navy-800 border-r border-navy-600 flex flex-col h-full transition-all duration-200 ease-in-out", w)}>
      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-5 z-20 w-6 h-6 rounded-full bg-white border border-gray-300 flex items-center justify-center text-gray-600 shadow-sm hover:scale-125 active:scale-95 transition-transform duration-150"
      >
        {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
      </button>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {/* Feed Section */}
        <div className="p-2 pt-4">
          {!collapsed && (
            <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2 px-2">Feed</h3>
          )}
          <nav className="space-y-0.5">
            {feedItems.map((item) => {
              const isActive =
                (item.id === "all" && pathname === "/" && !currentFilter) ||
                currentFilter === item.id;
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg text-sm transition-colors relative group",
                    collapsed ? "px-0 py-2 justify-center" : "px-2 py-2",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-gray-400 hover:text-white hover:bg-navy-700"
                  )}
                >
                  <item.icon className="w-4 h-4 flex-shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {!collapsed && item.id === "all" && stats?.today_count ? (
                    <span className="ml-auto bg-primary/20 text-primary text-[10px] px-1.5 py-0.5 rounded-full">
                      {stats.today_count}
                    </span>
                  ) : null}
                  {collapsed && (
                    <div className="absolute left-full ml-2 px-2 py-1 bg-navy-700 text-white text-xs rounded-md whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-50 shadow-lg">
                      {item.label}
                    </div>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Analytics Section */}
        <div className="p-2 border-t border-navy-600">
          {!collapsed && (
            <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2 px-2">Analytics</h3>
          )}
          <nav className="space-y-0.5">
            {analyticsItems.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg text-sm transition-colors relative group",
                    collapsed ? "px-0 py-2 justify-center" : "px-2 py-2",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-gray-400 hover:text-white hover:bg-navy-700"
                  )}
                >
                  <item.icon className="w-4 h-4 flex-shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {collapsed && (
                    <div className="absolute left-full ml-2 px-2 py-1 bg-navy-700 text-white text-xs rounded-md whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-50 shadow-lg">
                      {item.label}
                    </div>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Tools */}
        <div className="p-2 border-t border-navy-600">
          {!collapsed && (
            <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2 px-2">Tools</h3>
          )}
          <nav className="space-y-0.5">
            <NavItem href="/ai-analyzer" icon={Cpu} label="AI Analyzer" pathname={pathname} collapsed={collapsed} />
            <NavItem href="/place-order" icon={IndianRupee} label="Place Order" pathname={pathname} collapsed={collapsed} />
          </nav>
        </div>
      </div>

      {/* Bottom: Profile */}
      <div className="border-t border-navy-600">
        <div className="relative p-2" ref={profileRef}>
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className={cn(
              "w-full flex items-center gap-2.5 rounded-lg text-sm transition-colors text-gray-400 hover:text-white hover:bg-navy-700 relative",
              collapsed ? "px-0 py-2 justify-center" : "px-2 py-2"
            )}
          >
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary to-green-400 flex items-center justify-center flex-shrink-0">
              <User className="w-3.5 h-3.5 text-white" />
            </div>
            {!collapsed && (
              <>
                <div className="text-left flex-1 min-w-0">
                  <div className="text-xs font-medium text-gray-200 truncate">Admin</div>
                  <div className="text-[10px] text-gray-500 truncate">admin@stockhifi.com</div>
                </div>
              </>
            )}
          </button>

          {/* Profile dropdown */}
          {profileOpen && (
            <div className={cn(
              "absolute bottom-full mb-1 bg-navy-700 border border-navy-500 rounded-lg shadow-xl py-1 z-50",
              collapsed ? "left-full ml-1 w-40" : "left-2 right-2"
            )}>
              <button className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-300 hover:text-white hover:bg-navy-600 transition-colors">
                <Settings className="w-3.5 h-3.5" /> Settings
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-navy-600 transition-colors">
                <LogOut className="w-3.5 h-3.5" /> Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function NavItem({ href, icon: Icon, label, pathname, collapsed }: { href: string; icon: React.ElementType; label: string; pathname: string; collapsed: boolean }) {
  const isActive = pathname === href;
  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg text-sm transition-colors relative group",
        collapsed ? "px-0 py-2 justify-center" : "px-2 py-2",
        isActive
          ? "bg-primary/10 text-primary font-medium"
          : "text-gray-400 hover:text-white hover:bg-navy-700"
      )}
    >
      <Icon className="w-4 h-4 flex-shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
      {collapsed && (
        <div className="absolute left-full ml-2 px-2 py-1 bg-navy-700 text-white text-xs rounded-md whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-50 shadow-lg">
          {label}
        </div>
      )}
    </Link>
  );
}
