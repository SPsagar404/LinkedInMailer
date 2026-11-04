"use client";

import { useState } from "react";
import styles from "./PostsTable.module.css";

export default function PostsTable({ posts, onSendEmail, onSelectPosts, selectedPosts = [] }) {
  const [expandedId, setExpandedId] = useState(null);

  const toggleSelect = (postId) => {
    const updated = selectedPosts.includes(postId)
      ? selectedPosts.filter((id) => id !== postId)
      : [...selectedPosts, postId];
    onSelectPosts(updated);
  };

  const toggleSelectAll = () => {
    if (selectedPosts.length === posts.length) {
      onSelectPosts([]);
    } else {
      onSelectPosts(posts.map((p) => p.id));
    }
  };

  if (!posts || posts.length === 0) {
    return (
      <div className="glass-card">
        <div className="empty-state">
          <div className="empty-icon">📄</div>
          <h3>No posts yet</h3>
          <p>Start a scrape to find LinkedIn posts with hiring information and email contacts.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`glass-card ${styles.container}`}>
      <div className={styles.header}>
        <h2 className={styles.title}>📄 Scraped Posts ({posts.length})</h2>
        <div className={styles.headerActions}>
          {posts.some((p) => p.extracted_emails) && (
            <button
              className="btn btn-sm btn-secondary"
              onClick={toggleSelectAll}
            >
              {selectedPosts.length === posts.length ? "Deselect All" : "Select All"}
            </button>
          )}
          {selectedPosts.length > 0 && (
            <button
              className="btn btn-sm btn-primary"
              onClick={() => onSendEmail(selectedPosts, true)}
            >
              📧 Email Selected ({selectedPosts.length})
            </button>
          )}
        </div>
      </div>

      <div className={styles.tableWrapper}>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: "40px" }}></th>
              <th>Author</th>
              <th>Post Preview</th>
              <th>Emails</th>
              <th>Role</th>
              <th>Experience</th>
              <th>Location</th>
              <th style={{ width: "100px" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {posts.map((post) => (
              <tr key={post.id} className={expandedId === post.id ? styles.expanded : ""}>
                <td>
                  {post.extracted_emails && (
                    <div
                      className={`custom-checkbox ${selectedPosts.includes(post.id) ? "checked" : ""}`}
                      onClick={() => toggleSelect(post.id)}
                    />
                  )}
                </td>
                <td>
                  <div className={styles.author}>
                    <div className={styles.authorAvatar}>
                      {(post.author_name || "?")[0].toUpperCase()}
                    </div>
                    <div>
                      <div className={styles.authorName}>{post.author_name || "Unknown"}</div>
                      {post.author_headline && (
                        <div className={styles.authorHeadline}>
                          {post.author_headline.length > 40
                            ? post.author_headline.substring(0, 40) + "..."
                            : post.author_headline}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td>
                  <div
                    className={styles.contentPreview}
                    onClick={() => setExpandedId(expandedId === post.id ? null : post.id)}
                    title="Click to expand"
                  >
                    {expandedId === post.id
                      ? post.content
                      : post.content.length > 120
                        ? post.content.substring(0, 120) + "..."
                        : post.content}
                  </div>
                </td>
                <td>
                  {post.extracted_emails ? (
                    <div className={styles.emailsList}>
                      {post.extracted_emails.split(",").map((email, i) => (
                        <span key={i} className="badge badge-accent">
                          {email.trim()}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className={styles.noData}>—</span>
                  )}
                </td>
                <td>
                  {post.extracted_roles ? (
                    <div className={styles.tagsList}>
                      {post.extracted_roles.split(",").slice(0, 2).map((role, i) => (
                        <span key={i} className="badge badge-info">
                          {role.trim()}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className={styles.noData}>—</span>
                  )}
                </td>
                <td>
                  {post.extracted_experience ? (
                    <span className="badge badge-warning">{post.extracted_experience}</span>
                  ) : (
                    <span className={styles.noData}>—</span>
                  )}
                </td>
                <td>
                  {post.extracted_location ? (
                    <div className={styles.tagsList}>
                      {post.extracted_location.split(",").slice(0, 2).map((loc, i) => (
                        <span key={i} className="badge badge-success">
                          {loc.trim()}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className={styles.noData}>—</span>
                  )}
                </td>
                <td>
                  <div className={styles.actions}>
                    {post.extracted_emails && (
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => onSendEmail([post.id], false)}
                        title="Send Email"
                      >
                        📧
                      </button>
                    )}
                    {post.post_url && (
                      <a
                        href={post.post_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-sm btn-ghost"
                        title="View on LinkedIn"
                      >
                        🔗
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
