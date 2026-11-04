"use client";

import { useState } from "react";
import styles from "./Sidebar.module.css";

export default function Sidebar({ activeTab, onTabChange }) {
  const [collapsed, setCollapsed] = useState(false);

  const tabs = [
    { id: "dashboard", label: "Dashboard", icon: "📊" },
    { id: "scrape", label: "Scrape Posts", icon: "🔍" },
    { id: "posts", label: "Saved Posts", icon: "📄" },
    { id: "contacts", label: "Email Contacts", icon: "📇" },
    { id: "emails", label: "Email History", icon: "📧" },
    { id: "settings", label: "Settings", icon: "⚙️" },
  ];

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      {/* Logo */}
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="2" width="20" height="20" rx="4" fill="url(#grad)" />
            <path d="M7 10V17M10.5 13.5V17M10.5 10V10.01M14 11V17M17 8V17" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <defs>
              <linearGradient id="grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                <stop stopColor="#0a66c2" />
                <stop offset="1" stopColor="#378fe9" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        {!collapsed && (
          <div className={styles.logoText}>
            <span className={styles.logoTitle}>LinkedIn</span>
            <span className={styles.logoSubtitle}>Mailer</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className={styles.nav}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`${styles.navItem} ${activeTab === tab.id ? styles.active : ""}`}
            onClick={() => onTabChange(tab.id)}
            title={tab.label}
          >
            <span className={styles.navIcon}>{tab.icon}</span>
            {!collapsed && <span className={styles.navLabel}>{tab.label}</span>}
            {activeTab === tab.id && <div className={styles.activeIndicator} />}
          </button>
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        className={styles.collapseBtn}
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? "Expand" : "Collapse"}
      >
        <span style={{ transform: collapsed ? "rotate(180deg)" : "none", display: "inline-block", transition: "transform 0.3s" }}>
          ◀
        </span>
      </button>

      {/* Footer */}
      {!collapsed && (
        <div className={styles.footer}>
          <div className={styles.footerBadge}>
            <span className={styles.statusDot} />
            <span>System Ready</span>
          </div>
        </div>
      )}
    </aside>
  );
}
