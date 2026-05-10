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
} from "lucide-react";
import { useConfirm } from "@/components/ConfirmDialog";
import {
  fetchOrderSheet,
  getSessionStatus,
  authenticateTotp,
  fetchQuotes,
  placeAllOrders,
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

  // Orders
  const [placingOrders, setPlacingOrders] = useState(false);
  const [lastOrderTime, setLastOrderTime] = useState<string | null>(null);
  const [orderResult, setOrderResult] = useState<{ successful: number; total: number } | null>(null);

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

  // Load sheet + check session on mount, poll session every 30s
  useEffect(() => {
    loadSheet();
    checkSession();
    sessionPollRef.current = setInterval(checkSession, 30000);
    return () => {
      if (sessionPollRef.current) clearInterval(sessionPollRef.current);
    };
  }, [checkSession]);

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
        toast.success(result.message);
        setSheetData(result.rows || []);
        setLastQuoteFetch(result.fetch_time || new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }));
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
    try {
      const result = await placeAllOrders(185, 2);
      if (result.success) {
        toast.success(result.message);
        setLastOrderTime(result.order_time || new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }));
        setOrderResult({ successful: result.successful, total: result.total_orders });
      } else {
        toast.error(result.message || "Order placement failed");
      }
    } catch {
      toast.error("Order placement request failed");
    } finally {
      setPlacingOrders(false);
    }
  };

  const openGoogleSheet = () => {
    const url = sheetUrl || "https://docs.google.com/spreadsheets/d/1zftmphSqQfm0TWsUuaMl0J9mAsvQcafgmZ5U7DAXnzM";
    window.open(url, "_blank");
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
          <div className="flex gap-2">
            <button
              onClick={openGoogleSheet}
              className="bg-emerald-500 hover:bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" /> Open Sheet
            </button>
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
          <ol className="text-xs text-gray-600 space-y-1.5 list-decimal list-inside">
            <li>Open Google Docs</li>
            <li>Update in PLACE_ORDER_V2 sheet</li>
            <li>Update scrip list in Google Docs</li>
            <li>Refresh in Dashboard</li>
            <li>Put TOTP (Google Authenticator)</li>
            <li>Click &quot;Place Order&quot;</li>
          </ol>
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
          {lastQuoteFetch && (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-gray-500">
              <Clock className="w-3 h-3" />
              Last fetch: <span className="font-medium text-blue-600">Today {lastQuoteFetch}</span>
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
          {lastOrderTime && (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-gray-500">
              <Clock className="w-3 h-3" />
              Last order: <span className="font-medium text-blue-600">Today {lastOrderTime}</span>
            </div>
          )}
          {orderResult && (
            <div className="mt-2 text-[11px] text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
              <span className="text-emerald-600 font-semibold">{orderResult.successful}</span>/{orderResult.total} orders successful
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
