"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import styles from "./ContactsTable.module.css";

/** Deduped email contacts: one row per address, with filters and CSV export. */
export default function ContactsTable({ onNotify }) {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [uncontactedOnly, setUncontactedOnly] = useState(false);
  const [hasCompany, setHasCompany] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const filters = { q, uncontactedOnly, hasCompany, dateFrom, dateTo };

  const load = useCallback((f) => {
    setLoading(true);
    api
      .getContacts(f)
      .then(setContacts)
      .catch((e) => onNotify?.(`Could not load contacts: ${e.message}`, "error"))
      .finally(() => setLoading(false));
  }, [onNotify]);

  // Initial load only; later loads are triggered by Apply/Reset.
  useEffect(() => {
    let cancelled = false;
    api
      .getContacts({})
      .then((d) => !cancelled && setContacts(d))
      .catch(() => !cancelled && setContacts([]))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  const reset = () => {
    setQ(""); setUncontactedOnly(false); setHasCompany(false);
    setDateFrom(""); setDateTo("");
    load({});
  };

  return (
    <div className="glass-card">
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>📇 Email Contacts</h3>
          <p className={styles.subtitle}>
            One row per address — duplicates are merged, never listed twice.
          </p>
        </div>
        <a
          className="btn btn-primary btn-sm"
          href={api.contactsCsvUrl(filters)}
          onClick={() => onNotify?.("Exporting filtered contacts to CSV…", "info")}
        >
          ⬇ Export CSV
        </a>
      </div>

      <div className={styles.filters}>
        <input
          className={styles.input}
          placeholder="Search email, name, company or role…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(filters)}
        />
        <label className={styles.dateField}>
          <span>From</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className={styles.dateField}>
          <span>To</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <label className={styles.check}>
          <input type="checkbox" checked={uncontactedOnly}
                 onChange={(e) => setUncontactedOnly(e.target.checked)} />
          Not emailed yet
        </label>
        <label className={styles.check}>
          <input type="checkbox" checked={hasCompany}
                 onChange={(e) => setHasCompany(e.target.checked)} />
          Has company
        </label>
        <button className="btn btn-secondary btn-sm" onClick={() => load(filters)}>Apply</button>
        <button className="btn btn-ghost btn-sm" onClick={reset}>Reset</button>
      </div>

      <div className={styles.count}>
        {loading ? "Loading…" : `${contacts.length} unique email${contacts.length === 1 ? "" : "s"}`}
      </div>

      <div className={styles.tableWrap}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Email</th><th>Name</th><th>Company</th>
              <th>Designation</th><th>Seen</th><th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id}>
                <td className={styles.email}>{c.email}</td>
                <td>{c.author_name || "—"}</td>
                <td>{c.company || "—"}</td>
                <td>{(c.role || "").split(",")[0] || "—"}</td>
                <td>{c.times_seen > 1 ? `${c.times_seen}×` : "1"}</td>
                <td className={styles.dim}>
                  {c.last_seen_at ? new Date(c.last_seen_at).toLocaleDateString("en-IN") : "—"}
                </td>
              </tr>
            ))}
            {!loading && contacts.length === 0 && (
              <tr><td colSpan={6} className={styles.empty}>
                No contacts match these filters.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
