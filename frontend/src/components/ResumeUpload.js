"use client";

import { useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import styles from "./ResumeUpload.module.css";

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function ResumeUpload({ onNotify }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  // State is set from the promise callbacks rather than by awaiting inside the
  // effect body — react-hooks/set-state-in-effect rejects the latter.
  useEffect(() => {
    let cancelled = false;
    api
      .getResumeInfo()
      .then((data) => {
        if (cancelled) return;
        setInfo(data);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(`Could not load resume info: ${err.message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleFile = async (file) => {
    if (!file) return;
    setError(null);

    // Check locally first so obvious mistakes don't need a round trip. The
    // backend re-validates (including the real PDF header) regardless.
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    const maxMb = info?.max_size_mb ?? 10;
    if (file.size > maxMb * 1024 * 1024) {
      setError(`That file is ${formatBytes(file.size)} — the limit is ${maxMb} MB.`);
      return;
    }

    setBusy(true);
    try {
      const updated = await api.uploadResume(file);
      setInfo(updated);
      onNotify?.(`Resume uploaded: ${updated.filename}`, "success");
    } catch (err) {
      setError(err.message);
      onNotify?.(`Upload failed: ${err.message}`, "error");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Remove the stored resume? Emails will be sent without an attachment.")) {
      return;
    }
    setBusy(true);
    try {
      setInfo(await api.deleteResume());
      onNotify?.("Resume removed.", "info");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="glass-card">
      <div className={styles.header}>
        <h3 className={styles.title}>📎 Resume</h3>
        <p className={styles.subtitle}>
          Attached to outgoing emails when “Attach resume” is enabled. PDF only,
          up to {info?.max_size_mb ?? 10} MB.
        </p>
      </div>

      {loading ? (
        <div className={styles.placeholder}>Loading…</div>
      ) : (
        <>
          {info?.exists ? (
            <div className={styles.current}>
              <div className={styles.fileIcon}>PDF</div>
              <div className={styles.fileMeta}>
                <div className={styles.fileName}>{info.filename || "resume.pdf"}</div>
                <div className={styles.fileDetail}>
                  {formatBytes(info.size_bytes)}
                  {info.uploaded_at && ` · uploaded ${new Date(info.uploaded_at + "Z").toLocaleString("en-IN")}`}
                </div>
              </div>
              <div className={styles.fileActions}>
                <a
                  className="btn btn-secondary btn-sm"
                  href={api.resumeDownloadUrl()}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View
                </a>
                <button className="btn btn-danger btn-sm" onClick={handleDelete} disabled={busy}>
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <div className={styles.warning}>
              ⚠️ No resume uploaded — emails sent with “Attach resume” on will go out
              with no attachment.
            </div>
          )}

          <div
            className={`${styles.dropzone} ${dragging ? styles.dragging : ""} ${busy ? styles.busy : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => !busy && fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className={styles.hiddenInput}
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
            <div className={styles.dropIcon}>{busy ? "⏳" : "⬆️"}</div>
            <div className={styles.dropText}>
              {busy
                ? "Uploading…"
                : info?.exists
                  ? "Drop a PDF here or click to replace"
                  : "Drop your resume here or click to browse"}
            </div>
          </div>

          {error && <div className={styles.error}>{error}</div>}
        </>
      )}
    </div>
  );
}
