import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface ViewFilters {
  filters: Record<string, string>;
  search: string;
  sectors: string[];
  dateFrom: string;
  dateTo: string;
  remarkFilter?: string;
  signalFilter?: string;
  perPage: number;
}

interface FilterStore {
  views: Record<string, ViewFilters>;
  getViewFilters: (viewKey: string) => ViewFilters | undefined;
  setViewFilters: (viewKey: string, filters: Partial<ViewFilters>) => void;
  clearViewFilters: (viewKey: string) => void;
}

export const useFilterStore = create<FilterStore>()(
  persist(
    (set, get) => ({
      views: {},
      getViewFilters: (viewKey) => get().views[viewKey],
      setViewFilters: (viewKey, updated) =>
        set((state) => ({
          views: {
            ...state.views,
            [viewKey]: { ...state.views[viewKey], ...updated } as ViewFilters,
          },
        })),
      clearViewFilters: (viewKey) =>
        set((state) => {
          const { [viewKey]: _, ...rest } = state.views;
          return { views: rest };
        }),
    }),
    {
      name: "pe-filter-store",
      storage: createJSONStorage(() => sessionStorage),
    }
  )
);
