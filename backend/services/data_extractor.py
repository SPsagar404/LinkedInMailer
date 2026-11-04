"""
Data extraction service.
Extracts emails, roles, experience, and locations from LinkedIn post text.
Uses Regex for emails/experience and spaCy NLP for roles/locations.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger("DataExtractor")

# ── Common job titles/roles for keyword matching ────────────────
COMMON_ROLES = [
    "software engineer", "software developer", "java developer",
    "python developer", "frontend developer", "backend developer",
    "full stack developer", "fullstack developer", "web developer",
    "mobile developer", "android developer", "ios developer",
    "devops engineer", "data engineer", "data scientist",
    "data analyst", "machine learning engineer", "ml engineer",
    "ai engineer", "cloud engineer", "qa engineer", "test engineer",
    "sdet", "automation engineer", "site reliability engineer",
    "sre", "product manager", "project manager", "business analyst",
    "ux designer", "ui designer", "ui/ux designer", "graphic designer",
    "system administrator", "network engineer", "database administrator",
    "dba", "security engineer", "cybersecurity analyst", "tech lead",
    "team lead", "engineering manager", "architect", "solution architect",
    "react developer", "angular developer", "node.js developer",
    "nodejs developer", ".net developer", "dotnet developer",
    "php developer", "ruby developer", "golang developer", "go developer",
    "rust developer", "c++ developer", "c# developer", "kotlin developer",
    "swift developer", "flutter developer", "react native developer",
    "salesforce developer", "sap consultant", "scrum master",
    "technical writer", "content writer", "hr executive", "recruiter",
    "talent acquisition", "digital marketing", "marketing manager",
    "sales executive", "account manager", "customer support",
    "fresher", "intern", "trainee", "associate",
]

# ── Experience patterns ─────────────────────────────────────────
EXPERIENCE_PATTERNS = [
    # "2-4 years", "2 - 4 years", "2 to 4 years"
    r'(\d+)\s*[-–to]+\s*(\d+)\s*(?:\+)?\s*(?:years?|yrs?)(?:\s+(?:of\s+)?(?:experience|exp))?',
    # "2+ years", "2 plus years"
    r'(\d+)\s*\+?\s*(?:plus\s+)?(?:years?|yrs?)(?:\s+(?:of\s+)?(?:experience|exp))?',
    # "minimum 2 years", "at least 3 years"
    r'(?:minimum|min|at\s+least)\s+(\d+)\s*(?:years?|yrs?)',
    # "experience: 2-4 years"
    r'(?:experience|exp)\s*[:\-]\s*(\d+)\s*[-–to]+\s*(\d+)\s*(?:years?|yrs?)',
    # "2 years experience"
    r'(\d+)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)',
]

# ── Email pattern ───────────────────────────────────────────────
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

# Known non-email domains to filter out
EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "test.com", "email.com", "yourmail.com",
    "sentry.io", "domain.com", "company.com",
}


class DataExtractor:
    """Extracts structured data from unstructured LinkedIn post text."""

    def __init__(self):
        self._nlp = None  # Lazy load spaCy

    @property
    def nlp(self):
        """Lazy load spaCy model to avoid slow startup."""
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy model loaded successfully")
            except (ImportError, OSError) as e:
                logger.warning(
                    f"spaCy not available ({e}). "
                    "Location extraction will use fallback regex."
                )
                self._nlp = False  # Mark as unavailable
        return self._nlp

    def extract_emails(self, text: str) -> list[str]:
        """Extract email addresses from text."""
        if not text:
            return []

        emails = EMAIL_PATTERN.findall(text)

        # Filter out non-email matches and known bad domains
        filtered = []
        for email in emails:
            email = email.strip().rstrip(".,;:)")
            domain = email.split("@")[-1].lower()
            if domain not in EXCLUDED_EMAIL_DOMAINS and len(email) < 254:
                filtered.append(email.lower())

        return list(set(filtered))

    def extract_experience(self, text: str) -> Optional[str]:
        """Extract experience requirements from text."""
        if not text:
            return None

        text_lower = text.lower()

        for pattern in EXPERIENCE_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                groups = [g for g in match.groups() if g is not None]
                if len(groups) == 2:
                    return f"{groups[0]}-{groups[1]} years"
                elif len(groups) == 1:
                    return f"{groups[0]}+ years"

        return None

    def extract_roles(self, text: str) -> list[str]:
        """Extract job roles/titles from text using keyword matching."""
        if not text:
            return []

        text_lower = text.lower()
        found_roles = []

        for role in COMMON_ROLES:
            if role in text_lower:
                # Verify it's a word boundary match (not partial)
                pattern = r'\b' + re.escape(role) + r'\b'
                if re.search(pattern, text_lower):
                    found_roles.append(role.title())

        # Deduplicate while preserving order
        seen = set()
        unique_roles = []
        for role in found_roles:
            if role.lower() not in seen:
                seen.add(role.lower())
                unique_roles.append(role)

        return unique_roles

    def extract_locations(self, text: str) -> list[str]:
        """Extract location names using spaCy NER or fallback."""
        if not text:
            return []

        # Try spaCy NER first
        if self.nlp and self.nlp is not False:
            try:
                doc = self.nlp(text)
                locations = []
                for ent in doc.ents:
                    if ent.label_ in ("GPE", "LOC"):
                        loc = ent.text.strip()
                        if len(loc) > 1 and loc.lower() not in ("remote", "hybrid", "onsite"):
                            locations.append(loc)
                return list(set(locations))
            except Exception as e:
                logger.warning(f"spaCy extraction failed: {e}")

        # Fallback: regex-based location extraction for common Indian cities/locations
        return self._fallback_location_extraction(text)

    def _fallback_location_extraction(self, text: str) -> list[str]:
        """Fallback location extraction using known city names."""
        KNOWN_LOCATIONS = [
            "Bangalore", "Bengaluru", "Mumbai", "Delhi", "NCR", "Hyderabad",
            "Chennai", "Pune", "Kolkata", "Ahmedabad", "Noida", "Gurgaon",
            "Gurugram", "Chandigarh", "Jaipur", "Lucknow", "Indore",
            "Coimbatore", "Kochi", "Trivandrum", "Thiruvananthapuram",
            "New York", "San Francisco", "London", "Singapore", "Dubai",
            "Toronto", "Berlin", "Sydney", "Tokyo", "Remote", "Hybrid",
            "Work from Home", "WFH", "Pan India", "India", "USA", "UK",
            "Canada", "Australia", "Germany",
        ]

        text_lower = text.lower()
        found = []
        for loc in KNOWN_LOCATIONS:
            if loc.lower() in text_lower:
                found.append(loc)

        return found

    def extract_all(self, text: str) -> dict:
        """Extract all data points from post text."""
        return {
            "emails": self.extract_emails(text),
            "roles": self.extract_roles(text),
            "experience": self.extract_experience(text),
            "locations": self.extract_locations(text),
        }
