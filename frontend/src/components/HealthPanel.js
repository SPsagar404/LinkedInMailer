"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import styles from "./HealthPanel.module.css";

const ICONS = { ok: "✅", warning: "⚠️", error: "❌" };

export default function HealthPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [deepRunning, setDeepRunning] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getHealthStatus(false)
      .then((res) => !cancelled && setData(res))
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const runDeepCheck = () => {
    setDeepRunning(true);
    setError(null);
    api
      .getHealthStatus(true)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setDeepRunning(false));
  };

  return (
    <div className="glass-card" style={{ marginTop: "var(--space-lg)" }}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>🩺 System Health</h3>
          <p className={styles.subtitle}>
            Dependencies that fail quietly — a missing resume, an expired LinkedIn
            session, absent NLP models.
          </p>
        </div>
        <button
          className="btn btn-secondary btn-sm"
          onClick={runDeepCheck}
          disabled={deepRunning || loading}
        >
          {deepRunning ? "Checking…" : "Verify Gmail login"}
        </button>
      </div>

      {loading && <div className={styles.placeholder}>Running checks…</div>}
      {error && <div className={styles.error}>Could not load health status: {error}</div>}

      {data && (
        <ul className={styles.list}>
          {data.checks.map((c) => (
            <li key={c.name} className={`${styles.item} ${styles[c.status]}`}>
              <span className={styles.icon}>{ICONS[c.status] || "•"}</span>
              <div className={styles.body}>
                <div className={styles.name}>{c.name}</div>
                <div className={styles.detail}>{c.detail}</div>
                {c.status !== "ok" && c.hint && (
                  <div className={styles.hint}>→ {c.hint}</div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
