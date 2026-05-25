import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import { Upload, CheckCircle2, AlertTriangle, FileText } from "lucide-react";
import clsx from "clsx";

const SOURCE_TYPES = [
  {
    value: "SAP_FLAT_FILE",
    label: "SAP Flat File",
    scope: "Scope 1 — Fuel & Procurement",
    desc: "CSV/XLSX export from SAP SE16 or ALV Grid report (table MSEG, EKPO, or FAGLL03). German or English headers both supported.",
    accept: ".csv,.xlsx,.xls",
    example: "Posting Date, Plant, G/L Account, Quantity, ME, Vendor…",
  },
  {
    value: "UTILITY_CSV",
    label: "Utility Portal CSV",
    scope: "Scope 2 — Electricity",
    desc: "CSV download from your utility's online portal (PG&E, Con Edison, ComEd, National Grid, etc). Use the 'Download Usage Data' or 'Export' option.",
    accept: ".csv",
    example: "Account Number, Meter ID, Billing Start Date, Billing End Date, Usage (kWh)…",
  },
  {
    value: "TRAVEL_CSV",
    label: "Travel Platform CSV",
    scope: "Scope 3 — Business Travel",
    desc: "Detailed trip export from Concur (Travel Itinerary Detail Report) or Navan. Handles flights, hotels, and ground transport.",
    accept: ".csv",
    example: "Employee Name, Segment Type, Origin, Destination, Departure Date, Class of Service…",
  },
];

function UploadResult({ result }) {
  if (!result) return null;
  const { row_count_parsed, row_count_failed, parse_errors, status } = result;

  return (
    <div className={clsx(
      "mt-5 rounded-xl border p-5",
      status === "COMPLETE" ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"
    )}>
      <div className="flex items-center gap-2 mb-3">
        {status === "COMPLETE"
          ? <CheckCircle2 size={18} className="text-green-600" />
          : <AlertTriangle size={18} className="text-red-600" />}
        <span className="font-semibold text-sm">
          {status === "COMPLETE" ? "Ingestion complete" : "Ingestion failed"}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-4 text-sm mb-3">
        <div className="bg-white rounded-lg p-3 border border-green-100">
          <div className="text-2xl font-bold text-green-700">{row_count_parsed}</div>
          <div className="text-xs text-gray-500">Rows parsed successfully</div>
        </div>
        <div className="bg-white rounded-lg p-3 border border-red-100">
          <div className="text-2xl font-bold text-red-600">{row_count_failed}</div>
          <div className="text-xs text-gray-500">Rows failed to parse</div>
        </div>
      </div>

      {parse_errors?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-700 mb-2">Parse errors (first {parse_errors.length}):</p>
          <div className="space-y-1.5 max-h-48 overflow-auto">
            {parse_errors.map((e, i) => (
              <div key={i} className="bg-white border border-red-100 rounded p-2 text-xs">
                <span className="font-mono text-gray-500 mr-2">{e.row_ref}</span>
                <span className="text-red-700">{e.error_message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-gray-500 mt-3">
        Go to <strong>Review Records</strong> to inspect and approve the ingested rows.
      </p>
    </div>
  );
}

export default function UploadPage() {
  const qc = useQueryClient();
  const [sourceType, setSourceType] = useState("SAP_FLAT_FILE");
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState(null);
  const fileRef = useRef();

  const selected = SOURCE_TYPES.find((s) => s.value === sourceType);

  const uploadMut = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("source_type", sourceType);
      fd.append("file", file);
      return api.post("/jobs/upload/", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: (res) => {
      setResult(res.data);
      setFile(null);
      qc.invalidateQueries(["records"]);
      qc.invalidateQueries(["jobs"]);
      qc.invalidateQueries(["summary"]);
    },
    onError: (err) => {
      setResult({ status: "FAILED", row_count_parsed: 0, row_count_failed: 0, parse_errors: [{ row_ref: "upload", error_message: err.response?.data?.error || err.message }] });
    },
  });

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) { setFile(f); setResult(null); }
  };

  return (
    <div className="p-4 md:p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Upload Data</h1>
        <p className="text-sm text-gray-500 mt-1">Ingest emissions data from SAP, utility portals, or travel platforms.</p>
      </div>

      {/* Source type selector */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        {SOURCE_TYPES.map((s) => (
          <button
            key={s.value}
            onClick={() => { setSourceType(s.value); setFile(null); setResult(null); }}
            className={clsx(
              "text-left p-4 rounded-xl border-2 transition-all",
              sourceType === s.value
                ? "border-brand-500 bg-brand-50"
                : "border-gray-200 bg-white hover:border-gray-300"
            )}
          >
            <div className="text-sm font-semibold text-gray-900">{s.label}</div>
            <div className="text-xs text-gray-500 mt-0.5">{s.scope}</div>
          </button>
        ))}
      </div>

      {/* Source info */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 mb-6 text-sm text-gray-600">
        <p className="font-medium text-gray-800 mb-1">{selected.label}</p>
        <p className="mb-2">{selected.desc}</p>
        <p className="text-xs font-mono text-gray-500 bg-white border border-gray-100 rounded px-2 py-1">
          Expected columns: {selected.example}
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={clsx(
          "border-2 border-dashed rounded-xl p-6 md:p-10 text-center cursor-pointer transition-all",
          dragOver ? "border-brand-400 bg-brand-50" : "border-gray-300 bg-white hover:border-brand-400 hover:bg-gray-50"
        )}
      >
        <input
          ref={fileRef}
          type="file"
          accept={selected.accept}
          className="hidden"
          onChange={(e) => { setFile(e.target.files[0]); setResult(null); }}
        />
        <Upload size={28} className="mx-auto text-gray-400 mb-3" />
        {file ? (
          <div>
            <div className="flex items-center justify-center gap-2 text-brand-700 font-medium">
              <FileText size={16} />
              {file.name}
            </div>
            <p className="text-xs text-gray-400 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
        ) : (
          <>
            <p className="text-sm font-medium text-gray-700">Drop your file here, or click to browse</p>
            <p className="text-xs text-gray-400 mt-1">Accepts {selected.accept}</p>
          </>
        )}
      </div>

      {file && !uploadMut.isPending && (
        <button
          onClick={() => uploadMut.mutate()}
          className="mt-4 w-full bg-brand-600 hover:bg-brand-700 text-white rounded-xl py-3 font-medium text-sm transition-colors"
        >
          Upload and Parse
        </button>
      )}

      {uploadMut.isPending && (
        <div className="mt-4 w-full bg-gray-100 text-gray-500 rounded-xl py-3 text-center text-sm">
          Parsing… this may take a moment for large files
        </div>
      )}

      <UploadResult result={result} />
    </div>
  );
}
