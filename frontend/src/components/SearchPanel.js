"use client";

import { useState } from "react";
import styles from "./SearchPanel.module.css";

export default function SearchPanel({ onStartScrape, isLoading }) {
  const [query, setQuery] = useState("java spring boot backend developer");
  const [maxPosts, setMaxPosts] = useState(200);
  const [expMin, setExpMin] = useState(2);
  const [expMax, setExpMax] = useState(5);
  const [datePosted, setDatePosted] = useState("past-24h");
  const [sortByLatest, setSortByLatest] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    onStartScrape(query.trim(), maxPosts, {
      datePosted: datePosted || null,
      sortByLatest,
      experienceMin: expMin === "" ? null : Number(expMin),
      experienceMax: expMax === "" ? null : Number(expMax),
      // <input type="date"> gives YYYY-MM-DD; make the "to" bound inclusive.
      dateFrom: dateFrom ? `${dateFrom}T00:00:00` : null,
      dateTo: dateTo ? `${dateTo}T23:59:59` : null,
    });
  };

  const quickSearches = [
    "java spring boot backend developer",
    "spring boot microservices developer",
    "java backend developer",
    "backend developer java hiring",
    "senior java developer",
  ];

  return (
    <div className={`glass-card glass-card--accent ${styles.panel}`}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>🔍 Scrape LinkedIn Posts</h2>
          <p className={styles.subtitle}>
            Search for hiring posts and extract emails, roles, experience & location
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className={styles.form}>
        <div className={styles.searchRow}>
          <div className={styles.inputWrapper}>
            <svg className={styles.searchIcon} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Job title, e.g. java developer hiring"
              className={styles.searchInput}
              disabled={isLoading}
            />
          </div>

          <div className={styles.maxPostsWrapper}>
            <label className={styles.maxPostsLabel}>Target posts</label>
            <select
              value={maxPosts}
              onChange={(e) => setMaxPosts(Number(e.target.value))}
              className={styles.maxPostsSelect}
              disabled={isLoading}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={300}>300</option>
              <option value={500}>500</option>
            </select>
          </div>

          <button
            type="submit"
            className={`btn btn-primary ${styles.searchBtn}`}
            disabled={isLoading || !query.trim()}
          >
            {isLoading ? (
              <>
                <span className="spinner" />
                Scraping...
              </>
            ) : (
              <>
                <span>🚀</span>
                Start Scraping
              </>
            )}
          </button>
        </div>

        {/* Filters */}
        <div className={styles.filterRow}>
          <div className={styles.field}>
            <label className={styles.fieldLabel}>Experience (years)</label>
            <div className={styles.rangeRow}>
              <select
                value={expMin}
                onChange={(e) => setExpMin(e.target.value)}
                className={styles.fieldSelect}
                disabled={isLoading}
                aria-label="Minimum years"
              >
                <option value="">Any</option>
                {[0, 1, 2, 3, 4, 5, 6, 7, 8, 10].map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
              <span className={styles.rangeDash}>to</span>
              <select
                value={expMax}
                onChange={(e) => setExpMax(e.target.value)}
                className={styles.fieldSelect}
                disabled={isLoading}
                aria-label="Maximum years"
              >
                <option value="">Any</option>
                {[1, 2, 3, 4, 5, 6, 7, 8, 10, 15].map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel}>Posted within</label>
            <select
              value={datePosted}
              onChange={(e) => setDatePosted(e.target.value)}
              className={styles.fieldSelect}
              disabled={isLoading}
            >
              <option value="">Any time</option>
              <option value="past-24h">Past 24 hours</option>
              <option value="past-week">Past week</option>
              <option value="past-month">Past month</option>
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel}>Sort</label>
            <select
              value={sortByLatest ? "latest" : "relevance"}
              onChange={(e) => setSortByLatest(e.target.value === "latest")}
              className={styles.fieldSelect}
              disabled={isLoading}
            >
              <option value="latest">Latest first</option>
              <option value="relevance">Most relevant</option>
            </select>
          </div>

          <button
            type="button"
            className={styles.advancedToggle}
            onClick={() => setShowAdvanced(!showAdvanced)}
            disabled={isLoading}
          >
            {showAdvanced ? "− Exact dates" : "+ Exact dates"}
          </button>
        </div>

        {showAdvanced && (
          <div className={styles.filterRow}>
            <div className={styles.field}>
              <label className={styles.fieldLabel}>From date</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className={styles.fieldSelect}
                disabled={isLoading}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.fieldLabel}>To date</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className={styles.fieldSelect}
                disabled={isLoading}
              />
            </div>
            <p className={styles.advancedNote}>
              LinkedIn only filters by relative windows, so exact dates are applied
              afterwards using the age shown on each post (“5h”, “4d”) — accurate to
              that precision. Posts with no visible date are excluded.
            </p>
          </div>
        )}
      </form>

      {maxPosts >= 100 && (
        <p className={styles.scaleNote}>
          LinkedIn returns ~12 results per search, so {maxPosts} posts are gathered by
          expanding your title into related phrasings (“spring boot developer”, “java
          backend developer”, …) crossed with intent phrases (“send resume”, “urgent
          hiring”), then merging the results. Expect roughly{" "}
          {Math.ceil(maxPosts / 18)} minutes; duplicates are dropped automatically.
        </p>
      )}

      {/* Quick searches */}
      <div className={styles.quickSearches}>
        <span className={styles.quickLabel}>Quick:</span>
        {quickSearches.map((qs) => (
          <button
            key={qs}
            className={styles.quickChip}
            onClick={() => setQuery(qs)}
            disabled={isLoading}
          >
            {qs}
          </button>
        ))}
      </div>
    </div>
  );
}
