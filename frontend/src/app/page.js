"use client";

import { useState, useEffect, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import SearchPanel from "@/components/SearchPanel";
import PostsTable from "@/components/PostsTable";
import EmailComposer from "@/components/EmailComposer";
import EmailHistory from "@/components/EmailHistory";
import ResumeUpload from "@/components/ResumeUpload";
import HealthPanel from "@/components/HealthPanel";
import ContactsTable from "@/components/ContactsTable";
import Toast from "@/components/Toast";
import * as api from "@/lib/api";
import styles from "./page.module.css";

export default function Dashboard() {
  // ── State ──────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState("dashboard");
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [emailHistory, setEmailHistory] = useState([]);
  const [scrapeJobs, setScrapeJobs] = useState([]);
  const [selectedPosts, setSelectedPosts] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [activeScrapeJobId, setActiveScrapeJobId] = useState(null);
  const [toasts, setToasts] = useState([]);

  // Email composer
  const [showEmailComposer, setShowEmailComposer] = useState(false);
  const [emailTargetPostIds, setEmailTargetPostIds] = useState([]);
  const [emailIsBulk, setEmailIsBulk] = useState(false);
  // In-flight background bulk send, polled for progress.
  const [bulkJob, setBulkJob] = useState(null);

  // ── Toast helpers ──────────────────────────────────────────
  const addToast = useCallback((message, type = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // ── Data fetching ──────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    try {
      const data = await api.getDashboardStats();
      setStats(data);
    } catch {
      // API not running - use default stats
      setStats({
        total_posts_scraped: 0,
        total_emails_found: 0,
        total_emails_sent: 0,
        total_emails_failed: 0,
        recent_scrape_jobs: [],
      });
    }
  }, []);

  const fetchPosts = useCallback(async () => {
    try {
      const data = await api.getPosts({ limit: 100 });
      setPosts(data);
    } catch {
      setPosts([]);
    }
  }, []);

  const fetchEmailHistory = useCallback(async () => {
    try {
      const data = await api.getEmailHistory({ limit: 100 });
      setEmailHistory(data);
    } catch {
      setEmailHistory([]);
    }
  }, []);

  const fetchScrapeJobs = useCallback(async () => {
    try {
      const data = await api.getScrapeJobs();
      setScrapeJobs(data);
    } catch {
      setScrapeJobs([]);
    }
  }, []);

  // ── Initial load ───────────────────────────────────────────
  useEffect(() => {
    fetchStats();
    fetchPosts();
    fetchEmailHistory();
    fetchScrapeJobs();
  }, [fetchStats, fetchPosts, fetchEmailHistory, fetchScrapeJobs]);

  // ── Poll active scrape job ─────────────────────────────────
  useEffect(() => {
    if (!activeScrapeJobId) return;

    const interval = setInterval(async () => {
      try {
        const job = await api.getScrapeJob(activeScrapeJobId);
        if (job.status === "completed") {
          setIsScraping(false);
          setActiveScrapeJobId(null);
          addToast(
            `Scraping complete: ${job.total_posts} posts, ` +
            `${job.total_emails_found} new email${job.total_emails_found === 1 ? "" : "s"}.`,
            job.total_emails_found > 0 ? "success" : "warning"
          );
          fetchPosts();
          fetchStats();
          fetchScrapeJobs();
        } else if (job.status === "failed") {
          setIsScraping(false);
          setActiveScrapeJobId(null);
          addToast(`Scraping failed: ${job.error_message || "Unknown error"}`, "error");
          fetchScrapeJobs();
        }
      } catch {
        // API error, keep polling
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [activeScrapeJobId, addToast, fetchPosts, fetchStats, fetchScrapeJobs]);

  // ── Poll active bulk email job ─────────────────────────────
  useEffect(() => {
    if (!bulkJob || bulkJob.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const job = await api.getEmailJob(bulkJob.id);
        setBulkJob(job);

        if (job.status === "completed") {
          const parts = [`${job.sent} sent`];
          if (job.skipped) parts.push(`${job.skipped} skipped`);
          if (job.failed) parts.push(`${job.failed} failed`);
          addToast(`Bulk send complete: ${parts.join(", ")}.`,
            job.failed > 0 ? "warning" : "success");
          fetchEmailHistory();
          fetchStats();
        } else if (job.status === "failed") {
          addToast(`Bulk send failed: ${job.error_message || "Unknown error"}`, "error");
          fetchEmailHistory();
        }
      } catch {
        // transient API error — keep polling
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [bulkJob, addToast, fetchEmailHistory, fetchStats]);

  // ── Handlers ───────────────────────────────────────────────
  const handleStartScrape = async (query, maxPosts, filters = {}) => {
    setIsScraping(true);
    try {
      const job = await api.startScrape(query, maxPosts, filters);
      setActiveScrapeJobId(job.id);
      addToast(
        `Scraping "${query}" — running many search phrasings until at least ` +
        `10 new emails are found. This takes a few minutes.`,
        "info"
      );
      setActiveTab("scrape");
    } catch (err) {
      setIsScraping(false);
      addToast(`Failed to start scraping: ${err.message}`, "error");
    }
  };

  const handleOpenEmailComposer = (postIds, isBulk) => {
    setEmailTargetPostIds(postIds);
    setEmailIsBulk(isBulk);
    setShowEmailComposer(true);
  };

  const handleSendEmail = async ({ postIds, subject, body, attachResume }) => {
    try {
      if (postIds.length === 1 && !emailIsBulk) {
        const post = posts.find((p) => p.id === postIds[0]);
        if (post && post.extracted_emails) {
          const firstEmail = post.extracted_emails.split(",")[0].trim();
          try {
            await api.sendEmail({
              postId: post.id,
              recipientEmail: firstEmail,
              subject,
              body,
              attachResume,
            });
            addToast(`Email sent to ${firstEmail}!`, "success");
          } catch (err) {
            // 409 from the cooldown guard — offer to override rather than
            // reporting it as a failure, since nothing was actually sent.
            if (!/already emailed/i.test(err.message)) throw err;
            if (!window.confirm(`${err.message}\n\nSend anyway?`)) {
              addToast(`Skipped ${firstEmail} — already contacted.`, "warning");
              setShowEmailComposer(false);
              return;
            }
            await api.sendEmail({
              postId: post.id,
              recipientEmail: firstEmail,
              subject,
              body,
              attachResume,
              force: true,
            });
            addToast(`Email re-sent to ${firstEmail}.`, "success");
          }
        }
      } else {
        // Sends are paced by the backend rate limiter, so this returns a job
        // straight away and we poll it to completion.
        const job = await api.sendBulkEmails({ postIds, subject, body, attachResume });
        addToast(
          `Queued ${job.total_recipients} email(s) — sending in the background.`,
          "info"
        );
        setBulkJob(job);
      }
      setShowEmailComposer(false);
      setSelectedPosts([]);
      fetchEmailHistory();
      fetchStats();
    } catch (err) {
      addToast(`Email sending failed: ${err.message}`, "error");
    }
  };

  const handleResendEmail = async (emailId) => {
    try {
      await api.resendEmail(emailId);
      addToast("Email resent successfully!", "success");
      fetchEmailHistory();
    } catch (err) {
      addToast(`Resend failed: ${err.message}`, "error");
    }
  };

  // ── Render helpers ─────────────────────────────────────────
  const statCards = [
    {
      icon: "📄",
      value: stats?.total_posts_scraped ?? "—",
      label: "Posts Scraped",
      color: "var(--accent-glow)",
    },
    {
      icon: "📧",
      value: stats?.total_emails_found ?? "—",
      label: "Emails Found",
      color: "var(--info-bg)",
    },
    {
      icon: "✅",
      value: stats?.total_emails_sent ?? "—",
      label: "Emails Sent",
      color: "var(--success-bg)",
    },
    {
      icon: "❌",
      value: stats?.total_emails_failed ?? "—",
      label: "Emails Failed",
      color: "var(--error-bg)",
    },
  ];

  const renderDashboard = () => (
    <>
      {/* Stats */}
      <div className="stats-grid">
        {statCards.map((stat, i) => (
          <div key={i} className="glass-card glass-card--accent stat-card">
            <div className="stat-icon" style={{ background: stat.color }}>
              {stat.icon}
            </div>
            <div className="stat-value">{stat.value}</div>
            <div className="stat-label">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Search */}
      <SearchPanel onStartScrape={handleStartScrape} isLoading={isScraping} />

      {/* Recent Posts */}
      <PostsTable
        posts={posts.slice(0, 20)}
        onSendEmail={handleOpenEmailComposer}
        onSelectPosts={setSelectedPosts}
        selectedPosts={selectedPosts}
      />
    </>
  );

  const renderScrape = () => (
    <>
      <SearchPanel onStartScrape={handleStartScrape} isLoading={isScraping} />

      {/* Scraping status */}
      {isScraping && (
        <div className={`glass-card ${styles.scrapingStatus}`}>
          <div className="spinner spinner-lg" />
          <div>
            <h3>Scraping in progress...</h3>
            <p>The browser is searching LinkedIn and extracting post data. This may take a few minutes.</p>
          </div>
        </div>
      )}

      {/* Scrape Jobs History */}
      {scrapeJobs.length > 0 && (
        <div className="glass-card" style={{ marginTop: "var(--space-lg)" }}>
          <h3 style={{ marginBottom: "var(--space-md)" }}>📋 Scrape History</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Status</th>
                <th>Posts</th>
                <th>Emails</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {scrapeJobs.map((job) => (
                <tr key={job.id}>
                  <td style={{ fontWeight: 600 }}>{job.search_query}</td>
                  <td>
                    <span className={`badge badge-${job.status === "completed" ? "success" : job.status === "failed" ? "error" : "warning"}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>{job.total_posts}</td>
                  <td>{job.total_emails_found}</td>
                  <td style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
                    {new Date(job.started_at).toLocaleString("en-IN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );

  const renderPosts = () => (
    <PostsTable
      posts={posts}
      onSendEmail={handleOpenEmailComposer}
      onSelectPosts={setSelectedPosts}
      selectedPosts={selectedPosts}
    />
  );

  const renderEmails = () => (
    <EmailHistory emails={emailHistory} onResend={handleResendEmail} />
  );

  const renderContacts = () => <ContactsTable onNotify={addToast} />;

  const renderSettings = () => (
    <>
      <ResumeUpload onNotify={addToast} />
      <HealthPanel />
    </>
  );

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard": return renderDashboard();
      case "scrape": return renderScrape();
      case "posts": return renderPosts();
      case "emails": return renderEmails();
      case "contacts": return renderContacts();
      case "settings": return renderSettings();
      default: return renderDashboard();
    }
  };

  const tabTitles = {
    dashboard: "Dashboard",
    scrape: "Scrape Posts",
    posts: "Saved Posts",
    emails: "Email History",
    contacts: "Email Contacts",
    settings: "Settings",
  };

  return (
    <div className="app-layout">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      <main className="main-content">
        {/* Page Header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>{tabTitles[activeTab]}</h1>
            <p className={styles.pageSubtitle}>
              {activeTab === "dashboard" && "Overview of your LinkedIn scraping & email activity"}
              {activeTab === "scrape" && "Search and scrape LinkedIn posts for hiring information"}
              {activeTab === "posts" && "Browse all scraped posts with extracted data"}
              {activeTab === "emails" && "Track all sent emails and their delivery status"}
              {activeTab === "contacts" && "Every unique email collected — filter, then export to CSV"}
              {activeTab === "settings" && "Manage the resume attached to your outgoing emails"}
            </p>
          </div>
        </div>

        {/* Bulk send progress — sends are paced, so this can run for minutes */}
        {bulkJob && bulkJob.status === "running" && (
          <div className={styles.bulkProgress}>
            <span className={styles.bulkSpinner} />
            <span>
              Sending emails — {bulkJob.sent + bulkJob.failed + bulkJob.skipped} of{" "}
              {bulkJob.total_recipients} processed ({bulkJob.sent} sent
              {bulkJob.skipped ? `, ${bulkJob.skipped} skipped` : ""}
              {bulkJob.failed ? `, ${bulkJob.failed} failed` : ""})
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => setBulkJob(null)}>
              Hide
            </button>
          </div>
        )}

        {renderContent()}
      </main>

      {/* Email Composer Modal */}
      {showEmailComposer && (
        <EmailComposer
          posts={posts}
          postIds={emailTargetPostIds}
          isBulk={emailIsBulk}
          onSend={handleSendEmail}
          onClose={() => setShowEmailComposer(false)}
        />
      )}

      {/* Toast Notifications */}
      <Toast toasts={toasts} onRemove={removeToast} />
    </div>
  );
}
