import { useQuery } from "@tanstack/react-query";
import api from "../api/client";
import { AlertTriangle, CheckCircle2, Clock, Lock, XCircle, Zap } from "lucide-react";

const SCOPE_LABELS = { 1: "Scope 1 — Direct", 2: "Scope 2 — Electricity", 3: "Scope 3 — Value Chain" };
const SCOPE_COLORS = { 1: "bg-orange-100 text-orange-800", 2: "bg-blue-100 text-blue-800", 3: "bg-purple-100 text-purple-800" };

function StatCard({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
      <div className={`p-2.5 rounded-lg ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <div className="text-2xl font-bold tabular-nums">{value}</div>
        <div className="text-sm text-gray-500">{label}</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: summary, isLoading } = useQuery({
    queryKey: ["summary"],
    queryFn: () => api.get("/records/summary/").then((r) => r.data),
  });

  if (isLoading) return <div className="p-8 text-gray-400">Loading summary…</div>;

  const s = summary || {};
  const bs = s.by_status || {};
  const co2e = s.co2e_by_scope_kg || {};
  const totalCo2e = Object.values(co2e).reduce((a, b) => a + b, 0);

  return (
    <div className="p-4 md:p-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Review Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Emissions data waiting for analyst sign-off</p>
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <StatCard label="Pending Review" value={bs.PENDING ?? 0} icon={Clock} color="bg-yellow-100 text-yellow-700" />
        <StatCard label="Flagged" value={bs.FLAGGED ?? 0} icon={AlertTriangle} color="bg-red-100 text-red-700" />
        <StatCard label="Approved" value={bs.APPROVED ?? 0} icon={CheckCircle2} color="bg-green-100 text-green-700" />
        <StatCard label="Rejected" value={bs.REJECTED ?? 0} icon={XCircle} color="bg-gray-100 text-gray-700" />
        <StatCard label="Locked for Audit" value={bs.LOCKED ?? 0} icon={Lock} color="bg-indigo-100 text-indigo-700" />
        <StatCard label="Total Records" value={s.total_records ?? 0} icon={Zap} color="bg-brand-100 text-brand-700" />
      </div>

      {/* CO2e by scope */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h2 className="text-base font-semibold mb-4">CO₂e by Scope (kg)</h2>
        <div className="space-y-3">
          {[1, 2, 3].map((scope) => {
            const val = co2e[scope] || 0;
            const pct = totalCo2e > 0 ? (val / totalCo2e) * 100 : 0;
            return (
              <div key={scope}>
                <div className="flex justify-between text-sm mb-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${SCOPE_COLORS[scope]}`}>
                    {SCOPE_LABELS[scope]}
                  </span>
                  <span className="font-mono tabular-nums text-gray-700">
                    {val.toLocaleString(undefined, { maximumFractionDigits: 0 })} kg
                  </span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className="h-2 rounded-full bg-brand-500 transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-4 pt-4 border-t border-gray-100 flex justify-between text-sm">
          <span className="text-gray-500">Total CO₂e</span>
          <span className="font-semibold tabular-nums">
            {(totalCo2e / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} tCO₂e
          </span>
        </div>
      </div>

      {/* Data quality note */}
      {(s.flagged_rows ?? 0) > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex gap-3">
          <AlertTriangle size={18} className="text-amber-600 flex-none mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">
              {s.flagged_rows} row{s.flagged_rows !== 1 ? "s" : ""} have auto-detected data quality issues
            </p>
            <p className="text-xs text-amber-700 mt-0.5">
              These are rows where the parser detected unusual units, outlier values, unknown airport codes, or missing emission factors.
              Review them before locking.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
