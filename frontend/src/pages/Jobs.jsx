import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import { useAuth } from "../AuthContext";
import { Lock, CheckCircle2, AlertTriangle, Clock, XCircle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import clsx from "clsx";

const STATUS_ICON = {
  COMPLETE: <CheckCircle2 size={14} className="text-green-500" />,
  FAILED: <XCircle size={14} className="text-red-500" />,
  PROCESSING: <Clock size={14} className="text-yellow-500" />,
  PENDING: <Clock size={14} className="text-gray-400" />,
};

const SOURCE_LABELS = {
  SAP_FLAT_FILE: "SAP Flat File",
  UTILITY_CSV: "Utility Portal CSV",
  TRAVEL_CSV: "Travel Platform CSV",
};

function JobRow({ job, canLock }) {
  const [expanded, setExpanded] = useState(false);
  const qc = useQueryClient();

  const lockMut = useMutation({
    mutationFn: () => api.post("/records/lock/", { job_id: job.id }),
    onSuccess: () => qc.invalidateQueries(["records", "jobs", "summary"]),
  });

  const successRate = job.row_count_total > 0
    ? Math.round((job.row_count_parsed / job.row_count_total) * 100)
    : 0;

  return (
    <>
      <tr className="border-b border-gray-100 hover:bg-gray-50">
        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
          {new Date(job.uploaded_at).toLocaleString()}
        </td>
        <td className="px-4 py-3 text-sm font-medium text-gray-800">
          {SOURCE_LABELS[job.source_type] || job.source_type}
        </td>
        <td className="px-4 py-3 text-xs text-gray-500 max-w-[180px] truncate" title={job.original_filename}>
          {job.original_filename}
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1.5 text-xs">
            {STATUS_ICON[job.status]}
            {job.status}
          </div>
        </td>
        <td className="px-4 py-3 text-xs text-center">
          <span className="text-green-700 font-semibold">{job.row_count_parsed}</span>
          <span className="text-gray-400"> / {job.row_count_total}</span>
        </td>
        <td className="px-4 py-3 text-xs text-center">
          {job.row_count_failed > 0
            ? <span className="text-red-600 font-semibold">{job.row_count_failed}</span>
            : <span className="text-gray-300">0</span>}
        </td>
        <td className="px-4 py-3">
          <div className="w-20 bg-gray-200 rounded-full h-1.5">
            <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${successRate}%` }} />
          </div>
        </td>
        <td className="px-4 py-3 flex items-center gap-2">
          {canLock && job.status === "COMPLETE" && (
            <button
              onClick={() => lockMut.mutate()}
              disabled={lockMut.isPending}
              className="flex items-center gap-1 px-2.5 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              <Lock size={11} /> Lock for Audit
            </button>
          )}
          {lockMut.data && (
            <span className="text-xs text-green-600">
              ✓ {lockMut.data.data.locked} locked
              {lockMut.data.data.still_pending > 0 && ` | ${lockMut.data.data.still_pending} still pending`}
              {lockMut.data.data.still_flagged > 0 && ` | ${lockMut.data.data.still_flagged} still flagged`}
            </span>
          )}
          {(job.parse_errors?.length > 0 || job.error_detail) && (
            <button onClick={() => setExpanded(!expanded)} className="text-gray-400 hover:text-gray-700">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          )}
        </td>
      </tr>

      {expanded && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={8} className="px-6 py-4">
            {job.error_detail && (
              <div className="mb-3">
                <p className="text-xs font-semibold text-red-700 mb-1">Job-level error:</p>
                <pre className="text-xs bg-white border border-red-100 rounded p-2 overflow-auto max-h-32 text-red-700">
                  {job.error_detail}
                </pre>
              </div>
            )}
            {job.parse_errors?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-700 mb-2">
                  Parse errors ({job.parse_errors.length} shown):
                </p>
                <div className="space-y-1.5 max-h-48 overflow-auto">
                  {job.parse_errors.map((e, i) => (
                    <div key={i} className="flex gap-2 bg-white border border-gray-100 rounded p-2 text-xs">
                      <span className="font-mono text-gray-400 flex-none w-14">{e.row_ref}</span>
                      <span className="text-red-600">{e.error_message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {job.metadata && Object.keys(job.metadata).length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold text-gray-700 mb-1">Parser metadata:</p>
                <pre className="text-xs bg-white border border-gray-100 rounded p-2 text-gray-500 max-h-24 overflow-auto">
                  {JSON.stringify(job.metadata, null, 2)}
                </pre>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function JobsPage() {
  const { user } = useAuth();
  const { data: jobs, isLoading } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get("/jobs/").then((r) => r.data),
    refetchInterval: 5000,
  });

  return (
    <div className="p-4 md:p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Ingestion Jobs</h1>
        <p className="text-sm text-gray-500 mt-1">History of all data uploads and their parse results</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Uploaded</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Source Type</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">File</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Status</th>
              <th className="px-4 py-3 text-center text-xs font-semibold text-gray-600">Parsed / Total</th>
              <th className="px-4 py-3 text-center text-xs font-semibold text-gray-600">Errors</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Success</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
            ) : !jobs?.length ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No jobs yet. Upload some data to get started.</td></tr>
            ) : jobs.map((job) => (
              <JobRow key={job.id} job={job} canLock={user?.role === "ADMIN"} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-400 mt-3">
        Page auto-refreshes every 5 seconds. Lock for Audit is available to Admins only — it freezes all Approved rows from a job.
      </p>
    </div>
  );
}
