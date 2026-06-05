"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  IndianRupee,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  BarChart3,
  Rocket,
  Clock,
  CheckCircle2,
  Loader2,
  Upload,
  Database,
  FileSpreadsheet,
} from "lucide-react";
import { useConfirm } from "@/components/ConfirmDialog";
import {
  fetchOrderSheet,
  getSessionStatus,
  authenticateTotp,
  fetchQuotes,
  placeAllOrders,
  getOrderSource,
  uploadOrderStocksFile,
  syncMasterScrip,
  getRunStatus,
  getOrderProgress,
} from "@/lib/api";
import toast from "react-hot-toast";

interface SheetRow {
  OK?: string;
  STOCK_NAME?: string;
  EXCHANGE_TOKEN?: number;
  GAP?: number;
  MARKET?: string;
  QUANTITY?: number;
  "OPEN PRICE"?: number;
  "BUY ORDER"?: number;
  "SELL ORDER"?: number;
}

interface SessionInfo {
  active: boolean;
  message: string;
  expires_at: string | null;
  sid?: string;
  created_at?: string;
}

export default function PlaceOrderPage() {
  const confirm = useConfirm();
  // Sheet data
  const [sheetData, setSheetData] = useState<SheetRow[] | null>(null);
  const [sheetUrl, setSheetUrl] = useState<string>("");
  const [loadingSheet, setLoadingSheet] = useState(false);

  // Session
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checkingSession, setCheckingSession] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [authenticating, setAuthenticating] = useState(false);

  // Quotes
  const [fetchingQuotes, setFetchingQuotes] = useState(false);
  const [lastQuoteFetch, setLastQuoteFetch] = useState<string | null>(null);
  const [lastQuoteStatus, setLastQuoteStatus] = useState<{ success: boolean; timestamp: string; total_symbols?: number; prices_mapped?: number; error?: string } | null>(null);

  // Orders
  const [placingOrders, setPlacingOrders] = useState(false);
  const [lastOrderTime, setLastOrderTime] = useState<string | null>(null);
  const [orderResult, setOrderResult] = useState<{ successful: number; total: number } | null>(null);
  const [lastOrderStatus, setLastOrderStatus] = useState<{ success: boolean; timestamp: string; successful?: number; total_orders?: number; failed?: number; stocks?: number; error?: string } | null>(null);

  // Order progress (polling from Redis)
  interface OrderProgress {
    total: number;
    completed: number;
    success: number;
    failed: number;
    pending: number;
    percent: number;
    current_stock: string;
    status?: string;
    error?: string;
  }
  const [orderProgress, setOrderProgress] = useState<OrderProgress | null>(null);
  const progressPollRef = useRef<NodeJS.Timeout | null>(null);

  // Data source
  const [orderSource, setOrderSource] = useState<string>("gsheet");
  const [uploading, setUploading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Session polling
  const sessionPollRef = useRef<NodeJS.Timeout | null>(null);

  const checkSession = useCallback(async () => {
    setCheckingSession(true);
    try {
      const data = await getSessionStatus();
      setSession(data);
    } catch {
      setSession({ active: false, message: "Failed to check session", expires_at: null });
    } finally {
      setCheckingSession(false);
    }
  }, []);

  const loadRunStatus = useCallback(async () => {
    try {
      const data = await getRunStatus();
      if (data.quotes) setLastQuoteStatus(data.quotes);
      if (data.orders) setLastOrderStatus(data.orders);
    } catch { /* ignore */ }
  }, []);

  // Poll order progress while placing orders
  useEffect(() => {
    if (placingOrders) {
      progressPollRef.current = setInterval(async () => {
        try {
          const p = await getOrderProgress();
          if (!p) return;
          setOrderProgress(p as OrderProgress);
          if (p.status === "completed" || p.status === "error") {
            setPlacingOrders(false);
            loadRunStatus();
            if (p.status === "completed") {
              setOrderResult({ successful: p.success, total: p.total });
              setLastOrderTime(new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }));
              toast.success(`Orders done: ${p.success}/${p.total} successful`);
            } else {
              toast.error(p.error || "Order placement failed");
            }
          }
        } catch {}
      }, 2000);
    } else {
      if (progressPollRef.current) {
        clearInterval(progressPollRef.current);
        progressPollRef.current = null;
      }
    }
    return () => {
      if (progressPollRef.current) clearInterval(progressPollRef.current);
    };
  }, [placingOrders, loadRunStatus]);

  // Load sheet + check session + check source + run status on mount, poll session every 30s
  useEffect(() => {
    getOrderSource().then((d) => setOrderSource(d.source || "gsheet")).catch(() => {});
    loadSheet();
    checkSession();
    loadRunStatus();
    sessionPollRef.current = setInterval(checkSession, 30000);
    return () => {
      if (sessionPollRef.current) clearInterval(sessionPollRef.current);
    };
  }, [checkSession, loadRunStatus]);

  const loadSheet = async () => {
    setLoadingSheet(true);
    try {
      const data = await fetchOrderSheet();
      if (data.error) {
        toast.error(data.error);
        setSheetData([]);
      } else {
        setSheetData(data.rows || []);
        if (data.sheet_url) setSheetUrl(data.sheet_url);
        if (data.rows?.length) toast.success(`Loaded ${data.rows.length} stocks`);
      }
    } catch {
      toast.error("Failed to load sheet data");
    } finally {
      setLoadingSheet(false);
    }
  };

  const handleAuthenticate = useCallback(async (code?: string) => {
    const totp = code || totpCode;
    if (!totp || totp.length < 6) {
      toast.error("Enter a valid 6-digit TOTP code");
      return;
    }
    setAuthenticating(true);
    try {
      const result = await authenticateTotp(totp);
      if (result.success) {
        toast.success("Session authenticated!");
        setTotpCode("");
        await checkSession();
      } else {
        toast.error(result.message || "Authentication failed");
      }
    } catch {
      toast.error("Authentication request failed");
    } finally {
      setAuthenticating(false);
    }
  }, [totpCode, checkSession]);

  const handleGetQuotes = async () => {
    if (!session?.active) {
      toast.error("Authenticate first — session not active");
      return;
    }
    setFetchingQuotes(true);
    try {
      const result = await fetchQuotes();
      if (result.success) {
        setSheetData(result.rows || []);
        setLastQuoteFetch(result.fetch_time || new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }));
        const stats = result.stats || {};
        if (result.sheet_updated) {
          toast.success(`Quotes saved to DB — ${stats.prices_mapped || 0}/${stats.total_symbols || 0} prices mapped`);
        } else {
          toast.error(`Quotes fetched but DB write failed — ${stats.prices_mapped || 0} prices mapped (not saved)`);
        }
        loadRunStatus();
      } else {
        toast.error(result.message || "Failed to fetch quotes");
      }
    } catch {
      toast.error("Quote fetch request failed");
    } finally {
      setFetchingQuotes(false);
    }
  };

  const handlePlaceOrders = async () => {
    if (!session?.active) {
      toast.error("Authenticate first — session not active");
      return;
    }
    if (!sheetData || sheetData.length === 0) {
      toast.error("Load sheet and fetch quotes first");
      return;
    }
    const validRows = sheetData.filter((r) => r["BUY ORDER"] && r["SELL ORDER"] && Number(r["BUY ORDER"]) > 0);
    if (validRows.length === 0) {
      toast.error("No valid orders. Fetch quotes first.");
      return;
    }
    const ok = await confirm({
      title: "Confirm order placement",
      message: `You are about to place BUY + SELL orders for ${validRows.length} stocks. This will execute live trades through your broker.`,
      confirmLabel: `Place ${validRows.length} orders`,
      cancelLabel: "Cancel",
      variant: "warning",
    });
    if (!ok) return;

    setPlacingOrders(true);
    setOrderProgress(null);
    setOrderResult(null);
    try {
      const result = await placeAllOrders(185, 2);
      if (result.started) {
        toast.success("Order placement started");
      } else {
        toast.error(result.message || "Failed to start orders");
        setPlacingOrders(false);
      }
    } catch {
      toast.error("Order placement request failed");
      setPlacingOrders(false);
    }
  };

  const openGoogleSheet = () => {
    const url = sheetUrl || "https://docs.google.com/spreadsheets/d/1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM";
    window.open(url, "_blank");
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadOrderStocksFile(file);
      if (result.success) {
        toast.success(`Imported ${result.total_processed} stocks (${result.inserted} new, ${result.updated} updated)`);
        await loadSheet();
      } else {
        toast.error(result.message || "Import failed");
      }
    } catch {
      toast.error("File upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleSyncMasterScrip = async () => {
    setSyncing(true);
    try {
      const result = await syncMasterScrip();
      if (result.success) {
        toast.success(result.message);
        await loadSheet();
      } else {
        toast.error(result.message || "Sync failed");
      }
    } catch {
      toast.error("Master scrip sync failed. Ensure you are authenticated first.");
    } finally {
      setSyncing(false);
    }
  };

  const formatCurrency = (val: number | undefined | null) => {
    if (!val || isNaN(val)) return "—";
    return `₹${Number(val).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
  };

  const formatExpiry = (iso: string | null) => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-IN", { month: "short", day: "numeric", year: "numeric" }) + ", " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
    } catch {
      return iso;
    }
  };

  const formatTimestamp = (iso: string | null | undefined) => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      const today = new Date();
      const isToday = d.toDateString() === today.toDateString();
      const time = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
      if (isToday) return `Today ${time}`;
      return d.toLocaleDateString("en-IN", { month: "short", day: "numeric" }) + " " + time;
    } catch {
      return iso;
    }
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Left Panel — Table */}
      <div className="flex-1 space-y-4 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <IndianRupee className="w-5 h-5 text-primary" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Place Order</h2>
              <p className="text-xs text-gray-500">Market orders and TOTP authentication</p>
            </div>
          </div>
          <div className="flex gap-2 items-center">
            {/* Source badge */}
            <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-semibold ${
              orderSource === "postgres"
                ? "bg-violet-100 text-violet-700 border border-violet-200"
                : "bg-emerald-100 text-emerald-700 border border-emerald-200"
            }`}>
              {orderSource === "postgres" ? <Database className="w-3 h-3" /> : <FileSpreadsheet className="w-3 h-3" />}
              {orderSource === "postgres" ? "Postgres" : "Google Sheet"}
            </span>

            {orderSource === "postgres" ? (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="bg-violet-500 hover:bg-violet-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                  Import Stocks
                </button>
                <button
                  onClick={handleSyncMasterScrip}
                  disabled={syncing}
                  className="bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                  Sync Tokens
                </button>
              </>
            ) : (
              <button
                onClick={openGoogleSheet}
                className="bg-emerald-500 hover:bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" /> Open Sheet
              </button>
            )}
            <button
              onClick={loadSheet}
              disabled={loadingSheet}
              className="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingSheet ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Market Open Orders Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
          <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50/50">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-500" />
              <span className="text-sm font-medium text-gray-700">Market Open Orders</span>
              {sheetData && <span className="text-xs text-gray-400 ml-auto">{sheetData.length} stocks</span>}
            </div>
          </div>

          {sheetData === null ? (
            <div className="text-center py-16">
              <IndianRupee className="w-10 h-10 mx-auto mb-3 text-gray-300" />
              <p className="text-gray-500 text-sm">Click Refresh to load your order sheet</p>
            </div>
          ) : sheetData.length === 0 ? (
            <div className="text-center py-16">
              <p className="text-gray-400 text-sm">No orders found in sheet</p>
            </div>
          ) : (
            <div className="overflow-x-auto max-h-[calc(100vh-220px)]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-gray-200 text-[10px] text-gray-500 uppercase bg-gray-50 font-medium">
                    <th className="text-left px-3 py-2">OK</th>
                    <th className="text-left px-3 py-2">STOCK_NAME</th>
                    <th className="text-right px-3 py-2">EXCHANGE_TOKEN</th>
                    <th className="text-center px-3 py-2">GAP</th>
                    <th className="text-center px-3 py-2">MARKET</th>
                    <th className="text-center px-3 py-2">QUANTITY</th>
                    <th className="text-right px-3 py-2">OPEN PRICE</th>
                    <th className="text-right px-3 py-2">BUY ORDER</th>
                    <th className="text-right px-3 py-2">SELL ORDER</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {sheetData.map((row, i) => (
                    <tr key={i} className="hover:bg-blue-50/30 transition-colors">
                      <td className="px-3 py-2 text-gray-600 font-medium">{row.OK || ""}</td>
                      <td className="px-3 py-2 font-semibold text-gray-900">{row.STOCK_NAME || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-500">{row.EXCHANGE_TOKEN || "—"}</td>
                      <td className="px-3 py-2 text-center">
                        <span className="text-xs font-medium text-blue-600">{row.GAP ? `${row.GAP}%` : "—"}</span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                          {row.MARKET || "nse_cm"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center font-mono text-gray-700">{row.QUANTITY || 1}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-900">{formatCurrency(row["OPEN PRICE"])}</td>
                      <td className="px-3 py-2 text-right font-mono text-green-700 font-medium">{formatCurrency(row["BUY ORDER"])}</td>
                      <td className="px-3 py-2 text-right font-mono text-red-600 font-medium">{formatCurrency(row["SELL ORDER"])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Right Panel — Controls */}
      <div className="w-80 shrink-0 space-y-4">
        {/* Place Order Steps */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <span className="text-amber-500">📋</span> Place Order Steps
          </h3>
          {orderSource === "postgres" ? (
            <ol className="text-xs text-gray-600 space-y-1.5 list-decimal list-inside">
              <li>Import stocks via CSV/Excel (one-time)</li>
              <li>Refresh in Dashboard</li>
              <li>Get Quotes (fetches live prices)</li>
              <li>Put TOTP (Google Authenticator)</li>
              <li>Click &quot;Place Order&quot;</li>
            </ol>
          ) : (
            <ol className="text-xs text-gray-600 space-y-1.5 list-decimal list-inside">
              <li>Open Google Docs</li>
              <li>Update in PLACE_ORDER_V2 sheet</li>
              <li>Update scrip list in Google Docs</li>
              <li>Refresh in Dashboard</li>
              <li>Put TOTP (Google Authenticator)</li>
              <li>Click &quot;Place Order&quot;</li>
            </ol>
          )}
        </div>

        {/* Get Quotes */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800 mb-1 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-amber-500" /> Get Quotes
          </h3>
          <p className="text-[11px] text-gray-400 mb-3">Fetch street market quotes (3–4 mins)</p>
          <button
            onClick={handleGetQuotes}
            disabled={fetchingQuotes || !session?.active}
            className="w-full bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white font-bold text-sm py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 shadow-sm"
          >
            {fetchingQuotes ? (
              <><Loader2 className="w-4 h-4 animate-spin" /><span className="drop-shadow-sm">Fetching...</span></>
            ) : (
              <><BarChart3 className="w-4 h-4" /><span className="drop-shadow-sm">GET QUOTES (Manual)</span></>
            )}
          </button>
          {(lastQuoteFetch || lastQuoteStatus) && (
            <div className="mt-2 space-y-1">
              {lastQuoteFetch && (
                <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
                  <Clock className="w-3 h-3" />
                  Current session: <span className="font-medium text-blue-600">Today {lastQuoteFetch}</span>
                </div>
              )}
              {lastQuoteStatus && (
                <div className={`rounded-lg px-3 py-2 text-[11px] ${lastQuoteStatus.success ? "bg-emerald-50 border border-emerald-100" : "bg-red-50 border border-red-100"}`}>
                  <div className="flex items-center gap-1.5">
                    {lastQuoteStatus.success ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <ShieldAlert className="w-3 h-3 text-red-500" />
                    )}
                    <span className={`font-semibold ${lastQuoteStatus.success ? "text-emerald-700" : "text-red-700"}`}>
                      {lastQuoteStatus.success ? "Last run successful" : "Last run failed"}
                    </span>
                    <span className="text-gray-400 ml-auto">{formatTimestamp(lastQuoteStatus.timestamp)}</span>
                  </div>
                  {lastQuoteStatus.success && lastQuoteStatus.prices_mapped != null && (
                    <p className="text-gray-500 mt-0.5 ml-[18px]">{lastQuoteStatus.prices_mapped}/{lastQuoteStatus.total_symbols} prices mapped</p>
                  )}
                  {lastQuoteStatus.error && (
                    <p className="text-red-600 mt-0.5 ml-[18px] truncate">{lastQuoteStatus.error}</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Authentication */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800 mb-1 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-blue-500" /> Authentication
          </h3>
          <p className="text-[11px] text-gray-400 mb-3">Enter TOTP to activate trading</p>

          {/* TOTP Input */}
          <div className="mb-3">
            <label className="text-[11px] font-medium text-gray-600 mb-1 block">TOTP Code</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={totpCode}
                onChange={(e) => {
                  const val = e.target.value.replace(/\D/g, "").slice(0, 6);
                  setTotpCode(val);
                  if (val.length === 6) {
                    setTimeout(() => handleAuthenticate(val), 100);
                  }
                }}
                placeholder="• • • • • •"
                maxLength={6}
                className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm text-center font-mono tracking-[0.3em] focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                onKeyDown={(e) => e.key === "Enter" && handleAuthenticate()}
              />
              <button
                onClick={() => handleAuthenticate()}
                disabled={authenticating || totpCode.length < 6}
                className="px-3 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-300 text-white rounded-lg text-xs font-medium transition-colors"
              >
                {authenticating ? <Loader2 className="w-4 h-4 animate-spin" /> : "Verify"}
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-1">Enter the 6-digit code from your authenticator app</p>
          </div>

          {/* Session Status */}
          {session && (
            <div className={`rounded-lg p-3 ${session.active ? "bg-emerald-50 border border-emerald-200" : "bg-red-50 border border-red-200"}`}>
              <div className="flex items-center gap-2">
                {checkingSession ? (
                  <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
                ) : session.active ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                ) : (
                  <ShieldAlert className="w-4 h-4 text-red-500" />
                )}
                <span className={`text-xs font-semibold ${session.active ? "text-emerald-700" : "text-red-700"}`}>
                  {session.active ? "Session Active" : "Session Inactive"}
                </span>
              </div>
              {session.expires_at && session.active && (
                <p className="text-[10px] text-gray-500 mt-1.5 ml-6">
                  Session active until {formatExpiry(session.expires_at)}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Execute Orders */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800 mb-1 flex items-center gap-2">
            <Rocket className="w-4 h-4 text-blue-500" /> Execute Orders
          </h3>
          <p className="text-[11px] text-gray-400 mb-3">Place buy/sell orders for all stocks in the sheet</p>
          <button
            onClick={handlePlaceOrders}
            disabled={placingOrders || !session?.active}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-bold text-sm py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 shadow-sm"
          >
            {placingOrders ? (
              <><Loader2 className="w-4 h-4 animate-spin" /><span className="drop-shadow-sm">Placing Orders...</span></>
            ) : (
              <><Rocket className="w-4 h-4" /><span className="drop-shadow-sm">PLACE ORDERS</span></>
            )}
          </button>

          {/* Live Progress Bar */}
          {placingOrders && orderProgress && orderProgress.total > 0 && (
            <div className="mt-3 space-y-2">
              {/* 3-color progress bar */}
              <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden flex">
                {orderProgress.success > 0 && (
                  <div
                    className="bg-emerald-500 h-full transition-all duration-300"
                    style={{ width: `${(orderProgress.success / orderProgress.total) * 100}%` }}
                  />
                )}
                {orderProgress.failed > 0 && (
                  <div
                    className="bg-red-500 h-full transition-all duration-300"
                    style={{ width: `${(orderProgress.failed / orderProgress.total) * 100}%` }}
                  />
                )}
              </div>

              {/* Counts */}
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-gray-600 font-medium">
                  {orderProgress.completed}/{orderProgress.total}
                </span>
                <span className="text-gray-400">{orderProgress.percent}%</span>
              </div>
              <div className="flex gap-3 text-[10px]">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                  <span className="text-emerald-700 font-semibold">{orderProgress.success}</span>
                  <span className="text-gray-400">success</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                  <span className="text-red-600 font-semibold">{orderProgress.failed}</span>
                  <span className="text-gray-400">failed</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />
                  <span className="text-gray-600 font-semibold">{orderProgress.pending}</span>
                  <span className="text-gray-400">pending</span>
                </span>
              </div>

              {/* Current stock */}
              {orderProgress.current_stock && (
                <p className="text-[10px] text-gray-400 truncate">
                  Processing: <span className="text-gray-600 font-medium">{orderProgress.current_stock}</span>
                </p>
              )}
            </div>
          )}

          {(lastOrderTime || orderResult || lastOrderStatus) && (
            <div className="mt-2 space-y-1">
              {lastOrderTime && (
                <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
                  <Clock className="w-3 h-3" />
                  Current session: <span className="font-medium text-blue-600">Today {lastOrderTime}</span>
                </div>
              )}
              {orderResult && (
                <div className="text-[11px] text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                  <span className="text-emerald-600 font-semibold">{orderResult.successful}</span>/{orderResult.total} orders successful
                </div>
              )}
              {lastOrderStatus && (
                <div className={`rounded-lg px-3 py-2 text-[11px] ${lastOrderStatus.success ? "bg-emerald-50 border border-emerald-100" : "bg-red-50 border border-red-100"}`}>
                  <div className="flex items-center gap-1.5">
                    {lastOrderStatus.success ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <ShieldAlert className="w-3 h-3 text-red-500" />
                    )}
                    <span className={`font-semibold ${lastOrderStatus.success ? "text-emerald-700" : "text-red-700"}`}>
                      {lastOrderStatus.success ? "Last run successful" : "Last run failed"}
                    </span>
                    <span className="text-gray-400 ml-auto">{formatTimestamp(lastOrderStatus.timestamp)}</span>
                  </div>
                  {lastOrderStatus.success && lastOrderStatus.successful != null && (
                    <p className="text-gray-500 mt-0.5 ml-[18px]">{lastOrderStatus.successful}/{lastOrderStatus.total_orders} orders placed for {lastOrderStatus.stocks} stocks</p>
                  )}
                  {lastOrderStatus.error && (
                    <p className="text-red-600 mt-0.5 ml-[18px] truncate">{lastOrderStatus.error}</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
