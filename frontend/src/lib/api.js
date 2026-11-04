/**
 * API client helper for communicating with the FastAPI backend.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const config = {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ── Scraper API ────────────────────────────────────────────────
export async function startScrape(searchQuery, maxPosts = 10, filters = {}) {
  return request("/api/scrape/start", {
    method: "POST",
    body: JSON.stringify({
      search_query: searchQuery,
      max_posts: maxPosts,
      // null/undefined are omitted server-side; only send what was set.
      date_posted: filters.datePosted || null,
      sort_by_latest: filters.sortByLatest !== false,
      experience_min: filters.experienceMin ?? null,
      experience_max: filters.experienceMax ?? null,
      date_from: filters.dateFrom || null,
      date_to: filters.dateTo || null,
    }),
  });
}

export async function getScrapeJobs() {
  return request("/api/scrape/jobs");
}

export async function getScrapeJob(jobId) {
  return request(`/api/scrape/jobs/${jobId}`);
}

// ── Posts API ──────────────────────────────────────────────────
export async function getPosts({ scrapeJobId, hasEmail, search, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (scrapeJobId) params.set("scrape_job_id", scrapeJobId);
  if (hasEmail) params.set("has_email", "true");
  if (search) params.set("search", search);
  params.set("limit", limit);
  params.set("offset", offset);
  return request(`/api/posts/?${params.toString()}`);
}

export async function getPostCount(hasEmail = false) {
  const params = hasEmail ? "?has_email=true" : "";
  return request(`/api/posts/count${params}`);
}

export async function deletePost(postId) {
  return request(`/api/posts/${postId}`, { method: "DELETE" });
}

// ── Email API ──────────────────────────────────────────────────
// `force` re-sends to an address already contacted inside the backend's
// cooldown window; without it the API answers 409 instead of sending.
export async function sendEmail({ postId, recipientEmail, subject, body, attachResume = false, force = false }) {
  return request("/api/emails/send", {
    method: "POST",
    body: JSON.stringify({
      post_id: postId,
      recipient_email: recipientEmail,
      subject: subject,
      body: body,
      attach_resume: attachResume,
      force: force,
    }),
  });
}

export async function sendBulkEmails({ postIds, subject, body, attachResume = false, force = false }) {
  return request("/api/emails/send-bulk", {
    method: "POST",
    body: JSON.stringify({
      post_ids: postIds,
      subject: subject,
      body: body,
      attach_resume: attachResume,
      force: force,
    }),
  });
}

// Asks Gemini for a subject/body tailored to one post. 503 when no key is set.
export async function draftEmail(postId) {
  return request("/api/emails/draft", {
    method: "POST",
    body: JSON.stringify({ post_id: postId }),
  });
}

// ── Contacts (deduped emails) ──────────────────────────────────
function contactParams({ q, uncontactedOnly, dateFrom, dateTo, hasCompany, limit, offset } = {}) {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (uncontactedOnly) p.set("uncontacted_only", "true");
  if (hasCompany) p.set("has_company", "true");
  if (dateFrom) p.set("date_from", `${dateFrom}T00:00:00`);
  if (dateTo) p.set("date_to", `${dateTo}T23:59:59`);
  if (limit != null) p.set("limit", limit);
  if (offset != null) p.set("offset", offset);
  return p.toString();
}

export async function getContacts(filters = {}) {
  return request(`/api/emails/contacts?${contactParams({ limit: 1000, ...filters })}`);
}

export async function getContactsCount() {
  return request("/api/emails/contacts/count");
}

// Returns a URL rather than fetching: the browser must navigate to it so the
// Content-Disposition header triggers a real file download.
export function contactsCsvUrl(filters = {}) {
  return `${API_BASE}/api/emails/contacts/export.csv?${contactParams(filters)}`;
}

// Bulk sends are rate-limited and run in the background — this returns a job to
// poll via getEmailJob(), not a finished result.
export async function getEmailJob(jobId) {
  return request(`/api/emails/jobs/${jobId}`);
}

export async function getEmailJobs() {
  return request("/api/emails/jobs");
}

export async function getHealthStatus(deep = false) {
  return request(`/api/health/status${deep ? "?deep=true" : ""}`);
}

export async function getEmailHistory({ status, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", limit);
  params.set("offset", offset);
  return request(`/api/emails/history?${params.toString()}`);
}

export async function getEmailStats() {
  return request("/api/emails/stats");
}

export async function resendEmail(emailId) {
  return request(`/api/emails/resend/${emailId}`, { method: "POST" });
}

// ── Resume API ─────────────────────────────────────────────────
export async function getResumeInfo() {
  return request("/api/resume");
}

export async function uploadResume(file) {
  // Not routed through request(): that forces Content-Type: application/json,
  // and multipart uploads need the browser to set the type + boundary itself.
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/resume/upload`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function deleteResume() {
  return request("/api/resume", { method: "DELETE" });
}

export function resumeDownloadUrl() {
  return `${API_BASE}/api/resume/download`;
}

// ── Dashboard Stats ────────────────────────────────────────────
export async function getDashboardStats() {
  return request("/api/stats");
}
