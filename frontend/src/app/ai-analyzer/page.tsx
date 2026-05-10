"use client";

import { useState } from "react";
import { Cpu, Play } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

export default function AIAnalyzerPage() {
  const [symbol, setSymbol] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const handleAnalyze = async () => {
    if (!symbol.trim()) {
      toast.error("Enter a stock symbol");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const { data } = await api.post("/ai_analysis/start", {
        symbol: symbol.toUpperCase().trim(),
      });
      toast.success(`Analysis started for ${symbol}`);
      setResult(data);
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Analysis failed";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-lg font-semibold text-white mb-4">AI Stock Analyzer</h2>

      <div className="card max-w-lg">
        <div className="flex gap-3">
          <input
            type="text"
            placeholder="Enter stock symbol (e.g., RELIANCE)"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
            className="input flex-1"
          />
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <Cpu className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Analyze
          </button>
        </div>
      </div>

      {result && (
        <div className="card mt-4 max-w-2xl">
          <h3 className="text-sm font-medium text-gray-400 mb-2">Analysis Result</h3>
          <pre className="text-xs text-gray-300 whitespace-pre-wrap overflow-auto max-h-96">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
