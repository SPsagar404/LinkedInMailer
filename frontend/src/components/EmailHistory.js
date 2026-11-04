"use client";

import styles from "./EmailHistory.module.css";

export default function EmailHistory({ emails, onResend }) {
  if (!emails || emails.length === 0) {
    return (
      <div className="glass-card">
        <div className="empty-state">
          <div className="empty-icon">📧</div>
          <h3>No emails sent yet</h3>
          <p>Send your first email from the scraped posts to see the history here.</p>
        </div>
      </div>
    );
  }

  const getStatusBadge = (status) => {
    switch (status) {
      case "sent":
        return <span className="badge badge-success">✓ Sent</span>;
      case "failed":
        return <span className="badge badge-error">✕ Failed</span>;
      case "pending":
        return <span className="badge badge-warning">⏳ Pending</span>;
      default:
        return <span className="badge badge-info">{status}</span>;
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className={`glass-card ${styles.container}`}>
      <div className={styles.header}>
        <h2 className={styles.title}>📧 Email History ({emails.length})</h2>
      </div>

      <div className={styles.tableWrapper}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Recipient</th>
              <th>Subject</th>
              <th>Status</th>
              <th>Resume</th>
              <th>Sent At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {emails.map((email) => (
              <tr key={email.id}>
                <td>
                  <span className={styles.emailAddr}>{email.recipient_email}</span>
                </td>
                <td>
                  <span className={styles.subject}>
                    {email.subject.length > 50
                      ? email.subject.substring(0, 50) + "..."
                      : email.subject}
                  </span>
                </td>
                <td>{getStatusBadge(email.status)}</td>
                <td>
                  {email.has_resume ? (
                    <span className="badge badge-info">📎 Yes</span>
                  ) : (
                    <span className={styles.noData}>No</span>
                  )}
                </td>
                <td>
                  <span className={styles.date}>{formatDate(email.sent_at)}</span>
                </td>
                <td>
                  {email.status === "failed" && (
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => onResend(email.id)}
                    >
                      🔄 Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
