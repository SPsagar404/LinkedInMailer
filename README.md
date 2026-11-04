# LinkedIn Post Scraper & Auto-Email Dashboard

A full-stack web app that scrapes LinkedIn posts (hiring/job posts), extracts contact info (emails, experience, role, location), and sends automated emails via Gmail.

## Tech Stack

- **Frontend**: Next.js 14 (App Router) + React + Vanilla CSS
- **Backend**: FastAPI (Python) + SQLAlchemy + SQLite
- **Scraping**: Playwright + playwright-stealth
- **NLP**: Regex + spaCy (en_core_web_sm)
- **Email**: Gmail SMTP (smtplib)

## Setup

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Install spaCy model (optional, for better location extraction)
python -m spacy download en_core_web_sm

# Configure environment
copy .env.example .env
# Edit .env with your LinkedIn & Gmail credentials

# Run the backend
python main.py
```

The API will be available at `http://localhost:8000`

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

The dashboard will be available at `http://localhost:3000`

## Configuration (.env)

```
# LinkedIn (use a burner account!)
LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password

# Gmail SMTP (requires App Password)
GMAIL_EMAIL=your-gmail@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
```

### Gmail App Password Setup
1. Enable 2-Step Verification on your Google account
2. Go to Google Account → Security → App passwords
3. Generate a new app password for "Mail"
4. Use the 16-character code in your .env

## Features

- 🔍 **Smart Scraping** — Searches LinkedIn posts using Playwright with anti-detection
- 📧 **Email Extraction** — Regex-based email extraction from post text
- 💼 **Role Detection** — Identifies job titles from 60+ common roles
- 📅 **Experience Parsing** — Extracts "2-4 years", "3+ years" patterns
- 📍 **Location Detection** — Uses spaCy NLP for location entity recognition
- 📨 **Auto Email** — Send emails via Gmail SMTP with resume attachment
- 📊 **Dashboard** — Beautiful dark-themed UI with stats and history

## ⚠️ Important Notes

- **LinkedIn account risk**: Use a burner/secondary account. LinkedIn may ban accounts for automated scraping.
- **Gmail limits**: Personal Gmail has a 500 emails/day limit.
- **Resume**: Place your resume at `backend/resume.pdf` for auto-attachment.
