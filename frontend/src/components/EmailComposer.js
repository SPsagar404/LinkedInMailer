"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import styles from "./EmailComposer.module.css";

export default function EmailComposer({ posts, postIds, isBulk, onSend, onClose }) {
  const targetPosts = posts.filter((p) => postIds.includes(p.id));
  const allEmails = targetPosts
    .filter((p) => p.extracted_emails)
    .flatMap((p) => p.extracted_emails.split(",").map((e) => e.trim()));
  const uniqueEmails = [...new Set(allEmails)];

  const [subject, setSubject] = useState(
    "Application for the open position — Interested Candidate"
  );
  const [body, setBody] = useState(
    `<p>Dear Hiring Manager,</p>
<p>I came across your recent LinkedIn post about the open position and I'm very excited about this opportunity. With my relevant experience and skills, I believe I would be a great fit for this role.</p>
<p>I have attached my resume for your consideration. I would love the opportunity to discuss how my background and skills align with your team's needs.</p>
<p>Please feel free to reach out at your convenience. I look forward to hearing from you.</p>
<p>Best regards</p>`
  );
  const [attachResume, setAttachResume] = useState(true);
  const [sending, setSending] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState(null);
  // null while unknown, then the backend's resume info.
  const [resume, setResume] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getResumeInfo()
      .then((info) => !cancelled && setResume(info))
      .catch(() => !cancelled && setResume({ exists: false }));
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDraft = async () => {
    setDrafting(true);
    setDraftError(null);
    try {
      const draft = await api.draftEmail(postIds[0]);
      setSubject(draft.subject);
      setBody(draft.body);
    } catch (err) {
      setDraftError(err.message);
    } finally {
      setDrafting(false);
    }
  };

  const handleSend = async () => {
    setSending(true);
    try {
      await onSend({
        postIds,
        subject,
        body,
        attachResume,
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content">
        <div className="modal-header">
          <h2>📧 {isBulk ? "Send Bulk Emails" : "Send Email"}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        {/* Recipients info */}
        <div className={styles.recipientsBox}>
          <div className={styles.recipientsLabel}>
            To: {uniqueEmails.length} recipient{uniqueEmails.length !== 1 ? "s" : ""}
          </div>
          <div className={styles.recipientsList}>
            {uniqueEmails.map((email, i) => (
              <span key={i} className="badge badge-accent">{email}</span>
            ))}
          </div>
        </div>

        {/* AI draft — single-post only; a bulk blast shares one body, so a
            post-specific draft would be misleading for the other recipients. */}
        {!isBulk && postIds.length === 1 && (
          <div className={styles.aiRow}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleDraft}
              disabled={drafting || sending}
            >
              {drafting ? "Drafting…" : "✨ Draft with AI"}
            </button>
            <span className={styles.aiHint}>
              {draftError || "Writes a subject and body tailored to this post."}
            </span>
          </div>
        )}

        {/* Subject */}
        <div className="form-group">
          <label>Subject</label>
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="input-field"
            placeholder="Email subject..."
          />
        </div>

        {/* Body */}
        <div className="form-group">
          <label>Email Body (HTML)</label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className="textarea-field"
            rows={8}
            placeholder="Type your email body..."
          />
        </div>

        {/* Resume toggle */}
        <div className={styles.toggleRow}>
          <div
            className="toggle-wrapper"
            onClick={() => setAttachResume(!attachResume)}
          >
            <div className={`toggle ${attachResume ? "active" : ""}`} />
            <span>Attach Resume (PDF)</span>
          </div>
          <span className={styles.toggleHint}>
            {resume === null
              ? "Checking resume…"
              : resume.exists
                ? `Will attach ${resume.filename}`
                : "No resume uploaded — Settings › Resume"}
          </span>
        </div>

        {/* The toggle defaults to on, so warn loudly rather than sending a mail
            that promises an attachment and carries none. */}
        {attachResume && resume && !resume.exists && (
          <div className={styles.resumeWarning}>
            ⚠️ No resume is uploaded. This email will be sent{" "}
            <strong>without an attachment</strong>. Upload one under
            Settings › Resume, or turn this toggle off.
          </div>
        )}

        {/* Actions */}
        <div className="form-actions">
          <button className="btn btn-secondary" onClick={onClose} disabled={sending}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSend}
            disabled={sending || uniqueEmails.length === 0}
          >
            {sending ? (
              <>
                <span className="spinner" />
                Sending...
              </>
            ) : (
              <>
                📨 Send {uniqueEmails.length > 1 ? `${uniqueEmails.length} Emails` : "Email"}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
