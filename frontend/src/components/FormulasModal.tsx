"use client";

import { useState } from "react";
import { X, Plus, Check } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPEFormulas, createPEFormula, activatePEFormula } from "@/lib/api";
import toast from "react-hot-toast";

interface Formula {
  id: number;
  name: string;
  q1_expr: string;
  q2_expr: string;
  q3_expr: string;
  q4_expr: string;
  is_default: boolean;
}

interface FormulasModalProps {
  open: boolean;
  onClose: () => void;
}

export function FormulasModal({ open, onClose }: FormulasModalProps) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newRules, setNewRules] = useState({ q1: "Q1*4", q2: "(Q1+Q2)*2", q3: "(Q1+Q2+Q3)*4/3", q4: "FY" });
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["pe-formulas"],
    queryFn: fetchPEFormulas,
    enabled: open,
  });

  const formulas: Formula[] = data?.formulas || [];

  if (!open) return null;

  const handleActivate = async (id: number) => {
    try {
      await activatePEFormula(id);
      queryClient.invalidateQueries({ queryKey: ["pe-formulas"] });
      queryClient.invalidateQueries({ queryKey: ["pe-analysis"] });
      toast.success("Formula activated");
    } catch {
      toast.error("Failed to activate formula");
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      await createPEFormula({
        name: newName.trim(),
        q1_expr: newRules.q1 || "Q1*4",
        q2_expr: newRules.q2 || "(Q1+Q2)*2",
        q3_expr: newRules.q3 || "(Q1+Q2+Q3)*4/3",
        q4_expr: newRules.q4 || "FY",
      });
      queryClient.invalidateQueries({ queryKey: ["pe-formulas"] });
      toast.success("Formula created");
      setCreating(false);
      setNewName("");
      setNewRules({ q1: "Q1*4", q2: "(Q1+Q2)*2", q3: "(Q1+Q2+Q3)*4/3", q4: "FY" });
    } catch {
      toast.error("Failed to create formula");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl shadow-2xl border border-gray-700 w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h3 className="text-sm font-semibold text-primary">FY EPS Formulas</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-4 space-y-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide font-semibold">Active Formulas</p>

          {formulas.map((f) => (
            <div
              key={f.id}
              className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${f.is_default ? "border-primary bg-primary/5" : "border-gray-700 hover:border-gray-600"}`}
              onClick={() => handleActivate(f.id)}
            >
              <div className={`w-5 h-5 rounded flex items-center justify-center flex-shrink-0 mt-0.5 ${f.is_default ? "bg-primary" : "bg-gray-700 border border-gray-600"}`}>
                {f.is_default && <Check className="w-3 h-3 text-white" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-100">{f.name}</span>
                  {f.name === "Default" && <span className="text-[9px] text-gray-500">(built-in)</span>}
                </div>
                <p className="text-[11px] text-gray-400 mt-1">
                  Q1: {f.q1_expr} · Q2: {f.q2_expr} · Q3: {f.q3_expr} · Q4: {f.q4_expr}
                </p>
              </div>
            </div>
          ))}

          {creating ? (
            <div className="border border-dashed border-gray-600 rounded-xl p-3 space-y-2">
              <input
                type="text"
                placeholder="Formula name..."
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full bg-gray-800 text-gray-200 text-xs rounded-lg px-3 py-1.5 border border-gray-700 outline-none focus:border-primary"
              />
              <div className="grid grid-cols-2 gap-2">
                <input placeholder="Q1 expr (e.g. Q1*4)" value={newRules.q1} onChange={(e) => setNewRules({ ...newRules, q1: e.target.value })} className="bg-gray-800 text-gray-200 text-[11px] rounded-lg px-2 py-1 border border-gray-700 outline-none focus:border-primary" />
                <input placeholder="Q2 expr" value={newRules.q2} onChange={(e) => setNewRules({ ...newRules, q2: e.target.value })} className="bg-gray-800 text-gray-200 text-[11px] rounded-lg px-2 py-1 border border-gray-700 outline-none focus:border-primary" />
                <input placeholder="Q3 expr" value={newRules.q3} onChange={(e) => setNewRules({ ...newRules, q3: e.target.value })} className="bg-gray-800 text-gray-200 text-[11px] rounded-lg px-2 py-1 border border-gray-700 outline-none focus:border-primary" />
                <input placeholder="Q4 expr (e.g. FY)" value={newRules.q4} onChange={(e) => setNewRules({ ...newRules, q4: e.target.value })} className="bg-gray-800 text-gray-200 text-[11px] rounded-lg px-2 py-1 border border-gray-700 outline-none focus:border-primary" />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setCreating(false)} className="text-xs text-gray-400 hover:text-gray-200 px-2 py-1">Cancel</button>
                <button onClick={handleCreate} className="text-xs bg-primary text-white px-3 py-1 rounded-lg font-medium">Save</button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="w-full border border-dashed border-gray-600 rounded-xl p-3 text-xs text-gray-400 hover:text-primary hover:border-primary flex items-center justify-center gap-1.5 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Create New Formula
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
