import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Flag, X, Check } from "lucide-react";
import clsx from "clsx";

const STATUS_STYLES = {
  PENDING: "bg-yellow-100 text-yellow-800",
  APPROVED: "bg-green-100 text-green-800",
  FLAGGED: "bg-red-100 text-red-800",
  REJECTED: "bg-gray-100 text-gray-600 line-through",
  LOCKED: "bg-indigo-100 text-indigo-800",
};

const SCOPE_BADGE = {
  1: "bg-orange-100 text-orange-700",
  2: "bg-blue-100 text-blue-700",
  3: "bg-purple-100 text-purple-700",
};

const FLAG_DESCRIPTIONS = {
  UNIT_UNKNOWN: "Unit code not in SAP mapping table",
  UNIT_PIECE_UNCONVERTIBLE: "Unit is 'pieces' — cannot convert to mass/volume",
  UNIT_UNUSUAL: "Unexpected unit for this category",
  VALUE_ZERO_OR_NEGATIVE: "Quantity is zero or negative",
  VALUE_OUTLIER_HIGH: "Value is unusually high — verify against source",
  VALUE_NEGATIVE_CHECK_CREDIT: "Negative kWh — may be a credit or solar export",
  VALUE_ZERO: "Zero kWh — check for missing read",
  CATEGORY_UNMAPPED: "Could not map GL account or material group to a category",
  MISSING_FACTOR: "No emission factor available for this row",
  PERIOD_LONG_ESTIMATED_OR_COMBINED: "Billing period >35 days — may be estimated or combined bill",
  PERIOD_SHORT_CHECK_READ: "Billing period <25 days — short read, verify meter",
  CLASS_ASSUMED_ECONOMY: "No cabin class recorded — assumed Economy for emission factor",
  AIRPORT_UNKNOWN: "Airport code not in lookup table",
  MISSING_DISTANCE: "No distance for ground transport — CO₂e not computed",
  NIGHTS_ASSUMED_1: "Nights not recorded — assumed 1 night",
  NIGHTS_ZERO_OR_NEGATIVE: "Nights ≤ 0, defaulted to 1",
  SEGMENT_TYPE_UNKNOWN: "Segment type could not be categorized",
};

function FlagPill({ flag }) {
  const [showTip, setShowTip] = useState(false);
  const base = flag.split(":")[0];
  const desc = FLAG_DESCRIPTIONS[base] || flag;
  return (
    <span
      className="relative inline-flex items-center gap-1 bg-red-50 text-red-700 border border-red-200 text-xs px-1.5 py-0.5 rounded cursor-help"
      onMouseEnter={() => setShowTip(true)}
      onMouseLeave={() => setShowTip(false)}
    >
      <AlertTriangle size={10} />
      {flag}
      {showTip && (
        <span className="absolute bottom-full left-0 mb-1 w-64 bg-gray-900 text-white text-xs rounded p-2 z-50 shadow-lg">
          {desc}
        </span>
      )}
    </span>
  );
}

function RecordRow({ record, onAction, selected, onToggle }) {
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState("");

  const fmt = (n) => n != null ? Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—";

  return (
    <>
      <tr
        className={clsx(
          "hover:bg-gray-50 cursor-pointer border-b border-gray-100",
          selected && "bg-brand-50"
        )}
      >
        <td className="px-3 py-3" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
          <input type="checkbox" checked={selected} onChange={onToggle} className="rounded" />
        </td>
        <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
          {record.period_start}
          {record.period_end !== record.period_start && <><br />{record.period_end}</>}
        </td>
        <td className="px-3 py-3">
          <span className={clsx("text-xs px-1.5 py-0.5 rounded font-medium", SCOPE_BADGE[record.scope])}>
            S{record.scope}
          </span>
        </td>
        <td className="px-3 py-3 text-xs text-gray-700 max-w-[140px] truncate" title={record.category}>
          {record.category.replace(/_/g, " ")}
        </td>
        <td className="px-3 py-3 text-xs text-gray-600 max-w-[120px] truncate" title={record.description}>
          {record.description || record.vendor || "—"}
        </td>
        <td className="px-3 py-3 text-xs font-mono text-right">
          {fmt(record.activity_quantity_source)} {record.activity_unit_source}
        </td>
        <td className="px-3 py-3 text-xs font-mono text-right">
          {record.co2e_kg ? `${fmt(record.co2e_kg)} kg` : <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-3">
          <div className="flex flex-wrap gap-1">
            {record.flag_reasons?.map((f) => <FlagPill key={f} flag={f} />)}
          </div>
        </td>
        <td className="px-3 py-3">
          <span className={clsx("text-xs px-2 py-0.5 rounded font-medium", STATUS_STYLES[record.status])}>
            {record.status}
          </span>
        </td>
        <td className="px-3 py-3">
          <button onClick={() => setExpanded(!expanded)} className="text-gray-400 hover:text-gray-700">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={10} className="px-6 py-4">
            <div className="grid grid-cols-2 gap-6 text-xs">
              <div>
                <p className="font-semibold text-gray-700 mb-2">Normalized Data</p>
                <dl className="space-y-1">
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">Normalized qty</dt><dd>{fmt(record.activity_quantity)} {record.activity_unit}</dd></div>
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">CO₂e</dt><dd>{record.co2e_kg ? `${fmt(record.co2e_kg)} kg` : "Not computed"}</dd></div>
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">Emission factor</dt><dd>{record.emission_factor ?? "—"}</dd></div>
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">Factor source</dt><dd>{record.emission_factor_source || "—"}</dd></div>
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">Facility code</dt><dd>{record.facility_code || "—"}</dd></div>
                  <div className="flex gap-2"><dt className="text-gray-500 w-36">Source row</dt><dd>{record.source_row_ref}</dd></div>
                  {record.is_manually_edited && <div className="flex gap-2 text-amber-700"><dt className="w-36">⚠ Edited</dt><dd>{record.edit_history?.length} change(s)</dd></div>}
                </dl>
              </div>
              <div>
                <p className="font-semibold text-gray-700 mb-2">Raw Source Data</p>
                <pre className="text-xs bg-white border border-gray-200 rounded p-2 overflow-auto max-h-32 text-gray-600">
                  {JSON.stringify(record.raw_data, null, 2)}
                </pre>
              </div>
            </div>
            {/* Review actions */}
            {record.status !== "LOCKED" && (
              <div className="mt-4 flex gap-2 items-center">
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Add a note (optional)"
                  className="border border-gray-300 rounded px-2 py-1 text-xs flex-1 max-w-xs focus:outline-none focus:ring-1 focus:ring-brand-500"
                />
                <button
                  onClick={() => onAction(record.id, "approve", note)}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                >
                  <Check size={12} /> Approve
                </button>
                <button
                  onClick={() => onAction(record.id, "flag", note)}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs bg-amber-500 text-white rounded hover:bg-amber-600"
                >
                  <Flag size={12} /> Flag
                </button>
                <button
                  onClick={() => onAction(record.id, "reject", note)}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs bg-gray-500 text-white rounded hover:bg-gray-600"
                >
                  <X size={12} /> Reject
                </button>
              </div>
            )}
            {record.review_note && (
              <p className="mt-2 text-xs text-gray-500 italic">Note: {record.review_note}</p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function ReviewPage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState({ status: "", scope: "", flagged_only: false, search: "" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(new Set());
  const [bulkNote, setBulkNote] = useState("");

  const params = {
    page,
    page_size: 50,
    ...(filters.status && { status: filters.status }),
    ...(filters.scope && { scope: filters.scope }),
    ...(filters.search && { search: filters.search }),
    ...(filters.flagged_only && { flagged_only: "true" }),
  };

  const { data, isLoading } = useQuery({
    queryKey: ["records", params],
    queryFn: () => api.get("/records/", { params }).then((r) => r.data),
  });

  const reviewMut = useMutation({
    mutationFn: ({ id, action, note }) => api.post(`/records/${id}/review/`, { action, note }),
    onSuccess: () => qc.invalidateQueries(["records"]),
  });

  const bulkMut = useMutation({
    mutationFn: ({ ids, action, note }) => api.post("/records/bulk-review/", { ids, action, note }),
    onSuccess: () => { qc.invalidateQueries(["records"]); setSelected(new Set()); },
  });

  const records = data?.results || [];
  const total = data?.count || 0;
  const totalPages = Math.ceil(total / 50);

  const toggleSelect = (id) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };

  const toggleAll = () => {
    if (selected.size === records.length) setSelected(new Set());
    else setSelected(new Set(records.map((r) => r.id)));
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Review Records</h1>
          <p className="text-sm text-gray-500">{total.toLocaleString()} records</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={filters.status}
          onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">All statuses</option>
          {["PENDING", "FLAGGED", "APPROVED", "REJECTED", "LOCKED"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={filters.scope}
          onChange={(e) => { setFilters({ ...filters, scope: e.target.value }); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">All scopes</option>
          <option value="1">Scope 1</option>
          <option value="2">Scope 2</option>
          <option value="3">Scope 3</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={filters.flagged_only}
            onChange={(e) => { setFilters({ ...filters, flagged_only: e.target.checked }); setPage(1); }}
            className="rounded"
          />
          Flagged only
        </label>
        <input
          type="text"
          value={filters.search}
          onChange={(e) => { setFilters({ ...filters, search: e.target.value }); setPage(1); }}
          placeholder="Search vendor, description, facility…"
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 w-64"
        />
      </div>

      {/* Bulk actions */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-4 px-4 py-2.5 bg-brand-50 border border-brand-200 rounded-lg text-sm">
          <span className="text-brand-800 font-medium">{selected.size} selected</span>
          <input
            type="text"
            value={bulkNote}
            onChange={(e) => setBulkNote(e.target.value)}
            placeholder="Bulk note (optional)"
            className="border border-gray-300 rounded px-2 py-1 text-xs w-48"
          />
          <button
            onClick={() => bulkMut.mutate({ ids: [...selected], action: "approve", note: bulkNote })}
            className="flex items-center gap-1 px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
          >
            <Check size={11} /> Approve all
          </button>
          <button
            onClick={() => bulkMut.mutate({ ids: [...selected], action: "reject", note: bulkNote })}
            className="flex items-center gap-1 px-3 py-1 text-xs bg-gray-500 text-white rounded hover:bg-gray-600"
          >
            <X size={11} /> Reject all
          </button>
          <button onClick={() => setSelected(new Set())} className="text-gray-400 hover:text-gray-700 ml-auto">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-3 text-left">
                <input type="checkbox" onChange={toggleAll} checked={selected.size === records.length && records.length > 0} className="rounded" />
              </th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Period</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Scope</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Category</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Description</th>
              <th className="px-3 py-3 text-right text-xs font-semibold text-gray-600">Source Qty</th>
              <th className="px-3 py-3 text-right text-xs font-semibold text-gray-600">CO₂e</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Flags</th>
              <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600">Status</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
            ) : records.length === 0 ? (
              <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">No records match the current filters</td></tr>
            ) : records.map((r) => (
              <RecordRow
                key={r.id}
                record={r}
                selected={selected.has(r.id)}
                onToggle={() => toggleSelect(r.id)}
                onAction={(id, action, note) => reviewMut.mutate({ id, action, note })}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm text-gray-600">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
              className="px-3 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Previous
            </button>
            <button
              disabled={page === totalPages}
              onClick={() => setPage(page + 1)}
              className="px-3 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
