"use client";

import { useState, useRef, useEffect } from "react";
import { format, startOfMonth, endOfMonth, eachDayOfInterval, addMonths, subMonths, isSameDay, isSameMonth, isToday, isWithinInterval, startOfWeek, endOfWeek } from "date-fns";
import { Calendar, ChevronLeft, ChevronRight, X } from "lucide-react";

interface DateRangePickerProps {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}

export function DateRangePicker({ from, to, onChange }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState(new Date());
  const [selecting, setSelecting] = useState<"from" | "to">("from");
  const ref = useRef<HTMLDivElement>(null);

  const fromDate = from ? new Date(from) : null;
  const toDate = to ? new Date(to) : null;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const monthStart = startOfMonth(viewMonth);
  const monthEnd = endOfMonth(viewMonth);
  const calStart = startOfWeek(monthStart);
  const calEnd = endOfWeek(monthEnd);
  const days = eachDayOfInterval({ start: calStart, end: calEnd });

  const handleDayClick = (day: Date) => {
    const dateStr = format(day, "yyyy-MM-dd");
    if (selecting === "from") {
      onChange(dateStr, dateStr);
      setSelecting("to");
    } else {
      if (fromDate && day >= fromDate) {
        onChange(from, dateStr);
      } else {
        onChange(dateStr, dateStr);
      }
      setSelecting("from");
      setOpen(false);
    }
  };

  const isInRange = (day: Date) => {
    if (!fromDate || !toDate) return false;
    return isWithinInterval(day, { start: fromDate, end: toDate });
  };

  const label = fromDate && toDate
    ? `${format(fromDate, "dd MMM yyyy")} – ${format(toDate, "dd MMM yyyy")}`
    : fromDate
      ? `${format(fromDate, "dd MMM yyyy")} – ...`
      : "";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 text-xs py-1.5 px-3 rounded-lg border ${label ? "bg-primary/10 border-primary/30 text-primary font-medium" : "bg-white border-gray-200 text-gray-500"}`}
      >
        <Calendar className="w-3.5 h-3.5" />
        {label || "Date Range"}
        {label && (
          <span
            onClick={(e) => { e.stopPropagation(); onChange("", ""); }}
            className="ml-1 text-red-400 hover:text-red-600 cursor-pointer"
          >
            <X className="w-3 h-3" />
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 z-50 bg-white rounded-xl shadow-xl border border-gray-200 p-4 w-[280px]">
          <div className="flex items-center justify-between mb-3">
            <button onClick={() => setViewMonth(subMonths(viewMonth, 1))} className="p-1 rounded hover:bg-gray-100">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-semibold text-gray-800">{format(viewMonth, "MMMM yyyy")}</span>
            <button onClick={() => setViewMonth(addMonths(viewMonth, 1))} className="p-1 rounded hover:bg-gray-100">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-7 text-center text-[10px] font-medium text-gray-400 mb-1">
            {["SU", "MO", "TU", "WE", "TH", "FR", "SA"].map((d) => <div key={d}>{d}</div>)}
          </div>

          <div className="grid grid-cols-7 gap-0.5">
            {days.map((day, i) => {
              const isFrom = fromDate && isSameDay(day, fromDate);
              const isTo = toDate && isSameDay(day, toDate);
              const inRange = isInRange(day);
              const inMonth = isSameMonth(day, viewMonth);
              const today = isToday(day);

              return (
                <button
                  key={i}
                  onClick={() => handleDayClick(day)}
                  className={`w-8 h-8 rounded-full text-xs flex items-center justify-center transition-all
                    ${!inMonth ? "text-gray-300" : "text-gray-700"}
                    ${isFrom || isTo ? "bg-primary text-white font-bold" : ""}
                    ${inRange && !isFrom && !isTo ? "bg-primary/10" : ""}
                    ${today && !isFrom && !isTo ? "ring-2 ring-primary/50 font-semibold" : ""}
                    ${!isFrom && !isTo && inMonth ? "hover:bg-gray-100" : ""}
                  `}
                >
                  {format(day, "d")}
                </button>
              );
            })}
          </div>

          {label && (
            <div className="mt-3 text-center text-[10px] text-gray-500 border-t pt-2">
              {fromDate && toDate ? `${format(fromDate, "dd MMM yyyy")} → ${format(toDate, "dd MMM yyyy")}` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
