import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("session_token") : null;
  if (token) {
    config.headers["X-Session-Token"] = token;
  }
  return config;
});

let _knownAppVersion: string | null = null;
let _reloadScheduled = false;

function checkAppVersion(version: string | undefined) {
  if (typeof window === "undefined" || _reloadScheduled) return;
  if (!version || version === "dev") return;

  if (_knownAppVersion === null) {
    _knownAppVersion = version;
    return;
  }
  if (version !== _knownAppVersion) {
    _reloadScheduled = true;
    console.warn(`[auto-reload] Backend updated: ${_knownAppVersion} → ${version}`);
    window.location.reload();
  }
}

api.interceptors.response.use(
  (res) => {
    checkAppVersion(res.headers["x-app-version"] as string | undefined);
    return res;
  },
  (error) => {
    if (error.response?.headers) {
      checkAppVersion(error.response.headers["x-app-version"] as string | undefined);
    }
    const status = error.response?.status;
    if (status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("session_token");
    }
    if (status === 429) {
      const retryAfter = Number(error.response.headers?.["retry-after"]) || 5;
      error.retryAfterMs = retryAfter * 1000;
    }
    return Promise.reject(error);
  }
);

export default api;

// ─── Health ───

export async function fetchHealth() {
  const resp = await axios.get("/health", {
    timeout: 5_000,
    validateStatus: (s) => s === 200 || s === 503,
  });
  return resp.data;
}

// ─── Messages ───

export async function fetchMessages(
  page = 1,
  perPage = 50,
  option = "all",
  filters: { exchange?: string; sector?: string; search?: string } = {}
) {
  const params: Record<string, unknown> = { page, per_page: perPage, option };
  if (filters.exchange) params.exchange = filters.exchange;
  if (filters.sector) params.sector = filters.sector;
  if (filters.search) params.search = filters.search;
  const { data } = await api.get("/messages", { params });
  return data;
}

export async function fetchMessageStats() {
  const { data } = await api.get("/messages/stats");
  return data;
}

export async function fetchSectors() {
  const { data } = await api.get("/sectors");
  return data;
}

// ─── PE Analysis ───

export async function fetchPEAnalysis(params: {
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
  valuation?: string;
  signal?: string;
  segment?: string;
  sort_by?: string;
  sort_dir?: string;
}) {
  const { data } = await api.get("/pe_analysis", { params });
  return data;
}

export async function fetchPEFilters() {
  const { data } = await api.get("/pe_analysis/filters");
  return data;
}

export async function fetchReportSummary(params?: {
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
}) {
  const { data } = await api.get("/pe_analysis/report_summary", { params });
  return data;
}

export async function fetchReportDetail(params: {
  filter_type: string;
  filter_value: string;
  year?: string;
  quarter?: string;
  exchange?: string;
  sector?: string;
  page?: number;
  per_page?: number;
}) {
  const { data } = await api.get("/pe_analysis/report_detail", { params });
  return data;
}

export async function deletePEAnalysis(symbol: string) {
  const { data } = await api.delete(`/pe_analysis/${symbol}`);
  return data;
}

export async function updatePEAnalysis(
  symbol: string,
  body: Record<string, unknown>,
  rowId?: number,
) {
  const params = rowId != null ? { row_id: rowId } : undefined;
  const { data } = await api.put(`/pe_analysis/${symbol}`, body, { params });
  return data;
}

export async function bulkIgnorePE(rowIds: number[]) {
  const { data } = await api.post("/pe_analysis/bulk_ignore", { row_ids: rowIds });
  return data;
}

export async function retriggerPEExtraction(symbol: string, rowId?: number) {
  const params = rowId ? { row_id: rowId } : undefined;
  const { data } = await api.post(`/pe_analysis/${symbol}/retrigger`, null, { params });
  return data;
}

export async function fetchValuationOptions() {
  const { data } = await api.get("/pe_analysis/valuation_options");
  return data;
}

export async function createCustomValuation(value: string, label?: string, tone?: string) {
  const { data } = await api.post("/pe_analysis/valuation_options", {
    value,
    label: label || value,
    tone: tone || "neutral",
  });
  return data;
}

export async function deleteCustomValuation(value: string) {
  const { data } = await api.delete(`/pe_analysis/valuation_options/${encodeURIComponent(value)}`);
  return data;
}

// ─── PE Formulas ───

export async function fetchPEFormulas() {
  const { data } = await api.get("/pe_formulas");
  return data;
}

export async function createPEFormula(body: { name: string; q1_expr: string; q2_expr: string; q3_expr: string; q4_expr: string }) {
  const { data } = await api.post("/pe_formulas", body);
  return data;
}

export async function activatePEFormula(formulaId: number) {
  const { data } = await api.put(`/pe_formulas/${formulaId}/activate`);
  return data;
}

// ─── Jobs ───

export async function triggerJob(jobType: string) {
  const { data } = await api.post(`/jobs/${jobType}/start`);
  return data;
}

export async function fetchJobStatus(jobId: string) {
  const { data } = await api.get(`/jobs/${jobId}/status`);
  return data;
}

// ─── Orders / Place Order ───

export async function fetchOrderSheet() {
  const { data } = await api.get("/place_order/sheet");
  return data;
}

export async function getSessionStatus() {
  const { data } = await api.get("/place_order/session/status");
  return data;
}

export async function authenticateTotp(totp: string) {
  const { data } = await api.post("/place_order/session/authenticate", { totp });
  return data;
}

export async function fetchQuotes() {
  const { data } = await api.post("/place_order/quotes/fetch");
  return data;
}

export async function placeAllOrders(ordersPerMinute = 185, maxConcurrent = 2) {
  const { data } = await api.post("/place_order/execute/all", {
    orders_per_minute: ordersPerMinute,
    max_concurrent: maxConcurrent,
  });
  return data;
}

export async function executeOrder(order: { symbol: string; action: string; qty: number; price: number }) {
  const { data } = await api.post("/place_order/execute", order);
  return data;
}

export async function getOrderSource() {
  const { data } = await api.get("/place_order/source");
  return data;
}

export async function importOrderStocks(stocks: Record<string, unknown>[]) {
  const { data } = await api.post("/place_order/stocks/import", { stocks });
  return data;
}

export async function uploadOrderStocksFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/place_order/stocks/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60_000,
  });
  return data;
}

export async function deleteOrderStock(symbol: string) {
  const { data } = await api.delete(`/place_order/stocks/${encodeURIComponent(symbol)}`);
  return data;
}

export async function syncMasterScrip() {
  const { data } = await api.post("/place_order/sync_master_scrip", null, { timeout: 120_000 });
  return data;
}

export async function getRunStatus() {
  const { data } = await api.get("/place_order/run-status");
  return data;
}

export async function getOrderProgress() {
  const { data } = await api.get("/place_order/order-progress");
  return data;
}

// ─── Concall Insights ───

export async function fetchConcallInsightByMessage(messageId: number) {
  const { data } = await api.get(`/concall/insights/by-message/${messageId}`);
  return data;
}

export async function fetchConcallInsights(params?: {
  page?: number;
  per_page?: number;
  symbol?: string;
  quarter?: string;
  financial_year?: string;
}) {
  const { data } = await api.get("/concall/insights", { params });
  return data;
}

export async function triggerConcallExtraction(body: {
  symbol: string;
  pdf_url: string;
  exchange?: string;
  company_name?: string;
  message_id?: number;
}) {
  const { data } = await api.post("/concall/extract", body);
  return data;
}

// ─── Announcement Insights ───

export async function fetchAnnouncementInsightByMessage(messageId: number) {
  const { data } = await api.get(`/insights/announcements/by-message/${messageId}`);
  return data;
}

export async function fetchAnnouncementInsights(params?: {
  page?: number;
  per_page?: number;
  announcement_type?: string;
  symbol?: string;
  quarter?: string;
  financial_year?: string;
}) {
  const { data } = await api.get("/insights/announcements", { params });
  return data;
}

export async function fetchAllInsights(params?: {
  page?: number;
  per_page?: number;
  insight_type?: string;
  symbol?: string;
  quarter?: string;
  financial_year?: string;
  status?: string;
}) {
  const { data } = await api.get("/insights/all", { params });
  return data;
}

export async function fetchAIInsightsSummary() {
  const { data } = await api.get("/insights/ai/summary");
  return data;
}

export async function triggerAnnouncementExtraction(body: {
  symbol: string;
  pdf_url: string;
  announcement_type: string;
  exchange?: string;
  company_name?: string;
  message_id?: number;
}) {
  const { data } = await api.post("/insights/extract", body);
  return data;
}

// ─── Export ───

export async function exportPEAnalysisCSV(params: Record<string, string>) {
  const { data } = await api.get("/pe_analysis", { params: { ...params, per_page: "5000", page: "1" } });
  return data;
}
